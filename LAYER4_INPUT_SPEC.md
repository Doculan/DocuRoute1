# Layer 4 input spec

*What Layer 4 receives, so its wording can be drafted outside the codebase and an engine built to it. Written 2026-09-29 against the code at `cf26b04`. Nothing here changes Layers 1-3, the model or the published figures.*

Layer 4 is `explain()` in `Backend/ml/revision_pipeline/layer4_explain.py`. It is called from `pipeline.assess_texts()` twice per checked section, once per audience, with the same findings. What it returns is stored as text on the check (`RevisionPreAssessment.explanation_staff` and `explanation_reviewer`) and is never re-run.

**Source of the examples:** §5 was captured by wrapping `explain()` and running the real check path (`proposal_views._assess_unsaved`, the function the **Run the check** button calls) against a scratch copy of the database, on FAM 6.02. The ten edits were rebuilt from the diagnosis table in EVALUATION.md, because the originals were not saved. They reproduce its figures exactly (typo 0.9511, near-synonym 0.9968, clarifying sentence 0.9997, figure 0.8266). The complete capture, including every current note, is `LAYER4_INPUT_CASES.json` beside this file.

---

## 1. What Layer 4 receives for one section

```python
explain(fusion_result, layer1_result, section_label="", revision_id=None,
        max_sentences=5, seed=None, audience="reviewer",
        old_text=None, new_text=None) -> str
```

`revision_id`, `seed` and `max_sentences` are accepted and unused.

### 1.1 `fusion_result` (Layer 3's `FusionResult`)

| field | type | example | notes |
|---|---|---|---|
| `verdict` | str | `"needs_revision"` | `approve`, `needs_revision` or `reject`. Never shown; today it decides emphasis only. |
| `confidence` | float 0-1 | `0.9511` | Probability of the chosen verdict. 1.0 on any hard fail. Never shown. |
| `issues` | list of issue dicts | see 1.3 | Already filtered by the issue policy and each label's threshold. Sorted most severe first, then most confident. |
| `advisories` | list of advisory dicts | see 1.5 | The same list as `layer1_result.advisories`. |
| `overrides` | list of `{rule, detail}` | `[{"rule": "advisory", "detail": "vague_change_reason"}]` | Why Layer 3 moved its own verdict: `hard_fail`, `agreed_high_severity` (an approve raised because rules and model agree on a high-severity issue) or `advisory` (an approve raised by a vague reason). |
| `probabilities` | dict | `{"approve": 0.0468, "needs_revision": 0.9511, "reject": 0.0022}` | Empty on a hard fail. |
| `confidence_source` | str | `"fusion"` | `fusion`, `layer2`, or `rules` (no trained model on this machine; see §6). |

### 1.2 `layer1_result` (Layer 1's `Layer1Result`)

| field | type | example | notes |
|---|---|---|---|
| `change_type` | str | `"substantive"` | `cosmetic`, `terminology_equivalent`, `terminology_non_equivalent`, `substantive`. |
| `hard_fails` | list of `{reason, clause, detail}` | see 1.4 | |
| `flags` | list of flag dicts | see 1.3 | **Every** rule finding, including ones the issue policy dropped. Not the same list as `fusion_result.issues`; see below. |
| `advisories` | list | see 1.5 | |
| `features` | dict of 14 numbers | `{"numeric_changed_count": 4, ...}` | What the rules counted. Always present, never empty. Listed below. |
| `equivalent_swaps` | list of `[a, b]` | `[["Cashier", "Cash Management Office"]]` | Term pairs the glossary treats as meaning the same. |
| `marked` | str | `"... [DEL] 365 days [/DEL] [INS] 180 days [/INS] ..."` | Whole old text with the edits marked. What Layer 2 reads. |

**`flags` vs `issues`: the difference matters for wording.** Layer 3 keeps a rule flag only if the model also predicts the label (the issue becomes `source: "both"`), *or* the label is one of the three the rules are precise enough to add alone: `excessive_deletion`, `modal_weakened`, `non_equivalent_term` (`config.PRECISE_RULE_LABELS`, policy `rules_precise`). Every other rule-only flag is dropped from `issues` and survives only in `layer1_result.flags`. In the cases below that happens to: `numeric_changed` on "timely" (case 03), `requirement_removed` on a reassigned row (08), `responsibility_changed` when a step's owner is deleted with the step (09), and `contradicts_manual` in every case that has it (06, 10, P2). Today's Layer 4 uses `flags` only indirectly, through `features`.

**Features** (all always present):

| feature | meaning |
|---|---|
| `deleted_line_ratio`, `deleted_word_ratio`, `inserted_word_ratio` | share of lines or words removed or added, 0-1 |
| `net_deleted_word_ratio` | words that actually left the section (reordering is not deletion); `excessive_deletion` fires above 0.40 |
| `sentences_removed` | old sentences missing from the new text (table rows count too, often more than once) |
| `key_terms_deleted_count` | listed terms, form names and legal references no longer present |
| `modal_weakened_count` | obligations ("shall", "must", "should") lost *and* permissions ("may", "can") gained |
| `negation_changed` | difference in negation words, plus sense reversals ("before" → "after") |
| `numeric_changed_count` | figures, durations, legal references and frequency words that changed |
| `role_terms_changed_count` | named roles that appear or disappear |
| `equivalent_swaps`, `non_equivalent_swaps`, `unknown_swaps` | term swaps by glossary relation |
| `cross_ref_conflict_count` | changed values that still appear, unchanged, in the retrieved sections |

### 1.3 Issues and flags: common fields

| field | type | example | notes |
|---|---|---|---|
| `label` | str | `"numeric_changed"` | One of the ten in §2. |
| `source` | str | `"both"` | Issues only. `rule`, `model` or `both`. |
| `confidence` | float | `0.914` | Issues only. **Always 1.0 for `rule` and `both`.** Only a model-only issue carries the model's probability, which is at least that label's threshold (§2). |
| `severity` | str | `"high"` | Fixed per label (§2): `high` or `medium`. |
| `clause` | str | `"7.5.3"` | Fixed per label: `5.3` for `responsibility_changed`, `7.5.3` for the rest. |
| `evidence` | str | `"\"shall\" became \"may\""` | Layer 1's own summary, with straight quotes. **Always `""` for a model-only issue.** |
| label-specific fields | | | Present only when a rule raised it (`rule` or `both`). Per label in §2. Layer 3 copies `action ratio terms values roles swaps count conflicts added removed direction from_text to_text pairs`; it drops `from_values`, `to_values` and `reversals`, which remain in the flag. |

### 1.4 Hard fails

| `reason` | clause | `detail` (exact) | when |
|---|---|---|---|
| `no_change_reason` | 6.3 | "No reason for the change was recorded." or "The recorded reason does not describe the change." | Reason missing or invalid. **Rare in practice:** the proposal screen will not submit without an adequate overall reason. |
| `empty_revision` | 7.5.3 | "The proposed text is empty." | The section's new text is blank. |
| `no_change` | 7.5.3 | "The proposed text is identical to the current text." | Unreachable from the proposal screen, which refuses to check an unchanged section. |

A hard fail forces the verdict to `reject` at confidence 1.0; issues are still computed.

### 1.5 Advisories

| `label` | clause | `affects_verdict` | `evidence` | extra |
|---|---|---|---|---|
| `vague_change_reason` | 6.3 | true | always the fixed message: "This reason is vague, so a reviewer cannot tell what changed or why from it alone." | none |
| `malformed_citation` | 7.5.3 | false | up to three spans joined by "; ", then " (+n more)"; e.g. "...governed by Executive Order" | `kinds`: `split_abbreviation`, `truncated_citation` |
| `malformed_text` | 7.5.3 | false | same shape; unbalanced-bracket lines cut at 120 characters | `kinds`: `orphaned_acronym`, `unbalanced_brackets` |

All carry `severity: "low"`. Only faults the edit introduced are reported. None of the ten captured cases has an advisory.

### 1.6 The other arguments

| argument | type | example | notes |
|---|---|---|---|
| `section_label` | str | `"3.0 POLICIES"` | Number and title from the section's subtitle. Can be a title alone, or `""`. |
| `old_text`, `new_text` | str | the whole section | Full section texts. Tables arrive as pipe rows: `\| Accountant \| 1. Generates ... \|`; a continuation row has an empty first cell: `\| \| 2. Sort ... \|`. Policies are lines starting with their number: `3.4 Credentials ...`. |
| `audience` | str | `"submitter"` | `submitter` = the drafting office; `reviewer` = everyone else: concurring offices, the IMR, the custodian. The screen picks by `viewer_is_initiator`. |

