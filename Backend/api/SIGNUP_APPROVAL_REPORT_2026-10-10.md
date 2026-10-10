# Signup and approval completion — 10 October 2026

The unfinished changes already assigned an approved applicant to their
chosen office as an Encoder and exposed applicant details to the admin.
They did not yet implement the requested Head choice or password-confirmed
approval. This update completes that second task.

## Final behavior

| Application | Result after the admin confirms their password |
|---|---|
| Encoder, active office and position | Account approved and Encoder assignment created |
| Head, available active post | Account approved and Head assignment created |
| Head, office already has a Head | HTTP 409; account remains pending, no assignment or other account changes |
| Not sure, retired office, or inactive position | Account approved without a post; explicit manual-placement note |
| Already approved | Existing assignments remain unchanged |

Both Users and People show the requested position and warn about an
occupied Head post. The server checks again on approval; bypassing the
warning cannot grant a second Head or silently grant Encoder instead.
The incumbent stays unchanged. The admin can reject the application or
ask the applicant to reapply. Rejection still requires the admin's password.
A stale rejection of an already approved account now returns a conflict.

Applicant details expose only approved fields: full name, username, email,
chosen office and position, and signup time. Neither applicant passwords
nor hashes are returned. Signup cannot request system-admin or QMS posts.

## Implementation

- `people_views.approve` handles both approval endpoints in one transaction,
  including assignment and any submitted full-name update. Head conflicts
  abort the entire operation.
- User and office row locks are used where supported. The existing unique
  constraint on unended sole-holder assignments remains the final guard.
  Conflict tests exercise that constraint independently of the early check.
  Dated Head appointments ending today or later also block approval.
- Both frontends send the existing short-lived re-authentication token;
  the server requires it before attempting approval.
- Migration `0038_user_requested_position_kind` stores Encoder or Head.
  Existing applications default to Encoder because their requested position
  was not previously recorded. No existing assignment is changed.

## Validation and local database

- **84 backend tests passed** across signup, People and admin safeguards,
  using a disposable test database and a faster password hasher overridden
  only for the test process. Production password settings are unchanged.
- **Frontend production build passed.**
- **Chrome component checks passed with mocked API responses:** Head signup
  payload; visible applicant details without password; conflict warning;
  cancellation without approval; password token on both approval screens;
  occupied refusal; vacant success; password-protected rejection. No browser
  page errors. These are not a live-database end-to-end test.
- Focused frontend lint reports the same pre-existing two errors and one
  warning as HEAD: refresh exports in ConfirmDestructive, effect state in
  People, and hook dependencies in UserManagement. Signup is clean.
- Existing sklearn artifact-version and PyMuPDF deprecation warnings were
  emitted while loading the backend; no AI code or model files changed.

SQLite was backed up with its backup API to
`C:\Users\Eugene\AppData\Local\DocuRouteBackups\before-head-signup-2026-10-10-11232f55.sqlite3`.
Migration 0038 was first applied to a copy, then to the local database.
Integrity checks passed and all pre-existing user, office, position and
assignment columns/rows matched the backup. The new field defaults to
Encoder. Django reports no missing migrations. No real applicant was
approved, rejected or assigned during verification.

Restart any backend process that does not reload code and refresh the
frontend to use the updated screens. Other installations must apply
migration 0038 before running this code.
