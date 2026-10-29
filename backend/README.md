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
pytest
```

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

Only PDFs are processed. Processing defaults to the upload limit (10 MiB),
50 pages, a 60-second total budget, 12 seconds per OCR page, and 1,000,000
characters of extracted text. These limits can be configured with
`DOCUMENT_MAX_SIZE_BYTES`, `DOCUMENT_PROCESSING_MAX_PAGES`,
`DOCUMENT_PROCESSING_MAX_SECONDS`, `DOCUMENT_OCR_PAGE_TIMEOUT_SECONDS`, and
`DOCUMENT_PROCESSING_MAX_TEXT_CHARS`. The parser extracts document data as
untrusted text; it does not execute document scripts or follow embedded
instructions. Field extraction is label-based and returns missing values as
`null`; it does not validate the authenticity of certificates.

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
