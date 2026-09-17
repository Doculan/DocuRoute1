"""Build the context_v2 dataset from the stored master copies.

    py ml/revision_pipeline/scripts/build_dataset.py --out-dir ml/datasets/context_v2

Every example is a whole section as the app would submit it, with one to three
rows or sentences edited. Each candidate goes through the quality gate; what it
rejects is counted and reported rather than quietly dropped.
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config, generators, quality          # noqa: E402
from revision_pipeline.entities import get_entities                # noqa: E402
from revision_pipeline.retrieval import (                          # noqa: E402
    format_context, is_forms_section, sections_for_manual,
)
from revision_pipeline.section_doc import SectionDoc, section_type  # noqa: E402
from revision_pipeline.scripts._corpus import load_documents, setup_django  # noqa: E402

_NUMBER_RE = re.compile(r"\b\d{1,4}\b")
_TOP_RE = re.compile(r"^\s*(\d+)")


def resolve_section_types(sections) -> dict:
    """Map every section to the type of its top-level parent.

    "4.1 Onsite Application" is a Procedures unit; classifying on its own
    subtitle put it in "Other" and left the stratification meaningless.
    """
    tops = {}
    for section in sections:
        match = _TOP_RE.match(section["subtitle"])
        kind = section_type(section["subtitle"])
        if match and kind != "Other":
            tops[match.group(1)] = kind

    resolved = {}
    for section in sections:
        match = _TOP_RE.match(section["subtitle"])
        own = section_type(section["subtitle"])
        resolved[section["section_id"]] = (
            own if own != "Other" else tops.get(match.group(1) if match else "", "Other")
        )
    return resolved


_ACRONYM_DEF_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z]*\s+(?:of\s+|on\s+|and\s+|for\s+|the\s+|to\s+)?){1,6}"
    r"[A-Z][A-Za-z]*)\s*\(([A-Z]{2,7})\)"
)


def mine_acronyms(documents) -> dict:
    """Acronym -> the expansion the manuals themselves give it.

    Read out of the corpus rather than written by hand, so an expansion can
    only be one this organisation actually uses.
    """
    found = {}
    for doc in documents:
        for section in doc["sections"]:
            for match in _ACRONYM_DEF_RE.finditer(section["content"] or ""):
                full, acronym = match.group(1).strip(), match.group(2)
                # "of The Leyte Normal University (LNU) employees" - the
                # article belongs to the sentence, not to the name.
                full = re.sub(r"^(?:The|A|An)\s+", "", full)
                # A cheap check on the mining: the expansion should start with
                # the acronym's first letter. Without it the regex offered
                # "CHED = Higher Education", having lost "Commission on" to the
                # lowercase connector.
                if full[:1].upper() != acronym[:1].upper():
                    continue
                if 2 <= len(full.split()) <= 7 and acronym not in found:
                    found[acronym] = full
    return found


def build_context(documents) -> dict:
    """Per-document material the generators draw on."""
    entities = get_entities()
    acronyms = mine_acronyms(documents)
    all_rows, all_sentences = [], []
    per_document = {}

    for doc in documents:
        rows, numbers, roles = [], set(), set()
        prose = []
        for section in doc["sections"]:
            parsed = SectionDoc.parse(section["subtitle"], section["content"])
            for row in parsed.rows:
                rows.append(list(row.cells))
                if row.role:
                    roles.add(row.role)
                numbers.update(_NUMBER_RE.findall(row.body))
            prose += [t for _, _, t in parsed.sentences() if len(t.split()) >= 8]
            numbers.update(_NUMBER_RE.findall(section["content"] or ""))
        per_document[doc["title"]] = {
            "rows": rows,
            "numbers": sorted(numbers),
            "roles": sorted(roles) or entities.roles[:20],
            "acronyms": acronyms,
        }
        all_rows.extend((doc["title"], r) for r in rows)
        all_sentences.extend((doc["title"], s) for s in prose)

    for title, data in per_document.items():
        data["foreign_rows"] = [r for other, r in all_rows if other != title][:400]
        data["foreign_sentences"] = [
            s for other, s in all_sentences if other != title
        ][:200]
    return per_document


# A figure together with its unit, which is what makes two sections agree or
# disagree. A bare number shared between sections means nothing - most of them
# are step numbers.
_QUANTITY_PHRASE_RE = re.compile(
    r"\b(\d{1,4})\s*(%|working\s+days|calendar\s+days|days|day|weeks|week|"
    r"months|month|years|year|hours|hour|copies|copy|percent|pesos|peso)\b",
    re.IGNORECASE,
)

# Days per unit, so that "1 year" and "365 days" are recognised as the same
# fact stated two ways - which is the commonest way two sections of one manual
# come to disagree.
_DAYS_PER = {
    "day": 1, "days": 1, "working day": 1, "working days": 1,
    "calendar day": 1, "calendar days": 1,
    "week": 7, "weeks": 7, "month": 30, "months": 30,
    "year": 365, "years": 365,
}


def _canonical_quantity(value: str, unit: str):
    """A comparable key for a figure: days where it is a duration."""
    unit = re.sub(r"\s+", " ", unit.strip().lower())
    try:
        number = int(value)
    except ValueError:
        return None
    if unit in _DAYS_PER:
        return ("days", number * _DAYS_PER[unit])
    return (unit, number)


def shared_quantities(section, siblings) -> dict:
    """Figures in this section that a sibling section states as the same fact.

    Changing one of these creates a real contradiction: the manual then says
    two different things about the same thing. A figure appearing nowhere else
    is only a changed figure, which is a different label.

    Durations are compared in days, so "1 year" here and "365 days" in the
    sibling count as the same fact.
    """
    mine = {}
    for match in _QUANTITY_PHRASE_RE.finditer(section["content"] or ""):
        key = _canonical_quantity(match.group(1), match.group(2))
        if key:
            mine.setdefault(key, match.group(0))

    shared = {}
    for other in siblings:
        for match in _QUANTITY_PHRASE_RE.finditer(other["content"] or ""):
            key = _canonical_quantity(match.group(1), match.group(2))
            if key is None or key not in mine:
                continue
            phrase = mine[key]
            if phrase in shared:
                continue
            label = (other["subtitle"].split()[0] if other["subtitle"].split()
                     else other["subtitle"])
            stated = match.group(0)
            shared[phrase] = (f"{label} (\"{stated}\")" if stated.lower() != phrase.lower()
                              else label)
    return shared


def related_labels(sections, minimum: float = 0.08, most: int = 5) -> dict:
    """Which sibling sections each section is actually about.

    A cross-reference is only useful if it points somewhere related. TF-IDF
    cosine over the sections of one document is enough to tell "4.3 Public
    Bidding" from "1.0 OBJECTIVES"; anything below ``minimum`` is not a
    relation, it is two sections that happen to share the word "the". The
    default sits at the 75th percentile of within-document similarity measured
    across the 19 manuals (median 0.042, p75 0.079, p90 0.120).
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    usable = [s for s in sections if (s["content"] or "").strip()]
    if len(usable) < 2:
        return {}
    corpus = [f"{s['subtitle']} {s['content']}" for s in usable]
    try:
        matrix = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), min_df=1, sublinear_tf=True
        ).fit_transform(corpus)
    except ValueError:              # every section was stop words
        return {}
    similarity = cosine_similarity(matrix)

    out = {}
    for row, section in enumerate(usable):
        scored = [
            (similarity[row][other], usable[other]["subtitle"])
            for other in range(len(usable)) if other != row
            and similarity[row][other] >= minimum
        ]
        scored.sort(reverse=True)
        out[section["section_id"]] = [label for _, label in scored[:most]]
    return out


