# VIGILANT AI

VIGILANT AI is a local SIH26261 prototype for authenticated institutional application intake, PDF document processing, source-linked AICTE handbook search, and a conservative Fire Safety validation preview. It is not an approval system, an issuer-authentication service, or a determination of institutional compliance.

## Problem and approach

SIH26261 calls for support reviewing institutional application evidence and regulatory requirements. This prototype brings application records, uploaded PDF extraction, persisted reviewer assessments, audit events, and cross-document comparisons into one role-scoped workflow. Extracted values and registry outcomes are review aids; synthetic, unapproved, or uncertain rules are not presented as official current requirements.

## Current implementation

| Feature | Status |
| --- | --- |
| JWT login, current-user lookup, protected frontend routes | Implemented; backend authentication tests are available |
| Application list/detail/create/update | Implemented with server-side role and ownership checks; administrators select an existing institution; SQLite API tests cover lifecycle and isolation |
| Institution selection | Admin-only institution list/create endpoints support application association; institution users cannot choose another institution |
| PDF upload, storage hash, bounded text extraction and optional Tesseract OCR | Implemented; OCR output remains unverified |
| Fire Safety preview registry | Four candidates are disabled by default; source currentness and application scope remain unresolved |
| AICTE handbook Evidence Search | Authenticated retrieval API and citation display implemented; retrieval data/files must be present |
| Real-data Application and Document Verification pages | Use authenticated backend endpoints |
| Compliance assessments and review queue | Authenticated, role-scoped persisted assessment API and frontend display; no assessment is created by these read-only pages |
| Persisted findings | Authorized application findings API and application detail display |
| Validation workflow | Application detail can run registry validation and cross-document comparison, then show persisted assessments and run-by-run comparison history |
| Validation reports | Numeric application IDs show persisted application, document, and assessment records; illustrative nonnumeric routes remain explicitly demo-only |
| Audit history | Authenticated, role-scoped, paginated read API and UI; metadata is allowlisted to avoid exposing secrets or document contents |
| Integrity assistance | Same-application SHA-256 duplicate check and limited PDF structure/metadata heuristics; results are not authenticity findings |
| Authenticity and issuer verification | Not implemented; issuer checks are not performed and a file hash is not proof of authenticity |
| Production readiness | Not established; review security, deployment, retention, monitoring, and regulatory currentness before any production use |

Some unrelated illustrative pages and nonnumeric demo application routes remain synthetic and are labeled as demo data. The live review queue, compliance, reports, audit history, application dashboard, and document verification surfaces use authenticated backend data; none should be interpreted as an automatic compliance or authenticity decision.

See [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) for a feature-by-feature status report and the checks run.

## Architecture

- Frontend: React, TypeScript, Vite (`src/main.tsx`, `src/styles.css`).
- Backend: FastAPI routes in `backend/app/api/routes/`, SQLAlchemy models in `backend/app/models/`, and extraction/retrieval services in `backend/app/services/`.
- Database: PostgreSQL through SQLAlchemy; migrations are in `backend/alembic/`.
- Document storage: server-side files outside frontend public assets; document metadata and extraction JSON are stored in the database.
- Regulatory preview: static registry at `data/processed/regulatory_rules/fire_safety_preview_registry.json`; preview rules do not become enabled from CSV entries.
- Handbook search: retrieval pipeline in `src/retrieval_engine.py` and `src/answer_generator.py`, served through the authenticated AI route.

## Prerequisites and configuration

- Windows PowerShell
- Python and Node.js/npm versions compatible with the installed project dependencies
- PostgreSQL for local API use
- Tesseract OCR for scanned PDFs when OCR is needed (optional)

Backend settings are read by `backend/app/core/config.py` from environment variables and `.env` in the backend process working directory. See `backend/.env.example` for setting names. If creating a local `.env`, do not overwrite an existing one; replace example values with values appropriate for your machine. Keep secrets out of source control and logs. The development JWT fallback is not appropriate outside development; configure a strong secret for any shared deployment. Configure `DATABASE_URL`, `APP_ENV`, and `CORS_ORIGINS` for the intended environment. Document limits and optional Tesseract path are configurable there as well.

The frontend uses `VITE_API_URL` when supplied; otherwise it connects to `http://localhost:8000`.

