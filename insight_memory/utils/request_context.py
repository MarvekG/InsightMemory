from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import uuid4


_request_id_var: ContextVar[str | None] = ContextVar("memory_request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request ID from context."""
    return _request_id_var.get()


def set_request_id(request_id: str | None) -> Token:
    """Bind a request ID to the current execution context."""
    normalized = str(request_id or "").strip() or None
    return _request_id_var.set(normalized)


def clear_request_id(token: Token | None = None) -> None:
    """Clear the current request ID binding."""
    if token is not None:
        _request_id_var.reset(token)
        return
    _request_id_var.set(None)


def get_or_create_request_id(request_id: str | None = None) -> str:
    """Return the current request ID or create a new UUID4 hex value."""
    normalized = str(request_id or "").strip()
    if normalized:
        _request_id_var.set(normalized)
        return normalized
    current = get_request_id()
    if current:
        return current
    generated = uuid4().hex
    _request_id_var.set(generated)
    return generated
