# CivicPulse — from complaint to closure, with proof

A civic accountability layer for Bengaluru. Citizens report a pothole, dead streetlight or garbage black spot with a voice note (Kannada / English / Hindi) and a photo; Gemini turns it into a routed ticket; duplicates are clustered and ranked by civic impact; and every "Resolved" is **checked against evidence** — before/after photo audit, citizen proof photos, repeat-failure tracking and public ward scorecards.

## Documentation

| Document | What it covers |
|---|---|
| [docs/PRD.md](docs/PRD.md) | **Product Requirements** — problem, goals, personas, user journeys, functional requirements FR-1…FR-10 with acceptance criteria, NFRs, success metrics, roadmap, open questions |
| [docs/TDD.md](docs/TDD.md) | **Technical Design** — architecture, data model, intake pipeline, routing rules, impact score, closure state machine, AI resilience layer, privacy, deployment, testing, trade-offs |
| [docs/WHATSAPP.md](docs/WHATSAPP.md) | WhatsApp Business intake setup |

## Quick start

Prerequisites: Python 3.11+, Node 20+, optionally `ffmpeg` and a `GEMINI_API_KEY` (the app runs fully offline without one).

```bash
cp .env.example .env                       # add GEMINI_API_KEY=... for live voice/vision (optional)

cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m scripts.seed_demo      # loads the Bengaluru demo story
.venv/bin/uvicorn app.main:app --reload --port 8000     # http://localhost:8000/docs

cd ../frontend && npm install && npm run dev            # http://localhost:5173
```

Or: `make setup && make seed && make api` / `make web`. Single container: `docker build -t civicpulse . && docker run -p 8080:8080 -e GEMINI_API_KEY=... civicpulse`.

Tests: `cd backend && .venv/bin/python -m pytest -q` · `cd frontend && npm run typecheck`.

