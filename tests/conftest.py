from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
for path in (ROOT, WORKSPACE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


os.environ["MEMORY_DATABASE_URL"] = "postgresql+asyncpg://postgres:password@db.invalid:5432/memory_test"
os.environ["MEMORY_DATABASE_SCHEMA"] = "memory"
os.environ["LITELLM_BASE_URL"] = "https://llm.test/v1"
os.environ["LITELLM_API_KEY"] = "test-key"
os.environ["LITELLM_MEMORY_MODEL"] = "memory"
