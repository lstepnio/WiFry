# WiFry Agent Workflow

This file defines the git workflow for all AI agents (Claude Code, Codex, etc.)
contributing to this repository. Both platforms MUST follow these rules.

## Git Workflow

### Branching
- **Never commit directly to `main`** — always create a feature branch
- Branch naming: `fix/short-description` or `feat/short-description`
- Keep branches short-lived (one logical change per branch)

### Commits
- One logical change per commit
- Commit message format:
  ```
  type: short description

  Optional longer description.

  Co-Authored-By: <agent name> <noreply@anthropic.com>
  ```
- Types: `feat`, `fix`, `refactor`, `ui`, `remove`, `docs`, `test`

### Pull Requests
- All changes go through PRs — no direct pushes to main
- PR title matches the primary commit message
- PR body includes a summary of changes
- Wait for CI to pass before merging
- Use squash merge to keep main history clean

### Before Starting Work
1. `git fetch origin main`
2. `git checkout -b feat/my-change origin/main`
3. Check for open PRs: `gh pr list` — avoid conflicting with in-flight work
4. If another agent has an open PR touching the same files, coordinate or wait

### Releasing
- Only the human operator tags releases
- Tags follow semver: `v0.1.x`
- Tag only from `main` after all PRs are merged
- The CI pipeline builds the image and creates the GitHub release automatically
- After tagging, verify the build succeeds before announcing

### Deploying to RPi (Development)
- Use SSH: `scp <file> pi@192.168.10.238:/tmp/ && ssh pi@192.168.10.238 "sudo cp ..."`
- Always restart the backend after deploying: `sudo systemctl restart wifry-backend`
- For frontend changes: rebuild locally, tar + scp the dist, extract on RPi

### File Ownership
- Backend files on RPi: owned by `wifry:wifry`
- Config files in `/etc/`: owned by `root`, written via `sudo tee`
- Captures dir: mode 1777 (world-writable for dumpcap)

## Project Structure

```
backend/           — FastAPI Python backend
  app/
    routers/       — API endpoint handlers
    services/      — Business logic
    models/        — Pydantic models
    utils/         — Shared utilities (shell.py, etc.)
  tests/           — pytest test suite
frontend/          — React + TypeScript + Vite + Tailwind
  src/components/  — UI components
  src/hooks/       — Custom React hooks
  src/types/       — TypeScript type definitions
  src/api/         — API client
setup/             — systemd services, sudoers, templates
image-build/       — RPi image builder (build-image.sh)
```

## Key Technical Details

- Backend runs as `wifry` user on port 8080
- Frontend is served by FastAPI (no separate server)
- WiFi AP managed by hostapd (systemd override for rfkill + regdomain)
- Mock mode: `WIFRY_MOCK_MODE=true` for local development on non-Linux
- Tests: `cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/`
- Frontend build: `cd frontend && npm run build`
- SSH to RPi: `ssh pi@192.168.10.238` (key auth configured)

## What NOT to Do

- Don't push directly to main
- Don't create releases/tags (human operator only)
- Don't modify `/etc/sudoers.d/wifry` without testing with `visudo -c`
- Don't delete `.git` on the RPi
- Don't run `git push --force` on main
- Don't deploy untested code to the RPi