## Database setup

From `C:\Users\ASUS-TUF\OneDrive\ドキュメント\Playground\VIGILANT-AI\backend`, after confirming the configured database target is the intended local development database:

```powershell
.\venv\Scripts\python.exe -m alembic current
.\venv\Scripts\python.exe -m alembic upgrade head
```

Do not run migrations against production or an unverified database. These commands apply schema migrations; they do not seed an application. Application creation should use the authenticated API. Test suites use isolated SQLite test databases and must not be pointed at the development PostgreSQL database.

Pending migrations include the consistency-run migration, which backfills existing results into one legacy run per application, and the finding-review migration, which adds append-only reviewer decisions. Both preserve existing findings/results and have only been tested against isolated SQLite databases. Neither has been applied to an application database. The historical backfill cannot reconstruct validation attempts that older code had already overwritten.

## Start locally

Terminal 1, backend:

```powershell
Set-Location 'C:\Users\ASUS-TUF\OneDrive\ドキュメント\Playground\VIGILANT-AI\backend'
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Terminal 2, frontend:

```powershell
Set-Location 'C:\Users\ASUS-TUF\OneDrive\ドキュメント\Playground\VIGILANT-AI'
npm run dev
```

Open the Vite URL printed by the frontend command. FastAPI's interactive API documentation is available at `http://localhost:8000/docs` when the backend is running.

Dependencies are defined in `backend/requirements.txt` and the root `package.json`. Install or restore them only when the environment does not already have them.

## Authentication and application lifecycle

Sign in through the frontend with an existing active backend account. The backend issues a bearer token; protected routes enforce access independently of frontend role-based controls.

Application routes:

- `GET /api/applications/`: list applications visible to the authenticated role.
- `POST /api/applications/`: create with `reference`, `entity_name`, and `app_type`; the backend sets initial status to `submitted`.
- `GET /api/applications/{application_id}`: fetch a permitted application.
- `PATCH /api/applications/{application_id}`: update role-permitted application fields.
- `GET /api/institutions/` and `POST /api/institutions/`: administrator-only institution selection and creation.
- `GET /api/compliance-assessments/`: paginated assessments filtered by role and access scope.
- `GET /api/audit-events/`: paginated audit events filtered by role and access scope.
- `GET /api/applications/{application_id}/findings`: persisted findings for an authorized application.
- `POST /api/applications/{application_id}/validate-checklist`: run the configured synthetic category checklist and persist advisory completeness findings.
- `POST /api/applications/{application_id}/findings/{finding_id}/reviews`: append an outcome and reviewer note (assigned reviewers only).
- `GET /api/applications/{application_id}/consistency-runs`: persisted run history and comparison rows for an authorized application.

Institution users must already be assigned to an institution; ownership is derived from their account. Administrators can select an existing institution when creating an application and may create institutions through the admin-only endpoint. Creating an institution does not assign users to it. Reviewer application access depends on an assessment assignment. References are unique.

The live Applications page lists backend records and offers creation to administrators and institution users. A new application page displays its persisted reference, ID, timestamps, status, and document count.

On a persisted application detail page, authorized users can run the category checklist and registry-based validation and inspect persisted findings/assessments; the checklist is explicitly synthetic and the registry page labels source/currentness limits. Assigned reviewers can append a finding outcome and note, preserving all earlier reviews and the automated finding. With at least two processed documents, users can run cross-document validation. The server creates a distinct consistency run, stores its comparisons, and exposes authorized history at `GET /api/applications/{application_id}/consistency-runs`. Prior runs remain available and result rows include the associated document filenames. Validation and review actions are recorded in audit history.

## Document demonstration