def prepare_jobs(seed: int) -> tuple:
    """Parse every usable section once.

    Generation runs more than once - a first pass over all generators, then
    top-up passes for the labels still short of the floor - and re-parsing 109
    sections each time was the bulk of the build.
    """
    documents = load_documents()
    doc_context = build_context(documents)
    key_terms = get_entities().term_phrases
    setup_django()

    jobs = []
    for doc in documents:
        types = resolve_section_types(doc["sections"])
        ctx_base = doc_context[doc["title"]]
        related = related_labels(doc["sections"])

        for section in doc["sections"]:
            label = section["subtitle"]
            if is_forms_section(label) or types[section["section_id"]] == "Forms":
                continue     # decision 9
            parsed = SectionDoc.parse(label, section["content"])
            if parsed.unit_count() == 0 or len(section["content"].split()) < 15:
                continue

            sibling_sections = [s for s in doc["sections"]
                                if s["section_id"] != section["section_id"]]
            siblings = [s["content"] for s in sibling_sections]
            jobs.append({
                "doc": doc,
                "section": section,
                "label": label,
                "parsed": parsed,
                "type": types[section["section_id"]],
                "siblings": siblings,
                "ctx": {
                    "key_terms": key_terms,
                    "document_roles": ctx_base["roles"],
                    "foreign_rows": ctx_base["foreign_rows"],
                    "foreign_sentences": ctx_base["foreign_sentences"],
                    "acronyms": ctx_base["acronyms"],
                    # A step points at a section it is actually about, and
                    # never at the document's Objectives: "(see 1.0
                    # OBJECTIVES)" on a purchasing step is not something
                    # anyone would write.
                    "related_labels": [
                        label for label in related.get(section["section_id"], [])
                        if label.split()
                        and not re.match(r"^[12]\.0\b", label.strip())
                    ][:5],
                    "shared_quantities": shared_quantities(section, sibling_sections),
                },
            })
    return jobs, key_terms


