# VIGILANT AI synthetic end-to-end demo guide

This guide is a reproducible **planned demo sequence**, not a claim that the full sequence has been executed. Use synthetic data and a disposable database. Do not use the configured `vigilant_db` or production data for write operations.

## Before the demo

1. Use a disposable PostgreSQL database created specifically for the demonstration. Confirm its identity with read-only checks (`SELECT current_database()`, `SELECT current_user`) and verify it is not `vigilant_db`.
2. Read the migration head and current revision from the backend directory:

   ```powershell
   Set-Location .\backend
   .\venv\Scripts\python.exe -m alembic heads
   .\venv\Scripts\python.exe -m alembic current
   ```

3. Configure the backend process environment for that disposable database without changing the existing `.env`. Run the migration only against the verified disposable target when explicitly intended. Never use a broad reset or drop/recreate action.
4. Create test users through the supported account workflow in the disposable database. Use an administrator and an institution user with roles appropriate to the scenario. Do not reuse or disclose production credentials.
5. If testing scanned pages, verify a local Tesseract executable and language packs with `--version` and the OCR capability check. If unavailable, test the explicit unavailable state; do not present OCR as successful.
6. Start the backend and frontend only after confirming they use the disposable database:

   ```powershell
   # Backend terminal
   Set-Location .\backend
   .\venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

   ```powershell
   # Frontend terminal, repository root
   npm run dev
   ```

## Synthetic workflow

1. Sign in as the disposable administrator. Confirm unauthenticated registry requests are denied.
2. Create a synthetic document type and schema through Document Registry. Validate an invalid schema and confirm the API rejects it.
3. Edit the draft metadata/schema, activate a schema version, and confirm the resulting active version in the registry. Deactivate/reactivate the type and confirm the same active schema version remains in history.
4. Sign in as the synthetic institution user and create/select a synthetic application.
5. Upload two generated PDFs with distinct synthetic values. Verify the document list, file sizes, and recorded upload hashes.
6. Process a digital PDF. Inspect page text, classifier suggestion/evidence, schema-version ID, extracted raw/normalized values, missing fields, and warnings. Do not interpret extraction as authenticity.
7. Process a synthetic scanned PDF only if OCR has been independently confirmed available. Otherwise, verify `ocr_unavailable` and ensure extracted values are not fabricated.
8. Upload a malformed PDF to confirm safe rejection. Use an unknown document type to confirm it is explicitly unsupported/not evaluated rather than assigned an unrelated schema.
9. Run the document integrity check. Confirm stored-file hash status and duplicate status. If testing mismatch behavior, alter only a disposable synthetic stored file in the disposable environment; confirm the mismatch is logged and never labeled fraud or authentic.
10. Run central application validation. Inspect persisted stage outcomes, the validation-run ID, processing/schema evidence references, rule counts, integrity results, and any consistency comparison.
11. Confirm candidate regulatory rules without recorded approval remain not evaluated/inconclusive; do not create or mark a rule approved merely for demo completeness.
12. Record one authorized reviewer decision or document-type correction if the required role is configured. Confirm the original machine prediction/result and previous review remain available.
13. Reload the page and retrieve validation/consistency histories from the API. Confirm the same persisted run and evidence references are displayed.
14. Verify authorization boundaries using another synthetic account from a different institution. Confirm it cannot access or mutate the first institution’s records.
15. Capture only synthetic screenshots/logs and redact tokens and configuration values.

## Automated checks

From the repository root:

```powershell
npm test -- --run
npm run build
npm run lint
```

In the backend:

```powershell
Set-Location .\backend
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m scripts.evaluate_document_intelligence
```

The evaluation harness is a synthetic functional smoke suite, not a representative accuracy benchmark. GitHub Actions is configured to run frontend quality checks, backend tests, and a migration rehearsal on its job-local PostgreSQL service; a local configuration edit is not evidence that the remote workflow passed.

## Expected honesty and stopping conditions

- Stop before any write if database identity is uncertain or the target resolves to `vigilant_db`.
- Do not upload documents until authentication and application ownership are confirmed.
- OCR unavailable/error, unknown document type, missing schema, unapproved rule, unavailable issuer, and insufficient evidence must remain explicit non-success outcomes.
- Do not describe a checksum, metadata signal, OCR result, classifier suggestion, or retrieved passage as proof of authenticity or regulatory compliance.
- No browser-level E2E, live PostgreSQL workflow, issuer verification, or authoritative regulatory approval has been demonstrated by this guide.
