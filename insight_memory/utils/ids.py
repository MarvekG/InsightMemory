from uuid import uuid4


def new_uuid() -> str:
    return str(uuid4())


def new_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"
