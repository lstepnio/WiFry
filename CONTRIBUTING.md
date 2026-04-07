# Contributing to WiFry

This guide is for contributors working on WiFry locally. It is intentionally practical and aligned to the current repo state.

## Prerequisites

- Python 3.11+
- Node.js and npm
- A checked-out copy of this repo
- Optional: a Raspberry Pi running WiFry for hardware validation

## Local Setup

```bash
make install
cp backend/.env.example backend/.env
```

The backend reads `.env` from the `backend/` working directory. For most local development, keep:

- `WIFRY_MOCK_MODE=true`
- `WIFRY_DEBUG=true`

## Running the App

### Full local dev loop

```bash
make dev
```

This starts:

- FastAPI on `http://localhost:8080`
- Vite dev server on `http://localhost:3000`

### Backend only

```bash
make backend
```

### Frontend only

```bash
make frontend
```

## Validation

Run the checks that match the area you touched.

### Backend

```bash
cd backend
source .venv/bin/activate
WIFRY_MOCK_MODE=true python -m pytest tests/ --ignore=tests/hw -q
```

### Frontend

```bash
cd frontend
npm run lint
npm test
npx tsc --noEmit
npm run build
```

### Release-risk hardware validation

Mock-mode CI is not enough for hardware-adjacent changes. If you touch networking, WiFi, captures, HDMI, ADB, or update/install paths, validate on a real box when possible.

## Environment and Secrets

- Do not commit real API keys or device credentials
- Use `backend/.env` for local overrides
- Prefer defaults from `backend/app/config.py` unless you need an explicit override
- On a deployed Pi, the production service configuration comes from the systemd unit plus runtime files under `/var/lib/wifry`

## Docs Expectations

When you touch install, recovery, update, or operator-facing behavior:

- Cross-check service names against `setup/*.service` and `backend/app/main.py`
- Prefer the actual runtime model over older aspirational wording
- Call out experimental surfaces explicitly
- Update [README.md](README.md), [SETUP.md](SETUP.md), and [RUNBOOKS.md](RUNBOOKS.md) when operator behavior changes

## Git and PR Workflow

This repo uses a PR-first workflow.

- Shared agent rules: [AGENTS.md](AGENTS.md)
- Human/operator workflow: [WORKFLOW.md](WORKFLOW.md)

The short version:

- branch from `origin/main`
- keep one logical change per branch
- open a PR
- wait for CI
- prefer squash merge for easy rollback
