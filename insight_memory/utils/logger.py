import json
import logging
from pathlib import Path

from concurrent_log_handler import ConcurrentRotatingFileHandler

from insight_memory.config import RUNTIME_DIR
from insight_memory.utils.request_context import get_request_id


_SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "set-cookie",
}


_original_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs):
    record = _original_record_factory(*args, **kwargs)
    if not getattr(record, "request_id", None):
        record.request_id = get_request_id() or "-"
    if not getattr(record, "source", None):
        record.source = "memory"
    return record


logging.setLogRecordFactory(_record_factory)


def _is_sensitive_key(key: str | None) -> bool:
    normalized = str(key or "").strip().lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize_for_log(value, *, key: str | None = None):
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        sanitized = {
            str(item_key): _sanitize_for_log(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_log(item, key=key) for item in value]
    return value


def _format_log_value(value) -> str:
    sanitized = _sanitize_for_log(value)
    if isinstance(sanitized, str):
        return sanitized if " " not in sanitized and "=" not in sanitized else json.dumps(sanitized, ensure_ascii=False)
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True)


def _format_extra_fields(extra: dict) -> str:
    parts = []
    for key, value in extra.items():
        if key == "request_id":
            continue
        parts.append(f"{key}={_format_log_value(value)}")
    return " ".join(parts)


class ContextLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.pop("extra", None) or {}
        merged = {**(self.extra or {}), **extra}
        if merged:
            msg = f"{msg} | {_format_extra_fields(merged)}"
        return msg, kwargs


class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "process_id": record.process,
            "source": getattr(record, "source", "memory"),
        }

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        standard_attrs = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())
        extra_attrs = {k: v for k, v in record.__dict__.items() if k not in standard_attrs and k not in log_obj}
        if extra_attrs:
            log_obj.update({k: _sanitize_for_log(v, key=k) for k, v in extra_attrs.items()})

        return json.dumps(log_obj, ensure_ascii=False)


def create_runtime_file_handler(
    *,
    filename: str = "memory.log",
    max_bytes: int = 10485760,
    backup_count: int = 5,
    encoding: str = "utf-8",
    delay: bool = False,
) -> ConcurrentRotatingFileHandler:
    """Create a rotating file handler under the configured runtime log directory."""
    log_dir = RUNTIME_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return ConcurrentRotatingFileHandler(
        filename=str(log_dir / filename),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding=encoding,
        delay=delay,
    )


def get_logger(name: str = "memory"):
    """Return a logger adapter with context-aware request ID injection."""
    return ContextLoggerAdapter(logging.getLogger(name), {})


logger = get_logger()
