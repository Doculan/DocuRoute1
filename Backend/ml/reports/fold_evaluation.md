# Per-fold evaluation

Fusion trained on each fold's val predictions, scored on that
fold's test predictions. The shipped fusion model is trained
separately on all folds' val predictions.

| fold | system | verdict acc | verdict macro-F1 | issue micro-F1 |
|---|---|---:|---:|---:|
| fold_0 | rules_only | 0.772 | 0.778 | 0.677 |
| fold_0 | model_only | 0.964 | 0.962 | 0.888 |
| fold_0 | fusion | 0.981 | 0.981 | 0.886 |
| fold_1 | rules_only | 0.820 | 0.805 | 0.634 |
| fold_1 | model_only | 0.907 | 0.888 | 0.748 |
| fold_1 | fusion | 0.986 | 0.984 | 0.750 |
| fold_2 | rules_only | 0.785 | 0.786 | 0.663 |
| fold_2 | model_only | 0.963 | 0.962 | 0.889 |
| fold_2 | fusion | 0.965 | 0.963 | 0.893 |
| fold_3 | rules_only | 0.819 | 0.816 | 0.689 |
| fold_3 | model_only | 0.965 | 0.963 | 0.882 |
| fold_3 | fusion | 0.977 | 0.976 | 0.882 |
| fold_4 | rules_only | 0.760 | 0.757 | 0.659 |
| fold_4 | model_only | 0.956 | 0.955 | 0.856 |
| fold_4 | fusion | 0.981 | 0.981 | 0.856 |

## Averaged over folds

| system | verdict acc | verdict macro-F1 | issue micro-F1 |
|---|---:|---:|---:|
| rules_only | 0.791 | 0.788 | 0.664 |
| model_only | 0.951 | 0.946 | 0.853 |
| fusion | 0.978 | 0.977 | 0.854 |

## How Layer 3 should combine the two issue sets

The verdict is fusion's under every one of these; only the issue
set changes. Scored per fold, then averaged.

| policy | issue micro-F1 | labels it never reports |
|---|---:|---|
| model | 0.853 | - |
| union | 0.693 | - |
| rules_precise | 0.854  **<- chosen** | - |
| agree | 0.858 | contradicts_manual, out_of_scope_content |

A policy that never reports a label is not a candidate, whatever its average.


Configured: `rules_precise`. Best measured: `rules_precise`.

Labels the rules were precise enough to add, per fold:
- fold_0: excessive_deletion, modal_weakened, non_equivalent_term
- fold_1: excessive_deletion, modal_weakened, non_equivalent_term
- fold_2: excessive_deletion, modal_weakened, non_equivalent_term
- fold_3: excessive_deletion, modal_weakened, non_equivalent_term
- fold_4: excessive_deletion, modal_weakened, non_equivalent_term
