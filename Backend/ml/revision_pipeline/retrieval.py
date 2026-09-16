"""Related-section retrieval within a document.

Layer 2 judges a revision against the rest of the document it lives in: a
changed duration only reads as wrong when another section still states the old
one. This module finds the sections most likely to carry that context.

Default backend is scikit-learn TF-IDF, which needs no download. If
sentence-transformers is installed, ``backend="embedding"`` uses MiniLM
instead. Indexes are cached per document so a training run does not rebuild
them for every example.
"""

from __future__ import annotations

import json
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config

_WS_RE = re.compile(r"\s+")

# Decision 9: List of Forms is a reference list, not a revision unit. It is
# still retrievable as *context* - a procedure that names a form should be able
# to see the list - but it never becomes a query.
_FORMS_TITLE_RE = re.compile(r"^\s*\d+\.0\s+LIST\s+OF\s+FORMS\b", re.IGNORECASE)


def is_forms_section(subtitle: str) -> bool:
    return bool(_FORMS_TITLE_RE.match(subtitle or ""))


@dataclass
class Section:
    section_id: int
    subtitle: str
    content: str
    order: int = 0

    @property
    def label(self) -> str:
        return (self.subtitle or "").strip()


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", (text or "")).strip()


class DocumentIndex:
    """Similarity index over the sections of one document."""

    def __init__(self, document_id, sections: list, backend: str = "tfidf"):
        self.document_id = document_id
        self.sections = [s for s in sections if _clean(s.content)]
        self.backend = backend
        self._matrix = None
        self._vectorizer = None
        self._embedder = None
        if self.sections:
            self._fit()

    def _fit(self) -> None:
        corpus = [f"{s.label} {s.content}" for s in self.sections]
        if self.backend == "embedding":
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._matrix = self._embedder.encode(corpus, show_progress_bar=False)
        else:
            # min_df=1 because a document has only a handful of sections; the
            # defaults would throw most of the vocabulary away.
            self._vectorizer = TfidfVectorizer(
                stop_words="english", ngram_range=(1, 2), min_df=1, sublinear_tf=True
            )
            self._matrix = self._vectorizer.fit_transform(corpus)

    def _vector(self, text: str):
        if self.backend == "embedding":
            return self._embedder.encode([text], show_progress_bar=False)
        return self._vectorizer.transform([text])

    def top_k(self, query_text: str, exclude_section_id=None, k: int = 3) -> list:
        """The k most similar *other* sections, most similar first."""
        if not self.sections or self._matrix is None:
            return []
        scores = cosine_similarity(self._vector(_clean(query_text)), self._matrix)[0]
        ranked = sorted(
            (
                (score, section)
                for score, section in zip(scores, self.sections)
                if section.section_id != exclude_section_id
            ),
            key=lambda pair: (-pair[0], pair[1].order),
        )
        return [section for score, section in ranked[:k] if score > 0]


# -- cache -----------------------------------------------------

_MEMORY_CACHE: dict = {}


def _cache_path(document_id, backend: str) -> Path:
    return config.RETRIEVAL_CACHE / f"{backend}_{document_id}.pkl"


def build_index(document_id, sections: list, backend: str = "tfidf",
                use_disk: bool = True) -> DocumentIndex:
    key = (document_id, backend)
    if key in _MEMORY_CACHE:
        return _MEMORY_CACHE[key]

    path = _cache_path(document_id, backend)
    if use_disk and path.exists():
        try:
            with path.open("rb") as fh:
                index = pickle.load(fh)
            _MEMORY_CACHE[key] = index
            return index
        except Exception:
            # A stale or half-written cache should never break a training run.
            path.unlink(missing_ok=True)

    index = DocumentIndex(document_id, sections, backend=backend)
    _MEMORY_CACHE[key] = index
    if use_disk:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(index, fh)
    return index


def clear_cache() -> None:
    _MEMORY_CACHE.clear()


# -- context building ------------------------------------------

def format_context(parent_title: str, sections: list, max_chars: int = 1200) -> str:
    """One string: the parent heading, then each related section, labelled.

    Labelling matters - the model has to be able to tell that a conflicting
    duration came from section 3.6 rather than from the text being revised.
    """
    parts = []
    if parent_title:
        parts.append(f"PARENT {_clean(parent_title)}")
    for section in sections:
        body = _clean(section.content)
        parts.append(f"SECTION {section.label}: {body}")

    text = " ".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " ..."
    return text


def get_context(document_id, section_id, query_text: str, sections: list,
                parent_title: str = "", k: int = 3, backend: str = "tfidf",
                use_disk: bool = True) -> str:
    """Retrieve and format context for one revision.

    ``sections`` is every section of the document, so callers that already hold
    them (the dataset builder, the training loop) do not hit the database again.
    """
    index = build_index(document_id, sections, backend=backend, use_disk=use_disk)
    related = index.top_k(query_text, exclude_section_id=section_id, k=k)
    return format_context(parent_title, related)


def related_texts(document_id, section_id, query_text: str, sections: list,
                  k: int = 3, backend: str = "tfidf", use_disk: bool = True) -> list:
    """Raw texts of the related sections - what Layer 1's cross-reference
    check consumes, as opposed to the formatted string Layer 2 reads."""
    index = build_index(document_id, sections, backend=backend, use_disk=use_disk)
    return [s.content for s in index.top_k(query_text, exclude_section_id=section_id, k=k)]


# -- Django-backed convenience ---------------------------------

def sections_for_manual(manual) -> list:
    """Build Section records from a Django Manual instance."""
    return [
        Section(
            section_id=s.id,
            subtitle=s.subtitle or "",
            content=s.content or "",
            order=s.order or 0,
        )
        for s in manual.sections.all().order_by("order")
    ]


def save_manifest(path: Path | None = None) -> Path:
    """Record which documents have cached indexes, for check_setup.py."""
    cache_dir = config.RETRIEVAL_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = sorted(p.name for p in cache_dir.glob("*.pkl"))
    out = Path(path or cache_dir / "manifest.json")
    out.write_text(json.dumps({"indexes": manifest}, indent=2), encoding="utf-8")
    return out