_counter = itertools.count(1)


def generate(jobs, gens, per_section, rng, seen, key_terms) -> tuple:
    """One pass: every generator in ``gens`` over every job.

    ``seen`` carries the (old, new) pairs already produced, so a top-up pass
    adds only examples the earlier passes did not find.
    """
    candidates, rejected, quality_results = [], [], []

    for job in jobs:
        doc, section, label = job["doc"], job["section"], job["label"]
        for generator in gens:
            for _ in range(per_section):
                produced = generator(job["parsed"], job["ctx"], rng)
                if not produced:
                    break
                revision, old_text = produced
                key = (redact(old_text), redact(revision.new_text))
                if key in seen:
                    continue
                seen.add(key)
                example = {
                    "id": f"{doc['title'].replace(' ', '_')}-{section['section_id']}-{next(_counter)}",
                    "manual_id": doc["manual_id"],
                    "document_no": doc["title"],
                    "section_id": section["section_id"],
                    "section_number": label.split()[0] if label.split() else "",
                    "section_title": " ".join(label.split()[1:]),
                    "section_type": job["type"],
                    "old_text": redact(old_text),
                    "new_text": redact(revision.new_text),
                    "verdict": revision.verdict,
                    "issues": revision.issues,
                    "issues_labeled": True,
                    "generator": revision.generator,
                    "change_reason": revision.change_reason,
                    "edited_units": revision.edited_units,
                    "source": "synthetic",
                    "hard_negative": "hard negative" in (revision.note or ""),
                    "note": revision.note,
                    "strategy": revision.strategy,
                }
                result = quality.check(
                    example, key_terms=key_terms, related=job["siblings"][:3]
                )
                quality_results.append((example["generator"], result))
                if result.ok:
                    example["quality_score"] = round(result.score, 3)
                    example["quality_notes"] = result.reasons
                    candidates.append(example)
                else:
                    rejected.append((example["generator"], result.reasons))

    return candidates, rejected, quality_results


