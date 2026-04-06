"""WiFry — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .routers import adb, annotations, captures, dns, hdmi, hw_tests, impairments, network, network_config, profiles, remote, scanner, scenarios, sessions, sharing, streams, system, teleport, wifi_impairments

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("wifry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("WiFry starting up (mock_mode=%s)", settings.mock_mode)
    if settings.mock_mode:
        logger.warning("Running in MOCK MODE — tc commands will be logged, not executed")
    else:
        # Apply saved network config (or safe defaults) on boot
        # Non-fatal: backend must start even if hostapd/network config fails
        try:
            from .services import network_config as nc_svc
            await nc_svc.boot_apply()
        except Exception as e:
            logger.error("boot_apply failed (non-fatal): %s", e)
            logger.warning("Backend starting with degraded network config — check hostapd/dnsmasq manually")

    # Detect WiFi hardware capabilities (non-fatal, cached for UI)
    try:
        from .services import hw_capabilities
        await hw_capabilities.detect_capabilities()
    except Exception as e:
        logger.error("WiFi capability detection failed (non-fatal): %s", e)

    yield

    # --- Graceful shutdown: cancel background tasks, kill subprocesses ---
    logger.info("WiFry shutting down — cleaning up...")
    try:
        from .services import wifi_impairment, gremlin, capture, adb_manager
        # Deactivate gremlin if active
        await gremlin.deactivate()
        # Clear WiFi impairments (stops background tasks)
        await wifi_impairment.clear()
        # Stop all running captures
        for cap_id, info in list(capture._captures.items()):
            if info.status == "running":
                try:
                    await capture.stop_capture(cap_id)
                except Exception:
                    pass
        # Stop all logcat sessions
        for sess_id in list(adb_manager._logcat_sessions.keys()):
            try:
                await adb_manager.stop_logcat(sess_id)
            except Exception:
                pass
        logger.info("Cleanup complete")
    except Exception as e:
        logger.error("Error during shutdown cleanup: %s", e)


# Read version from VERSION file
_version = "0.1.0-dev"
try:
    from pathlib import Path as _P
    _vf = _P(__file__).resolve().parent.parent.parent / "VERSION"
    if _vf.exists():
        _version = _vf.read_text().strip()
except Exception:
    pass

app = FastAPI(
    title="WiFry - IP Video Edition",
    description="Raspberry Pi Network Impairment Simulator for IP Video Testing",
    version=_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(impairments.router)
app.include_router(wifi_impairments.router)
app.include_router(profiles.router)
app.include_router(network.router)
app.include_router(captures.router)
app.include_router(streams.router)
app.include_router(adb.router)
app.include_router(scanner.router)
app.include_router(scenarios.router)
app.include_router(annotations.router)
app.include_router(hdmi.router)
app.include_router(sessions.router)
app.include_router(teleport.router)
app.include_router(dns.router)
app.include_router(network_config.router)
app.include_router(sharing.router)
app.include_router(system.router)
app.include_router(hw_tests.router)
app.include_router(remote.router)


@app.get("/api/v1/health")
async def health():
    return {"status": "ok", "mock_mode": settings.mock_mode}


# --- Easter egg: PacketGremlin ---

from .services import gremlin  # noqa: E402


@app.post("/api/v1/gremlin/activate", include_in_schema=False)
async def activate_gremlin(intensity: int = 2):
    return await gremlin.activate(intensity)


@app.post("/api/v1/gremlin/deactivate", include_in_schema=False)
async def deactivate_gremlin():
    return await gremlin.deactivate()


@app.get("/api/v1/gremlin/status", include_in_schema=False)
async def gremlin_status():
    return gremlin.get_status()


# --- Serve frontend static files ---
# The built React app is served from the same origin so API calls
# to /api/v1/... are handled by the routes above, and everything
# else falls through to the SPA.

_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _frontend_dist.is_dir():
    # Serve static assets (JS, CSS, images) under /assets
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")

    # SPA fallback: any non-API route returns index.html
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Never intercept API routes
        if full_path.startswith("api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Try to serve a static file first
        file_path = _frontend_dist / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        # Fall back to index.html for SPA routing
        return FileResponse(str(_frontend_dist / "index.html"))
