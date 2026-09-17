# Evaluation — revision assessment pipeline

What the four-layer pipeline scores, how it was measured, and what the numbers
do and do not support.

Reproduce everything here from a checkout with the fold predictions in place:

```bash
py ml/revision_pipeline/scripts/evaluate_folds.py \
    --predictions-dir ml/datasets/context_v2/folds_from_drive --out-dir ml/reports
py ml/revision_pipeline/scripts/report_per_label.py \
    --predictions-dir ml/datasets/context_v2/folds_from_drive \
    --out ml/reports/per_label_issue_f1.md
```

---

## 0. Which figures to quote

| | |
|---|---|
| **Verdict accuracy** | **0.978** |
| **Issue micro-F1** | **0.854** |

Both are the **mean of five per-fold scores**, and that is the basis to quote.
It is what `evaluate_folds.py` reports, what `fold_evaluation.md` records, and
what every other document in this project uses.

One other basis appears here, and only inside §3 and §4: **pooled**, which puts
every held-out row into a single bucket and scores once. Per-label figures
need it — a label with 89 examples cannot be scored five separate times and
averaged — and pooled issue micro-F1 is **0.844**, about a hundredth lower
because small folds no longer count equally with large ones.

**Every table below says which basis it uses.** Do not mix them: quoting
pooled issues (0.844) next to fold-mean verdicts (0.978) would put the two
headline numbers on different footings.

---

## 1. The headline, and what it means

**Verdict accuracy 0.978** on held-out documents, against **0.791** for the
rule layer alone. Both are means of five per-fold scores.

That figure needs its qualifier attached every time it is quoted:

> **0.978 is agreement with generated labels on documents the model never saw
> during training. It is not accuracy on real revisions submitted by staff.**

The training data is synthetic. Edits were produced by 25 generators applying
known transformations to real manual text, so the label is known by
construction rather than assigned by a person. This buys scale and a balanced
set of failure modes; it costs realism. A generated `modal_weakened` example
is a clean single-word substitution, where a real one arrives inside a
paragraph that was also reformatted, renumbered, and partly rewritten.

The honest reading: **0.978 says the pipeline reliably recognises the kinds of
change it was built to recognise, on documents it has not seen.** It does not
say 97.8% of real revisions will be judged correctly. The blind audit in §7 is
the closest thing here to a check against human judgement, and it is small.

---

## 2. Ablation — what each layer adds

Five-fold cross-validation grouped by document: every example from one
document falls entirely inside one fold, so no document appears in both
training and test. Splitting by example instead would leak — generated edits
from the same section share wording, and the model would be scored on text it
had effectively memorised.

### Per fold

| fold | system | verdict acc | verdict macro-F1 | issue micro-F1 |
|---|---|---:|---:|---:|
| 0 | rules only | 0.772 | 0.778 | 0.678 |
| 0 | model only | 0.964 | 0.962 | 0.888 |
| 0 | **fusion** | **0.981** | 0.981 | 0.886 |
| 1 | rules only | 0.820 | 0.805 | 0.637 |
| 1 | model only | 0.907 | 0.888 | 0.748 |
| 1 | **fusion** | **0.985** | 0.983 | 0.750 |
| 2 | rules only | 0.785 | 0.786 | 0.665 |
| 2 | model only | 0.963 | 0.962 | 0.889 |
| 2 | **fusion** | **0.965** | 0.963 | 0.893 |
| 3 | rules only | 0.819 | 0.816 | 0.691 |
| 3 | model only | 0.965 | 0.963 | 0.882 |
| 3 | **fusion** | **0.979** | 0.978 | 0.882 |
| 4 | rules only | 0.760 | 0.757 | 0.663 |
| 4 | model only | 0.956 | 0.955 | 0.856 |
| 4 | **fusion** | **0.981** | 0.981 | 0.856 |

### Averaged over the five folds — the figures to quote

| system | verdict acc | verdict macro-F1 | issue micro-F1 |
|---|---:|---:|---:|
| Layer 1 — rules only | 0.791 | 0.788 | 0.667 |
| Layer 2 — model only | 0.951 | 0.946 | 0.853 |
| **Layers 1+2+3 — fusion** | **0.978** | **0.977** | **0.854** |

### Reading it

**The rules alone reach 0.791.** Not nothing — deterministic checks catch
modal weakening, deletions above a threshold and numeric changes reliably.
They cannot judge whether a change contradicts the rest of the document, and
that ceiling is what Layer 2 exists to lift.

