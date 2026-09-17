"""Judging the reason a submitter gave for a change.

Clause 6.3 asks that a reason for the change is recorded. "Recorded" has to
mean something more than a non-empty string, or the requirement is met by a
single full stop -- so this module grades a reason into three tiers:

``missing`` / ``invalid``
    Nothing usable. The API refuses the submission with 400, and Layer 1
    raises a hard fail for anything already in the database.

``weak``
    A real sentence that says nothing specific -- "updated", "as discussed".
    Never blocks: it is a soft flag that nudges the verdict towards
    ``needs_revision`` and is shown to the reviewer.

``ok``
    Left alone.

Both callers share this one function so the API and Layer 1 cannot drift
apart. Note what is deliberately *not* here: nothing checks the reason against
the edit it describes. The reason is traceability for the reviewer, never an
input to Layer 2 -- see PROGRESS.md.
"""

from __future__ import annotations

import re

# -- Tier 1: blocking ------------------------------------------

MIN_CHARACTERS = 15
MIN_WORDS = 3
# "......", "aaaaaaaaaaaaaaa" -- long enough to pass the length check and
# still empty of content. Two distinct characters allows "ab ab ab" to fail
# while keeping any real word safe.
MIN_DISTINCT_CHARACTERS = 3

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_ALNUM_RE = re.compile(r"[^\W_]", re.UNICODE)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace, drop surrounding punctuation."""
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    return text.strip(" .,:;-_/\\\"'()[]")


# -- Tier 2: weak ----------------------------------------------

# Words that carry no information about *this* change. A reason built only
# out of these has told the reviewer nothing they did not already know from
# the fact that a revision exists.
_VAGUE_WORDS = {
    "update", "updated", "updates", "updating",
    "change", "changed", "changes", "changing",
    "edit", "edited", "edits", "editing",
    "revise", "revised", "revision", "revisions",
    "correct", "corrected", "correction", "corrections",
    "fix", "fixed", "fixes", "typo", "typos",
    "modify", "modified", "modification", "modifications",
    "adjust", "adjusted", "adjustment", "adjustments",
    "improve", "improved", "improvement", "improvements",
    "clarify", "clarified", "clarification",
    "cleanup", "housekeeping", "minor", "small", "simple",
    "discussed", "instructed", "requested", "advised", "required",
    "necessary", "needed", "applicable", "appropriate",
    "compliance", "purposes", "reference",
    "test", "testing", "sample", "dummy",
}

_STOPWORDS = {
    "a", "an", "the", "this", "that", "these", "those", "it", "its",
    "to", "of", "in", "on", "at", "for", "from", "with", "without",
    "by", "as", "per", "into", "onto", "about", "over", "under",
    "and", "or", "but", "so", "because", "due", "since",
    "is", "are", "was", "were", "be", "been", "being", "has", "have",
    "had", "do", "does", "did", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must",
    "i", "we", "our", "us", "you", "your", "they", "them", "their",
    "he", "she", "his", "her", "my", "me",
    "here", "there", "now", "then", "new", "old", "more", "less",
    "some", "any", "all", "only", "just", "also", "very", "please",
    "it's", "na", "n", "nil", "none",
}

# Below this many content words -- words that are neither filler nor vague --
# the reason is a gesture rather than an explanation.
MIN_CONTENT_WORDS = 2


def content_words(reason: str) -> list[str]:
    """The words in ``reason`` that actually say something about the change."""
    return [
        w for w in _words(reason)
        if w not in _STOPWORDS and w not in _VAGUE_WORDS and len(w) > 1
    ]


def classify_reason(reason: str, section_title: str = None) -> tuple[str, str]:
    """Grade a change reason.

    Returns ``(tier, message)`` where tier is ``"missing"``, ``"invalid"``,
    ``"weak"`` or ``"ok"``. The message is written for the submitter and is
    what the API puts in its 400, so it says what to do, not what went wrong
    in the abstract.
    """
    text = (reason or "").strip()

    if not text:
        return "missing", (
            "A reason for this change is required. Please say briefly what you "
            "changed and why."
        )

    if len(text) < MIN_CHARACTERS:
        return "invalid", (
            "That reason is too short to be useful. Please give at least "
            "{} characters saying what you changed and why.".format(MIN_CHARACTERS)
        )

    if len(_words(text)) < MIN_WORDS:
        return "invalid", (
            "Please write the reason as a short sentence of at least "
            "{} words, not a single word or two.".format(MIN_WORDS)
        )

    if not _ALNUM_RE.search(text):
        return "invalid", (
            "That reason contains no words. Please describe the change in a "
            "short sentence."
        )

    distinct = {c for c in text.lower() if _ALNUM_RE.match(c)}
    if len(distinct) < MIN_DISTINCT_CHARACTERS:
        return "invalid", (
            "That reason does not look like a description of the change. "
            "Please write a short sentence explaining it."
        )

    if section_title and _normalise(text) == _normalise(section_title):
        return "invalid", (
            "The reason repeats the section title. Please explain what changed "
            "in this section and why, rather than naming it."
        )

    if len(content_words(text)) < MIN_CONTENT_WORDS:
        return "weak", (
            "This reason is vague, so a reviewer cannot tell what changed or "
            "why from it alone."
        )

    return "ok", ""


def blocks_submission(tier: str) -> bool:
    """Tier 1. The API refuses these and Layer 1 hard-fails them."""
    return tier in ("missing", "invalid")
