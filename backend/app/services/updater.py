"""Tag-based self-update system.

Discovers available versions via git tags, checks out specific
releases, rebuilds frontend/backend, and auto-restarts.

Update flow:
  1. Ensure git repo exists at /opt/wifry (bootstrap if needed)
  2. Fetch tags from remote
  3. Compare current VERSION with latest tag
  4. Checkout target tag
  5. pip install + npm build
  6. Write new VERSION file
  7. Auto-restart backend (deferred 3s)

Rollback: on failure, restore previous version tag + VERSION file.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..config import settings
from ..utils.shell import run

logger = logging.getLogger(__name__)

INSTALL_DIR = "/opt/wifry"
VERSION_FILE = Path(INSTALL_DIR) / "VERSION"
BACKUP_FILE = Path("/var/lib/wifry/update_backup.json")
GIT_REMOTE = "https://github.com/lstepnio/WiFry.git"


# --- Version helpers ---

def get_current_version() -> str:
    """Read current version from VERSION file."""
    try:
        return VERSION_FILE.read_text().strip()
    except Exception:
        return "unknown"


def _parse_semver(tag: str) -> tuple:
    """Parse a version tag like 'v0.1.3' into a sortable tuple."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", tag)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (0, 0, 0)


# --- Git repo management ---

async def ensure_git_repo() -> bool:
    """Ensure /opt/wifry has a git repo. Bootstrap if missing."""
    git_dir = Path(INSTALL_DIR) / ".git"
    if git_dir.is_dir():
        return True

    if settings.mock_mode:
        return True

    # Check git is available
    git_check = await run("which", "git", check=False, timeout=5)
    if not git_check.success:
        logger.warning("git not installed — cannot bootstrap repo")
        return False

    logger.info("Bootstrapping git repo at %s", INSTALL_DIR)

    # Init repo
    result = await run("git", "init", check=False, timeout=10)
    if not result.success:
        # Try from the install dir
        result = await run("git", "-C", INSTALL_DIR, "init", check=False, timeout=10)
        if not result.success:
            logger.error("git init failed: %s", result.stderr)
            return False

    # Add remote
    await run("git", "-C", INSTALL_DIR, "remote", "add", "origin", GIT_REMOTE,
              check=False, timeout=10)

    # Fetch tags (shallow)
    result = await run("git", "-C", INSTALL_DIR, "fetch", "--tags", "--depth=1",
                       check=False, timeout=60)
    if not result.success:
        logger.warning("git fetch tags failed: %s", result.stderr)

    return git_dir.is_dir()


async def get_available_versions() -> List[str]:
    """Get list of available version tags from remote, sorted newest first."""
    if settings.mock_mode:
        return ["v0.1.3", "v0.1.2", "v0.1.1", "v0.1.0"]

    # Check git is installed
    git_check = await run("which", "git", check=False, timeout=5)
    if not git_check.success:
        logger.warning("git not installed — cannot check for updates")
        return []

    await ensure_git_repo()

    # Fetch latest tags
    await run("git", "-C", INSTALL_DIR, "fetch", "--tags",
              check=False, timeout=30)

    result = await run("git", "-C", INSTALL_DIR, "tag", "-l", "v*",
                       check=False, timeout=10)
    if not result.success or not result.stdout.strip():
        return []

    tags = [t.strip() for t in result.stdout.splitlines() if t.strip()]
    # Sort by semver, newest first
    tags.sort(key=_parse_semver, reverse=True)
    return tags


async def get_latest_version() -> Optional[str]:
    """Get the latest available version tag."""
    versions = await get_available_versions()
    return versions[0] if versions else None


# --- Update check ---