**The model adds 16 points** (0.791 → 0.951) — the largest single
contribution. The structural reason is that Layer 1 sees only the old and new
text: it has no access to the rest of the document, so a change that is wrong
*only in relation to what the manual says elsewhere* is invisible to it,
whatever rule is written. Layer 2 is given retrieved context, so it can judge
those. (This explains where the headroom comes from; it is not a measured
decomposition of the 16 points by label.)

**Fusion adds 2.7 more** (0.951 → 0.978) and, more importantly, it stabilises.
Look at fold 1: the model alone drops to 0.907, four points below its average,
while fusion holds at 0.985. Where the model is uncertain the rule features
carry the decision, and that is the case fusion is there for. The averaged gain
understates it; the variance reduction is the real benefit.

**Issue micro-F1 barely moves** between model-only (0.853) and fusion (0.854).
This is expected and is not a failure: fusion decides the *verdict*, while the
issue set is chosen by the policy in §4. The verdict is the part fusion
improves.

---

## 3. Per-label issue scores

Micro-F1 is one number over ten labels, and it hides which labels the system is
actually good at. A label with 89 examples can score near zero without moving
it.

Scored under the shipped `rules_precise` policy, **pooled** over the five test
folds — see §0 for why per-label figures use pooling rather than the fold mean.
Every example is issue-labelled, so test support equals corpus support.

| label | precision | recall | F1 | support |
|---|---:|---:|---:|---:|
| `modal_weakened` | 0.991 | 1.000 | **0.996** | 229 |
| `numeric_changed` | 0.973 | 0.960 | **0.966** | 150 |
| `responsibility_changed` | 0.940 | 0.993 | **0.966** | 283 |
| `non_equivalent_term` | 0.908 | 1.000 | **0.952** | 89 |
| `negation_changed` | 0.906 | 1.000 | **0.951** | 155 |
| `requirement_removed` | 0.671 | 0.941 | 0.783 | 303 |
| `key_term_deleted` | 0.743 | 0.825 | 0.782 | 126 |
| `out_of_scope_content` | 0.624 | 0.947 | 0.753 | 265 |
| `contradicts_manual` | 0.626 | 0.793 | 0.700 | 150 |
| `excessive_deletion` | 0.536 | 1.000 | 0.698 | 150 |

Pooled micro-F1 **0.844** — the same system as §2's **0.854**, measured over
pooled rows rather than as a mean of five fold scores. **0.854 is the figure to
quote**; 0.844 exists so the per-label rows above have a consistent total.

### The split is by kind of judgement, not by label frequency

The top five are **local and lexical** — a modal changed, a figure changed, a
role moved, a negation flipped. They live in a single sentence and either
happened or did not.

The bottom five all require a **judgement of degree or relevance**: was *this*
deletion excessive, was the removed clause a *requirement*, was the term a
*key* term, does this contradict the manual, is it out of scope. Their recall
is mostly fine — 0.941, 0.947, 1.000 — and precision is what suffers.
**The system over-reports these: it finds them, and it also finds them where
they are not.** For an advisory tool shown to a reviewer, that is the better
direction to fail in, but it should be stated rather than averaged away.

`excessive_deletion` is the clearest case: **recall 1.000, precision 0.536.**
It never misses a large deletion and it is wrong about half the time it speaks.
The threshold is a fixed ratio of words removed, and how much deletion is
"excessive" plainly depends on what was deleted.

### `key_term_deleted` — 126 examples

F1 0.782, the second-smallest label. Its difficulty is definitional as much as
statistical: whether a deleted phrase was a *key* term depends on the manual it
came from. The mined entity list mitigates this and does not settle it. Treat
the finding as a prompt to look, not a determination.

### `non_equivalent_term` — 89 examples, and the score is misleading

F1 **0.952**, which looks like one of the better labels. It is the one to
distrust most, and the reason is in the data. Counted over `all.jsonl`:

| swap | n |
|---|---:|
| `all` → `some` | 38 |
| `all` → `any` | 36 |
| `submit` → `file` | 3 |
| `issue` → `print` | 2 |
| eight further pairs | 1 each |

**74 of 89 — 83% — are the same substitution**, and the whole tail is ten pairs
occurring once to three times each. So the held-out rows are also mostly
`all → any/some`, and 0.952 largely measures whether the model can spot *that
one swap*. It can. Whether it has learned the underlying idea — that two words
a manual treats as interchangeable may not be — is essentially untested, and
the score cannot tell the two apart.

