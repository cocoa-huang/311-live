# 311 Live

311 Live is a clean rebuild of a mobile-first civic issue reporting app for live 311 intake demos. The MVP helps a citizen describe a local condition with camera, microphone, and location context, then produces a structured draft report with transparent data-use indicators before the citizen confirms submission.

This repository is a clean rebuild. No app code has been copied or migrated from an older repository.

## Product Goal

Build a phone-friendly 311 reporting flow that can:

- Guide a resident through a live multimodal intake conversation.
- Collect only the data needed for the report and make that collection visible with DTPR-style indicators.
- Generate a structured report draft with narrative, category, location, routing, uncertainty, and evidence fields.
- Let the resident review and confirm before a report is submitted or exported.
- Demonstrate a reliable flooding-near-school-crossing scenario for hackathon or exhibition use.

## Current Scope

The current milestone is a live-intake vertical slice:

- FastAPI backend health endpoint.
- Deterministic report draft, edit, model-context, and confirm workflow.
- Backend `/ws/live` contract for live session start, observation, candidate detection, follow-up, location confirmation, and draft creation.
- Next.js frontend that uses camera preview, browser geolocation, browser speech recognition where available, typed fallback, report review, and DTPR data chain rendering.
- Deterministic fallback behavior when the live socket, speech recognition, or civic data lookup is unavailable.

Gemini Live media streaming, final Vertex AI model selection, production reverse geocoding, real 311 submission, and deployment are still upcoming.

Read [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) first in future sessions. It records the product context, source-code boundary, DTPR requirements, and MVP assumptions.

## Planned Stack

- Backend: FastAPI, Pydantic, pytest
- Frontend: Next.js, TypeScript, Tailwind CSS
- Live agent: deterministic WebSocket bridge now; Gemini Live through Vertex AI with Application Default Credentials next
- Deployment target: Cloud Run, likely split frontend and backend services
- Civic routing: Socrata/Open Data lookup where available, with deterministic fallback routing for demo reliability

## Rebuild Rules

- Do not copy source files from the old repo.
- Treat CityNerve as a reference boundary only: ideas and product lessons may inform this rebuild, but code must be written fresh.
- Keep privacy, consent, and data lineage visible in the UI from the first functional prototype.
- Work one step at a time and verify each step before moving on.

## Repository Layout

```text
backend/
  main.py                  FastAPI app and API routes
  schemas.py               Pydantic API/report/DTPR models
  agents/report_builder.py Deterministic demo report builder
  tools/                   DTPR, routing, and in-memory report store helpers
  tests/                   Backend pytest suite
frontend/
  app/                     Next.js App Router pages/styles
  components/              Report review, DTPR chain, status UI
  lib/api.ts               Typed frontend API client
docs/
  PROJECT_CONTEXT.md       Durable project and product context
  IMPLEMENTATION_PLAN.md   Stepwise implementation plan and acceptance criteria
README.md                  Project overview and onboarding
.env.example               Future environment variable template
.gitignore                 Repo hygiene for Python, Node, local env, and build output
```

## Getting Started

Create a local Python environment and install the backend dependencies:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Run backend tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider backend/tests
```

Start the backend locally:

```bash
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Then check `http://127.0.0.1:8000/api/health`.

Create the deterministic demo draft:

```bash
curl -s -X POST http://127.0.0.1:8000/api/report/draft \
  -H "Content-Type: application/json" \
  -d '{"scenario":"flooding_near_school_crossing"}'
```

Run the frontend vertical slice:

```bash
cd frontend
npm install
npm run dev -- -H 127.0.0.1 -p 3000
```

Open `http://127.0.0.1:3000` while the backend is running on port `8000`.

## Vertex Live Adapter

The default live agent mode is deterministic so local demos work without Google Cloud credentials. To test the Vertex-backed Gemini Live adapter, create or select a Google Cloud project, enable Vertex AI, authenticate with Application Default Credentials, and set:

```bash
gcloud auth application-default login
export LIVE_MODEL_MODE=vertex
export GOOGLE_CLOUD_PROJECT=<your-project-id>
export GOOGLE_CLOUD_LOCATION=us-central1
export GEMINI_TEXT_LOCATION=global
export GEMINI_TEXT_MODEL=gemini-2.5-flash
export GEMINI_LIVE_LOCATION=us-central1
export GEMINI_LIVE_MODEL=gemini-live-2.5-flash-preview-native-audio-09-2025
```

