# WiFry

WiFry is a Raspberry Pi-based network impairment appliance for testing and diagnosing IP video devices such as STBs. In production, a single FastAPI service serves both the API and the built React frontend on port `8080`, while the Pi also manages the WiFi AP, DHCP/DNS, captures, and related diagnostics.

This README is the onboarding entrypoint for the repo. It favors the current code and scripts over older assumptions.

## What Is Supported Today

- Configure the appliance in **Network Config**
- Create a **Session** before collecting artifacts
- Capture packets, ADB evidence, screenshots, and related test data into that session
- Generate or share a **session bundle** as the supported handoff path for STB/test evidence

## Experimental or Limited Surfaces

- **System > Remote Access** (Cloudflare tunnel / collaboration) is opt-in and experimental
- **Scenario APIs** remain available for automation and testing, but there is no supported primary UI workflow for them
- Hardware-adjacent flows still need real-box validation even when mock-mode CI is green

## Runtime Truth

- Production UI and API are served by `wifry-backend` on port `8080`
- The built frontend lives in `frontend/dist` and is served by FastAPI
- Local frontend development still uses the Vite dev server on port `3000`
- There is no separate `wifry-frontend` systemd service in the current runtime model

## Quick Start

### Local development

```bash
make install
cp backend/.env.example backend/.env
make dev
```

Open:

- UI/API: [http://localhost:8080](http://localhost:8080)
- Vite dev server: [http://localhost:3000](http://localhost:3000)
- API docs: [http://localhost:8080/docs](http://localhost:8080/docs)

### Deploy to a Raspberry Pi from a laptop

```bash
make deploy-ssh RPI=pi@wifry.local
```

### Install directly on a Raspberry Pi

```bash
sudo bash setup/install.sh
```

After install, the appliance should be reachable at:

- WiFi AP: [http://192.168.4.1:8080](http://192.168.4.1:8080)
- Fallback Ethernet recovery IP: [http://169.254.42.1:8080](http://169.254.42.1:8080)

## Key Commands

```bash
# Backend tests (mock mode)
cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/ --ignore=tests/hw -q

# Frontend quality gates
cd frontend && npm run lint && npm test && npx tsc --noEmit && npm run build

# Check a deployed box
make status-ssh RPI=pi@wifry.local
make logs-ssh RPI=pi@wifry.local
```

## Docs Map

- [SETUP.md](SETUP.md): Raspberry Pi install and deployment setup
- [RUNBOOKS.md](RUNBOOKS.md): operator runbooks for install, update, recovery, and security
- [ARCHITECTURE.md](ARCHITECTURE.md): system architecture and supported product surface
- [CONTRIBUTING.md](CONTRIBUTING.md): local setup, validation, and contribution guidance
- [AGENTS.md](AGENTS.md): shared AI-agent workflow rules
- [WORKFLOW.md](WORKFLOW.md): human operator workflow for PRs, releases, and agent coordination

## Repository Layout

```text
WiFry/
├── backend/          FastAPI app, services, models, tests, profiles
├── frontend/         React + TypeScript + Vite UI
├── setup/            Install scripts, systemd units, recovery tools
├── image-build/      Raspberry Pi image build tooling
├── docs/             Screenshots and supporting assets
├── ARCHITECTURE.md   Architecture and runtime model
├── SETUP.md          Deployment setup guide
├── RUNBOOKS.md       Operator runbooks
└── CONTRIBUTING.md   Contributor guide
```

## Notes for Operators

- Session bundles are for STB/test evidence, not for WiFry appliance support dumps.
- WiFry appliance diagnostics live in structured logs, audit events, and operator runbooks.
- If a command or doc still mentions `wifry-frontend`, treat it as stale unless the code or script in the repo has been updated to match.