async def check_updates() -> dict:
    """Check if updates are available."""
    current = get_current_version()

    if settings.mock_mode:
        return {
            "current_version": current,
            "latest_version": "v0.1.3",
            "update_available": True,
            "available_versions": ["v0.1.3", "v0.1.2", "v0.1.1"],
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    versions = await get_available_versions()
    latest = versions[0] if versions else None

    # Compare: strip 'v' prefix for comparison
    update_available = False
    if latest and current != "unknown":
        latest_tuple = _parse_semver(latest)
        current_tuple = _parse_semver(current)
        update_available = latest_tuple > current_tuple

    return {
        "current_version": current,
        "latest_version": latest,
        "update_available": update_available,
        "available_versions": versions[:10],
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }


# --- Apply update ---

async def apply_update(target_version: str = "") -> dict:
    """Apply an update to a specific version (or latest).

    Steps: backup → fetch → checkout → pip install → npm build → write VERSION → restart
    Returns immediately with status; restart happens 3s later.
    """
    if settings.mock_mode:
        return {
            "status": "ok",
            "message": f"Update to {target_version or 'latest'} simulated (mock mode)",
            "previous_version": get_current_version(),
            "new_version": target_version or "v0.1.3",
            "steps": ["git checkout: ok", "pip install: ok", "frontend build: ok", "restart: scheduled"],
        }

    # Determine target
    if not target_version:
        target_version = await get_latest_version()
        if not target_version:
            return {"status": "error", "message": "No versions available. Check internet connection."}

    # Ensure tag format
    if not target_version.startswith("v"):
        target_version = f"v{target_version}"

    previous_version = get_current_version()
    steps = []

    # Ensure git repo
    if not await ensure_git_repo():
        return {"status": "error", "message": "Failed to initialize git repo"}
    steps.append("git repo: ok")

    # Save backup
    previous_commit = ""
    commit_result = await run("git", "-C", INSTALL_DIR, "rev-parse", "--short", "HEAD",
                               check=False, timeout=5)
    if commit_result.success:
        previous_commit = commit_result.stdout.strip()

    try:
        BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        BACKUP_FILE.write_text(json.dumps({
            "previous_version": previous_version,
            "previous_commit": previous_commit,
            "target_version": target_version,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception as e:
        logger.warning("Failed to save update backup: %s", e)
    steps.append(f"backup: {previous_version} ({previous_commit})")

    # Fetch
    result = await run("git", "-C", INSTALL_DIR, "fetch", "--tags", "--force",
                       check=False, timeout=60)
    if not result.success:
        return {"status": "error", "message": f"git fetch failed: {result.stderr}",
                "steps": steps}
    steps.append("git fetch: ok")

    # Checkout target tag
    result = await run("git", "-C", INSTALL_DIR, "checkout", target_version, "--force",
                       check=False, timeout=30)
    if not result.success:
        return {"status": "error", "message": f"git checkout {target_version} failed: {result.stderr}",
                "steps": steps}
    steps.append(f"git checkout {target_version}: ok")

    # Write VERSION file
    version_str = target_version.lstrip("v")
    try:
        VERSION_FILE.write_text(version_str + "\n")
        steps.append(f"VERSION: {version_str}")
    except PermissionError:
        await run("bash", "-c", f"echo '{version_str}' > {VERSION_FILE}", sudo=True, check=False)
        steps.append(f"VERSION (sudo): {version_str}")

    # pip install
    result = await run(
        f"{INSTALL_DIR}/backend/.venv/bin/pip", "install", "-r",
        f"{INSTALL_DIR}/backend/requirements.txt", "-q",
        check=False, timeout=180,
    )
    if result.success:
        steps.append("pip install: ok")
    else:
        logger.error("pip install failed: %s", result.stderr)
        steps.append(f"pip install: FAILED ({result.stderr[:100]})")
        await _rollback(previous_version, previous_commit)
        return {"status": "error", "message": "pip install failed, rolled back",
                "steps": steps}

    # npm build
    result = await run(
        "bash", "-c", f"cd {INSTALL_DIR}/frontend && npm run build",
        check=False, timeout=180,
    )
    if result.success:
        steps.append("frontend build: ok")
    else:
        logger.error("npm build failed: %s", result.stderr)
        steps.append(f"frontend build: FAILED ({result.stderr[:100]})")
        await _rollback(previous_version, previous_commit)
        return {"status": "error", "message": "Frontend build failed, rolled back",
                "steps": steps}

    # Schedule restart (deferred so HTTP response completes)
    asyncio.create_task(_deferred_restart())
    steps.append("restart: scheduled (3s)")

    logger.info("Update to %s complete, restarting...", target_version)

    return {
        "status": "ok",
        "message": f"Updated to {target_version}. Restarting...",
        "previous_version": previous_version,
        "new_version": version_str,
        "steps": steps,
    }


# --- Rollback ---

async def _rollback(previous_version: str, previous_commit: str) -> None:
    """Restore previous version on update failure."""
    logger.warning("Rolling back to %s (%s)", previous_version, previous_commit)

    if previous_commit:
        await run("git", "-C", INSTALL_DIR, "checkout", previous_commit, "--force",
                  check=False, timeout=30)

    try:
        VERSION_FILE.write_text(previous_version + "\n")
    except PermissionError:
        await run("bash", "-c", f"echo '{previous_version}' > {VERSION_FILE}",
                  sudo=True, check=False)

    logger.info("Rollback complete")


async def _deferred_restart() -> None:
    """Wait 3 seconds then restart the backend service."""
    await asyncio.sleep(3)
    logger.info("Restarting wifry-backend...")
    await run("systemctl", "restart", "wifry-backend", sudo=True, check=False)


# --- Backward compatibility ---

async def pull_update() -> dict:
    """Legacy alias for apply_update (latest version)."""
    return await apply_update()