The application shows the difference. Revision 13's `accounts → payments` is a
pair the glossary does not contain: the edit is rejected correctly, but
labelled `out_of_scope_content` where `non_equivalent_term` fits better. A
high in-distribution F1 sitting next to an out-of-distribution miss is exactly
what an 83%-one-pattern label predicts.

**This is the sharpest limitation in the dataset**, and it is not visible in
either the micro-F1 or this label's own F1 — only in the distribution behind
them. Fixing it needs more glossary pairs that occur often enough in the corpus
to generate from, which the corpus does not currently contain.

---

## 4. How the issue set is chosen

Layer 1 and Layer 2 each produce a set of issue labels. Something has to
combine them. Four policies were scored with the verdict held constant at
fusion's — only the issue set varies.

| policy | mean of folds | pooled | labels it never reports |
|---|---:|---:|---|
| `model` — trust the model only | 0.853 | 0.842 | — |
| `union` — everything either found | 0.695 | 0.686 | — |
| **`rules_precise`** — model, plus rule labels precise enough to earn it | **0.854** | **0.844** | — |
| `agree` — only what both found | **0.858** | **0.855** | `contradicts_manual`, `out_of_scope_content` |

Two columns because two things are being asked. **Mean of folds** scores each
fold separately and averages the five, which is what `evaluate_folds.py`
reports and what §2 uses. **Pooled** puts every test row in one bucket and
scores once, which is what per-label figures need — a label with 89 examples
is too thin to score five times over. Pooled runs slightly lower throughout
because small folds no longer count equally with large ones; the ordering of
the policies is identical either way, which is what matters for the choice.

### Why `agree` was rejected despite scoring highest

`agree` wins by 0.004 on the fold mean and 0.011 pooled, and is disqualified on
the substance. Per label, pooled over the five test folds:

| label | `model` | `union` | `rules_precise` | `agree` | support |
|---|---:|---:|---:|---:|---:|
| `excessive_deletion` | 0.703 | 0.698 | 0.698 | 0.993 | 150 |
| `key_term_deleted` | 0.782 | 0.694 | 0.782 | 0.904 | 126 |
| `modal_weakened` | 0.998 | 0.996 | 0.996 | 1.000 | 229 |
| `negation_changed` | 0.951 | 0.765 | 0.951 | 1.000 | 155 |
| `numeric_changed` | 0.966 | 0.460 | 0.966 | 0.976 | 150 |
| `responsibility_changed` | 0.966 | 0.596 | 0.966 | 0.986 | 283 |
| `requirement_removed` | 0.783 | 0.637 | 0.783 | 0.964 | 303 |
| `non_equivalent_term` | 0.905 | 0.952 | 0.952 | 0.953 | 89 |
| `contradicts_manual` | 0.700 | 0.700 | 0.700 | **0.000** | 150 |
| `out_of_scope_content` | 0.753 | 0.753 | 0.753 | **0.000** | 265 |
| **micro-F1** | **0.842** | **0.686** | **0.844** | **0.855** | |

`agree` is better than every other policy on eight labels and scores **exactly
zero** on two. Requiring both layers to agree means a label the rules cannot
produce can never be reported, and the rules have no way to detect
`contradicts_manual` or `out_of_scope_content` — both need the document context
only Layer 2 sees.

Those two labels are **415 of 2,762 examples**, and they are the two that
justify having a model at all. A policy that buys a hundredth of micro-F1 by
never reporting them is not a better system; it is a system with two of its ten
capabilities switched off, hidden behind an average.

This is micro-F1 masking a policy failure, in one table. `evaluate_folds.py`
encodes the rule: **a policy that silences a label is not a candidate, whatever
it averages.**

### What `rules_precise` does

Take the model's labels, then add a rule-found label only if the rules hit that
label with precision ≥ **0.90**, measured on each fold's *training* rows and
never on the rows being scored. The same three labels qualified in all five
folds — `excessive_deletion`, `modal_weakened`, `non_equivalent_term` — which
is why the learned list and the fixed `config.PRECISE_RULE_LABELS` give
identical scores (0.8436 either way).

### Which of the three actually earn their place

Only one does. Pooled over the test folds:

