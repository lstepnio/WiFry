#!/usr/bin/env python3
"""Validate deploy/release paths against the current single-service runtime model."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

RULES = {
    "Makefile": {
        "must_contain": [
            r"ci-deploy-smoke:",
            r"python3 tools/validate_release_paths\.py",
            r"sudo systemctl restart wifry-backend",
            r"curl -sf http://localhost:8080/ \| grep -qi '<!doctype html>'",
            r"rsync -a --delete /tmp/wifry-update/frontend/dist/ /opt/wifry/frontend/dist/",
        ],
        "must_not_contain": [
            r"\bwifry-frontend\b",
            r"cp -r /tmp/wifry-update/frontend/dist /opt/wifry/frontend/dist",
        ],
    },
    "setup/install.sh": {
        "must_contain": [
            r"cp \"\$INSTALL_DIR/setup/wifry-backend\.service\" /etc/systemd/system/",
            r"cp \"\$INSTALL_DIR/setup/wifry-recovery\.service\" /etc/systemd/system/",
            r"systemctl enable wifry-backend\.service",
            r"systemctl enable wifry-recovery\.service",
            r"systemctl start wifry-backend",
            r"sync_frontend_dist\(\)",
            r"rsync -a --delete \"\$src_dir/\" \"\$dest_dir/\"",
            r"check \"Frontend served by backend\" \"curl -sf http://localhost:8080/ \| grep -qi '<!doctype html>'\"",
        ],
        "must_not_contain": [
            r"\bwifry-frontend\b",
            r"cp -r \"\$PROJECT_DIR/frontend/dist\" \"\$INSTALL_DIR/frontend/dist\"",
        ],
    },
    "setup/wifry-recovery.sh": {
        "must_contain": [
            r"for SVC in wifry-backend hostapd dnsmasq; do",
            r"journalctl -u wifry-backend -u hostapd -u dnsmasq",
        ],
        "must_not_contain": [r"\bwifry-frontend\b"],
    },
    "backend/app/routers/system.py": {
        "must_contain": [
            r"journalctl\", \"-u\", \"wifry-backend\",",
            r"\"-u\", \"hostapd\", \"-u\", \"dnsmasq\"",
        ],
        "must_not_contain": [r"\bwifry-frontend\b"],
    },
    "image-build/build-image.sh": {
        "must_contain": [
            r"frontend/dist/index\.html",
            r"rsync -a --delete \"\$PROJECT_DIR/frontend/dist/\" \"\$INSTALL_DIR/frontend/dist/\"",
            r"systemctl restart hostapd dnsmasq wifry-backend",
        ],
        "must_not_contain": [r"\bwifry-frontend\b"],
    },
    ".github/workflows/ci.yml": {
        "must_contain": [
            r"name: Deploy Script Smoke",
            r"make ci-deploy-smoke",
            r"make ci-backend",
            r"make ci-backend-release-risk",
            r"make ci-frontend",
        ],
    },
    ".github/workflows/build-image.yml": {
        "must_contain": [
            r"make ci-release",
            r"xz -t",
            r"sha256sum -c",
        ],
    },
}


def main() -> int:
    failures: list[str] = []

    for rel_path, checks in RULES.items():
        path = ROOT / rel_path
        if not path.exists():
            failures.append(f"missing required file: {rel_path}")
            continue

        content = path.read_text()
        for pattern in checks.get("must_contain", []):
            if not re.search(pattern, content, re.MULTILINE):
                failures.append(f"{rel_path}: missing pattern {pattern!r}")
        for pattern in checks.get("must_not_contain", []):
            if re.search(pattern, content, re.MULTILINE):
                failures.append(f"{rel_path}: unexpected pattern {pattern!r}")

    if failures:
        print("Release path validation failed:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1

    print("Release path validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
