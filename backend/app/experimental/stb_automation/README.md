# STB_AUTOMATION — STB Test Automation Platform

Automated UI crawling, test flow recording, anomaly detection, and
diagnostic collection for Android-based set-top boxes via ADB + optional
HDMI vision.

## Feature Flag

`stb_automation` — disabled by default, category `experimental`.
All endpoints return 404 when disabled.

## Current Phase: 1A — Screen Reader + Logcat Monitor

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/experimental/stb/status` | Automation status |
| GET | `/api/v1/experimental/stb/state?serial=...` | Current screen state |
| GET | `/api/v1/experimental/stb/events` | Recent logcat events |
| POST | `/api/v1/experimental/stb/monitor/start` | Start logcat monitor |
| POST | `/api/v1/experimental/stb/monitor/stop` | Stop logcat monitor |

### Dependencies

- Existing `adb_manager` service (shell, logcat, send_key)
- Existing `feature_flags` service
- No additional pip packages required

### Signal Sources (ranked by cost)

1. **Logcat stream** — real-time, free, detects activity transitions
2. **`dumpsys window windows`** — on-demand, ~50ms
3. **`uiautomator dump`** — on-demand, ~200-500ms
4. **HDMI AI vision** — on-demand, ~$0.01/frame (Phase 1G)

## Planned Phases

- **1A** Screen Reader + Logcat Monitor *(current)*
- **1B** Smart Remote Control (settle detection)
- **1C** Crawl Engine + Navigation Model
- **1D** Anomaly Detection + Auto Diagnostics
- **1E** Test Flow Recording & Replay
- **1F** Chaos Mode
- **1G** Natural Language Test Runner + Vision Fallback
- **1H** Frontend Panel

## Removal

To fully remove this module:

1. Delete `backend/app/experimental/stb_automation/`
2. Remove the guarded import block in `backend/app/main.py`
3. Remove `stb_automation` from `feature_flags.py` DEFAULTS
4. Remove storage path entries (`stb_nav_models`, `stb_test_flows`)
   from `storage.py`
5. Remove `stb_automation: false` from `useFeatureFlags.ts` FALLBACK
6. Remove TS types and API client functions from frontend
7. Remove any frontend panel components