| label | model alone | with the rule added | Δ F1 |
|---|---|---|---:|
| `non_equivalent_term` | F1 0.905 · p 0.900 · **r 0.910** | F1 0.952 · p 0.908 · r 1.000 | **+0.047** |
| `modal_weakened` | F1 0.998 · p 0.996 · **r 1.000** | F1 0.996 · p 0.991 · r 1.000 | −0.002 |
| `excessive_deletion` | F1 0.703 · p 0.542 · **r 1.000** | F1 0.698 · p 0.536 · r 1.000 | −0.005 |

**The mechanism is visible in the recall column.** A rule can only help where
the model's recall is below 1.000. For `non_equivalent_term` the model misses
9% of instances and the rule supplies exactly those, lifting recall to 1.000.
For the other two the model already finds every instance, so anything the rule
adds is by definition a false positive.

Scoring the candidate lists directly confirms it:

| `PRECISE_RULE_LABELS` | micro-F1 | Δ |
|---|---:|---:|
| learned per fold (current) | 0.8436 | — |
| shipped fixed list, all three | 0.8436 | +0.0000 |
| drop `excessive_deletion` | 0.8442 | +0.0006 |
| drop `excessive_deletion` and `modal_weakened` | 0.8444 | +0.0008 |
| drop all three (= `model`) | 0.8422 | −0.0014 |

### The shipped list was left unchanged, deliberately

Micro-F1 says drop `excessive_deletion`. **The configuration was kept as it is**,
because that measurement is taken with the model present and cannot see what
the label is also for.

`PRECISE_RULE_LABELS` governs the rules-only fallback as well. With no weights
loaded, `model_labels` is empty, so `keep = rule_labels ∩ precise` — the
precise list becomes *the entire issue output*. Removing `excessive_deletion`
therefore costs this, on an edit deleting 69% of a section:

```
precise = [excessive_deletion, modal_weakened, non_equivalent_term]
  verdict  reject
  issues   excessive_deletion [rule] "69% of the wording was removed"

precise = [modal_weakened, non_equivalent_term]
  verdict  reject
  issues   (none)
```

The verdict survives — `rules_only_verdict` reads the rule flags directly — but
the reviewer loses the evidence, and the explanation degrades to "Please check
these points" with no points to check.

**+0.0006 micro-F1 is not worth that.** It is roughly one prediction in 1,600,
far below the fold-to-fold variation in §2, and it is paid for by a real
capability in the mode where the system is already degraded. The same argument
applies to `modal_weakened`.

### Future work: the list is overloaded

`PRECISE_RULE_LABELS` does two unrelated jobs, and that is the underlying
problem:

1. **With Layer 2 present**, it filters which rule flags are worth adding to
   the model's labels. Here a label earns inclusion only if the model's recall
   for it is below 1.000 — otherwise the rule contributes false positives and
   nothing else.
2. **With Layer 2 absent**, it *is* the issue output. `keep = rule_labels &
   precise`, so a label missing from the list is not merely unfiltered, it is
   unreportable.

The two jobs pull in opposite directions: job 1 wants the list short, job 2
wants it to cover everything the rules can reliably say. **A configuration
choice here therefore cannot be judged on micro-F1**, because micro-F1 is
measured with the model present and is blind to job 2 entirely. That is not a
hypothetical — it is why `excessive_deletion` stays in the list despite
scoring +0.0006 against it.

The fix is to separate them: a filter list used when Layer 2's labels are
available, and the full set of rule flags when they are not. Rules-only mode
would then report everything the rules found, which is what a degraded mode
should do, and the filter list could be tuned on micro-F1 honestly. It needs a
second config entry, a branch in `merge_issues` on whether issue
probabilities arrived, and tests for both paths — small, but a design change
rather than a setting, so it is recorded here rather than made.

---

## 5. Dataset

| | |
|---|---|
| examples | **2,762** |
| source documents | **19** |
| generators | **25** |
| verdicts | approve 1,019 · reject 1,013 · needs_revision 730 |
| all examples issue-labelled | yes |
| hard negatives | 19 |
| quality score | median 1.00, floor 0.50 |

Issue label distribution:

| label | n | | label | n |
|---|---:|---|---|---:|
| `requirement_removed` | 303 | | `contradicts_manual` | 150 |
| `responsibility_changed` | 283 | | `excessive_deletion` | 150 |
| `out_of_scope_content` | 265 | | `numeric_changed` | 150 |
| `modal_weakened` | 229 | | `key_term_deleted` | 126 |
| `negation_changed` | 155 | | `non_equivalent_term` | 89 |

