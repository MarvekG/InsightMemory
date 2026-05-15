from __future__ import annotations

import re

from insight_memory.utils.request_context import clear_request_id
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.utils.request_context import get_request_id


def test_get_or_create_request_id_generates_uuid4hex() -> None:
    clear_request_id()

    request_id = get_or_create_request_id()

    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert get_request_id() == request_id
    clear_request_id()


def test_get_or_create_request_id_uses_supplied_value() -> None:
    clear_request_id()
    request_id = "0123456789abcdef0123456789abcdef"

    assert get_or_create_request_id(request_id) == request_id
    assert get_request_id() == request_id
    clear_request_id()
