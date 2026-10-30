# VIGILANT AI Backend

This is the FastAPI backend for the VIGILANT AI project.

## Setup Instructions (Windows)

### 1. Create Virtual Environment
Using PowerShell:
```powershell
cd backend
python -m venv venv
.\venv\Scripts\activate
```

Using Git Bash:
```bash
cd backend
python -m venv venv
source venv/Scripts/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` and replace placeholders with your actual configuration. The
development-only JWT fallback must not be used in staging or production.
Outside development, `JWT_SECRET_KEY` must be configured with at least 32
characters. Generate a secret, for example, with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`, then keep it in
your deployment's secret manager rather than source control.

### 4. Running the Application
```bash
uvicorn app.main:app --reload
```
The API will be available at `http://localhost:8000`.

### 5. API Documentation
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 6. Running Tests
```bash
python -m pytest -q
```

The GitHub Actions workflow runs the backend suite against isolated test
fixtures, then applies the migration chain to a clean PostgreSQL service
created for that CI job only. It also runs frontend lint, tests, and a
production build. The CI PostgreSQL service is disposable and is not the
configured developer or production database. A passing local test run does not
by itself prove that the remote Actions workflow has executed successfully.

## Document uploads

Authenticated users can upload PDF documents to an application at
`POST /api/applications/{application_id}/documents` using multipart form data
with a `file` field and an optional `doc_type` field. Authorized users can list
documents at `GET /api/applications/{application_id}/documents` and download a
document at
`GET /api/applications/{application_id}/documents/{document_id}/download`.

Uploads are validated using the PDF signature and end-of-file marker, limited
to 10 MiB by default, stored under generated filenames outside the frontend
assets, and recorded with a SHA-256 digest and file size. Configure
`DOCUMENT_STORAGE_DIR` and `DOCUMENT_MAX_SIZE_BYTES` to change the storage
location and size limit. Apply the latest Alembic migration before deploying
the new document metadata fields.

## PDF text extraction and OCR

Install the Python dependencies from `requirements.txt`. The pipeline uses
`pypdf` to extract embedded PDF text and PyMuPDF to render image-only pages.
Scanned pages are sent to the single configured OCR engine, Tesseract, through
`pytesseract`. Tesseract itself is a separate system installation and must be
installed manually with the required language data (English by default); make
its executable available on `PATH` or set
`TESSERACT_CMD` to its absolute path. Without Tesseract, scanned pages return
`ocr_unavailable` with a warning rather than implying OCR succeeded. OCR
confidence is the mean recognized-word confidence for the source page; native
PDF text has no confidence estimate.

On Windows, install Tesseract only through a software source approved for your
environment, including the language data you need. Then either add its
installation directory to `PATH` or set `TESSERACT_CMD` in `backend/.env` to
the full executable path (for example,
`C:\Program Files\Tesseract-OCR\tesseract.exe`). Restart the backend and verify
the executable from PowerShell with:

```powershell
Get-Command tesseract
& 'C:\Program Files\Tesseract-OCR\tesseract.exe' --version
```

For a custom location, verify with the configured full path instead. The API
reports the probed OCR engine version and languages; `ocr.available` means the
engine capability probe passed, not that every page was successfully read.
Uniformly near-white pages are reported in `blank_pages` and skipped by OCR.
Pages with no recognized text that are not detected as blank are reported in
`unreadable_pages` with a warning. A noisy or faint scan can be difficult to
distinguish from a failed OCR attempt; it remains a partial result requiring
manual review, not a blank-page or successful-extraction claim.

Only PDFs are processed. Processing defaults to the upload limit (10 MiB),
50 pages, a 60-second total budget, 12 seconds per OCR page, and 1,000,000
characters of extracted text. These limits can be configured with
`DOCUMENT_MAX_SIZE_BYTES`, `DOCUMENT_PROCESSING_MAX_PAGES`,
`DOCUMENT_PROCESSING_MAX_SECONDS`, `DOCUMENT_OCR_PAGE_TIMEOUT_SECONDS`, and
`DOCUMENT_PROCESSING_MAX_TEXT_CHARS`. The parser extracts document data as
untrusted text; it does not execute document scripts or follow embedded
instructions. Field extraction is label-based and returns missing values as
`null`; it does not validate the authenticity of certificates.

The classifier is a deterministic registry-alias matcher, not a trained model.
Its heuristic score is not a calibrated probability, and suggestions always
require human confirmation. Field extraction is deterministic label matching;
it retains source text and page provenance but does not independently verify
the extracted value.

Run the small synthetic functional check from `backend` with:

```powershell
python -m scripts.evaluate_document_intelligence
```