Full provenance, generator list and accepted limitations:
`ml/datasets/context_v2/DATASET_CARD.md`.

---

## 6. Configuration of the shipped system

### Layer 2 training

| | |
|---|---|
| base | `distilbert-base-uncased` |
| architecture | shared encoder, two heads — verdict (weighted cross-entropy), issues (BCE with `pos_weight`) |
| hardware | **Kaggle, single NVIDIA T4** |
| max sequence length | **384 tokens** |
| epochs | **3** |
| batch size | **16** |
| learning rate | 3e-5 |
| truncation | `only_second` — the revision is never cut, only the context |

**384 was not a deliberate choice, and saying otherwise would misrepresent
it.** The training notebook pinned 384 while `config.MAX_LENGTH` still said
512, and the five folds trained at 384 before the discrepancy was noticed. The
options were to retrain everything at 512 or to set the configuration to the
length the reported numbers were actually measured at. The second was taken:
`config.MAX_LENGTH` is now 384, the notebook reads it from config so the two
cannot drift again, and the value is recorded in the weights' fingerprint —
evaluating at a different length than training degrades the result silently,
which is the failure this prevents.

What the shorter length costs, measured: at 512 the marked change fits whole
for **75%** of examples; at 384, for **68%**. The other 32% are not truncated
blindly — `_window_around_change` keeps a window around the change markers plus
the head and tail of the section, so the edit itself is always in the input. It
is surrounding context that is trimmed, never the change being judged.

Raising `MAX_LENGTH` invalidates every figure in §2 and means retraining all
five folds.

### Issue thresholds

Tuned per fold on that fold's validation split; the shipped model uses the
**median across the five folds**, which is more robust than any single fold's
choice.

| label | per-fold | shipped |
|---|---|---:|
| `excessive_deletion` | 0.85, 0.90, 0.90, 0.75, 0.80 | **0.85** |
| `key_term_deleted` | 0.35, 0.75, 0.90, 0.50, 0.90 | **0.75** |
| `modal_weakened` | 0.95, 0.95, 0.95, 0.95, 0.95 | **0.95** |
| `negation_changed` | 0.70, 0.85, 0.95, 0.95, 0.80 | **0.85** |
| `numeric_changed` | 0.90, 0.40, 0.95, 0.40, 0.90 | **0.90** |
| `responsibility_changed` | 0.85, 0.75, 0.90, 0.30, 0.85 | **0.85** |
| `requirement_removed` | 0.85, 0.85, 0.80, 0.55, 0.75 | **0.80** |
| `non_equivalent_term` | 0.80, 0.25, 0.50, 0.95, 0.95 | **0.80** |
| `contradicts_manual` | 0.35, 0.80, 0.90, 0.95, 0.95 | **0.90** |
| `out_of_scope_content` | 0.85, 0.75, 0.75, 0.75, 0.80 | **0.75** |

The spread is itself informative. `modal_weakened` picks 0.95 in every fold —
the model is decisive about it. `non_equivalent_term` ranges 0.25 to 0.95,
which is the §3 sparsity showing up as instability: with 89 examples, mostly
one pattern, each fold's validation split disagrees about where the boundary
sits. The median is the defensible choice, not a confident one.

### Layer 3

**Pinned to gradient boosting** (`HistGradientBoostingClassifier`), no
estimator selection.

Selection between logistic regression and boosting had been automatic, picking
whichever scored better on each fold. That made the headline figure depend on
scikit-learn's version, because the two estimators disagree most on the fold
where the decision is closest:

| estimator | per fold | mean |
|---|---|---:|
| logistic only | 0.985, **0.946**, 0.971, 0.977, 0.979 | 0.9715 |
| boosting only | 0.981, **0.985**, 0.965, 0.979, 0.981 | **0.9782** |
| as selected | boost, boost, logistic, boost, boost | 0.9794 |

Fold 1 is the problem: **0.946 against 0.985**, a four-point gap on the one
fold where selection could go either way. Automatic selection therefore
reported 0.979 in one environment and 0.975 in another, on identical
predictions, with nothing pinning which scikit-learn was installed. A reported
accuracy that moves when a library is upgraded is not a reported accuracy.

