from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def tokenize(value: str | None) -> list[str]:
    text = normalize_text(value).lower()
    return _TOKEN_RE.findall(text)


def dedupe_preserve_order(values: Iterable[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
        if limit is not None and len(result) >= limit:
            break
    return result


def overlap_score(left: str | None, right: str | None) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    left_counter = Counter(left_tokens)
    right_counter = Counter(right_tokens)
    common = sum(min(left_counter[token], right_counter[token]) for token in set(left_counter) | set(right_counter))
    if common <= 0:
        return 0.0
    return common / math.sqrt(len(left_tokens) * len(right_tokens))


def chargram_score(left: str | None, right: str | None, *, n: int = 2) -> float:
    left_text = normalize_text(left).lower().replace(" ", "")
    right_text = normalize_text(right).lower().replace(" ", "")
    if not left_text or not right_text:
        return 0.0
    if len(left_text) < n or len(right_text) < n:
        return 1.0 if left_text == right_text else overlap_score(left_text, right_text)

    def _ngrams(value: str) -> list[str]:
        return [value[idx : idx + n] for idx in range(max(len(value) - n + 1, 0))]

    left_counter = Counter(_ngrams(left_text))
    right_counter = Counter(_ngrams(right_text))
    common = sum(min(left_counter[token], right_counter[token]) for token in set(left_counter) | set(right_counter))
    if common <= 0:
        return 0.0
    return common / math.sqrt(sum(left_counter.values()) * sum(right_counter.values()))