### 1.7 The diff: what Layer 4 derives itself

Layer 1 does not hand over a structured diff. Today's Layer 4 builds one from `old_text` and `new_text` (class `_Change`). A new engine can keep it; it is in every example below as `diff_derived_by_layer4`.

| field | type | example | reliability |
|---|---|---|---|
| `hunks[]` | list | one per changed run; edits a word or two apart on one line are merged | reliable |
| `hunks[].tag` | str | `replace`, `delete`, `insert` | reliable |
| `hunks[].old`, `.new` | str | `"365 days or 1 year"` → `"180 days or 6 months"` | exact text |
| `hunks[].old_ctx`, `.new_ctx` | str | the same plus up to two unchanged words each side, stopping at a table cell or line break | reliable |
| `hunks[].removed`, `.added` | int | words (punctuation not counted) | reliable |
| `hunks[].punctuation_only` | bool | `true` for a comma | reliable |
| `hunks[].item` | str | `"3.6"`, `"step 2"` or `""` | Where it is. `"3.6"` for a numbered policy line, `"step n"` for a numbered table row. `""` for prose without numbers (e.g. 2.0 SCOPE). A continuation row is placed by its own step number, not by the role above it. |
| `words_removed`, `words_added` | int | totals | reliable |
| `items` | list of str | `["step 2", "step 3"]` | every place touched, in order |
| `removed_lines`, `added_lines` | list of str | whole lines that went or came (as pipe rows) | reliable |
| `only_whole_lines` | bool | the edit only removed or added whole lines | reliable |
| `lines_quotable` | bool | whole lines only, at most 3 of them, each ≤ 30 words | reliable |

**Not available anywhere:** the *role* that owns a table step (Layer 4 would have to walk up to the last non-empty first cell), which of several figures became which (§2, `numeric_changed`), and which other section a conflict is with (§2, `contradicts_manual`).

### 1.8 The verdict and the audience, today

- **Verdict:** `reject` or `needs_revision` gives every concern its question and what-to-check; `approve` gives them to the first concern only. With no concern, a non-approve verdict adds one paragraph saying the reading was "less settled than that suggests". Nothing else.
- **Audience:** changes the first heading ("What you changed" / "What changed") and the question's prefix ("Expect to be asked:" / "Worth asking the drafting office:"). Everything else is identical.

### 1.9 Available at the call site but not passed today

Passing any of these is a change to `pipeline.py`'s call to `explain()` only. Nothing before Layer 4 would see anything new, so the figures are unaffected.

