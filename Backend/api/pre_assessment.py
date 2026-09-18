"""Tying an assessment to the exact content it was made about.

The assessment now happens before submission, on the staff side, and the
result the admin reads is the one the staff member read. That only holds if
the system can prove the submitted content is the content that was assessed,
so every pre-assessment is fingerprinted by its content and the fingerprint is
recomputed at submit.

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

# Unconsumed pre-assessments are working state: a staff member checked, then
# closed the tab. Kept long enough to survive a weekend, then swept.
RETENTION_DAYS = 7
RETENTION = timedelta(days=RETENTION_DAYS)

# A check costs a model run (~0.3s warm, ~14s in a cold worker), and the
# button is now on every staff member's screen rather than a handful of
# admins'. Generous enough that honest re-checking never trips it.
RATE_LIMIT_PER_HOUR = 60

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

    Variadic because a merge rests on more than one section: the target the
    revision lands on and each source being folded into it. If any of them
    moves, the assessment describes a comparison that no longer exists, and
    the submitter needs telling it was not their doing. Hashing only the
    target would blame them for a source someone else edited.
    """
    joined = "\x00".join(normalise(text) for text in base_texts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# -- why a submitted hash did not match --------------------------

EDITED_AFTER_CHECK = (
    "You have changed the text since the AI check. Please run the check again "
    "so the reviewer sees the assessment of what you are actually submitting."
)
SECTION_MOVED = (
    "This section was updated by someone else while you were working, so the "
    "AI check no longer applies to the current version. Please review the "
    "section again and re-run the check."
)
NEVER_CHECKED = (
    "Please run the AI check before submitting. You can submit whatever it "
    "says - the result is advice for the reviewer, not a decision."
)


def mismatch_reason(snapshot, *base_texts: str) -> str:
    """Which of the two mismatches happened, so the message can say.

    They are not the submitter's fault in the same way, and one generic
    "please re-check" makes the innocent case read as a bug.
    """
    if snapshot.section_content_hash != section_content_hash(*base_texts):
        return SECTION_MOVED
    return EDITED_AFTER_CHECK
