"""Is this checkout ready to assess a revision?

Checks the things that are actually missing when the pipeline does not work on
a fresh clone: the packages, the entity lists, the dataset, the trained
weights, and whether the weights were trained by the code that is here now.

    py ml/revision_pipeline/scripts/check_setup.py

Exit code 0 means the pipeline will run. 1 means something is missing; every
line says what to do about it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OK = "  ok   "
MISSING = " MISSING"
WARN = " check "

problems = []
warnings = []


def report(status: str, what: str, detail: str = "") -> None:
    print(f"[{status}] {what}" + (f"  -  {detail}" if detail else ""))


def main() -> int:
    print("DocuRoute revision pipeline - setup check\n")

    # -- packages --------------------------------------------------
    for module, why in (
        ("torch", "Layer 2 cannot run without it"),
        ("transformers", "the tokenizer and encoder"),
        ("sklearn", "Layer 3"),
        ("joblib", "loading the fusion model"),
        ("django", "the app itself"),
    ):
        try:
            importlib.import_module(module)
            report(OK, module)
        except ImportError:
            report(MISSING, module, f"{why}. pip install -r requirements.txt")
            problems.append(module)

    print()

    # -- the pipeline's own data -----------------------------------
    from revision_pipeline import config

    for path, what, fix in (
        (Path(config.__file__).parent / "entities.json", "entity lists",
         "run scripts/build_entities_draft.py then clean_entities.py"),
        (Path(config.__file__).parent / "glossary.txt", "glossary",
         "it is committed; the checkout may be incomplete"),
        (config.DATASET_DIR / "all.jsonl", "dataset",
         "run scripts/build_dataset.py"),
    ):
        if path.exists():
            report(OK, what, str(path.relative_to(Path(config.__file__).parents[2])))
        else:
            report(MISSING, what, fix)
            problems.append(what)

    print()

    # -- the trained model -----------------------------------------
    model_dir = config.MODEL_DIR
    pieces = {
        "encoder": model_dir / "encoder",
        "tokenizer": model_dir / "tokenizer",
        "heads.pt": model_dir / "heads.pt",
        "label_config.json": model_dir / "label_config.json",
        "fusion.pkl": model_dir / "fusion.pkl",
    }
    for name, path in pieces.items():
        if path.exists():
            report(OK, f"model: {name}")
        elif name == "fusion.pkl":
            report(MISSING, "model: fusion.pkl",
                   "train it: scripts/train_fusion.py --predictions-dir <folds> "
                   "--split val --out-dir ml/saved_models/context_v2")
            problems.append(name)
        else:
            report(MISSING, f"model: {name}",
                   "Layer 2 weights are not in git. See PHASE5_TRAINING.md - "
                   "train on Kaggle, or copy the folder from a backup.")
            problems.append(name)

    print()

    # -- do the weights match this code? ---------------------------
    label_config = model_dir / "label_config.json"
    if label_config.exists():
        import json

        saved = json.loads(label_config.read_text(encoding="utf-8"))
        here = config.pipeline_fingerprint()
        if saved.get("fingerprint") == here:
            report(OK, "fingerprint", f"{here} - weights match this code")
        else:
            report(WARN, "fingerprint",
                   f"weights say {saved.get('fingerprint')}, code says {here}. "
                   "The labels, thresholds or max_length have changed since "
                   "training; predictions may be wrong.")
            warnings.append("fingerprint")

        if saved.get("max_length") != config.MAX_LENGTH:
            report(WARN, "max_length",
                   f"weights trained at {saved.get('max_length')}, "
                   f"config says {config.MAX_LENGTH}")
            warnings.append("max_length")

    # -- can it actually load? -------------------------------------
    print()
    if not problems:
        try:
            from revision_pipeline.pipeline import load_models

            bundle = load_models()
            for part in ("layer2", "tokenizer", "fusion"):
                if bundle.get(part) is None:
                    report(MISSING, f"load: {part}", "; ".join(bundle["warnings"]))
                    problems.append(part)
                else:
                    report(OK, f"load: {part}")
            for warning in bundle.get("warnings", []):
                report(WARN, "load", warning)
                warnings.append(warning)
        except Exception as error:                      # noqa: BLE001
            report(MISSING, "load", str(error))
            problems.append("load")

    print()
    if problems:
        print(f"{len(problems)} thing(s) missing: {', '.join(map(str, problems))}")
        print("The app still runs - assessment falls back to the rules alone.")
        return 1
    if warnings:
        print(f"Ready, with {len(warnings)} thing(s) worth checking.")
        return 0
    print("Ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
