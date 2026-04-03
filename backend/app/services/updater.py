"""Self-update service via git pull.

Pulls latest changes from the git remote and optionally
rebuilds the frontend and restarts services.
"""

import logging
from datetime import datetime, timezone

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

INSTALL_DIR = "/opt/wifry"


async def check_updates() -> dict:
    """Check if updates are available from the remote."""
    if settings.mock_mode:
        return {
            "current_commit": "abc1234",
            "current_branch": "main",
            "remote_ahead": 3,
            "update_available": True,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    result = await run("git", "-C", INSTALL_DIR, "fetch", "--dry-run", check=False, timeout=30)

    branch = await run("git", "-C", INSTALL_DIR, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    commit = await run("git", "-C", INSTALL_DIR, "rev-parse", "--short", "HEAD", check=False)
    behind = await run("git", "-C", INSTALL_DIR, "rev-list", "--count", f"HEAD..origin/{branch.stdout.strip()}", check=False)

    ahead_count = int(behind.stdout.strip()) if behind.success and behind.stdout.strip().isdigit() else 0

    return {
        "current_commit": commit.stdout.strip() if commit.success else "unknown",
        "current_branch": branch.stdout.strip() if branch.success else "unknown",
        "remote_ahead": ahead_count,
        "update_available": ahead_count > 0,
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }


async def pull_update() -> dict:
    """Pull latest changes and rebuild."""
    if settings.mock_mode:
        return {
            "status": "ok",
            "message": "Update simulated (mock mode)",
            "new_commit": "def5678",
            "changes": ["3 files changed", "frontend rebuilt"],
        }

    steps = []

    # Git pull
    result = await run("git", "-C", INSTALL_DIR, "pull", "--ff-only", check=False, timeout=60)
    if not result.success:
        return {"status": "error", "message": f"git pull failed: {result.stderr}"}
    steps.append(f"git pull: {result.stdout.strip()}")

    # Install Python deps
    result = await run(
        f"{INSTALL_DIR}/backend/.venv/bin/pip", "install", "-r",
        f"{INSTALL_DIR}/backend/requirements.txt", "-q",
        check=False, timeout=120,
    )
    steps.append("pip install: " + ("ok" if result.success else result.stderr[:100]))

    # Rebuild frontend
    result = await run(
        "npm", "run", "build",
        check=False, timeout=120,
    )
    steps.append("frontend build: " + ("ok" if result.success else result.stderr[:100]))

    # Get new commit
    commit = await run("git", "-C", INSTALL_DIR, "rev-parse", "--short", "HEAD", check=False)

    return {
        "status": "ok",
        "message": "Update complete. Restart services to apply.",
        "new_commit": commit.stdout.strip() if commit.success else "unknown",
        "changes": steps,
    }
