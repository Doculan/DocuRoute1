"""Tying an assessment to the exact content it was made about.

A proposal's section is checked before submission, and everyone who reads
the proposal reads that stored result. That only holds if the system can
prove the submitted content is the content that was assessed, so every
check is fingerprinted by its content and the fingerprint is compared at
submit.

Two rules this module exists to enforce:

* **The client never computes the hash, and never supplies the result.** It
  receives an opaque id and hands it back. Everything else is read from the
  server's own row. A hash computed in JavaScript would be a second
  implementation to drift, and a result posted by the client would be a
  snapshot of whatever the client felt like claiming.
* **The base text is part of the hash.** An assessment is about a *change* -
  old text against new - so if the section itself moved underneath, the
  advice is about a comparison that no longer exists, even though the
  submitter changed nothing.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import timedelta

# A check no section change points at any more is working state - the
# text was edited and checked again. Kept long enough to survive a
# weekend, then swept. A check a change points at is never swept.
RETENTION_DAYS = 7
RETENTION = timedelta(days=RETENTION_DAYS)

_TRAILING_WS_RE = re.compile(r"[^\S\n]+$", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def normalise(text: str) -> str:
    """Text reduced to what a reader would call the same content.

    Deliberately aggressive. The hash decides whether a staff member is sent
    back to press the button again, and being sent back over a trailing space
    or a pasted CRLF would teach people the check is broken. Anything that
    changes meaning survives this; anything that does not, does not.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS_RE.sub("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def content_hash(section_id, base_text: str, proposed_content: str,
                 change_reason: str) -> str:
    """Fingerprint of everything the assessment depended on.

    The reason is included because Layer 1 judges it under clause 6.3, so a
    revision whose reason changed has genuinely not been assessed.
    """
    payload = "\x00".join((
        str(section_id or ""),
        normalise(base_text),
        normalise(proposed_content),
        normalise(change_reason),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def section_content_hash(*base_texts: str) -> str:
    """Every server-held text the assessment was derived from.

    Variadic so a change resting on several sections can be fingerprinted
    by all of them; a proposal's section check passes one.
    """
    joined = "\x00".join(normalise(text) for text in base_texts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
