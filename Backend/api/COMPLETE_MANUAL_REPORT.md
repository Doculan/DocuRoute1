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