Pinning to boosting gives up 0.0012 against the selected variant and removes
the ambiguity entirely. **0.978 is the figure, it is reproducible, and it is
the one quoted everywhere in this project.**

The shipped `fusion.pkl` is trained on all folds' validation predictions, on
CPU, locally. It is 0.8 MB and is the one model component not trained on a GPU.

---

## 7. Blind label audit

Model metrics score the pipeline against generated labels. They cannot detect a
generator that produces the wrong label consistently — the model would learn
the mistake and score well on it. The audit exists to check the labels
themselves.

**Method:** 50 examples, seeded and stratified by verdict, judged with the
labels hidden, then compared.

| | |
|---|---|
| verdict agreement | **44 / 50 = 88%** |
| issue set exact match | **47 / 50 = 94%** |
| both correct | 44 / 50 |

Confusion: 18 approve and 18 reject agreed outright, 8 `needs_revision` agreed;
2 `needs_revision` judged approve, 2 judged reject, 2 reject judged
`needs_revision` — disagreement concentrated on the boundary between "send it
back" and "refuse it", which is the genuinely debatable distinction.

**The six disagreements were acted on, not explained away:**

| generator | disagreement | outcome |
|---|---|---|
| `step_reorder_dependent` | reject vs needs_revision | **143 examples relabelled** `needs_revision` — a swapped sequence is a slip, not a control removed |
| `non_equivalent_swap` | "any" → "all" flagged as an issue | **Fixed** — widening a scope is strengthening, and strengthening is not an issue |
| `non_equivalent_swap` | "computer file" → "computer record" | **Fixed** — noun/verb ambiguous glossary pairs now apply only in verb position |
| `numeric_change` | "365 days or 1 year" → "730 days or 1 year" | **Fixed** — a figure restating another in the same unit is left alone |
| `combo` | weights no longer totalling 100% | Resolved by the same fix |

`verify | check` was also removed from the glossary: in this register it is not
a change of meaning.

**Read this figure with care in two directions.** The audit was performed on
the dataset *before* these fixes, so it measures the version that prompted
them; the shipped dataset is the corrected one, and is expected to agree better.
But it is 50 examples judged by one person, which is a sanity check on label
quality — not an independent evaluation, and not a substitute for testing
against real submitted revisions.

---

## 8. Runtime

Measured on the deployment target — Intel i3-1215U, 6 cores, 7.7 GB RAM, **CPU
only, no GPU**.

| | |
|---|---|
| **cold start** — first assessment in a process | **13.6 s** |
| **warm** — every assessment after | **0.3 – 0.5 s** |
| two concurrent | 0.40 s wall |
| three concurrent | 0.61 s wall |
| resident memory, steady state | ~680 MB |
| peak, three concurrent | 740 MB |

The cold start is the encoder being read from disk. The model is cached per
process behind a lock, so simultaneous first requests wait for one load rather
than each performing their own — **memory does not scale with concurrent
users, it scales with worker processes.** Pre-warming at startup removes the
13.6 s entirely; `DEPLOYMENT.md` §6 has the mechanism.

Assessment is CPU-bound and blocking, which is what limits throughput rather
than the database. The scaling path — moving it to a task queue — is documented
in `DEPLOYMENT.md` §8.

### Retraining without a GPU

Layer 2 is trained on a GPU. Whether it *can* be trained without one was
measured rather than assumed, on the same i3-1215U:

```
py ml/revision_pipeline/scripts/train_layer2.py     --data-dir ml/datasets/context_v2 --out-dir <scratch>     --max-examples 200 --device cpu

device=cpu  threads=8  max_length=384  batch=4x1=4  train=200  val=200  epochs=3

epoch 1/3  loss 2.3953  191.3 s  peak 1150 MB  val_acc 0.335  val_issue_f1 0.190
epoch 2/3  loss 1.9695  232.5 s  peak 1347 MB  val_acc 0.565  val_issue_f1 0.295
epoch 3/3  loss 1.3531  227.9 s  peak 1222 MB  val_acc 0.705  val_issue_f1 0.386

total 943 s (15.7 min)
```

**It works.** Loss falls monotonically and validation accuracy climbs
0.335 → 0.565 → 0.705, still rising at the third epoch — the CPU path trains,
it does not merely avoid crashing.

Scaled to the full split (1,561 training rows, a 7.8x increase):