1. Sign in as an administrator (admin-created applications are visible to administrators), or as an institution user assigned to an institution.
2. Open **Applications**, create a record using synthetic organization details, or choose an existing authorized record.
3. Open its document workspace and upload a synthetic PDF. The initial document type choices are Fire Safety Certificate, Faculty Qualification Certificate, Accreditation Certificate, and Other Supporting Document. The API currently stores document type as a string.
4. Upload the same file again under another filename to demonstrate the same-application SHA-256 duplicate finding. It is an advisory indicator only and does not mean fraud.
5. Select **Process document**. Native PDF text is preferred; OCR is attempted for text-poor pages when Tesseract is available.
6. Review returned fields, page and evidence excerpts, extraction method, warnings, and processing status. These values are unverified; missing fields do not establish non-compliance.
7. On the application detail page, run **Run document checklist**. It distinguishes missing items, incomplete extraction, and processing states. Checklist requirements are synthetic demo configuration, not official AICTE requirements.
8. **Validate document** is enabled only when the backend reports processing status `completed`. The preview displays candidate rules and review state. Unreviewed, disabled rules remain `unknown` or `not_assessed`; the preview does not determine authenticity, fraud, expiry, or compliance.

Document APIs:

- `POST /api/applications/{application_id}/documents`
- `GET /api/applications/{application_id}/documents`
- `GET /api/applications/{application_id}/documents/{document_id}/download`
- `POST /api/applications/{application_id}/documents/{document_id}/process`
- `POST /api/applications/{application_id}/documents/{document_id}/validate`
- `POST /api/applications/{application_id}/documents/{document_id}/integrity-check`

Use synthetic records only. The extraction service recognizes a limited set of explicitly labeled institution, certificate number, issue date, and expiry date fields. It does not establish document type or verify a certificate with its issuer. No certificate validity period is inferred.

Generate a conspicuously fictional PDF for extraction testing (the command refuses to overwrite an existing file):

```powershell
Set-Location C:\Users\ASUS-TUF\VIGILANT-AI\backend
.\venv\Scripts\python.exe .\create_synthetic_demo_pdf.py --output .\synthetic-fire-safety-demo.pdf
```

The generated example has no authority, signature, seal, legal effect, or regulatory status. Do not present it as an authentic certificate.

## Regulatory and AI Evidence Search

The static Fire Safety registry contains candidate rules `DOCUMENT-0004`, `DOCUMENT-0012`, `DOCUMENT-0021`, and `INFRASTRUCTURE-0002`. They remain disabled unless source mapping, currentness, application-specific applicability, reviewer metadata, and explicit preview approval satisfy the registry gate. Current handbook amendments have not been independently confirmed. Free-form `app_type` is not used as proof of application scope.

AI Evidence Search calls authenticated `POST /api/ai/ask` and displays retrieved passages and citations. It searches the bundled regulatory evidence; it does not inspect private uploaded application documents or establish applicability/compliance. Retrieval failure returns an unavailable response rather than claiming a generated answer.

## Development utilities and tests

Administrator bootstrap/reset utilities are in `backend/bootstrap_admin.py` and `backend/reset_admin_password.py`. Inspect their development-target safeguards before use; they prompt for passwords and do not provide hardcoded initial credentials. Do not run them against an unverified database.

Run backend tests from `backend` with the project's virtual environment:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

Run focused application/document/compliance/regulatory tests:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\test_applications.py tests\test_ownership.py tests\test_documents.py tests\test_compliance.py tests\test_regulatory_validation.py
```

Run frontend checks from the project root:

```powershell
npm run build
npm run lint
git diff --check
```

No browser-based end-to-end test is currently configured. An API or unit test passing does not verify a live PostgreSQL connection, browser interaction, OCR binary availability, issuer checks, or the current legal status of a handbook clause.

## Known limitations and security notes

- The static regulatory candidate mappings/currentness are not all approved; do not enable them to make a demo produce pass/fail results.
- The existing application type and status fields are free-form strings; this prototype does not define a complete application workflow or formal status transition policy.
- Administrator-created records require an institution selected through the institution picker on the create-application page.
- Audit history is paginated and scoped; it is not a tamper-proof or complete compliance ledger. It exposes selected creation, update, upload, and processing events, not full document contents.
- Integrity checks are limited heuristics and same-application duplicate hashes. The checklist is synthetic and category mappings are not official AICTE requirements. No issuer authentication, fraud detection, or calibrated anomaly analysis is implemented.
- Protect `.env`, database backups, document storage, logs, and JWT secrets. Configure HTTPS, least privilege, backups, monitoring, rate limiting, retention controls, and a reviewed production secret/database setup before deployment.
- Human review remains necessary. Extracted text, OCR confidence, successful upload, and field matching are not proof of authenticity or institutional compliance.