# Account numbers taken from the master copies. The dataset is a training
# corpus, not a record of the university's banking, and the model has no use
# for the digits - the shape of the row is what matters.
# Two or more hyphens, which is how every account number in the master copies
# is written ("0182-1029-54", "5-37490-775-80"). A single hyphen would also
# match a year range like "2016-2017", which is not sensitive and is sometimes
# the figure a revision changes.
_ACCOUNT_NO_RE = re.compile(r"\b\d[\d-]*-[\d-]*-[\d-]*\d\b")
ACCOUNT_PLACEHOLDER = "0000-0000-00"


def redact(text: str) -> str:
    """Replace bank account numbers with a fixed placeholder."""
    return _ACCOUNT_NO_RE.sub(ACCOUNT_PLACEHOLDER, text or "")


def label_counts(examples) -> collections.Counter:
    counts = collections.Counter()
    for example in examples:
        for label in example["issues"]:
            counts[label] += 1
    return counts


def make_examples(args) -> tuple:
    """The first pass, then top-up passes aimed at the labels still short.

    A uniform number of attempts per section cannot reach the floor for a rare
    label: only 156 units in the whole corpus carry an obligation modal, so
    raising ``--per-section`` for everything mostly produces more of what is
    already plentiful. The top-up passes re-run just the generators that can
    produce a short label, and stop as soon as a pass adds nothing new.
    """
    rng = random.Random(args.seed)
    jobs, key_terms = prepare_jobs(args.seed)
    seen = set()

    candidates, rejected, results = generate(
        jobs, generators.ALL, args.per_section, rng, seen, key_terms
    )

    # Which generator can produce which label, learned from the first pass
    # rather than declared, so the map cannot drift from the generators.
    gen_labels = collections.defaultdict(set)
    for example in candidates:
        gen_labels[example["generator"]].update(example["issues"])

    for _ in range(args.topup_rounds):
        short = {label for label in config.ISSUE_LABELS
                 if label_counts(candidates)[label] < args.issue_floor}
        if not short:
            break
        gens = [g for g in generators.ALL if gen_labels[g.__name__] & short]
        if not gens:
            break
        more, more_rejected, more_results = generate(
            jobs, gens, args.topup_per_section, rng, seen, key_terms
        )
        rejected += more_rejected
        results += more_results
        if not more:
            break
        candidates += more

    # The issue top-ups only run generators that produce an issue, so every
    # round pushes the approve share down. A model trained on 8% approve learns
    # to say no; the approve generators get their own rounds.
    for _ in range(args.topup_rounds):
        approvals = sum(1 for e in candidates if e["verdict"] == "approve")
        if approvals >= args.approve_share * len(candidates):
            break
        more, more_rejected, more_results = generate(
            jobs, generators.APPROVE, args.topup_per_section, rng, seen, key_terms
        )
        rejected += more_rejected
        results += more_results
        if not more:
            break
        candidates += more

    return candidates, rejected, results


def cap_strategies(examples, rng, max_share: float = 0.06) -> list:
    """Stop one phrasing filling the dataset.

    ``clarifying_addition`` was 55% of the approve class and reused two
    sentences between them, so the model could have learned "this sentence
    means approve" and scored well. No single strategy - one typo, one synonym
    pair, one added clause - may hold more than a small share.
    """
    limit = max(4, int(max_share * len(examples)))
    kept, seen = [], collections.Counter()
    for example in _shuffled_copy(examples, rng):
        key = (example["generator"], example.get("strategy") or "")
        if seen[key] >= limit and not example.get("hard_negative"):
            continue
        seen[key] += 1
        kept.append(example)
    return kept


def _shuffled_copy(examples, rng):
    out = list(examples)
    rng.shuffle(out)
    return out