| | |
|---|---|
| measured at 200 examples | 217 s/epoch |
| projected, full split | **~28 min/epoch** |
| projected, 3 epochs | **~1.4 h**, and nearer 2 h with the full 735-row validation pass |
| peak memory | **1.35 GB** |

**So: retraining Layer 2 on this laptop is roughly a two-hour job needing about
1.4 GB, against minutes on a T4. Practical once, impractical to iterate with** —
which is why the Kaggle path in §6 exists.

Two limits on that projection, both worth stating:

- CPU forces **batch 4** (the T4 used 16), so three epochs here is not the same
  optimisation run as three epochs there. The wall-clock scaling holds; the
  training trajectory does not transfer.
- 0.705 on 200 examples is far below the shipped 0.951. This measures
  **throughput, not attainable accuracy** — it does not show that a
  CPU-trained model would reach the same figures, only that the machine can
  do the work.

Memory is the practical obstacle rather than time: 1.35 GB peak on a 7.7 GB
machine that frequently has ~1 GB free means training would page unless other
applications are closed first.

---

## 9. Limitations

**On the evaluation:**

1. **Labels are generated, not human.** §1. Every figure here measures
   agreement with a construction, on unseen documents. Real revisions are
   messier.
2. **19 documents.** Grouped cross-validation is the right protocol at this
   size, but five folds over 19 documents means each test fold rests on three
   or four, and fold 1's four-point swing shows the sensitivity.
3. **The audit is 50 examples, one judge, pre-fix.** §7.
4. **No test against real submitted revisions.** The most valuable missing
   evaluation. It needs a corpus of genuine revisions with adjudicated
   outcomes, which does not exist yet.

**On the system:**

5. **`non_equivalent_term` is 83% one swap pattern.** §3. Its F1 of 0.952 is
   not evidence the label works — the held-out rows are mostly the same
   substitution, so the score cannot distinguish "learned the concept" from
   "learned `all → any/some`". A high score can hide a narrow one.
6. **The five judgement-of-degree labels over-report.** §3. `excessive_deletion`
   has recall 1.000 and precision 0.536; `contradicts_manual`,
   `out_of_scope_content`, `requirement_removed` and `key_term_deleted` are
   similar in kind. They err towards flagging, which suits an advisory tool
   and still means roughly one in three of those findings is spurious.
7. **The rules cannot see document context**, so `contradicts_manual` and
   `out_of_scope_content` rest entirely on Layer 2. If the weights are absent
   the pipeline degrades to rules-only and says so — those two labels are then
   unavailable rather than silently negative.
8. **The change reason is never an input to the model.** It is traceability
   under clause 6.3 and is shown to the reviewer; the verdict depends only on
   the textual change and its context, so a well-written justification cannot
   talk the pipeline into approving a bad edit. Whether the reason actually
   *describes* the edit is unchecked, and is future work.
9. **`PRECISE_RULE_LABELS` is overloaded, so it cannot be tuned on micro-F1.**
   It filters rule flags when Layer 2 is present and *is* the whole issue
   output when Layer 2 is absent. §4 has the demonstration; the decoupling is
   future work.
10. **Clause 7.5.2 is deliberately out of scope.** Document number, revision
   number and effectivity date are handled by the system's document-control
   features, not the model.
11. **The assessment is advisory.** It never changes a revision's status. Every
    figure in this document describes advice to a human reviewer who decides.

---

## 10. Summary

| claim | evidence |
|---|---|
| Fusion beats rules by 19 points on verdicts | 0.978 vs 0.791, 5-fold grouped CV |
| The model is the largest contributor | 0.791 → 0.951 |
| Fusion's value is stability, not just average | fold 1: model 0.907, fusion 0.985 |
| Issue detection is uneven by kind of judgement | lexical labels 0.95-1.00, judgement labels 0.70-0.78 (§3, pooled) |
| A good label score can still hide a narrow label | `non_equivalent_term` F1 0.952 on 83% one pattern (§3) |
| The issue policy was chosen on substance | `agree` scored higher and was rejected for silencing two labels |
| The reported figure is stable | fusion pinned to boosting; 0.979/0.975 ambiguity removed |
| Labels were checked against a human | 44/50 verdicts, 47/50 issue sets; six disagreements fixed |
| It runs on the target hardware | 0.3–0.5 s warm, ~680 MB, no GPU |

The system is **advisory**, its training labels are **generated**, and its
headline figure is **agreement on unseen documents** — not accuracy on real
revisions.
