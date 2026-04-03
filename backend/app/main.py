"""WiFry — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import adb, annotations, captures, dns, hdmi, impairments, network, network_config, profiles, scanner, scenarios, sessions, sharing, streams, system, teleport, wifi_impairments

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
        from .services import network_config as nc_svc
        await nc_svc.boot_apply()
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