It generates temporary digital PDFs, checks known/unknown registry matching
and checks known, unknown, ambiguous, and inactive-type classification,
schema-label extraction, missing values, and available provenance. It removes
the temporary samples afterward. The reported counts cover only those
fixtures; they are functional smoke checks, not accuracy or generalization
metrics. OCR is deliberately reported as not evaluated because this harness
contains no scanned ground-truth corpus.

After uploading a PDF, process it with:

```http
POST /api/applications/123/documents/456/process
Authorization: Bearer <access-token>
```

Example response:

```json
{
  "document_id": 456,
  "processing_status": "completed",
  "extraction_method": "text",
  "pages_processed": 2,
  "fields": {
    "institution_name": {
      "value": "Northern Research Institute",
      "page": 1,
      "evidence": "Institution Name: Northern Research Institute",
      "confidence": null,
      "status": "extracted"
    },
    "certificate_number": {
      "value": "NR-2026-0042",
      "page": 1,
      "evidence": "Certificate No: NR-2026-0042",
      "confidence": null,
      "status": "extracted"
    },
    "issue_date": {
      "value": "2026-02-14",
      "page": 2,
      "evidence": "Issue Date: 2026-02-14",
      "confidence": null,
      "status": "extracted"
    },
    "expiry_date": {
      "value": null,
      "page": null,
      "evidence": null,
      "confidence": null,
      "status": "missing"
    }
  },
  "warnings": [],
  "processed_at": "2026-10-24T12:00:00Z"
}
```

Results are cached per document; a concurrent process request receives HTTP
409 while another is working. Apply the latest Alembic migration before
deploying the processing API, because it adds nullable result and timestamp
columns to the existing documents table.

## Versioned document type registry

Document-type definitions and their schemas are managed through the authenticated
`/api/document-types` API. Any authenticated user can list and read active types;
only administrators can create types, edit draft type metadata and schema
versions, activate a schema, deactivate/reactivate a type, or deprecate a type.
A new type and its first schema are always drafts.
The current legacy classifier categories are migrated as `legacy_preview`
drafts; they are synthetic suggestions and are not activated or represented as
authoritative requirements.

The administrator endpoints include:

- `GET /api/document-types/` and `GET /api/document-types/{type_id}` to read
  definitions (non-administrators see active types only).
- `POST /api/document-types/` to create a draft type and initial schema.
- `PATCH /api/document-types/{type_id}` to update draft metadata. Metadata
  becomes immutable after activation; create a new schema version for schema
  changes.
- `POST /api/document-types/{type_id}/schema-versions` to add a greater
  semantic version, and `PUT
  /api/document-types/{type_id}/schema-versions/{version_id}` to edit a draft.
- `POST /api/document-types/{type_id}/schema-versions/{version_id}/activate`
  to activate a schema. The former active version is retained as deprecated;
  active and deprecated definitions cannot be edited.
- `POST /api/document-types/{type_id}/deprecate` to stop new processing against
  the type while retaining its version history.
- `POST /api/document-types/{type_id}/deactivate` and
  `POST /api/document-types/{type_id}/activate` to temporarily disable or
  restore an active type without changing its active schema version.
- `POST /api/document-types/validate-schema` to validate a schema definition
  without persisting it.

Schema fields support string, integer, number, boolean, ISO date/datetime,
enumeration, array, and object types with validated constraints and
normalization. A schema checks the shape of unverified extracted values only.
It does not prove authenticity, issuer identity, legal applicability, or
regulatory compliance. Processing responses identify their selected type and
exact schema-version ID and retain field source page/excerpt references.
Unknown, inactive, unsupported-format, unavailable, invalid, pending, and
blocked schema outcomes are explicit; they are not successful validation
claims. Documents without an active applicable schema remain processable but
receive an explicit non-evaluated schema outcome.

Administrators and application-assigned reviewers can record a type correction
at `POST /api/applications/{application_id}/documents/{document_id}/type-corrections`.
The request requires an active type and a reason. Corrections append history,
retain the original classifier prediction separately, and invalidate cached
extraction so the corrected document can be processed again. The matching
`GET .../type-corrections` endpoint returns that history. Classifier suggestions
never automatically change the selected document type.

Apply the current Alembic head only to an explicitly authorized target
environment. Do not run migration commands against the configured application
database as part of local development or testing without database-owner
approval.

## Application validation status

Run the current registry checks with
`POST /api/applications/{application_id}/validate-all`. The response separates
execution from outcome: `execution_status` reports whether orchestration
completed or had an unavailable/failed stage; `status` is `completed`,
`partial`, or `inconclusive`. An inconclusive result means no regulatory rule
was evaluated, including when no rule applies. A partial result indicates
that a rule check needs review, some rules were not evaluated, or a stage was
incomplete. Neither status indicates that an application is compliant.

