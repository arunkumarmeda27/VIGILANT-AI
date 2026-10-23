# VIGILANT AI

Evidence-led institutional application validation prototype for SIH26261.

## Run locally

```powershell
npm install
npm run dev
```

Build the production bundle with `npm run build`.

## Share a demo with ngrok

VIGILANT AI is configured to listen beyond `localhost` and to accept only an explicitly declared ngrok host header. No ngrok credential or public URL is stored in the project.

1. Install the [ngrok agent](https://ngrok.com/download) and authenticate it locally with the authtoken from your ngrok dashboard. Do not add that token to this repository.
2. If you are using a reserved ngrok domain, create a local `.env` file from `.env.example` and set `NGROK_DOMAIN` to its hostname, for example `team-demo.ngrok.app`.
3. Start VIGILANT AI:

```powershell
npm install
npm run dev:public
```

4. In a second terminal, create a temporary tunnel:

```powershell
ngrok http 5173
```

For a reserved domain, use the command shown in the ngrok dashboard for that domain, pointing it to port `5173`. Share the resulting HTTPS URL with judges. Vite provides SPA fallback, so direct links such as `/applications/APP-2026-00418` continue to resolve through the tunnel.

For a production-style local preview, run `npm run build`, then `npm run preview:public`, and point ngrok to port `4173` instead.

## Scope and limitations

This frontend prototype provides routing, local form validation, uploads held in browser state, deterministic synthetic application data, review findings, filters, tabs, and legal pages. Authentication is explicitly simulated and no data is sent to a backend. Verification outcomes are clearly labelled simulated. It must not be used with real personal or institutional documents until a secured backend, authorized identity service, private object storage, PostgreSQL, retention policy, and authorized source integrations have been configured.

The expected production architecture separates a React frontend from FastAPI services for server-side authorization, document handling, OCR, SHA-256/perceptual deduplication, PostgreSQL migrations, and audit logging. Environment variables and authority credentials are intentionally not included in this prototype.

When exposing this prototype through ngrok, treat the link as a presentation surface only. It has simulated authentication and must not receive real institutional documents or personal data.
