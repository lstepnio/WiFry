# WiFry — Agent Workflow Rules

Shared rules for all AI agents (Claude Code, Codex) contributing to this repo.
The human operator is the final authority on merges, releases, and GitHub settings.

See [WORKFLOW.md](WORKFLOW.md) for detailed operator scenarios with exact commands and prompts.

## Branching

- **Never commit directly to `main`.**
- Create a feature branch from `origin/main` for every change.
- Branch naming: `feat/short-description`, `fix/short-description`, `docs/short-description`
- Keep branches short-lived — one logical change per branch.

## Before Starting Work

1. `git fetch origin main`
2. `git checkout -b feat/my-change origin/main`
3. Check for open PRs: `gh pr list` — avoid conflicting with in-flight work.
4. If another agent has an open PR touching the same files, wait or coordinate.

## Commits

- One logical change per commit.
- Format:
  ```
  type: short description

  Optional longer explanation.

  Co-Authored-By: <agent name> <noreply@anthropic.com>
  ```
- Types: `feat`, `fix`, `refactor`, `ui`, `remove`, `docs`, `test`

## Pull Requests

- All changes go through PRs.
- PR title matches the primary commit message.
- PR body includes a short summary.
- CI must pass before the human operator merges.
- Default merge method: **squash merge** (keeps main history clean, easy rollback).

## Conflict Resolution

- If your PR has conflicts with main, rebase: `git fetch origin main && git rebase origin/main`
- If two agents have overlapping PRs, the second one rebases after the first merges.
- Never force-push to main.

## Releases

- **Only the human operator creates tags and releases.**
- Agents must not run `git tag`, `gh release create`, or push tags.
- Tags follow semver: `v0.1.x` for patches.
- Tag only from `main` after all PRs are merged.
- CI builds the RPi image and creates the GitHub release automatically on tag push.

## RPi Deployment (Development Testing)

RPi deployment via SSH is **separate from the git workflow** and unrestricted.

- Agents may deploy any code to the RPi for testing without a PR.
- Use the `wifry` SSH alias: `scp <file> wifry:/tmp/` and `ssh wifry "sudo cp ..."`
- Always restart after deploying: `sudo systemctl restart wifry-backend`
- This is for rapid iteration only — all tested changes must be committed via PR.

## What Agents Must NOT Do

- Push directly to main
- Create tags or releases
- Merge PRs (human operator only)
- Change GitHub settings (branch protection, merge methods)
- Hard-code DHCP IP addresses — use `wifry.local` or the `wifry` SSH alias
- Delete branches without human approval

## CI Gates

- PR fast feedback:
  - Backend: `cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/ --ignore=tests/hw -q`
  - Backend release-risk: targeted runtime/session/capture/system/storage tests in mock mode
  - Frontend: `cd frontend && npm run lint && npm test && npx tsc --noEmit && npm run build`
- Coverage is informational only. Do not add synthetic tests just to satisfy a percentage target.
- Release verification:
  - Run the manual hardware readiness + smoke suite on a real WiFry box before tagging
  - Run hardware integration checks with `--hw-client-ip` when a connected client is available

## Project Reference

- [SETUP.md](SETUP.md) — installation and RPi setup
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [WORKFLOW.md](WORKFLOW.md) — operator guide with commands and prompts