Each request creates a persisted validation run with an ID, timestamps,
initiating user, per-stage outcomes, rule counts, result snapshot, and
associations to regulatory assessments and any consistency run. The response
includes the same stored run ID, stages, and result snapshot.
`GET /api/applications/{application_id}/validation-runs` reloads the authorized
application's persisted run history. Evidence references contain only
document, extracted-field, page, or excerpt data that was actually stored;
extraction remains unverified. Missing provenance is reported as unavailable.
Pending, failed, OCR-unavailable, and unsupported document types are not
treated as successful validation evidence. Registry unavailability is
persisted as a partial execution with an inconclusive outcome; result
persistence failure returns HTTP 500.

The central run inspects each stored PDF using the upload-time/current-file
SHA-256 comparison, existing duplicate-hash, PDF-structure, and metadata
checks. A hash mismatch indicates that stored bytes differ from the upload-time
hash; it does not establish fraud or issuer identity. These are advisory
signals only:
`issuer_verification` remains `not_performed` and `authenticity_status` remains
`not_assessed`. Findings are included in the run snapshot with their persisted
finding IDs and available document evidence references. A run processes pending
documents through the existing document-processing endpoint before validation.
Current completed extraction results are reused. Failed and partial documents
require an explicit retry from the document workspace; OCR-unavailable results
are not presented as successful extraction. The run snapshots each persisted
document-schema outcome, schema-version ID, and available extracted-field
source references. Missing schema evaluations are recorded as `not_evaluated`;
schema outcomes remain data-shape checks, not regulatory or authenticity
decisions.

The current registry contains unapproved candidate rules whose IDs do not
have implementations in the legacy evaluator. Those candidates remain
`Not evaluated`; they are not automatically approved or reported as
compliant. The existing synthetic checklist and extracted-field consistency
comparisons are included as explicitly identified stages. Differing extracted
values are reported as `POSSIBLE_MISMATCH`; a human reviewer must verify the
source documents, and the difference does not establish which value is
correct. Historical `CONFIRMED_MISMATCH` records are presented as unverified
discrepancy indicators. Extracted fields, checklist matches, and field checks
do not establish document authenticity or regulatory compliance. Apply the
latest Alembic migration before deploying the validation-run endpoints.

No trusted issuer-verification service, standalone AI anomaly detector, or
automated reviewer assignment is invoked by this workflow. The separate AI
evidence-search capability is not used to make validation decisions. Duplicate
hash, PDF parser, and metadata checks are limited advisory indicators, not
fraud or authenticity determinations. Rule approval, authoritative rule
mapping, and verified application-scope facts require external review; no
owning issue numbers for these dependencies are established here.

### Safe migration procedure

Before migration, obtain database-owner approval for an explicitly named
non-production target, confirm a restorable backup, and verify the target
using a read-only connection (`SELECT current_database()`, `SELECT
current_user`, and `SELECT version_num FROM alembic_version`). Do not proceed
if the database identity is uncertain or it resolves to `vigilant_db`.

In a dedicated PowerShell process, set `DATABASE_URL` to the approved target's
connection URL without saving it in tracked files, then run from `backend`:

```powershell
python -m alembic current
python -m alembic upgrade head
python -m alembic current
Remove-Item Env:\DATABASE_URL
```

Confirm the resulting revision matches the intended repository head and run
authorized application smoke checks against that same target. The current
repository head is `d29f6a4c120e`; a read-only `alembic current` check in this
workspace also reported `d29f6a4c120e`. Verify the target again immediately
before any future migration because database state is environment-dependent.

## Architecture
- `app/main.py`: Application entry point.
- `app/core/`: Configuration and security utilities.
- `app/db/`: Database session and base model configuration.
- `app/models/`: SQLAlchemy ORM models.
- `app/schemas/`: Pydantic data validation schemas.
- `app/api/`: API route handlers.
- `app/services/`: Business logic.

## Implemented capabilities and limitations
- Database connectivity and Alembic migrations.
- JWT-based authentication, role checks, and institution-based application
  isolation.
- Application and document APIs, including PDF upload, listing, and authorized
  download.
- PDF text extraction and optional Tesseract OCR for scanned pages, followed by
  label-based structured-field extraction.

OCR requires a separately installed Tesseract executable and language data.
Document processing extracts evidence but does not establish certificate
authenticity or replace human regulatory review. See the sections above for
setup, limits, endpoint usage, and response details.
