"""What a push would carry, and what it should not.

Run before pushing. It reports the working tree's largest tracked files, what
the next push would add, and anything that looks like it does not belong in
version control - model weights, virtual environments, caches, credentials.

    py ml/revision_pipeline/scripts/check_repo_size.py
    py ml/revision_pipeline/scripts/check_repo_size.py --against origin/main
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys
from pathlib import Path

# GitHub warns above 50 MB for a single file and refuses above 100 MB.
WARN_FILE_MB = 50
HARD_FILE_MB = 100
# A push much larger than this is worth a second look on a student connection.
WARN_PUSH_MB = 25

SUSPICIOUS = (
    (".pyc", "compiled Python - should be gitignored"),
    (".pyo", "compiled Python - should be gitignored"),
    (".pt", "model weights - keep these out of git"),
    (".bin", "model weights - keep these out of git"),
    (".safetensors", "model weights - keep these out of git"),
    (".ckpt", "a checkpoint - keep these out of git"),
    (".env", "may hold credentials"),
    (".pem", "may hold a private key"),
    (".key", "may hold a private key"),
)
SUSPICIOUS_DIRS = (
    "venv/", ".venv/", "node_modules/", "__pycache__/",
    "saved_models/", "training_checkpoints/",
)


def git(*args, root: Path) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return result.stdout


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return here.parents[4]


def megabytes(size: int) -> float:
    return size / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--against", default="origin/main",
                    help="what the push would be measured against")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    root = repo_root()
    print(f"repository: {root}\n")

    # -- tracked files, largest first ------------------------------
    tracked = [line for line in git("ls-files", root=root).splitlines() if line]
    sizes = []
    for name in tracked:
        path = root / name
        if path.is_file():
            sizes.append((path.stat().st_size, name))
    sizes.sort(reverse=True)

    total = sum(size for size, _ in sizes)
    print(f"tracked files: {len(sizes)}, {megabytes(total):.1f} MB in the working tree")
    print(f"\nlargest {args.top}:")
    for size, name in sizes[: args.top]:
        flag = ""
        if megabytes(size) >= HARD_FILE_MB:
            flag = "  <-- OVER GITHUB'S 100 MB LIMIT"
        elif megabytes(size) >= WARN_FILE_MB:
            flag = "  <-- over 50 MB, GitHub will warn"
        print(f"   {megabytes(size):8.2f} MB  {name}{flag}")

    # -- by extension ----------------------------------------------
    by_extension = collections.Counter()
    for size, name in sizes:
        by_extension[Path(name).suffix.lower() or "(none)"] += size
    print("\nby file type:")
    for extension, size in by_extension.most_common(8):
        print(f"   {megabytes(size):8.2f} MB  {extension}")

    # -- things that should not be tracked -------------------------
    problems = []
    for _, name in sizes:
        lowered = name.lower()
        for directory, why in ((d, f"inside {d}") for d in SUSPICIOUS_DIRS):
            if directory in lowered:
                problems.append((name, why))
                break
        else:
            for suffix, why in SUSPICIOUS:
                if lowered.endswith(suffix):
                    problems.append((name, why))
                    break

    print(f"\nfiles that probably should not be tracked: {len(problems)}")
    shown = collections.Counter(why for _, why in problems)
    for why, count in shown.most_common():
        example = next(name for name, reason in problems if reason == why)
        print(f"   {count:>5}  {why}  (e.g. {example})")

    # -- what the next push would add ------------------------------
    ahead = git("rev-list", "--count", f"{args.against}..HEAD", root=root).strip()
    if ahead.isdigit():
        print(f"\ncommits not on {args.against}: {ahead}")
        if ahead != "0":
            changed = [
                line.split("\t")[-1]
                for line in git("diff", "--name-only", f"{args.against}..HEAD",
                                root=root).splitlines() if line
            ]
            push_bytes = sum((root / name).stat().st_size
                             for name in changed if (root / name).is_file())
            print(f"files changed: {len(changed)}, {megabytes(push_bytes):.1f} MB "
                  f"in their current form")
            if megabytes(push_bytes) >= WARN_PUSH_MB:
                print("   <-- large push; check the list above before sending it")
    else:
        print(f"\n{args.against} not found - no comparison made")

    over_limit = [n for s, n in sizes if megabytes(s) >= HARD_FILE_MB]
    if over_limit:
        print("\nBLOCKED: these exceed GitHub's hard limit and must be removed "
              "from history before any push:")
        for name in over_limit:
            print(f"   {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