def stratify(examples, rng, max_share: float = 0.45, floor: int = 0,
             verdict_share: float = 0.2) -> list:
    """Stop any one section type swamping the dataset - and nothing else.

    All 487 table rows live in Procedures sections, so left alone a build comes
    out overwhelmingly procedures. But the cap is the *weakest* of the three
    things this dataset has to get right, and it was quietly overruling the
    other two: capping each type at a multiple of the smallest took the whole
    surplus out of the approve class, leaving 8% approve examples and not one
    from typo_fix, whitespace_format or benign_reorder.

    So a type over its share is trimmed weakest-first, and an example is only
    spare while:

    * every issue label it carries stays at or above ``floor``; and
    * its verdict class stays at or above ``verdict_share`` of the dataset.

    A type that cannot be trimmed that far stays over its share, and the report
    says so. Getting the labels and the verdicts right matters more than an
    even split across section types.
    """
    total = len(examples)
    if not total:
        return examples

    counts = label_counts(examples)
    verdicts = collections.Counter(e["verdict"] for e in examples)
    verdict_floor = int(verdict_share * total)
    type_cap = int(max_share * total)

    by_type = collections.defaultdict(list)
    for example in examples:
        by_type[example["section_type"]].append(example)

    kept = []
    for kind, rows in by_type.items():
        if len(rows) <= type_cap:
            kept.extend(rows)
            continue
        # Weakest first, so the cap costs the least confident examples - except
        # that a hard negative scores 0.5 *by design*, because it trips a rule
        # on purpose. Sorting on the score alone put every one of them at the
        # front of the queue to be dropped, and row_merge_reformat went from 50
        # examples to none. They are excluded from the cull above instead.
        rows = sorted(rows, key=lambda e: -e.get("quality_score", 1.0))
        surplus = len(rows) - type_cap
        survivors = []
        for example in reversed(rows):
            spare = (
                surplus > 0
                and not example.get("hard_negative")
                and all(counts[label] - 1 >= floor for label in example["issues"])
                and verdicts[example["verdict"]] - 1 >= verdict_floor
            )
            if spare:
                for label in example["issues"]:
                    counts[label] -= 1
                verdicts[example["verdict"]] -= 1
                surplus -= 1
            else:
                survivors.append(example)
        kept.extend(survivors)

    rng.shuffle(kept)
    return kept


def cap_cross_references(examples, rng, share: float = 0.15) -> list:
    """Hold pointer-additions to a share of the approve class.

    They are the easiest approve example to generate and the least
    interesting: a model that learns "a bracket at the end means approve" has
    learned nothing about revisions.
    """
    approvals = [e for e in examples if e["verdict"] == "approve"]
    pointers = [e for e in approvals if e["generator"] == "cross_reference_addition"]
    limit = int(share * len(approvals))
    if len(pointers) <= limit:
        return examples
    drop = {id(e) for e in rng.sample(pointers, len(pointers) - limit)}
    return [e for e in examples if id(e) not in drop]


