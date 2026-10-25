# Engineering audit — 25 October 2026

This audit records repository findings and checks performed for the SIH26261 completion brief. It is a prototype assessment, not a production security certification or regulatory approval.

## Key findings and repairs

| Severity | Finding and cause | Repair or disposition |
| --- | --- | --- |
| High | The assessment decision form is rendered only when the signed-in user has role `REVIEWER` **and** their ID matches the assessment's assigned reviewer ID. An administrator sees assignment controls, not the decision form; an unassigned reviewer sees an assignment notice. The earlier local database report also had no active `REVIEWER` accounts, so an administrator could not assign anyone. | This is an authorization-gated workflow, not a missing API. Keep the backend check authoritative. Administration now provides persisted user management, and the empty-reviewer state links to that page. The current development database could not be queried because no local PostgreSQL/API service was listening; the earlier no-reviewer observation remains unverified for the current database state. |
| High | Legacy tests connected to named SQLite files under `backend/` and called `drop_all`, which could erase ignored local test/application data during a routine pytest run. | Six test modules now use isolated in-memory SQLite engines with `StaticPool`; per-test setup still creates/drops only its own in-memory schema. Migration/document tests use `tmp_path`. |
| Medium | Administration only showed the signed-in account and navigation; it had no user directory or account controls. | Added an administrator-only paginated/filterable user API and a responsive UI for creating users, changing roles, and activating/deactivating accounts. Backend schemas constrain roles to the existing enum, account changes are audited, password output is excluded, and administrators cannot deactivate or demote themselves. No database migration was needed. |
| Medium | TestClient stalled in the restricted Windows sandbox before completing even the health request. | A faulthandler trace showed asyncio stuck in Windows `ProactorEventLoop._make_self_pipe` while creating the local socketpair AnyIO needs for TestClient. The suite passed when run with local IPC permission; this was environmental, not an application route deadlock. |
| Medium | Live service and database state cannot be established from repository-only checks. | No process was listening locally on ports 5432, 8000, or 5173 during this pass. The repository Alembic head is `a71c9f4e2b36`; `alembic current` against the intended database was not verified. No migration was run and no database record was created or changed. |
| Low | Existing nonnumeric illustrative dashboard, finding, and report routes contain synthetic demo records. | Existing UI labels them as illustrative/simulated. They remain outside the persisted numeric application workflow and are listed as a limitation in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md). |
| High | The persisted application update endpoint allowed assigned reviewers to edit application status, and both reviewers and administrators had a free-text status field. This could let an assessment review alter the application lifecycle without a controlled transition workflow. | Removed status editing from the application detail UI and API update operation. Reviewer decisions remain append-only assessment/finding review records and cannot alter application status. Status remains visible and can only be changed once a validated lifecycle workflow is implemented. |
| Medium | The persisted report showed finding-review notes but omitted human assessment decisions, even though authorized assessment detail requests already returned that append-only history. | Added the role-scoped review history to paginated assessment responses using eager loading, displayed the decision count/latest result in the queue, and included reviewer, outcome, note, and timestamp in numeric application reports. |
| Medium | Application checklist results were returned only by a mutating `POST` operation that also created findings and audit events, so reports could not inspect checklist results without modifying application data. | Extracted a shared checklist evaluator and added an authorized read-only `GET /api/applications/{id}/checklist` preview. The existing POST still records deduplicated findings and its audit event; reports use GET and label the checklist as synthetic. |
| Medium | The dashboard loaded applications, assessments, audit events, and every document list as one `Promise.all`, so one ancillary failure hid all otherwise available overview data. It also omitted findings and pending assigned reviews and offered no refresh action. | Dashboard loading now isolates ancillary results, clearly reports incomplete counts, counts open findings and assessments still awaiting the currently assigned reviewer, and exposes a refresh control. The pending count uses assigned reviewer IDs and each decision's reviewer ID, so a prior review by a different reviewer does not mark a reassigned task complete. |

## Workflow and authorization checks

- Assessment decisions support only `evidence_accepted`, `evidence_rejected`, `information_requested`, and `further_investigation`. The note is required by the UI; the API validates the outcome and only accepts a request from an authenticated reviewer assigned to that assessment.
- Review history is append-only and returns reviewer identity, outcome, note, and timestamp. Review submission does not update the automated assessment or application approval status.
- Only administrators can list active reviewers or assign reviewers. Reviewer eligibility is an active user with role exactly `REVIEWER`; administrators are not substituted.
- User list/create/update routes require an administrator on the server. Role updates are enum-validated; account creation follows the existing 12 non-whitespace-character password policy; no plaintext password is included in API output. Self-deactivation and self-demotion are blocked. No password reset/recovery flow exists.
- Test coverage includes review assignment, authentication, unassigned reviewer denial, invalid outcomes, multiple appended decisions, persistence/history, user-management authorization, invalid role rejection, and audit events.

## Verification

- Backend full suite: **143 passed, 16 warnings**.
- Frontend lint: **passed**.
- Frontend production build (TypeScript + Vite): **passed**.
- Python `compileall`: **passed**.
- Alembic source heads: one head, `a71c9f4e2b36`.
- The backend suite was run with test data isolated from the PostgreSQL configuration and project-local SQLite files.
- No frontend test runner, browser E2E suite, running PostgreSQL service, or running API service was available. Browser behavior, live reviewer availability, live database migration state, and actual human review against persisted development data require manual verification.

## Remaining limitations

- Some illustrative routes remain synthetic; use numeric persisted application/assessment routes for backend-backed workflows.
- AI evidence search uses the configured local retrieval corpus and ranked text retrieval, not an LLM. No model was trained in this pass.
- OCR depends on Tesseract and was not tested here with representative scanned documents. Issuer authenticity verification and authoritative currentness/applicability review are not implemented.
- Regulatory candidate rules remain advisory/unapproved where provenance, currentness, or scope is incomplete. No official compliance conclusion is produced.
- Cross-document, document-processing, audit, and reviewer workflows have automated tests, but no live service/browser demonstration was performed in this environment.
- Password recovery, bulk administration, institution assignment when creating a user, rate limiting, formal security certification, and deployment readiness remain outside the implemented surface.

## Safe local verification

From the repository root, open separate terminals and start the API and frontend using the commands in [README.md](./README.md). Before inspecting data or changing schema, verify the backend `.env` target is the intended local database. Use `alembic current` to inspect its revision; do not run `alembic upgrade head` until the target and pending migrations are reviewed. A reviewer workflow requires an administrator to create or activate a separate reviewer account, assign an assessment, then sign in as that assigned reviewer. No review or assignment was submitted during this pass.