| what | where it is now | could support |
|---|---|---|
| the change reason (overall, or the section's note if there is none) | `assess_texts(change_reason=...)`; Layer 1 grades it | quoting the reason, or noting that it does not mention what the check found |
| retrieved sections (top 3, text) | `related`; `retrieved_section_ids` stored by the view | naming which section a `contradicts_manual` conflict is with |
| the model's raw issue probabilities, all ten, below threshold too | `trace.layer2.issue_probs` | not recommended: below-threshold hints would reintroduce the overconfidence problem |
| the thresholds | `bundle["thresholds"]` (§2) | how far above its threshold a model-only issue is |
| the document title | `section.manual.title` | "FAM 6.02, 3.0 POLICIES" |

---

## 2. The issue labels and their evidence

Thresholds are the model's per-label cut-offs (`saved_models/context_v2/thresholds.json`). "Rule alone reaches `issues`" means a rule flag without the model's agreement survives the policy.

| label | severity | clause | model threshold | rule alone reaches `issues` | rules can raise it |
|---|---|---|---:|---|---|
| `excessive_deletion` | high | 7.5.3 | 0.85 | yes | yes |
| `key_term_deleted` | medium | 7.5.3 | 0.75 | no | yes |
| `modal_weakened` | medium | 7.5.3 | 0.95 | yes | yes |
| `negation_changed` | high | 7.5.3 | 0.85 | no | yes |
| `numeric_changed` | medium | 7.5.3 | 0.90 | no | yes |
| `responsibility_changed` | high | 5.3 | 0.85 | no | yes |
| `requirement_removed` | high | 7.5.3 | 0.80 | no | yes |
| `non_equivalent_term` | medium | 7.5.3 | 0.80 | yes | yes |
| `contradicts_manual` | high | 7.5.3 | 0.90 | no | yes |
| `out_of_scope_content` | medium | 7.5.3 | 0.75 | no | **never**: always model-only |

**For every label, a model-only issue has `evidence: ""` and no other field.** Everything below is the rule side (`source` `rule` or `both`).

| label | fields | reliably present | can be empty or misleading |
|---|---|---|---|
| `excessive_deletion` | `evidence` "55% of the wording was removed"; `ratio` 0.55 | both, whenever a rule raised it (ratio > 0.40) | none. Model-only: use `features.net_deleted_word_ratio`, always present. |
| `key_term_deleted` | `evidence` "term, term" (first 5); `terms` full list | `terms`, at least one | Terms are as the entity list spells them (often lower case). Includes statutes no longer cited ("republic act 10173"). **Case 01:** model-only at 0.98 on a typo fix, with `key_terms_deleted_count` 0. |
| `modal_weakened` | `evidence` '"shall" became "may"'; `pairs` [["shall","may"]] | `evidence` | `pairs` is **empty** when the weakening is not a one-word swap (a "shall" sentence removed, a "may" sentence added); `evidence` is then "an obligation became a permission". |
| `negation_changed` | `evidence` '"not"' or '"before" became "after"'; `action` added / removed / changed / reversed; `added`, `removed` (negation words); `reversals` (flag only) | `action`, `evidence` | Deleting a whole sentence that contained "not" reads as `action: "removed"` (case 10): **not necessarily a reversal**. `added` or `removed` is empty for a reversal. |
| `numeric_changed` | `evidence` '"1 year", "365 days" to "180 days", "6 months"'; `values`; `direction` changed / added / removed; `from_text`, `to_text` (pre-quoted, comma-joined); `from_values`, `to_values` (flag only) | `direction`, `values` | **Not paired**: each side is sorted alphabetically, so "which became which" is unknown with more than one figure. One side is empty for added or removed. **Frequency words count as figures**: "timely", "immediately", "monthly" (case 03, where the rule's `numeric_changed` on "timely" was then dropped by the policy). |
| `responsibility_changed` | `evidence` "accountant, records management staff"; `roles` | `roles`, at least one | Roles are **normalised lower case** and the list is the **symmetric difference**: it does not say who left and who arrived (today's Layer 4 finds each in the texts). A role deleted along with its whole step also fires (case 09). |
| `requirement_removed` | `evidence` the first removed sentence; `count` | `count` ≥ 1 | `evidence` is cut at **160 characters, mid-word** ("...implementation of the Fre", case 10), and for a table it can be a **fragment like "\| \| 4."** (cases 09, P1). `count` is inflated by tables: two rows removed gave `count: 4`. A **reassigned** row also raises it, since the old row no longer exists verbatim (case 08, dropped by the policy there). |
| `non_equivalent_term` | `evidence` '"a" became "b"'; `swaps` [[a, b]] | `swaps` | none: pairs the glossary marks as different in meaning. Modal and reversal pairs are excluded, since their own labels report them. |
| `contradicts_manual` | `evidence` "1 year"; `conflicts` [{`value`, `kind` numeric / role}] | `conflicts` | Gives the **value only, not which section** still has it. Fires when the other section is being changed consistently in the same proposal (P2, the known interim gap). Dropped by the policy unless the model agrees, so in `issues` it is usually model-only with no evidence at all. |
| `out_of_scope_content` | none | nothing | Always model-only, always without evidence. **Case 05:** 0.96 on a clarifying sentence. |

**How often a model-only issue is wrong where the rules looked and found nothing** is the diagnosis in EVALUATION.md §1: cases 01, 03 and 05 are all model-only, and all three are harmless edits. Today's note calls these "a possible false lead" when the matching feature is zero (`_RULE_COUNTERPART` in §4).

---

## 3. Multi-section proposals

**Today: one note per changed section, and no note for the proposal.** Each section's check runs when its **Run the check** button is pressed, and is stored against that section's change. Editing a section clears only its own check. The notes are rendered under their sections, and nothing combines them.

**What each section's check receives from the proposal:** the proposal's overall reason, or the section's own note when there is no overall reason (`version.overall_reason or change.note`). When both exist, **the section's note is not passed**. Nothing else about the proposal reaches the pipeline, and it must not reach Layers 1-2.

**What exists at proposal level** (all in the database, readable at display time):

| what | where |
|---|---|
| the document, its series, the owning and initiating offices | `Proposal`, `Manual`, `ManualSeries` |
| version number, overall reason | `ProposalVersion.number`, `.overall_reason` |
| every changed section: label, order, old and new text, its note | `SectionChange` |
| each section's stored check: all of §1's fields except `marked` and `features`, which are in `trace.layer1` | `RevisionPreAssessment` (`issues`, `advisories`, `hard_fails`, `change_type`, `verdict`, `confidence`, `trace`) |
| which sections each check retrieved | `RevisionPreAssessment.retrieved_section_ids` |
| whether each check is current | `SectionChange.check_is_current` |
| who is reading | `viewer_is_initiator` |

**The coordinated-change line** is the only cross-section text today. It is computed at display time, not by Layer 4, and shown under the section's note: *"This may be because 4.0 PROCEDURES is also being changed in this proposal."* It fires only when `contradicts_manual` is in the section's **issues** and a retrieved section is also changed. The P2 capture shows the gap: both sections' **rules** found the "1 year" conflict, the policy dropped it (the model did not agree), and the line did not appear.

**The constraint on a proposal-level note:** checks are never re-run for display. A proposal note would therefore have to be **composed from the stored section checks**, either at display time or once when the proposal is submitted (frozen with the version). Composing stored results is not re-running. Things it could say from what is stored: how many sections changed and which carry concerns; the same figure changed consistently across sections (P2: "365 days / 1 year" → "180 days / 6 months" in 3.0, "1 year" → "6 months" in 4.5); a rule conflict that points at another changed section; the reason advisory once, instead of on every section. **Open for you to decide:** whether there is a proposal note, and whether a section's note may refer to other sections, since today it cannot.

---

## 4. The current wording

Everything Layer 4 writes today, from `layer4_explain.py` at `cf26b04`. The tables are printed from the module itself.

### 4.1 Format and headings

Parts are separated by a blank line and open with a heading. `- ` opens an item, two leading spaces continue it, anything else is a paragraph. Parts in order, each only when it has content:

| part | heading (submitter / reviewer) |
|---|---|
| 1 | "What you changed" / "What changed" |
| 2 | "What to look at" |
| 3 | "What looks fine" |
| 4 | "What this check can't tell you" |

At most **5** concerns are written out (`MAX_CONCERNS`). The rest become one item: "Also noted: {up to three short names, joined}." Order: hard fails, then concerns (the rules-corroborated ones first, then the "possible false lead" ones), then the leftover line, then advisories.

### 4.2 Part 1: what changed

Chosen in this order; `{where}` is "{section}, at {items joined}", or just "{section}", and `{section}` falls back to "this section".

| when | template |
|---|---|
| no word changed, only spacing | "A formatting change to {section}: only spacing or line breaks moved." |
| whole lines only, quotable | "Removed {n} line(s) from {section}: “{line}”; “{line}”." and/or "Added {n} line(s) to {section}: “{line}”." |
| whole lines only, not quotable | "Removed {n} lines from {section}, at {items}." / "Added {n} lines to {section}, at {items}." |
| one insertion of 5-30 words ending a sentence | "An added sentence in {where}: “{sentence}”." |
| ≤ 3 hunks, each ≤ 12 words each side | "{kind} to {where}: “{old_ctx}” → “{new_ctx}”; ..." with " ({item})" after each when there are several places. `{kind}`: "A punctuation fix" (cosmetic, punctuation only), "A spelling or formatting fix" (other cosmetic), "A change of terms" (equivalent terms), "A small wording edit" (anything else). |
| otherwise | "{A large change / A moderate change} to {where}: {n} words removed and {n} words added[, about {share} of the section's wording]." Large: ≥ 30% removed or added, or over 60 words. The share is added only when large and ≥ 30% removed. |

Numbers under eleven are written as words ("two lines").

### 4.3 Part 2: each concern

An item is: **lead** + (**doubt** *or* **why**), then, when detailed, **ask** and **check**, then the **clause line**.

- **Detailed** when the verdict is `reject` or `needs_revision`, or the concern is the first. Never when a doubt is present.
- **Ask** prefix: "Expect to be asked: " (submitter) / "Worth asking the drafting office: " (reviewer). **Check** prefix: "To check: ".
- **Clause line**, first time a clause appears: "This touches ISO 9001:2015 clause {clause}, which asks that {asks_that}." After that: "This also touches clause {clause}."
- **Placement:** "At {item}, {text}." when the place is known; "In this section, {text}." when the text opens on a quotation mark; otherwise the text capitalised.

**Leads, rule-sourced** (`source` `rule` or `both`):

| label | lead |
|---|---|
| `excessive_deletion` | "{ratio as %, or "A large part"} of the section's wording was removed." |
| `key_term_deleted` | "In this section, “{t}” no longer appears in the section." / "In this section, “{t}”, “{t}” and “{t}” no longer appear in the section." (up to 3 terms; never placed at an item) |
| `modal_weakened` | "At {item}, “{a}” became “{b}”, so a requirement becomes a permission." (up to 3 pairs; the evidence when there are none) |
| `negation_changed` (added / removed) | "At {item}, “{word}” was {added/removed}, which reverses what the sentence requires." |
| `negation_changed` (other) | "At {item}, {evidence}, which reverses the sense of the requirement." |
| `numeric_changed` | "At {item}, a figure changed: {from} became {to}." / "a figure was added: {to}" / "a figure was removed: {from}" / "a figure changed: {evidence}" |
| `responsibility_changed` | "At {item}, {gone} is no longer named; {came} is named instead." / "{gone} is no longer named" / "{came} is now named" / "a step changed hands ({roles})" |
| `requirement_removed` | "A requirement no longer appears: “{text}”." / "{N} requirements no longer appear: “{text}”; “{text}”." / "...: it is the line removed above." / "...: they are the lines removed above." / "... in the section." |
| `non_equivalent_term` | "At {item}, “{a}” became “{b}”; this manual does not treat them as meaning the same." |
| `contradicts_manual` | "Another section of this document still uses “{value}”, which this change replaces here." |
| `out_of_scope_content` | "At {item}, the added wording may go beyond what this section covers." (never reached: the rules never raise it) |

**Leads, model-only:** "{strength} {what}, though it found no specific words to point to." Strength: above 0.85 "The check's model strongly suspects"; above 0.65 "The check's model suspects"; otherwise "The check's model sees a possibility". Since every model-only issue is at or above its threshold (0.75-0.95), the weakest phrase is unreachable and the strongest is the usual one.

**Doubt**, model-only only, replacing *why* and suppressing ask and check: "The rule check found that {what the rules found}, so this may be a false lead." For `excessive_deletion`: "The rule check measured {share} of the wording as removed, so this may be a false lead." (only when under 40%).

**Per label** (printed from `_WHY`, `_ASK`, `_CHECK`, `_CANNOT_TELL`, `_MODEL_ONLY`, `_RULE_COUNTERPART` and `_SHORT_NAME`):

`excessive_deletion`
- why: Readers lose guidance they relied on, and whatever the removed text required stops being required unless it is stated somewhere else.
- ask: Is everything that was removed covered somewhere else?
- check: Compare the two versions and note where each removed requirement now lives.
- can't tell: Whether what was removed is covered by another manual, a memorandum or a form.
- model-only: {what}: that a large part of the section was removed
- doubt: the rules found: the share removed, when under 40%
- short name: a large removal

`key_term_deleted`
- why: Other sections, forms and audits may refer to it; without it, readers may not know which form, office or rule applies.
- ask: Is it still needed, or has something replaced it?
- check: Search the document and its forms for other references to it.
- can't tell: Whether the dropped term is still in use elsewhere, such as on a form or in a system.
- model-only: {what}: that a term the section depends on — a defined term, a form name or a legal reference — was dropped
- doubt: the rules found: no listed term, form name or legal reference is missing from the new text (when `key_terms_deleted_count` is 0)
- short name: a dropped term

`modal_weakened`
- why: People following the section may now treat the step as optional, and an auditor can no longer hold the office to it.
- ask: Is this step meant to become optional, and who decides when it is skipped?
- check: Read the sentence as someone who would rather skip the step, and see whether it still holds.
- can't tell: Whether the law or policy this section rests on allows the change.
- model-only: {what}: that an obligation was softened into a permission
- doubt: the rules found: no “shall”, “must” or “should” gave way to “may” or “can” (when `modal_weakened_count` is 0)
- short name: a softened obligation

`negation_changed`
- why: The section now allows what it prohibited, or the reverse, so the people applying it will act the opposite way.
- ask: Is the reversal intended, and does the law or policy behind this section allow it?
- check: Read the sentence before and after, and confirm the new meaning is the one intended.
- can't tell: Whether the law or policy this section rests on allows the change.
- model-only: {what}: that a negation changed, reversing what the section requires
- doubt: the rules found: no “not”, “no” or “never” was added or removed (when `negation_changed` is 0)
- short name: a changed negation

`numeric_changed`
- why: Offices schedule and measure their work against this figure, and forms, systems and other sections that repeat it may now disagree.
- ask: Where does the new figure come from: a memorandum, a policy or a law?
- check: Look for other sections, forms and systems that use the same figure.
- can't tell: Whether the new figure matches the memorandum, policy or law it comes from.
- model-only: {what}: that a figure, deadline or amount changed
- doubt: the rules found: no figure changed (when `numeric_changed_count` is 0)
- short name: a changed figure

`responsibility_changed`
- why: The office now named takes on the work and the accountability for it; if it has not agreed, the step may go undone.
- ask: Has the office now named agreed to take this on?
- check: Confirm with the office now named, and look for other sections that assign the same step.
- can't tell: Whether the office now named has agreed, and has the people to do the work.
- model-only: {what}: that the party responsible for a step changed
- doubt: the rules found: no named role was added or removed (when `role_terms_changed_count` is 0)
- short name: a change of responsibility

`requirement_removed`
- why: Whatever the removed text required is no longer required by this document, and an auditor will no longer look for it.
- ask: Why is this no longer required, and is it covered somewhere else?
- check: Say where the requirement now lives, or state in the reason that it is being dropped.
- can't tell: Whether what was removed is covered by another manual, a memorandum or a form.
- model-only: {what}: that a required step was removed
- doubt: the rules found: no sentence of the old text is missing from the new one (when `sentences_removed` is 0)
- short name: a removed requirement

`non_equivalent_term`
- why: Readers may apply the new term differently from how the rest of the manual uses it, so the same rule could be read two ways.
- ask: Is the new term meant to change what is being asked?
- check: See how this manual uses both terms elsewhere.
- can't tell: What the new wording is meant to change: the check reads words, not intent.
- model-only: {what}: that a term was replaced with one that means something different in this manual
- doubt: the rules found: none: no doubt is ever written
- short name: a non-equivalent term

`contradicts_manual`
- why: Readers following one section will act differently from those following the other, and an auditor will ask which one applies.
- ask: Which statement is correct, and will the other section change to match?
- check: Open the other section and decide which statement stands; if it is also being changed in this proposal, say so.
- can't tell: Which of the two statements the university actually follows.
- model-only: {what}: that the change conflicts with another section of this document
- doubt: the rules found: none: no doubt is ever written
- short name: a conflict with another section

`out_of_scope_content`
- why: Readers looking for this rule may not find it where it belongs, and the same point may end up stated in two places.
- ask: Does this belong in this section, or in another one?
- check: See whether another section already covers it.
- can't tell: Whether the added wording is accurate, and where readers expect to find it.
- model-only: {what}: that the added wording goes beyond what this section covers
- doubt: the rules found: none: no doubt is ever written
- short name: content outside the section's scope

### 4.4 Hard fails and advisories

| finding | item |
|---|---|
| hard fail | its `detail`, with a full stop. For `no_change_reason` add: " The reason is the record that the change was planned, and the first thing a reviewer or auditor reads." Then the clause line. |
| `vague_change_reason` | "The reason given is too general to show what prompted the change or what it is meant to achieve. {evidence}." then the clause line |
| `malformed_citation` | "A legal reference looks broken after the edit: {evidence, cut at 120}." then the clause line |
| `malformed_text` | "The edit left text that looks broken: {evidence, cut at 120}." then the clause line |

### 4.5 Part 2 with no concerns, and parts 3 and 4

- **No concern and a non-approve verdict:** "No specific concern passed its threshold, but the check's overall reading of this change was less settled than that suggests. It is worth reading once more against what the section is for."
- **What looks fine:**
  - with no concern at all, first: "No specific concern passed its threshold."
  - cosmetic: "Nothing the section requires has changed; the edit touches spelling, punctuation or layout only." (and stop)
  - equivalent terms: "“{a}” and “{b}” mean the same thing in this manual, so the requirement is unchanged." or, without pairs, "The terms swapped mean the same thing in this manual, so the requirement is unchanged." (and stop)
  - otherwise: "No {figure / obligation / named role, joined with "or"} changed." (each only if its feature is 0 and no concern contradicts it), and "Nothing was removed." (if no words or sentences went and no removal concern)
- **What this check can't tell you:** one line per concern label (table above), unless the concern carries a doubt; at most 3. With none, when words were added and the change is not cosmetic or equivalent: "Whether the {added/new} wording is accurate: the check compares wording, not facts."

### 4.6 Outside the note

- **List of Forms sections** are not checked: "Not checked: {section} is a list of forms rather than a requirement, so the check does not assess it."
- **Coordinated change** (`proposal_views._coordinated_advisory`, shown under the note): "This may be because {sections, comma-joined} is/are also being changed in this proposal."
- **Legacy notes** (single paragraphs from before the current format) have 23 exact verdict sentences stripped on the way out (`_LEGACY_VERDICT_SENTENCES`). Reference only; not wording to draft.

### 4.7 `iso_relevance.json`

```json
{
  "_about": [
    "Which ISO 9001:2015 clause each concern in the AI note relates to, and how the note paraphrases that clause.",
    "Read by Layer 4 only (layer4_explain.py). Nothing here reaches Layers 1-3, the trained model or the published figures.",
    "Paraphrases are our own words. Never paste text from the standard: it is copyrighted. Refer to clause numbers only.",
    "The note prints: 'This touches ISO 9001:2015 clause <clause>, which asks that <asks_that>.' - so each asks_that must complete that sentence.",
    "The clause for each trained issue label must also match config.ISSUE_CLAUSE, which stamps the clause onto each stored issue. A test enforces it.",
    "Status: DRAFT - to be confirmed with the QMS office. Only 6.3, 7.5.3 and 5.3 are used, per PROGRESS.md decision 7."
  ],
  "standard": "ISO 9001:2015",
  "clauses": {
    "5.3": {
      "asks_that": "each role's responsibilities and authority are given to someone specific and made known to the people who work with them"
    },
    "6.3": {
      "asks_that": "changes to how the organisation works are made on purpose, with their reasons and their knock-on effects thought through before they take effect"
    },
    "7.5.3": {
      "asks_that": "the documents people work from stay correct, usable and protected, and that changes to them are controlled so everyone works from the right version"
    }
  },
  "concerns": {
    "excessive_deletion": "7.5.3",
    "key_term_deleted": "7.5.3",
    "modal_weakened": "7.5.3",
    "negation_changed": "7.5.3",
    "numeric_changed": "7.5.3",
    "responsibility_changed": "5.3",
    "requirement_removed": "7.5.3",
    "non_equivalent_term": "7.5.3",
    "contradicts_manual": "7.5.3",
    "out_of_scope_content": "7.5.3",

    "no_change_reason": "6.3",
    "vague_change_reason": "6.3",
    "empty_revision": "7.5.3",
    "no_change": "7.5.3",
    "malformed_citation": "7.5.3",
    "malformed_text": "7.5.3"
  }
}
```

---

## 5. Real inputs

### Section texts

The `old_text` of every example below, as the database holds it. Each `new_text` is this with the edit applied; the hunks in `diff_derived_by_layer4` are the complete difference. Full texts, `marked`, and the current note for both audiences are in `LAYER4_INPUT_CASES.json`.

**2.0 SCOPE**

```text
These procedures apply to all accounts receivable arising from the official transactions of the University such as from the operations of the LNU House, of the LNU Cafeteria, and Inter-Agency transaction with the Commission on Higher Education (CHED) for the implementation of the Free Higher Education, among others.
```

**3.0 POLICIES**

```text
3.1 Any records which may contain personal information shall be handled in accordance with Republic Act 10173 or the Data Privacy Act of 2012.
3.2 Any request for information shall be governed by Executive Order No. 02, series of 2016 or the Freedom of Information.
3.3 Accounts Receivable should be collected in a timely manner.
3.4 Credentials and official records of Undergraduate students will not be released if they still have unpaid school fees prior to the implementation of the Free Higher Education.
3.5 Credentials and official records of ILS/PLC and Masters/Doctoral students will only be released upon settlement of all their assessed school fees.
3.6 Accounts Receivable that are outstanding for more than 365 days or 1 year are considered past due already.
3.7 Demand Letters should be sent to the debtors for those past due accounts.
```

**4.4 Accounts Receivable from Employees**

```text
| Responsibility | Activity |
| --- | --- |
| Employees | 1. Submit Promissory Notes to the Accounting Office. |
| Accounting Staff-7 | 2. Prepares Summary of all the Promissory Notes received from the employees for the payment of school fees of their children including books, for the payment of their own school fees at the Graduate School, among others. The Summary shall include a column if which particular claim of the employee (e.g. midyear bonus, year-end bonus, CNA Incentive, IGP Incentive, Honoraria, etc.) the said the accountability will be charged or deducted from. |
| | 3. Furnish the Payroll Preparer, Accounting Staff, a copy of the Summary so that it can be deducted to the claims of the employees. |
| Accounting Staff-2 | 4. Effects the deduction in the payroll. |
```

**4.5 Accounts Receivable from Other Debtors**

```text
| Responsibility | Activity |
| --- | --- |
| Accountant | 1. Generates the Schedule of Accounts Receivable with Aging using the eNGAS System. |
| | 2. Sort those accounts with age of over 1 year. |
| | 3. Prepares Demand Letters to those debtors with accounts aging over 1 year. |
| | 4. Forwards copies of the demand letters to the University President for signature. |
| University President | 5. Signs the Demand Letters. |
| Records Management Staff | 6. Sends the Demand Letters to the debtors through a courier if necessary. |
```

The change reason for every check: *"Aligned with the collection guidelines adopted at the August 2026 management review."* It passes the reason check, so no case carries a reason advisory.

### Summary

| case | edit | verdict (hidden) | issues reaching Layer 4 | rule flags the policy dropped |
|---|---|---|---|---|
| 01_typo | a duplicated word removed (typo) | needs_revision 0.9511 | `key_term_deleted` model 0.9832 | none |
| 02_comma | a comma added | approve 0.9989 | none | none |
| 03_near_synonym | "in a timely manner" -> "promptly" | reject 0.9968 | `negation_changed` model 0.914 | `numeric_changed` |
| 04_shall_may | "shall" -> "may" | needs_revision 1.0 | `modal_weakened` both | none |
| 05_clarifying | a clarifying sentence added | reject 0.9997 | `out_of_scope_content` model 0.9604 | none |
| 06_figure | 365 days -> 180 days | reject 0.8266 | `numeric_changed` both | `contradicts_manual` |
| 07_not_removed | "not" removed | reject 1.0 | `negation_changed` both | none |
| 08_reassigned | a step reassigned | reject 1.0 | `responsibility_changed` both | `requirement_removed` |
| 09_approvals_removed | two approval steps removed | reject 1.0 | `requirement_removed` both | `responsibility_changed` |
| 10_policies_deleted | two policies deleted | reject 1.0 | `requirement_removed` both | `negation_changed`, `responsibility_changed`, `contradicts_manual` |
| P1_mixed | 2.0 SCOPE | approve 1.0 | none | none |
| P1_mixed | 4.5 Accounts Receivable from Other Debtors | reject 1.0 | `requirement_removed` both | `responsibility_changed` |
| P2_coordinated | 3.0 POLICIES | reject 0.8266 | `numeric_changed` both | `contradicts_manual` |
| P2_coordinated | 4.5 Accounts Receivable from Other Debtors | needs_revision 0.9999 | `numeric_changed` both | `contradicts_manual` |

### The ten diagnosis cases

```json
{
  "01_typo": {
    "edit": "a duplicated word removed (typo)",
    "section_label": "4.4 Accounts Receivable from Employees",
    "old_text": "<the current text of 4.4 Accounts Receivable from Employees - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "needs_revision",
      "confidence": 0.9511,
      "issues": [
        {
          "label": "key_term_deleted",
          "source": "model",
          "confidence": 0.9832,
          "severity": "medium",
          "clause": "7.5.3",
          "evidence": ""
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0468, "needs_revision": 0.9511, "reject": 0.0022},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0061,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.0061,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "delete",
          "old": "the",
          "new": "",
          "old_ctx": "the said the accountability will",
          "new_ctx": "the said accountability will",
          "removed": 1,
          "added": 0,
          "punctuation_only": false,
          "item": "step 2"
        }
      ],
      "words_removed": 1,
      "words_added": 0,
      "items": ["step 2"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "02_comma": {
    "edit": "a comma added",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "approve",
      "confidence": 0.9989,
      "issues": [],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.9989, "needs_revision": 0.0, "reject": 0.0011},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "cosmetic",
      "hard_fails": [],
      "advisories": [],
      "flags": [],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0,
        "inserted_word_ratio": 0.0062,
        "net_deleted_word_ratio": 0.0,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "insert",
          "old": "",
          "new": ",",
          "old_ctx": "1 year are considered",
          "new_ctx": "1 year, are considered",
          "removed": 0,
          "added": 0,
          "punctuation_only": true,
          "item": "3.6"
        }
      ],
      "words_removed": 0,
      "words_added": 0,
      "items": ["3.6"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "03_near_synonym": {
    "edit": "\"in a timely manner\" -> \"promptly\"",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 0.9968,
      "issues": [
        {
          "label": "negation_changed",
          "source": "model",
          "confidence": 0.914,
          "severity": "high",
          "clause": "7.5.3",
          "evidence": ""
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0032, "needs_revision": 0.0, "reject": 0.9968},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "numeric_changed",
          "clause": "7.5.3",
          "severity": "medium",
          "evidence": "\"timely\"",
          "values": ["timely"],
          "from_values": ["timely"],
          "to_values": [],
          "direction": "removed",
          "from_text": "\"timely\"",
          "to_text": ""
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.0248,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 1,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "replace",
          "old": "in a timely manner",
          "new": "promptly",
          "old_ctx": "be collected in a timely manner.",
          "new_ctx": "be collected promptly.",
          "removed": 4,
          "added": 1,
          "punctuation_only": false,
          "item": "3.3"
        }
      ],
      "words_removed": 4,
      "words_added": 1,
      "items": ["3.3"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "04_shall_may": {
    "edit": "\"shall\" -> \"may\"",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "needs_revision",
      "confidence": 1.0,
      "issues": [
        {
          "label": "modal_weakened",
          "source": "both",
          "confidence": 1.0,
          "severity": "medium",
          "clause": "7.5.3",
          "evidence": "\"shall\" became \"may\"",
          "pairs": [["shall", "may"]]
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0, "needs_revision": 1.0, "reject": 0.0},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "modal_weakened",
          "clause": "7.5.3",
          "severity": "medium",
          "evidence": "\"shall\" became \"may\"",
          "pairs": [["shall", "may"]]
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.0062,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 1,
        "negation_changed": 0,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 1,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "replace",
          "old": "shall",
          "new": "may",
          "old_ctx": "personal information shall be handled",
          "new_ctx": "personal information may be handled",
          "removed": 1,
          "added": 1,
          "punctuation_only": false,
          "item": "3.1"
        }
      ],
      "words_removed": 1,
      "words_added": 1,
      "items": ["3.1"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "05_clarifying": {
    "edit": "a clarifying sentence added",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 0.9997,
      "issues": [
        {
          "label": "out_of_scope_content",
          "source": "model",
          "confidence": 0.9604,
          "severity": "medium",
          "clause": "7.5.3",
          "evidence": ""
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0003, "needs_revision": 0.0, "reject": 0.9997},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0,
        "inserted_word_ratio": 0.0932,
        "net_deleted_word_ratio": 0.0,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "insert",
          "old": "",
          "new": "The age of an account is counted from the date the receivable was recorded.",
          "old_ctx": "",
          "new_ctx": "The age of an account is counted from the date the receivable was recorded.",
          "removed": 0,
          "added": 14,
          "punctuation_only": false,
          "item": "3.6"
        }
      ],
      "words_removed": 0,
      "words_added": 14,
      "items": ["3.6"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "06_figure": {
    "edit": "365 days -> 180 days",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 0.8266,
      "issues": [
        {
          "label": "numeric_changed",
          "source": "both",
          "confidence": 1.0,
          "severity": "medium",
          "clause": "7.5.3",
          "evidence": "\"1 year\", \"365 days\" to \"180 days\", \"6 months\"",
          "values": ["1 year", "365 days", "180 days", "6 months"],
          "direction": "changed",
          "from_text": "\"1 year\", \"365 days\"",
          "to_text": "\"180 days\", \"6 months\""
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0005, "needs_revision": 0.173, "reject": 0.8266},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "numeric_changed",
          "clause": "7.5.3",
          "severity": "medium",
          "evidence": "\"1 year\", \"365 days\" to \"180 days\", \"6 months\"",
          "values": ["1 year", "365 days", "180 days", "6 months"],
          "from_values": ["1 year", "365 days"],
          "to_values": ["180 days", "6 months"],
          "direction": "changed",
          "from_text": "\"1 year\", \"365 days\"",
          "to_text": "\"180 days\", \"6 months\""
        },
        {
          "label": "contradicts_manual",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "1 year",
          "conflicts": [{"value": "1 year", "kind": "numeric"}]
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.0186,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 4,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 3,
        "cross_ref_conflict_count": 1
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "replace",
          "old": "365 days or 1 year",
          "new": "180 days or 6 months",
          "old_ctx": "more than 365 days or 1 year are considered",
          "new_ctx": "more than 180 days or 6 months are considered",
          "removed": 3,
          "added": 3,
          "punctuation_only": false,
          "item": "3.6"
        }
      ],
      "words_removed": 3,
      "words_added": 3,
      "items": ["3.6"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "07_not_removed": {
    "edit": "\"not\" removed",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 1.0,
      "issues": [
        {
          "label": "negation_changed",
          "source": "both",
          "confidence": 1.0,
          "severity": "high",
          "clause": "7.5.3",
          "evidence": "\"not\"",
          "action": "removed",
          "added": [],
          "removed": ["not"]
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0, "needs_revision": 0.0, "reject": 1.0},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "negation_changed",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "\"not\"",
          "action": "removed",
          "added": [],
          "removed": ["not"],
          "reversals": []
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0062,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.0062,
        "sentences_removed": 0,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 1,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 0,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "delete",
          "old": "not",
          "new": "",
          "old_ctx": "students will not be released",
          "new_ctx": "students will be released",
          "removed": 1,
          "added": 0,
          "punctuation_only": false,
          "item": "3.4"
        }
      ],
      "words_removed": 1,
      "words_added": 0,
      "items": ["3.4"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "08_reassigned": {
    "edit": "a step reassigned",
    "section_label": "4.5 Accounts Receivable from Other Debtors",
    "old_text": "<the current text of 4.5 Accounts Receivable from Other Debtors - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 1.0,
      "issues": [
        {
          "label": "responsibility_changed",
          "source": "both",
          "confidence": 1.0,
          "severity": "high",
          "clause": "5.3",
          "evidence": "accountant, records management staff",
          "roles": ["accountant", "records management staff"]
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0, "needs_revision": 0.0, "reject": 1.0},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "responsibility_changed",
          "clause": "5.3",
          "severity": "high",
          "evidence": "accountant, records management staff",
          "roles": ["accountant", "records management staff"]
        },
        {
          "label": "requirement_removed",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "| Records Management Staff | 6.",
          "count": 1
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.0,
        "deleted_word_ratio": 0.0,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.0256,
        "sentences_removed": 1,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 2,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "replace",
          "old": "Records Management Staff",
          "new": "Accountant",
          "old_ctx": "Records Management Staff",
          "new_ctx": "Accountant",
          "removed": 3,
          "added": 1,
          "punctuation_only": false,
          "item": "step 6"
        }
      ],
      "words_removed": 3,
      "words_added": 1,
      "items": ["step 6"],
      "removed_lines": [],
      "added_lines": [],
      "only_whole_lines": false,
      "lines_quotable": false
    }
  },
  "09_approvals_removed": {
    "edit": "two approval steps removed",
    "section_label": "4.5 Accounts Receivable from Other Debtors",
    "old_text": "<the current text of 4.5 Accounts Receivable from Other Debtors - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 1.0,
      "issues": [
        {
          "label": "requirement_removed",
          "source": "both",
          "confidence": 1.0,
          "severity": "high",
          "clause": "7.5.3",
          "evidence": "| | 4.",
          "count": 4
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0, "needs_revision": 0.0, "reject": 1.0},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "responsibility_changed",
          "clause": "5.3",
          "severity": "high",
          "evidence": "university president",
          "roles": ["university president"]
        },
        {
          "label": "requirement_removed",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "| | 4.",
          "count": 4
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.25,
        "deleted_word_ratio": 0.2564,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.2564,
        "sentences_removed": 4,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 0,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 1,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 0
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "delete",
          "old": "| 4. Forwards copies of the demand letters to the University President for signature. |\n| University President | 5. Signs the Demand Letters. |\n|",
          "new": "",
          "old_ctx": "| 4. Forwards copies of the demand letters to the University President for signature. |\n| University President | 5. Signs the Demand Letters. |\n| Records Management",
          "new_ctx": "Records Management",
          "removed": 20,
          "added": 0,
          "punctuation_only": false,
          "item": "step 4"
        }
      ],
      "words_removed": 20,
      "words_added": 0,
      "items": ["step 4"],
      "removed_lines": [
        "| | 4. Forwards copies of the demand letters to the University President for signature. |",
        "| University President | 5. Signs the Demand Letters. |"
      ],
      "added_lines": [],
      "only_whole_lines": true,
      "lines_quotable": true
    }
  },
  "10_policies_deleted": {
    "edit": "two policies deleted",
    "section_label": "3.0 POLICIES",
    "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
    "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
    "fusion_result": {
      "verdict": "reject",
      "confidence": 1.0,
      "issues": [
        {
          "label": "requirement_removed",
          "source": "both",
          "confidence": 1.0,
          "severity": "high",
          "clause": "7.5.3",
          "evidence": "3.4 Credentials and official records of Undergraduate students will not be released if they still have unpaid school fees prior to the implementation of the Fre",
          "count": 2
        }
      ],
      "advisories": [],
      "overrides": [],
      "probabilities": {"approve": 0.0, "needs_revision": 0.0, "reject": 1.0},
      "confidence_source": "fusion"
    },
    "layer1_result": {
      "change_type": "substantive",
      "hard_fails": [],
      "advisories": [],
      "flags": [
        {
          "label": "negation_changed",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "\"not\"",
          "action": "removed",
          "added": [],
          "removed": ["not"],
          "reversals": []
        },
        {
          "label": "responsibility_changed",
          "clause": "5.3",
          "severity": "high",
          "evidence": "student",
          "roles": ["student"]
        },
        {
          "label": "requirement_removed",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "3.4 Credentials and official records of Undergraduate students will not be released if they still have unpaid school fees prior to the implementation of the Fre",
          "count": 2
        },
        {
          "label": "contradicts_manual",
          "clause": "7.5.3",
          "severity": "high",
          "evidence": "student",
          "conflicts": [{"value": "student", "kind": "role"}]
        }
      ],
      "equivalent_swaps": [],
      "features": {
        "deleted_line_ratio": 0.2857,
        "deleted_word_ratio": 0.3478,
        "inserted_word_ratio": 0.0,
        "net_deleted_word_ratio": 0.3478,
        "sentences_removed": 2,
        "key_terms_deleted_count": 0,
        "modal_weakened_count": 0,
        "negation_changed": 1,
        "numeric_changed_count": 0,
        "role_terms_changed_count": 1,
        "equivalent_swaps": 0,
        "non_equivalent_swaps": 0,
        "unknown_swaps": 0,
        "cross_ref_conflict_count": 1
      },
      "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
    },
    "diff_derived_by_layer4": {
      "hunks": [
        {
          "tag": "delete",
          "old": "4 Credentials and official records of Undergraduate students will not be released if they still have unpaid school fees prior to the implementation of the Free Higher Education.\n3.5 Credentials and official records of ILS/PLC and Masters/Doctoral students will only be released upon settlement of all their assessed school fees.\n3.",
          "new": "",
          "old_ctx": "3.4 Credentials and official records of Undergraduate students will not be released if they still have unpaid school fees prior to the implementation of the Free Higher Education.\n3.5 Credentials and official records of ILS/PLC and Masters/Doctoral students will only be released upon settlement of all their assessed school fees.\n3.6 Accounts",
          "new_ctx": "3.6 Accounts",
          "removed": 52,
          "added": 0,
          "punctuation_only": false,
          "item": "3.4"
        }
      ],
      "words_removed": 52,
      "words_added": 0,
      "items": ["3.4"],
      "removed_lines": [
        "3.4 Credentials and official records of Undergraduate students will not be released if they still have unpaid school fees prior to the implementation of the Free Higher Education.",
        "3.5 Credentials and official records of ILS/PLC and Masters/Doctoral students will only be released upon settlement of all their assessed school fees."
      ],
      "added_lines": [],
      "only_whole_lines": true,
      "lines_quotable": true
    }
  }
}
```

### Two multi-section proposals

**P1, mixed:** a comma added in 2.0 SCOPE alongside two approval steps removed from 4.5. **P2, coordinated:** the past-due period changed in 3.0 POLICIES and, consistently, in 4.5. Both use one overall reason.

```json
{
  "P1_mixed": {
    "description": "A harmless edit alongside a serious one",
    "overall_reason": "Aligned with the collection guidelines adopted at the August 2026 management review.",
    "sections": [
      {
        "retrieved_section_ids": [8988, 8987, 8985],
        "coordinated_change_advisory": null,
        "section_label": "2.0 SCOPE",
        "old_text": "<the current text of 2.0 SCOPE - see 'Section texts'>",
        "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
        "fusion_result": {
          "verdict": "approve",
          "confidence": 1.0,
          "issues": [],
          "advisories": [],
          "overrides": [],
          "probabilities": {"approve": 1.0, "needs_revision": 0.0, "reject": 0.0},
          "confidence_source": "fusion"
        },
        "layer1_result": {
          "change_type": "cosmetic",
          "hard_fails": [],
          "advisories": [],
          "flags": [],
          "equivalent_swaps": [],
          "features": {
            "deleted_line_ratio": 0.0,
            "deleted_word_ratio": 0.0,
            "inserted_word_ratio": 0.0185,
            "net_deleted_word_ratio": 0.0,
            "sentences_removed": 0,
            "key_terms_deleted_count": 0,
            "modal_weakened_count": 0,
            "negation_changed": 0,
            "numeric_changed_count": 0,
            "role_terms_changed_count": 0,
            "equivalent_swaps": 0,
            "non_equivalent_swaps": 0,
            "unknown_swaps": 0,
            "cross_ref_conflict_count": 0
          },
          "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
        },
        "diff_derived_by_layer4": {
          "hunks": [
            {
              "tag": "insert",
              "old": "",
              "new": ",",
              "old_ctx": "CHED) for the",
              "new_ctx": "CHED), for the",
              "removed": 0,
              "added": 0,
              "punctuation_only": true,
              "item": ""
            }
          ],
          "words_removed": 0,
          "words_added": 0,
          "items": [],
          "removed_lines": [],
          "added_lines": [],
          "only_whole_lines": false,
          "lines_quotable": false
        }
      },
      {
        "retrieved_section_ids": [8987, 8989, 8985],
        "coordinated_change_advisory": null,
        "section_label": "4.5 Accounts Receivable from Other Debtors",
        "old_text": "<the current text of 4.5 Accounts Receivable from Other Debtors - see 'Section texts'>",
        "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
        "fusion_result": {
          "verdict": "reject",
          "confidence": 1.0,
          "issues": [
            {
              "label": "requirement_removed",
              "source": "both",
              "confidence": 1.0,
              "severity": "high",
              "clause": "7.5.3",
              "evidence": "| | 4.",
              "count": 4
            }
          ],
          "advisories": [],
          "overrides": [],
          "probabilities": {"approve": 0.0, "needs_revision": 0.0, "reject": 1.0},
          "confidence_source": "fusion"
        },
        "layer1_result": {
          "change_type": "substantive",
          "hard_fails": [],
          "advisories": [],
          "flags": [
            {
              "label": "responsibility_changed",
              "clause": "5.3",
              "severity": "high",
              "evidence": "university president",
              "roles": ["university president"]
            },
            {
              "label": "requirement_removed",
              "clause": "7.5.3",
              "severity": "high",
              "evidence": "| | 4.",
              "count": 4
            }
          ],
          "equivalent_swaps": [],
          "features": {
            "deleted_line_ratio": 0.25,
            "deleted_word_ratio": 0.2564,
            "inserted_word_ratio": 0.0,
            "net_deleted_word_ratio": 0.2564,
            "sentences_removed": 4,
            "key_terms_deleted_count": 0,
            "modal_weakened_count": 0,
            "negation_changed": 0,
            "numeric_changed_count": 0,
            "role_terms_changed_count": 1,
            "equivalent_swaps": 0,
            "non_equivalent_swaps": 0,
            "unknown_swaps": 0,
            "cross_ref_conflict_count": 0
          },
          "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
        },
        "diff_derived_by_layer4": {
          "hunks": [
            {
              "tag": "delete",
              "old": "| 4. Forwards copies of the demand letters to the University President for signature. |\n| University President | 5. Signs the Demand Letters. |\n|",
              "new": "",
              "old_ctx": "| 4. Forwards copies of the demand letters to the University President for signature. |\n| University President | 5. Signs the Demand Letters. |\n| Records Management",
              "new_ctx": "Records Management",
              "removed": 20,
              "added": 0,
              "punctuation_only": false,
              "item": "step 4"
            }
          ],
          "words_removed": 20,
          "words_added": 0,
          "items": ["step 4"],
          "removed_lines": [
            "| | 4. Forwards copies of the demand letters to the University President for signature. |",
            "| University President | 5. Signs the Demand Letters. |"
          ],
          "added_lines": [],
          "only_whole_lines": true,
          "lines_quotable": true
        }
      }
    ],
    "section_ids": {"2.0 SCOPE": 8986, "4.5 Accounts Receivable from Other Debtors": 8990}
  },
  "P2_coordinated": {
    "description": "The same figure changed consistently in two sections",
    "overall_reason": "Aligned with the collection guidelines adopted at the August 2026 management review.",
    "sections": [
      {
        "retrieved_section_ids": [8988, 8990, 8986],
        "coordinated_change_advisory": null,
        "section_label": "3.0 POLICIES",
        "old_text": "<the current text of 3.0 POLICIES - see 'Section texts'>",
        "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
        "fusion_result": {
          "verdict": "reject",
          "confidence": 0.8266,
          "issues": [
            {
              "label": "numeric_changed",
              "source": "both",
              "confidence": 1.0,
              "severity": "medium",
              "clause": "7.5.3",
              "evidence": "\"1 year\", \"365 days\" to \"180 days\", \"6 months\"",
              "values": ["1 year", "365 days", "180 days", "6 months"],
              "direction": "changed",
              "from_text": "\"1 year\", \"365 days\"",
              "to_text": "\"180 days\", \"6 months\""
            }
          ],
          "advisories": [],
          "overrides": [],
          "probabilities": {"approve": 0.0005, "needs_revision": 0.173, "reject": 0.8266},
          "confidence_source": "fusion"
        },
        "layer1_result": {
          "change_type": "substantive",
          "hard_fails": [],
          "advisories": [],
          "flags": [
            {
              "label": "numeric_changed",
              "clause": "7.5.3",
              "severity": "medium",
              "evidence": "\"1 year\", \"365 days\" to \"180 days\", \"6 months\"",
              "values": ["1 year", "365 days", "180 days", "6 months"],
              "from_values": ["1 year", "365 days"],
              "to_values": ["180 days", "6 months"],
              "direction": "changed",
              "from_text": "\"1 year\", \"365 days\"",
              "to_text": "\"180 days\", \"6 months\""
            },
            {
              "label": "contradicts_manual",
              "clause": "7.5.3",
              "severity": "high",
              "evidence": "1 year",
              "conflicts": [{"value": "1 year", "kind": "numeric"}]
            }
          ],
          "equivalent_swaps": [],
          "features": {
            "deleted_line_ratio": 0.0,
            "deleted_word_ratio": 0.0,
            "inserted_word_ratio": 0.0,
            "net_deleted_word_ratio": 0.0186,
            "sentences_removed": 0,
            "key_terms_deleted_count": 0,
            "modal_weakened_count": 0,
            "negation_changed": 0,
            "numeric_changed_count": 4,
            "role_terms_changed_count": 0,
            "equivalent_swaps": 0,
            "non_equivalent_swaps": 0,
            "unknown_swaps": 3,
            "cross_ref_conflict_count": 1
          },
          "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
        },
        "diff_derived_by_layer4": {
          "hunks": [
            {
              "tag": "replace",
              "old": "365 days or 1 year",
              "new": "180 days or 6 months",
              "old_ctx": "more than 365 days or 1 year are considered",
              "new_ctx": "more than 180 days or 6 months are considered",
              "removed": 3,
              "added": 3,
              "punctuation_only": false,
              "item": "3.6"
            }
          ],
          "words_removed": 3,
          "words_added": 3,
          "items": ["3.6"],
          "removed_lines": [],
          "added_lines": [],
          "only_whole_lines": false,
          "lines_quotable": false
        }
      },
      {
        "retrieved_section_ids": [8987, 8985, 8989],
        "coordinated_change_advisory": null,
        "section_label": "4.5 Accounts Receivable from Other Debtors",
        "old_text": "<the current text of 4.5 Accounts Receivable from Other Debtors - see 'Section texts'>",
        "new_text": "<old_text with the edit applied - the hunks below are the whole difference>",
        "fusion_result": {
          "verdict": "needs_revision",
          "confidence": 0.9999,
          "issues": [
            {
              "label": "numeric_changed",
              "source": "both",
              "confidence": 1.0,
              "severity": "medium",
              "clause": "7.5.3",
              "evidence": "\"1 year\" to \"6 months\"",
              "values": ["1 year", "6 months"],
              "direction": "changed",
              "from_text": "\"1 year\"",
              "to_text": "\"6 months\""
            }
          ],
          "advisories": [],
          "overrides": [],
          "probabilities": {"approve": 0.0001, "needs_revision": 0.9999, "reject": 0.0001},
          "confidence_source": "fusion"
        },
        "layer1_result": {
          "change_type": "substantive",
          "hard_fails": [],
          "advisories": [],
          "flags": [
            {
              "label": "numeric_changed",
              "clause": "7.5.3",
              "severity": "medium",
              "evidence": "\"1 year\" to \"6 months\"",
              "values": ["1 year", "6 months"],
              "from_values": ["1 year"],
              "to_values": ["6 months"],
              "direction": "changed",
              "from_text": "\"1 year\"",
              "to_text": "\"6 months\""
            },
            {
              "label": "contradicts_manual",
              "clause": "7.5.3",
              "severity": "high",
              "evidence": "1 year",
              "conflicts": [{"value": "1 year", "kind": "numeric"}]
            }
          ],
          "equivalent_swaps": [],
          "features": {
            "deleted_line_ratio": 0.0,
            "deleted_word_ratio": 0.0,
            "inserted_word_ratio": 0.0,
            "net_deleted_word_ratio": 0.0342,
            "sentences_removed": 0,
            "key_terms_deleted_count": 0,
            "modal_weakened_count": 0,
            "negation_changed": 0,
            "numeric_changed_count": 2,
            "role_terms_changed_count": 0,
            "equivalent_swaps": 0,
            "non_equivalent_swaps": 0,
            "unknown_swaps": 4,
            "cross_ref_conflict_count": 1
          },
          "marked": "<omitted: old/new text with [DEL]...[/DEL] [INS]...[/INS] - in LAYER4_INPUT_CASES.json>"
        },
        "diff_derived_by_layer4": {
          "hunks": [
            {
              "tag": "replace",
              "old": "1 year",
              "new": "6 months",
              "old_ctx": "of over 1 year.",
              "new_ctx": "of over 6 months.",
              "removed": 2,
              "added": 2,
              "punctuation_only": false,
              "item": "step 2"
            },
            {
              "tag": "replace",
              "old": "1 year",
              "new": "6 months",
              "old_ctx": "aging over 1 year.",
              "new_ctx": "aging over 6 months.",
              "removed": 2,
              "added": 2,
              "punctuation_only": false,
              "item": "step 3"
            }
          ],
          "words_removed": 4,
          "words_added": 4,
          "items": ["step 2", "step 3"],
          "removed_lines": [],
          "added_lines": [],
          "only_whole_lines": false,
          "lines_quotable": false
        }
      }
    ],
    "section_ids": {"3.0 POLICIES": 8987, "4.5 Accounts Receivable from Other Debtors": 8990}
  }
}
```

---

## 6. Constraints

**Format the frontend parses** (`frontend/src/components/AiNote.jsx`):
- Parts separated by one blank line. A part's first line is a heading **only if it exactly matches** one of the heading strings, which are listed twice: `NOTE_HEADINGS` in `layer4_explain.py` and `HEADINGS` in `AiNote.jsx`. A new or renamed heading must change both, or it renders as a paragraph.
- `- ` at the start of a line opens an item; two spaces continue it (a detail line); anything else is a paragraph. So: **no line breaks inside a sentence, no blank lines inside a part**, and no paragraph that begins with "- " or with spaces.
- **Plain text only.** React escapes it: no Markdown, bold, links or HTML.
- `is_note()` recognises a current-format note by its first line being a heading, or by "Not checked:". A note that fails this is treated as legacy, and the verdict-sentence filter runs over it (harmless unless it contains one of the 23 old sentences).

**Wording rules the tests enforce** (`tests/test_layer4_explain.py`):
- None of these words, as whole words, in any note: **approve, approves, approved, approval, reject, rejected, rejects, needs revision, verdict, confidence, turned down, ready to submit, you can still submit** (case-insensitive). Note that "approval" rules out phrasing like "two approval steps"; if the drafts need it, the list needs changing.
- No "{" or "}" in output, no " ." and no ".." (an ellipsis "…" is allowed).
- Every concern item carries a clause line.
- ISO wording is relevance, never judgement: `iso_relevance.json` must not contain "violat", "breach" or "shall ". Paraphrases are our own words; the standard's text is copyrighted.
- The clause for each label in `iso_relevance.json` must equal `config.ISSUE_CLAUSE`. Only 5.3, 6.3 and 7.5.3 are in use.
- The same inputs always produce the same note. Nothing random or time-based.
- "What looks fine" may only repeat what the rules counted, and must never contradict a concern.

**Placeholders, for your drafts:** today's templates are Python f-strings, so no syntax is fixed yet. I suggest `{name}` using the field names in §1 and §2 (`{section}`, `{item}`, `{from_text}`, `{roles}`) plus the derived ones (`{where}`, `{old_ctx}`), and one line per variant with its condition, e.g. `[source=model, feature numeric_changed_count=0]`. Lists need a joining rule ("a, b and c"; how many before "and others").

**Characters:** UTF-8 throughout. The note uses curly quotes “ ” for quoting (Layer 1's straight quotes are converted), "→" between old and new, "—" in table rows, "…" when clipping. All render.

**Lengths:** no database limit (text fields). The limits are the note's own: 5 concerns written out; quoted hunks at most 12 words a side with 2 words of context; whole lines quoted only if at most 3 lines of 30 words; long evidence clipped at 160 characters at a word boundary with "…"; malformed evidence at 120. Layer 1 truncates `requirement_removed` evidence at 160 characters mid-word (§2), so a new engine should finish the sentence from the old text, as today's does.

**Stored notes are never rewritten.** Notes already stored keep the current wording, and the screen must keep rendering them. New wording applies only to checks run after it ships.

**Rules-only mode:** on a clone without trained weights, Layer 2 is unavailable, `confidence_source` is `rules`, and there are no model-only or `both` issues. Because the policy keeps a rule-only flag only for the three precise labels, **`issues` can then hold only `excessive_deletion`, `modal_weakened` and `non_equivalent_term`**; everything else the rules found is in `layer1_result.flags` alone. The wording must still read correctly.

**The pipeline boundary:** the new engine may read anything in §1 and the derived diff. Passing it more (§1.9) changes only the `explain()` call. Anything that would change what **Layer 2** receives stops for approval.
