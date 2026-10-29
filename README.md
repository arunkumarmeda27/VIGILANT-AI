# VIGILANT AI

Evidence-led institutional application validation frontend prototype for SIH26261. It uses deterministic synthetic data only; document extraction, authority verification, anomaly detection, compliance assessments, roles, and audit history are explicitly simulated.

## Run locally

```powershell
npm install
npm run dev
```

Build the production bundle with `npm run build` and run the available lint check with `npm run lint`.

## Development validation API

`npm run dev:api` starts a local API on port 3000. It persists only application metadata and validation-run JSON under `.data/`, which is intentionally ignored by Git. The API requires a trusted upstream identity gateway in production. For local tests only, requests use an `x-vigilant-actor` JSON header; this header is not authentication and must never be exposed directly to the internet.

The API accepts document metadata, not binary document content. It validates filenames, MIME type and declared size before creating a deterministic validation run. Issuer checks and regulatory evaluation are correctly returned as unavailable or skipped until authorized adapters and datasets are supplied.

## Share a demo with ngrok

VIGILANT AI accepts an ngrok hostname only when it is supplied at runtime. No ngrok credential or public URL is stored in the project.

1. Install and authenticate the ngrok agent locally; never commit its token.
2. Optionally set `NGROK_DOMAIN` in a local environment file for a reserved hostname.
3. Run `npm run dev:public`, then use `ngrok http 5173`.

## Important limitation

This is not a production approval system. It has no backend, persistent database, real OCR, authorized source connection, secure file storage, authentication, server-enforced permissions, or immutable audit log. Do not upload real institutional or personal documents.
