from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar


T = TypeVar("T")


def run_async(awaitable: Awaitable[T]) -> T:
    """Run one async operation in sync pytest code."""

    return asyncio.run(awaitable)
