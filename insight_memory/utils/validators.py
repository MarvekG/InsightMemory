from collections.abc import Mapping
from insight_memory.config import settings


def validate_json_size(value: Mapping | None) -> None:
    if value is None:
        return
    encoded = str(dict(value)).encode("utf-8")
    if len(encoded) > settings.MEMORY_MAX_CONTEXT_BYTES:
        raise ValueError("JSON payload too large")
