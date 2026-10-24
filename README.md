# VIGILANT AI

Evidence-led institutional application validation frontend prototype for SIH26261. It uses deterministic synthetic data only; document extraction, authority verification, anomaly detection, compliance assessments, roles, and audit history are explicitly simulated.

## Run locally

```powershell
npm install
npm run dev
```

Build the production bundle with `npm run build` and run the available lint check with `npm run lint`.

## Share a demo with ngrok

VIGILANT AI accepts an ngrok hostname only when it is supplied at runtime. No ngrok credential or public URL is stored in the project.

1. Install and authenticate the ngrok agent locally; never commit its token.
2. Optionally set `NGROK_DOMAIN` in a local environment file for a reserved hostname.
3. Run `npm run dev:public`, then use `ngrok http 5173`.

## Important limitation

This is not a production approval system. It has no backend, persistent database, real OCR, authorized source connection, secure file storage, authentication, server-enforced permissions, or immutable audit log. Do not upload real institutional or personal documents.
