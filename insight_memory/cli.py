from __future__ import annotations

from pathlib import Path

import uvicorn

from insight_memory.config import settings


def _resolve_log_config() -> str | None:
    """
    Find a local uvicorn logging config when the service runs from source.

    Returns:
        Path to an existing logging config, or None to let uvicorn use its default logging.
    """
    candidates = [
        Path.cwd() / "insight_memory" / "config" / "log_config.json",
        Path(__file__).resolve().parent / "config" / "log_config.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _resolve_reload_dirs() -> list[str]:
    """
    Find reload directories that exist in a source-tree runtime.

    Returns:
        Existing directories to watch when uvicorn reload is enabled.
    """
    candidates = [
        Path.cwd() / "insight_memory",
        Path.cwd() / "insight_memory" / "config",
    ]
    return [str(candidate) for candidate in candidates if candidate.exists()]


def run_server() -> None:
    """
    Run the memory service with settings loaded from environment and .env files.
    """
    uvicorn_options = {
        "host": "0.0.0.0",
        "port": settings.MEMORY_SERVICE_PORT,
        "reload": settings.MEMORY_APP_RELOAD,
        "timeout_graceful_shutdown": 0,
    }
    log_config = _resolve_log_config()
    if log_config is not None:
        uvicorn_options["log_config"] = log_config
    reload_dirs = _resolve_reload_dirs()
    if settings.MEMORY_APP_RELOAD and reload_dirs:
        uvicorn_options["reload_dirs"] = reload_dirs
        uvicorn_options["reload_includes"] = ["*.json"]
    uvicorn.run("insight_memory.main:app", **uvicorn_options)


def main() -> None:
    """Run the memory service from the installed console script."""
    run_server()