def deduplicate(examples) -> list:
    seen, out = set(), []
    for example in examples:
        key = (example["old_text"], example["new_text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(example)
    return out


def balance(examples, rng, floor: int) -> collections.Counter:
    """Positives per issue label, for the floor report."""
    return label_counts(examples)


def write_outputs(examples, out_dir: Path, rng, folds: int = 5) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Group split by document, so no document's wording appears in two splits.
    documents = sorted({e["document_no"] for e in examples})
    rng.shuffle(documents)
    assignment = {doc: i % folds for i, doc in enumerate(documents)}

    (out_dir / "folds.json").write_text(
        json.dumps({"by_document": assignment, "folds": folds}, indent=2),
        encoding="utf-8",
    )
    with (out_dir / "all.jsonl").open("w", encoding="utf-8") as fh:
        for example in examples:
            slim = {k: v for k, v in example.items() if k != "context"}
            fh.write(json.dumps(slim, ensure_ascii=False) + "\n")

    # Default single split: fold 0 is test, fold 1 validation, the rest train.
    for name, keep in (
        ("train", lambda d: assignment[d] > 1),
        ("val", lambda d: assignment[d] == 1),
        ("test", lambda d: assignment[d] == 0),
    ):
        rows = [e for e in examples if keep(e["document_no"])]
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for example in rows:
                fh.write(json.dumps(example, ensure_ascii=False) + "\n")

    return assignment


def _short(text: str, width: int = 300) -> str:
    text = " / ".join(line.strip() for line in text.splitlines() if line.strip())
    return text if len(text) <= width else text[:width] + " …"


def print_samples(examples, rng, per_generator: int) -> None:
    """Checkpoint 4: read these as a real admin would."""
    by_generator = collections.defaultdict(list)
    for example in examples:
        by_generator[example["generator"]].append(example)

    print("\n" + "=" * 78)
    print(f"SAMPLES - {per_generator} random per generator")
    print("=" * 78)
    for name in sorted(by_generator):
        rows = by_generator[name]
        print(f"\n--- {name}  ({len(rows)} examples) ---")
        for example in rng.sample(rows, min(per_generator, len(rows))):
            print(f"  [{example['verdict']}] {example['document_no']} :: "
                  f"{example['section_number']} {example['section_title'][:34]}"
                  f"  issues={example['issues']}  units={example['edited_units']}")
            print(f"     reason : {example['change_reason'] or '(none given)'}")
            print(f"     before : {_short(example['old_text'], 220)}")
            print(f"     after  : {_short(example['new_text'], 220)}")

    print("\n" + "=" * 78)
    print("MOST BORDERLINE - the 10 the quality check was least sure about")
    print("=" * 78)
    doubtful = sorted(examples, key=lambda e: e.get("quality_score", 1.0))[:10]
    for example in doubtful:
        print(f"\nscore {example.get('quality_score'):.2f}  [{example['verdict']}] "
              f"{example['generator']}  {example['document_no']} :: "
              f"{example['section_number']}")
        for note in example.get("quality_notes", []):
            print(f"     ! {note}")
        print(f"     before : {_short(example['old_text'], 220)}")
        print(f"     after  : {_short(example['new_text'], 220)}")


def write_card(examples, out_dir: Path, assignment, args, rejected) -> None:
    by_verdict = collections.Counter(e["verdict"] for e in examples)
    by_type = collections.Counter(e["section_type"] for e in examples)
    by_generator = collections.Counter(e["generator"] for e in examples)
    by_label = collections.Counter(
        label for e in examples for label in e["issues"]
    )
    by_document = collections.Counter(e["document_no"] for e in examples)
    non_approve = [e for e in examples if e["verdict"] != "approve"]
    rule_hard = [e for e in non_approve if e["generator"] in generators.RULE_HARD]

    def table(counter, header):
        lines = [f"| {header} | count |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in counter.most_common()]
        return "\n".join(lines)

    card = f"""# context_v2 dataset card

Generated by `build_dataset.py` with `--seed {args.seed}` and
`--per-section {args.per_section}`. Rebuilding from the same database
reproduces this file.

## Source

19 master-copy documents held in the system. `COE` is excluded: it is a
byte-identical duplicate of `HRM 4.02`, and leaving it in would put the same
wording in two split groups. `List of Forms` sections are excluded as revision
units (decision 9) - they are reference lists, not requirements - though their
form names still feed the entity lists.

Text comes from the stored sections after the re-extraction and artefact
repair described in PROGRESS.md.

## What one example is

The app submits **whole sections**, so `old_text` and `new_text` are the
entire stored section. Edits land on one to three table rows or sentences,
the way a real revision changes a few steps rather than rewriting a procedure.

## Counts

**Examples: {len(examples)}**

{table(by_verdict, "verdict")}

{table(by_type, "section type")}

{table(by_generator, "generator")}

### Issue labels

| label | positives |
|---|---:|
""" + "\n".join(
        f"| {label} | {by_label.get(label, 0)} |" for label in config.ISSUE_LABELS
    ) + f"""

Floor was {args.issue_floor} positives per label.

### Documents

{table(by_document, "document")}

## Splits

Grouped by document, so no document's wording appears in two splits.
`folds.json` assigns each document to one of 5 folds; `train/val/test.jsonl`
is the default single split, with fold 0 as test and fold 1 as validation.

## Avoiding a circular dataset

{100 * len(rule_hard) / max(len(non_approve), 1):.0f}% of non-approve examples come from generators the Layer 1 rules
cannot reliably catch ({', '.join(sorted(generators.RULE_HARD))}), against a
target of 40%. Without that, Layer 2 would only be re-learning the rule layer.

Hard negatives are included: legitimate edits that trip a rule, such as
removing a genuine duplicate row or reordering two independent items.

## Quality gate

Every candidate was checked before being kept. {len(rejected)} were rejected.
Checks: leftover markers, defects the edit introduced (as opposed to ones
already in the source), label consistency against the Layer 1 flags for the
six labels the rules detect reliably, and sentence matches near the 0.6
similarity threshold that decides removal from rewrite.

## Known limitations

Accepted before training rather than fixed, because each is a limit of the
corpus rather than of the generator.

- **Cross-section contradictions are thin.** A real contradiction needs one
  fact stated in two places. Comparing durations in days as well as literally -
  so "1 year" here and "365 days" there count as the same fact - finds
  **2 sections in the whole corpus**, and `contradiction_from_context` yields
  a handful of examples. `contradicts_manual` is carried almost entirely by
  `step_reorder_dependent`.
- **Out-of-sequence steps are only detected as a swap.** The generator swaps
  two consecutive numbered steps, which is a real defect and one the rules
  cannot see. It does not cover a step moved several places, or a step whose
  prerequisite is in another section.
- **Typo variety is narrow.** Ten hand-written misspellings, applied to
  whatever word they match. Real typos are more varied and often less obvious;
  a model trained here may be better at spotting "teh" than a real slip.
- **Only a dozen hard negatives.** Legitimate edits that trip a rule are the
  most valuable examples and the hardest to find honestly. `row_merge_reformat`
  has almost nothing left to merge now that extraction joins wrapped rows, so
  the dataset carries far fewer than intended.
- **Two labels are below the 150 floor.** `key_term_deleted` (126) is limited
  by how many named documents appear in editable units. `non_equivalent_term`
  (89) fell there deliberately after the blind audit: the generator no longer
  widens a scope (that is strengthening, not an issue) and no longer applies a
  verb-sense pair to a noun, and both cuts were worth more than the count.
- **`non_equivalent_term` is concentrated on one word.** 74 of its 89 examples
  swap "all" for "any" or "some". The remaining glossary pairs occur only a
  handful of times each in the corpus.
- **The blind audit agreed on 44 of 50 verdicts (88%) and 47 of 50 issue sets
  (94%).** Four of the six disagreements were fixed; `step_reorder_dependent`
  was relabelled from reject to needs_revision on the auditor's reasoning.
- Synthetic throughout. Real admin-decided revisions are too few to evaluate
  against; the two in the database are test entries.
- `contradicts_manual` and `out_of_scope_content` are constructed, so they are
  cleaner than a real contradiction or a real scope error would be.
- Extraction artefacts were repaired before generation, so the dataset does not
  teach the model to recognise them. That is deliberate - they are damage from
  the PDF text layer, not revisions a person would submit.
- Bank account numbers are replaced with a fixed placeholder, so the dataset
  cannot be used to check an account number against the manual.
"""
    (out_dir / "DATASET_CARD.md").write_text(card, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(config.DATASET_DIR))
    ap.add_argument("--per-section", type=int, default=3,
                    help="attempts per generator per section")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--issue-floor", type=int, default=150)
    ap.add_argument("--no-stratify", action="store_true")
    ap.add_argument("--cross-ref-share", type=float, default=0.15,
                    help="largest share of approvals that may be pointer additions")
    ap.add_argument("--strategy-max-share", type=float, default=0.06,
                    help="largest share one generator strategy may hold")
    ap.add_argument("--topup-rounds", type=int, default=6,
                    help="extra passes aimed at labels below the floor")
    ap.add_argument("--topup-per-section", type=int, default=4,
                    help="attempts per generator per section in a top-up pass")
    ap.add_argument("--type-max-share", type=float, default=0.45,
                    help="no section type may hold more than this share")
    ap.add_argument("--approve-share", type=float, default=0.4,
                    help="approve examples to aim for, as a share of the dataset")
    ap.add_argument("--verdict-floor-share", type=float, default=0.2,
                    help="no verdict class is trimmed below this share")
    ap.add_argument("--samples", type=int, default=5,
                    help="random examples per generator to print")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    candidates, rejected, results = make_examples(args)
    examples = deduplicate(candidates)
    before_cap = len(examples)
    examples = cap_strategies(examples, rng, args.strategy_max_share)
    before_strat = len(examples)
    if not args.no_stratify:
        examples = stratify(examples, rng, args.type_max_share, args.issue_floor,
                            args.verdict_floor_share)
    # After the type cap, so the share is the one the dataset actually ships
    # with: capping first left 17% because stratifying then removed approvals.
    examples = cap_cross_references(examples, rng, args.cross_ref_share)

    out_dir = Path(args.out_dir)
    assignment = write_outputs(examples, out_dir, rng)

    # -- report ---------------------------------------------------
    by_verdict = collections.Counter(e["verdict"] for e in examples)
    by_generator = collections.Counter(e["generator"] for e in examples)
    by_type = collections.Counter(e["section_type"] for e in examples)
    by_label = balance(examples, rng, args.issue_floor)
    non_approve = [e for e in examples if e["verdict"] != "approve"]
    rule_hard = [e for e in non_approve if e["generator"] in generators.RULE_HARD]

    print(f"examples kept: {len(examples)}  (generated {len(candidates) + len(rejected)}, "
          f"gate rejected {len(rejected)}, strategy-capped "
          f"{before_cap - before_strat}, stratified out {before_strat - len(examples)})")
    print(f"\nverdicts: {dict(by_verdict)}")
    print(f"section types: {dict(by_type)}")
    print(f"rule-hard share of non-approve: "
          f"{100 * len(rule_hard) / max(len(non_approve), 1):.0f}% (target >= 40%)")

    print("\nper generator:")
    for name, count in by_generator.most_common():
        print(f"   {name:<28} {count}")

    print(f"\nper issue label (floor {args.issue_floor}):")
    for label in config.ISSUE_LABELS:
        count = by_label.get(label, 0)
        mark = "" if count >= args.issue_floor else "   <-- BELOW FLOOR"
        print(f"   {label:<24} {count}{mark}")

    print("\ndiscards per generator:")
    by_generator_rejects = collections.Counter(name for name, _ in rejected)
    for name, count in by_generator_rejects.most_common():
        attempts = by_generator.get(name, 0) + count
        share = 100 * count / attempts if attempts else 0
        print(f"   {name:<28} {count:>4} of {attempts:<5} ({share:.0f}%)")

    print("\nrejections by reason:")
    for reason, count in collections.Counter(
        r.split(":")[0] for _, reasons in rejected for r in reasons
    ).most_common(12):
        print(f"   {count:>5}  {reason}")

    print(f"\nfold assignment: {assignment}")
    size = (out_dir / "all.jsonl").stat().st_size / 1e6
    print(f"all.jsonl: {size:.2f} MB")

    write_card(examples, out_dir, assignment, args, rejected)
    print(f"wrote {out_dir / 'DATASET_CARD.md'}")

    if args.samples:
        print_samples(examples, random.Random(args.seed + 1), args.samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
