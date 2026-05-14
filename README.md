# 311 Live

311 Live is a mobile-first civic reporting demo. A resident can show a local
street condition through their phone camera, talk with a live intake agent, and
review a structured 311-style report draft before confirming it.

## Live Demo

- Citizen reporting app: [311 Live Demo](https://live311-frontend-916762998168.us-central1.run.app)
- Backend service: [Cloud Run API](https://live311-backend-916762998168.us-central1.run.app)

The hosted Gemini Live path is protected by an access code. Ask the project
owner for the current demo code before testing live voice/video intake.

## What It Does

- Streams phone microphone audio and camera frames to a live intake agent.
- Uses browser geolocation and backend reverse geocoding as approximate location
  context.
- Requires the resident to confirm or correct the location before drafting.
- Generates a reviewable 311-style report draft with title, description,
  location, routing, evidence, uncertainty, and DTPR-style data-use disclosures.
- Lets the resident edit key draft fields and confirm the demo report.
- Keeps 311 reports non-emergency: immediate danger or emergency help should go
  to 911.

## Demo Flow

1. Open the hosted demo on a phone.
2. Enter the live demo access code.
3. Allow camera, microphone, and location permissions.
4. Say what you want to report while showing the issue.
5. Confirm the issue details and report location when the agent asks.
6. Review the generated report draft.
7. Confirm the report when the draft looks correct.

The strongest current demo path is a sidewalk or curb obstruction, such as trash
bags, boxes, or loose refuse narrowing pedestrian passage.

## Current Safety Boundaries

- Location from the phone is approximate and must be confirmed by the resident.
- Reverse-geocoded street labels are treated as candidates, not final truth.
- If the resident corrects the location, the agent must repeat the corrected
  location back and receive explicit confirmation before drafting.
- Priority labels are intentionally not part of the product; 311 reports should
  capture facts and impacts without presenting a computed urgency score.
- This app creates a demo draft. It does not submit to the live NYC311 system.

## Stack

- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: FastAPI, Pydantic, pytest
- Live agent: Gemini Live through a backend WebSocket bridge
- Location labeling: deterministic fallback plus optional Mapbox reverse
  geocoding
- Deployment: Google Cloud Run, split frontend and backend services

## Repository Layout

```text
backend/
  main.py                  FastAPI app, REST routes, and live WebSocket bridge
  schemas.py               Pydantic API and report models
  agents/                  Gemini Live session and report-building logic
  tools/                   DTPR, routing, location labeling, and report storage
  tests/                   Backend test suite
frontend/
  app/                     Next.js app shell and live intake UI
  components/              Report review, DTPR chain, and status UI
  lib/api.ts               Typed frontend API client
docs/                      Internal planning and project context
```

## Local Development

Create a Python environment and install backend dependencies:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Run backend tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider backend/tests
```

Start the backend:

```bash
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend:

```bash
cd frontend
npm install
BACKEND_INTERNAL_URL=http://127.0.0.1:8000 npm run dev -- -H 127.0.0.1 -p 3000
```

Open:

http://127.0.0.1:3000

## Local Gemini Live Testing

Gemini Live requires Google Cloud credentials and Vertex AI access. Set the
needed environment variables in your local `.env`, then run the backend with
live mode enabled:

```bash
bash -c 'set -a && source .env && set +a && LIVE_MODEL_MODE=gemini-live .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --log-level info'
```

Run the frontend against that backend:

```bash
cd frontend
BACKEND_INTERNAL_URL=http://127.0.0.1:8001 NEXT_PUBLIC_WS_BASE_URL=ws://127.0.0.1:8001 NEXT_PUBLIC_REAL_LOCATION_MODE=true npm run dev -- -H 127.0.0.1 -p 3001
```

For phone testing, expose both frontend and backend through HTTPS/WSS tunnels.
Mobile camera and geolocation require a secure browser context.

## Verification

Backend:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider backend/tests
```

Frontend:

```bash
cd frontend
npm run build
```

Hosted smoke checks:

```bash
curl -sS https://live311-backend-916762998168.us-central1.run.app/api/health
curl -sS https://live311-frontend-916762998168.us-central1.run.app/api/backend/api/health
```

## Notes

- The hosted demo is optimized for live exhibition testing, not production 311
  submission.
- Keep secrets in `.env` or Cloud Run environment variables. Do not commit API
  keys, access codes, or local environment files.
- Planning documents under `docs/` are internal working context and are not
  required to run the demo.
