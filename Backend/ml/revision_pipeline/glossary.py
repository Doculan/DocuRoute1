"""Loader and lookup for the controlled term-equivalence list.

A pair is `equivalent`, `not_equivalent`, or `unknown`. Unknown is never
treated as equivalent - if the list does not say two terms mean the same
thing, a swap between them is a change worth looking at.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from . import config

EQUIVALENT = "equivalent"
NOT_EQUIVALENT = "not_equivalent"
UNKNOWN = "unknown"

_WS_RE = re.compile(r"\s+")


def _key(term: str) -> str:
    return _WS_RE.sub(" ", (term or "").strip().lower())


class Glossary:
    """Symmetric term-relation lookup, plus the vocabulary it covers."""

    def __init__(self, pairs: dict[tuple[str, str], str] | None = None):
        self._pairs: dict[tuple[str, str], str] = pairs or {}
        self._terms: set[str] = set()
        self._multiword: list[str] = []
        for a, b in self._pairs:
            self._terms.update((a, b))
        self._multiword = sorted(
            (t for t in self._terms if " " in t), key=len, reverse=True
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "Glossary":
        path = Path(path or config.GLOSSARY_PATH)
        pairs: dict[tuple[str, str], str] = {}
        if not path.exists():
            return cls(pairs)
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 3:
                raise ValueError(f"{path.name}:{lineno}: expected 3 fields, got {len(parts)}")
            a, b, relation = _key(parts[0]), _key(parts[1]), parts[2].lower()
            if relation not in (EQUIVALENT, NOT_EQUIVALENT):
                raise ValueError(f"{path.name}:{lineno}: unknown relation {relation!r}")
            # Stored both ways round so lookup never has to care about order.
            pairs[(a, b)] = relation
            pairs[(b, a)] = relation
        return cls(pairs)

    def relation(self, a: str, b: str) -> str:
        if _key(a) == _key(b):
            return EQUIVALENT
        return self._pairs.get((_key(a), _key(b)), UNKNOWN)

    def is_equivalent(self, a: str, b: str) -> bool:
        return self.relation(a, b) == EQUIVALENT

    def knows(self, term: str) -> bool:
        return _key(term) in self._terms

    @property
    def terms(self) -> set[str]:
        return set(self._terms)

    @property
    def multiword_terms(self) -> list[str]:
        """Longest first, so "at least" matches before "at"."""
        return list(self._multiword)

    def __len__(self) -> int:
        # Each pair is stored twice.
        return len(self._pairs) // 2


@functools.lru_cache(maxsize=4)
def get_glossary(path: str | None = None) -> Glossary:
    """Cached loader - the file is read once per process."""
    return Glossary.load(Path(path) if path else None)
