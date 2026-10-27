# CivicPulse developer shortcuts. Requires: python3.11+, node 20+, (optional) uv.
PY ?= backend/.venv/bin/python
UV := $(shell command -v uv 2>/dev/null)

.PHONY: setup backend-setup frontend-setup dev api web seed test lint build docker

setup: backend-setup frontend-setup ## install everything

backend-setup:
ifdef UV
	cd backend && uv venv .venv -q && uv pip install -q --python .venv/bin/python -r requirements-dev.txt
else
	cd backend && python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt
endif

frontend-setup:
	cd frontend && npm install --no-audit --no-fund

api: ## run the API on :8000 (serves the built PWA too if frontend/dist exists)
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web: ## run the Vite dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

seed: ## load the Bengaluru demo story
	cd backend && .venv/bin/python -m scripts.seed_demo

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check app tests scripts
	cd frontend && npm run typecheck

build: ## production build of the PWA (served by the API at /)
	cd frontend && npm run build

docker:
	docker build -t civicpulse .
