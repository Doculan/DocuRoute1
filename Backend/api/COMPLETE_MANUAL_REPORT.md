# Complete draft manuals — implementation and verification

## Stage 1: scope and inventory (30 September 2026)

Starting commit: `027f732`. The working tree was clean.

Every newly locked proposal must produce one complete draft manual on the
existing blank template. Read all manual sections in document order; substitute
the agreed text for changed sections and retain current content for the rest.
The generated file is the snapshot at lock time. DCR summaries and concurrence
records still describe only the proposal. Effectivity updates only changed
sections. No schema migration or AI change is needed.

Read-only inventory of the local database: one current generated partial draft,
awaiting signature, with no uploaded signature records; two draft proposals and
one withdrawn proposal without generated drafts. The partial draft covers one of
eight sections. Files on disk without attachment records are not recovery targets.
No personal data or document content is included in this inventory.

Existing partial drafts must not be silently overwritten. The database has no
complete immutable snapshot of unchanged sections at the original lock. Recovery
must preserve the original attachment and distinguish a reconstruction using the
current manual from an original lock-time snapshot. Signed/downstream packages
must be refused by replacement tooling. Start with a dry run; live replacements
need a named actor, a reason and explicit acceptance of the current baseline.

## Stages

1. Record scope and inventory; commit this plan.
2. Generate complete manuals and add focused content/order/table regression tests.
3. Verify package download stability, rollback and unchanged effectivity scope.
4. Produce isolated sample documents; inspect rendered output if a renderer exists.
5. Add dry-run-first recovery tooling, preservation/audit tests and instructions.
6. Finish documentation, final checks, stage commits and remote delivery.

Each stage is reported and committed before proceeding. Generated documents,
private data, database files and model artifacts stay out of Git.

## Stage 2: complete generation

The generator now reads every section ordered by `order, pk`, substitutes only
actual proposal changes, and labels the result as a complete draft. Subsections
and unchanged tables are included. Building and saving are separated to support
isolated previews and explicitly labelled recovery. Empty manuals and changes
pointing outside the manual are refused rather than producing incomplete files.

The replacement regression test failed on the old generator (one heading instead
of four), then passed with the implementation. All four DraftCopyTests pass,
including multiple changed sections, unchanged content/tables and NUMPAGES fields.
Tests use an isolated database and temporary media. A fast password hasher is set
only inside the test process; production password settings are untouched.

## Stage 3: workflow integrity

167 tests pass across `tests_generation`, `tests_package`, `tests_concurrence`
and `tests_effective`. The downloaded complete draft retains identical bytes
after an unrelated section changes. Its unchanged section remains the lock-time
text. A draft-rendering exception rolls back the final concurrence, DCR number
and attachment rows. Existing tests confirm authenticated downloads, preserved
superseded copies and effectivity limited to changed sections.

As in the pre-existing generation path, a database rollback does not remove
files already written before a later generator fails; such orphan files are not
downloadable through attachment records. This change does not add file cleanup.

## Stage 4: rendered-document inspection

Three synthetic eight-section manuals were built with the production generator
and official template, without database writes: one revised section, three
revised sections, and a long manual with three revisions and a 35-row table.
Microsoft Word exported the drafts to PDF. The resulting PDFs contain 2, 2 and
12 pages respectively. All eight headings and the expected unchanged/revised
markers are present. All 120 numbered paragraphs and 35 table rows in the long
sample survive export.

Visually inspected the short draft's two pages and the long draft's table
continuation and final pages. Headers, blank status fields, footer boxes and
confidentiality text remain in place. Table headers repeat across page breaks;
empty cells retain their columns. Final pages show `2 of 2` and `12 of 12`.
No layout patch was needed. These are synthetic samples, not certification of
every possible source document or a browser walkthrough. Samples remain under
the local temporary `docuroute-complete-manual-*` folder, outside Git.

## Stage 5: historical recovery

Added `recover_complete_draft`, dry-run by default. Application requires an
approved active administrator ID, a reason and explicit current-baseline
acceptance. It refuses downstream states, any signature records (including
superseded scans), changed-section baseline mismatches, unreadable originals and
already complete drafts. Original bytes and rows are retained; replacement uses
the existing supersession relationship and adds an audit event. Failed recovery
rolls back records and removes only its newly written file.

The package API exposes earlier generated copies, and the proposal screen puts
their downloads in a collapsed reference-only section. Current reconstructed
copies display their replacement reason. Existing download permissions apply.

Nine recovery tests passed; after adding the history display, all 15 recovery and
package-reading tests passed. Frontend production build passed. The changed
component is lint-clean both at the starting commit and now. Repository-wide
lint reports 11 errors and 2 warnings in unchanged files; this work does not
claim a clean global lint run.

The user explicitly chose to replace the existing unsigned draft and preserve
the original. A SQLite online backup was created and integrity-checked locally
before applying recovery. Recovery replaced attachment 2 with attachment 4 for
the sole eligible unsigned package, under administrator account 1, with a dated
current-baseline reconstruction label and one audit event. All eight headings
are present in order. Original attachment 2 remains available as an earlier copy.
Manual content, proposal/version/change records, concurrence, section history
and document status were compared with the backup and are unchanged.

Local backup: `Backend/db.sqlite3.bak-20260930-210347-pre-complete-draft` (not in Git).

### Recovery operation on another installation

Take a consistent database backup (SQLite online backup API, or the deployment's
database backup process) and preserve the media files before applying recovery.
From `Backend`, with its environment active:

```text
python manage.py recover_complete_draft --proposal PROPOSAL_ID
python manage.py recover_complete_draft --proposal PROPOSAL_ID --apply --actor ADMIN_USER_ID --reason "Reason for reconstructing the unsigned draft" --accept-current-baseline
```

The command is deliberately limited to unsigned legacy drafts. A current-baseline
reconstruction is not evidence of unchanged sections as they stood at the original
lock. Signed or completed packages need a separately agreed records procedure.

## Stage 6: final documentation and delivery (1 October 2026)

README and standing project documentation now describe complete draft manuals.
The stage log and recovery instructions distinguish lock-time snapshots from
current-baseline reconstructions. No migrations, trained-model changes or changes
to assessment inputs were required. The external PDF guide was not edited.

Validation commands (from Backend with the environment active):

```text
python manage.py test api.tests_generation api.tests_package api.tests_concurrence api.tests_effective
python manage.py test api.tests_draft_recovery api.tests_package.PackageReadingTests
```

The runs used `MD5PasswordHasher` only in their isolated test processes to shorten
fixture account creation. Production password hashing was unchanged. Frontend
validation used `npm run lint`, `npm run build`, and a baseline/current ESLint
comparison of `ProposalPackage.jsx`. Global lint remains a known pre-existing
failure as detailed in Stage 5. No browser interaction test was performed.

Stage commits:

| Stage | Commit |
| --- | --- |
| Scope and inventory | `ebfb7a5` |
| Complete generation | `6885726` |
| Workflow verification | `4c4f789` |
| Rendered verification | `280c353` |
| Recovery and earlier-copy downloads | `f193585` |
| Final documentation | This document's finalization commit |

To use the update, restart backend workers that have not reloaded the code and
refresh the frontend (or deploy the new production build). Re-download the
current draft for the recovered unsigned package. Copies already downloaded or
printed before recovery are not modified. Database backups, actual documents and
generated review samples are excluded from the source commits.