The current Vertex path uses `GEMINI_TEXT_MODEL` for REST candidate classification and `GEMINI_LIVE_MODEL` for the local spoken Gemini Live path. Local Gemini Live testing on May 9 confirmed microphone PCM → backend WebSocket → Gemini Live → transcript/audio response works on `127.0.0.1`.

The active Gemini Live demo is now a trash-bags civic intake flow near a demo geolock at East 8th Street and Avenue A, East Village, Manhattan. The prompt is structured around evidence boundaries, category correction, accessibility impact, recurrence, slot quality gates, and readiness criteria. The model should behave like a civic intake investigator rather than a form filler.

During Gemini Live mode, the frontend sends:

- 16 kHz PCM microphone frames over `/ws/live`
- JPEG camera frames at startup and about 1 FPS
- a geolocked demo location payload

The backend forwards audio/image frames to Gemini, streams back 24 kHz PCM audio, streams transcripts, handles `create_report_draft`, and delays `draft_ready` until after `turn_complete` so the final spoken summary is less likely to be cut off.

Latest local status: backend logs now confirm image-frame delivery (`gemini-live: received image frame #1`, `#5`, `#10`, ...), but Gemini still may answer that it cannot see anything. The next debugging target is visual grounding and frame usefulness, not frame transport. Prompt steering also still needs work because Gemini can fall back to generic intake wording instead of the intended trash-bags investigator workflow.

For local laptop Gemini Live testing:

```bash
# Terminal 1
bash -c 'set -a && source .env && set +a && unset GEMINI_API_KEY && LIVE_MODEL_MODE=gemini-live GOOGLE_CLOUD_PROJECT=live-cloud-495302 GEMINI_LIVE_MODEL=gemini-live-2.5-flash-preview-native-audio-09-2025 BACKEND_PORT=8001 .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --log-level info'

# Terminal 2
cd frontend
BACKEND_INTERNAL_URL=http://127.0.0.1:8001 NEXT_PUBLIC_WS_BASE_URL=ws://127.0.0.1:8001 npm run dev -- -H 127.0.0.1 -p 3001
```

Open `http://127.0.0.1:3001`.

## Phone Testing

Mobile camera and location require a secure browser context. Plain `http://<your-laptop-ip>:3000` is useful for layout checks, but phone camera/location permissions usually require HTTPS.

Recommended local phone test:

1. Start the backend:

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

2. Start the frontend without `NEXT_PUBLIC_API_BASE_URL` so it uses the same-origin backend proxy:

```bash
cd frontend
BACKEND_INTERNAL_URL=http://127.0.0.1:8000 npm run dev -- -H 127.0.0.1 -p 3000
```

Do not set `NEXT_PUBLIC_WS_BASE_URL` for the one-tunnel phone demo. The frontend will use the same-origin REST classify path through `/api/backend/...`, which lets Vertex-backed candidate detection work through the frontend tunnel. Set `NEXT_PUBLIC_WS_BASE_URL` only when the backend WebSocket is separately reachable from the phone over `wss://`.

3. Expose the frontend through an HTTPS tunnel, such as ngrok or Cloudflare Tunnel, pointing at `http://127.0.0.1:3000`.

4. Open the HTTPS tunnel URL on your phone. The frontend will call its own `/api/backend/...` proxy, and the Next.js dev server will forward those calls to the local FastAPI backend.

If you set `NEXT_PUBLIC_API_BASE_URL`, make sure it is an HTTPS URL reachable by the phone. Do not set it to `http://127.0.0.1:8000` for phone testing, because that points to the phone itself.

Frontend verification:

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```

## Current Notes

- `npm audit` currently reports two moderate advisories through Next's bundled PostCSS. The critical advisory from the original Next install was resolved by updating to Next `15.5.15`; the remaining npm-suggested fix is an invalid downgrade path, so revisit during dependency maintenance.
- The next planned implementation step is report pipeline expansion: Socrata routing, editable report fields, stronger uncertainty modeling, DTPR taxonomy mapping, and demo controls.
