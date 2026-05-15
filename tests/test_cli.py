from __future__ import annotations

from insight_memory import cli
from insight_memory.utils import logger as logger_module


def test_resolve_log_config_prefers_runtime_config(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "insight_memory" / "config"
    config_dir.mkdir(parents=True)
    log_config = config_dir / "log_config.json"
    log_config.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli._resolve_log_config() == str(log_config)


def test_runtime_file_handler_uses_runtime_log_dir(tmp_path, monkeypatch) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(logger_module, "RUNTIME_DIR", runtime_dir)

    handler = logger_module.create_runtime_file_handler(filename="memory.log", delay=True)
    try:
        assert handler.baseFilename == str(runtime_dir / "logs" / "memory.log")
        assert (runtime_dir / "logs").is_dir()
    finally:
        handler.close()


def test_run_server_uses_reload_setting(tmp_path, monkeypatch) -> None:
    watched_dir = tmp_path / "insight_memory"
    watched_dir.mkdir()
    captured: dict = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.settings, "MEMORY_APP_RELOAD", True)
    monkeypatch.setattr(cli.settings, "MEMORY_SERVICE_PORT", 8123)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app_path, **options: captured.update(app_path=app_path, **options))

    cli.run_server()

    assert captured["app_path"] == "insight_memory.main:app"
    assert captured["port"] == 8123
    assert captured["reload"] is True
    assert captured["log_config"].endswith("config/log_config.json")
    assert captured["reload_dirs"] == [str(watched_dir)]
