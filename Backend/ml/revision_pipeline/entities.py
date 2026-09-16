"""Loader for the reviewed entity lists (roles, offices, systems, forms).

Falls back to the draft when no reviewed file exists yet, so the pipeline runs
before a human has been through entities_draft.json.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from . import config

_WS_RE = re.compile(r"\s+")

# Shorter than this and a mined phrase matches too much to be useful.
_MIN_PHRASE = 5


def _key(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip().lower())


class Entities:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.roles = [r for r in data.get("roles", []) if r]
        self.offices = [o for o in data.get("offices", []) if o]
        self.systems = [s for s in data.get("systems", []) if s]
        self.forms = [f for f in data.get("forms", []) if f]

        self._role_keys = {_key(r) for r in self.roles} | {_key(o) for o in self.offices}
        self._term_keys = {_key(s) for s in self.systems} | {_key(f) for f in self.forms}

        # Longest first so "Accounting Staff-4" matches before "Accounting".
        # Very short entries are mining noise ("Office", "One") and match
        # almost anything, so they are dropped rather than left to fire
        # responsibility_changed on unrelated edits.
        self._role_phrases = sorted(
            (r for r in self.roles + self.offices if r and len(r.strip()) >= _MIN_PHRASE),
            key=len, reverse=True,
        )
        self._term_phrases = sorted(
            (t for t in self.systems + self.forms if t and len(t.strip()) >= _MIN_PHRASE),
            key=len, reverse=True,
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "Entities":
        for candidate in (path or config.ENTITIES_PATH, config.ENTITIES_DRAFT_PATH):
            candidate = Path(candidate)
            if candidate.exists():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return cls(data)
        return cls({})

    def is_role(self, phrase: str) -> bool:
        return _key(phrase) in self._role_keys

    def is_key_term(self, phrase: str) -> bool:
        return _key(phrase) in self._term_keys

    @property
    def role_phrases(self) -> list[str]:
        return list(self._role_phrases)

    @property
    def term_phrases(self) -> list[str]:
        return list(self._term_phrases)


@functools.lru_cache(maxsize=4)
def get_entities(path: str | None = None) -> Entities:
    return Entities.load(Path(path) if path else None)
