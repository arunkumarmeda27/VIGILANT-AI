# VIGILANT AI Prototype Status

This report reflects repository inspection and automated tests run during the current implementation pass. It does not certify production readiness or current regulatory applicability.

| Feature | Status | Files/coverage | Limitations and manual verification |
| --- | --- | --- | --- |
| Authenticated application lifecycle | Implemented and tested | `backend/app/api/routes/applications.py`, `backend/app/api/routes/institutions.py`, `backend/app/schemas/applications.py`, application/ownership tests, live pages in `src/main.tsx` | API creates with a client-supplied unique reference; backend sets initial status. Institution users derive ownership from their account. Administrators select an institution; institution creation does not automatically assign users. |
| Live application dashboard, list, detail, create and update | Implemented and tested | `src/main.tsx`, `src/styles.css`; backend lifecycle tests | TypeScript/build/lint and backend tests pass. Browser/manual interaction and live PostgreSQL requests were not run. |
| PDF upload and processing | Implemented and tested | `backend/app/services/documents.py`, `backend/app/services/document_processing.py`, `backend/app/api/routes/applications.py`, `backend/tests/test_documents.py` | Native text extraction and optional OCR are available. OCR depends on Tesseract installation/configuration. Extracted values remain unverified. |
| Synthetic PDF demonstration input | Implemented and tested | `backend/create_synthetic_demo_pdf.py` | Local extraction verified; generator refuses to overwrite. The sample is conspicuously fictional and has no legal/issuer status. |
| Fire Safety preview rules | Implemented and tested | `backend/app/services/regulatory_validation.py`, `data/processed/regulatory_rules/fire_safety_preview_registry.json`, `backend/tests/test_regulatory_validation.py` | Candidate rules remain disabled absent source, currentness, applicability and explicit approval. No current-law determination or final compliance result. |
| AICTE Evidence Search | Implemented and tested | `backend/app/api/routes/ai.py`, `backend/app/services/ai_evidence.py`, existing retrieval/generation modules, `backend/tests/test_ai.py`, `src/main.tsx` | Retrieval datasets and source documents must be available. It does not establish rule applicability or inspect private uploads. |
| Integrity assistance | Partially implemented and tested | `backend/app/api/routes/applications.py`, `backend/app/schemas/applications.py`, `backend/tests/test_documents.py`, document UI | Same-application SHA-256 duplicate comparison and limited PDF structure/metadata checks are available. They are heuristics only; issuer verification is not performed and authenticity remains `not_assessed`. |
| Audit history | Implemented and tested | `backend/app/api/routes/audit.py`, `backend/app/api/routes/applications.py`, `backend/tests/test_applications.py`, `backend/tests/test_documents.py`, `src/main.tsx` | Authenticated, role-scoped, paginated read API/UI. Selected application, institution, and document events are recorded; metadata is allowlisted. This is not a tamper-proof or complete audit ledger. Validation preview remains read-only. |
| Compliance assessment display | Implemented and tested | `backend/app/api/routes/compliance.py`, `backend/tests/test_compliance.py`, `src/main.tsx` | Read-only, role-scoped persisted assessments appear in the review queue and compliance page. The pages do not create assessments or infer compliance from missing records. |
| Persisted report summaries | Implemented | `src/main.tsx` | Numeric application routes show authorized application, document, and recorded assessment records. Nonnumeric prototype routes remain explicitly simulated. No authenticity or compliance conclusion is generated. |
| Security and production readiness | Partially implemented | Auth dependencies, ownership checks, file storage/download checks, configuration and tests | Tests exercise auth and ownership, but no production security certification, deployment review, rate limiting, or browser E2E verification has been performed. |

## Verification performed

- `.\venv\Scripts\python.exe -m pytest -q` from `backend`: **106 passed, 15 warnings**.
- `npm run build`: **passed**.
- `npm run lint`: **passed**.
- `git diff --check`: **passed** (Git printed line-ending normalization warnings for existing backend files).
- Synthetic PDF generation and native text extraction: **passed**; expected synthetic institution and certificate-number fields were extracted.
- Synthetic PDF overwrite refusal: **passed**.

The automated backend tests use isolated SQLite test databases. No live PostgreSQL request, database migration, or record creation was performed as part of this report. No browser-level end-to-end run was performed. Frontend build and lint validate compilation/style rules, not actual browser interaction.
