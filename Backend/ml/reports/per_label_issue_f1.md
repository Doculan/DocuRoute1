# Per-label issue scores

Policy `rules_precise`, pooled over 5 folds. Support is the number of examples carrying the label: *corpus* over the whole dataset, *test* over the held-out rows these scores come from.

| label | precision | recall | F1 | test support | corpus |
|---|---:|---:|---:|---:|---:|
| `excessive_deletion` | 0.536 | 1.000 | 0.698 | 150 | 150 |
| `key_term_deleted` | 0.743 | 0.825 | 0.782 | 126 | 126 |
| `modal_weakened` | 0.991 | 1.000 | 0.996 | 229 | 229 |
| `negation_changed` | 0.906 | 1.000 | 0.951 | 155 | 155 |
| `numeric_changed` | 0.973 | 0.960 | 0.966 | 150 | 150 |
| `responsibility_changed` | 0.940 | 0.993 | 0.966 | 283 | 283 |
| `requirement_removed` | 0.671 | 0.941 | 0.783 | 303 | 303 |
| `non_equivalent_term` | 0.908 | 1.000 | 0.952 | 89 | 89 |
| `contradicts_manual` | 0.626 | 0.793 | 0.700 | 150 | 150 |
| `out_of_scope_content` | 0.624 | 0.947 | 0.753 | 265 | 265 |

Pooled micro-F1: **0.844**

## Every policy, per label

F1 per label under each candidate policy. A 0.000 against a label with real support means the policy can never report it.

| label | `model` | `union` | `rules_precise` | `agree` | support |
|---|---:|---:|---:|---:|---:|
| `excessive_deletion` | 0.703 | 0.698 | 0.698 | 0.993 | 150 |
| `key_term_deleted` | 0.782 | 0.665 | 0.782 | 0.904 | 126 |
| `modal_weakened` | 0.998 | 0.996 | 0.996 | 1.000 | 229 |
| `negation_changed` | 0.951 | 0.765 | 0.951 | 1.000 | 155 |
| `numeric_changed` | 0.966 | 0.460 | 0.966 | 0.976 | 150 |
| `responsibility_changed` | 0.966 | 0.596 | 0.966 | 0.986 | 283 |
| `requirement_removed` | 0.783 | 0.637 | 0.783 | 0.964 | 303 |
| `non_equivalent_term` | 0.905 | 0.952 | 0.952 | 0.953 | 89 |
| `contradicts_manual` | 0.700 | 0.700 | 0.700 | 0.000 | 150 |
| `out_of_scope_content` | 0.753 | 0.753 | 0.753 | 0.000 | 265 |
| **micro-F1** | **0.842** | **0.684** | **0.844** | **0.855** | |
