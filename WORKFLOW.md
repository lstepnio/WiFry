# WiFry — Operator Workflow Guide

Step-by-step scenarios for managing WiFry development with Claude Code and Codex.
All scenarios follow the rules in [AGENTS.md](AGENTS.md).

---

## Scenario 1: Feature Development with Claude Code

**When:** You're in a Claude Code session and want to build a feature or fix a bug.

**Prompt to give Claude Code:**
> Create a branch, implement [description], run tests, and create a PR. Follow AGENTS.md.

**What happens:**
```bash
# Claude Code creates a branch
git fetch origin main
git checkout -b feat/my-feature origin/main

# ... makes changes ...

# Run tests
cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/
cd frontend && npx tsc --noEmit && npm run build

# Commit and push
git add <files>
git commit -m "feat: description

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
git push -u origin feat/my-feature

# Create PR
gh pr create --title "feat: description" --body "## Summary
..."
```

**You then:** Review the PR, wait for CI, squash merge when ready.

---

## Scenario 2: Feature Development with Codex

**When:** You want Codex to work on a task autonomously.

**Prompt to give Codex:**
> Implement [description]. Create a branch from main, make the changes, run tests, and open a PR. Follow the rules in AGENTS.md. Do not merge the PR.

**What happens:** Codex creates a branch, makes changes, pushes, and opens a PR automatically.

**You then:** Review the PR, wait for CI, squash merge when ready.

**Tip:** If Claude Code is also working, tell Codex:
> Before starting, check `gh pr list` for open PRs that might conflict with your changes.

---

## Scenario 3: Quick Fix → Test on RPi via SSH

**When:** You're debugging on the RPi and need rapid iteration.

**The loop:**
```bash
# 1. Edit locally (Claude Code or your editor)

# 2. Deploy to RPi for testing
scp backend/app/services/myfile.py wifry:/tmp/
ssh wifry "sudo cp /tmp/myfile.py /opt/wifry/backend/app/services/myfile.py && \
  sudo chown wifry:wifry /opt/wifry/backend/app/services/myfile.py && \
  sudo systemctl restart wifry-backend"

# 3. Test on RPi (browser, curl, logs)
ssh wifry "sudo journalctl -u wifry-backend -f --no-pager"

# 4. Iterate steps 1-3 until it works

# 5. When done, commit via PR (not direct to main)
git checkout -b fix/my-fix origin/main
git add <changed files>
git commit -m "fix: description

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
git push -u origin fix/my-fix
gh pr create --title "fix: description" --body "..."
```

**For frontend changes:**
```bash
# Build locally
cd frontend && npm run build

# Deploy dist to RPi
tar czf /tmp/wifry-fe.tar.gz -C frontend/dist .
scp /tmp/wifry-fe.tar.gz wifry:/tmp/
ssh wifry "sudo rm -rf /opt/wifry/frontend/dist/assets && \
  sudo tar xzf /tmp/wifry-fe.tar.gz -C /opt/wifry/frontend/dist/ && \
  sudo chown -R wifry:wifry /opt/wifry/frontend/dist/ && \
  sudo systemctl restart wifry-backend"
```

**Prompt to give Claude Code for this workflow:**
> Fix [description]. Deploy to the RPi via SSH to test. Once it works, create a branch and PR. Follow AGENTS.md.

---

## Scenario 4: Claude Code and Codex Working in Parallel

**When:** Both agents have tasks assigned at the same time.

**Before assigning work:**
```bash
# Check what's in flight
gh pr list
```

**Rules:**
- Assign non-overlapping areas (e.g., Codex on backend, Claude Code on frontend)
- If overlap is unavoidable, merge the first PR, then tell the second agent to rebase:

**Prompt to give the second agent:**
> Your PR may have conflicts. Run `git fetch origin main && git rebase origin/main`, resolve any conflicts, and force-push your branch.

**After both PRs merge:**
```bash
# Verify main is clean
git checkout main && git pull
cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/
cd frontend && npx tsc --noEmit && npm run build
```

---

## Scenario 5: Tagging a Release

**When:** All PRs are merged and you want to ship a version.

**Steps:**
```bash
# 1. Make sure main is clean
git checkout main && git pull
git status  # should be clean

# 2. Run tests locally
cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/
cd frontend && npx tsc --noEmit && npm run build

# 3. Check what's changed since last release
git log --oneline v0.1.8..HEAD  # adjust previous tag

# 4. Tag the release
git tag -a v0.1.9 -m "v0.1.9: brief description"
git push origin v0.1.9

# 5. Watch the CI build
gh run watch $(gh run list --workflow=build-image.yml --limit 1 --json databaseId --jq '.[0].databaseId')

# 6. Update release notes
gh release edit v0.1.9 --notes "## WiFry v0.1.9
### Changes
- ...
### Flash Instructions
..."
```

**Never ask an agent to tag a release.** This is a human-only action.

---

## Scenario 6: Hotfix on a Released Version

**When:** A critical bug is found on a released version and main has moved ahead.

```bash
# 1. Branch from the release tag
git fetch --tags
git checkout -b fix/hotfix-description v0.1.9

# 2. Make the fix (or ask Claude Code)
# ... edit files ...

# 3. Test
cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/

# 4. Push and create PR targeting main
git push -u origin fix/hotfix-description
gh pr create --title "fix: hotfix description" --body "Hotfix for v0.1.9 issue"

# 5. After merge to main, tag the patch release
git checkout main && git pull
git tag -a v0.1.10 -m "v0.1.10: hotfix for ..."
git push origin v0.1.10
```

---

## Scenario 7: RPi Self-Update from the UI

**When:** The RPi updates itself via System > App Settings > Update.

**What happens under the hood:**
1. Backend calls `git fetch --tags` to discover versions
2. User picks a version (e.g., v0.1.9)
3. Backend runs `git checkout v0.1.9 --force`
4. Runs `chown -R wifry:wifry /opt/wifry`
5. Runs `pip install -r requirements.txt`
6. Runs `npm install && npm run build` in frontend/
7. Writes version to `/opt/wifry/VERSION`
8. Auto-restarts the backend service (3s delay)
9. On failure: rolls back to previous version tag

**Relationship to git tags:** The self-update system checks out the exact same git tag that CI used to build the flashable image. A flashed image and a git-updated RPi have identical code.

**If the update fails:**
```bash
# SSH in and check
ssh wifry
sudo journalctl -u wifry-backend --no-pager -n 30
cat /opt/wifry/VERSION
cat /var/lib/wifry/update_backup.json
```

---

## SSH Setup (One-Time)

Add to `~/.ssh/config`:
```
Host wifry
    HostName wifry.local
    User pi
    StrictHostKeyChecking no
    ConnectTimeout 5
```

Fallback if mDNS doesn't resolve: use `169.254.42.1` (direct Ethernet).

---

## Quick Reference

| Action | Command |
|--------|---------|
| Check open PRs | `gh pr list` |
| Run backend tests | `cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/` |
| Build frontend | `cd frontend && npm run build` |
| Deploy file to RPi | `scp <file> wifry:/tmp/ && ssh wifry "sudo cp /tmp/<file> /opt/wifry/..."` |
| Restart RPi backend | `ssh wifry "sudo systemctl restart wifry-backend"` |
| Check RPi logs | `ssh wifry "sudo journalctl -u wifry-backend -f --no-pager"` |
| Tag a release | `git tag -a v0.1.X -m "..." && git push origin v0.1.X` |
| Watch CI build | `gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId')` |
