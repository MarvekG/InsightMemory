from __future__ import annotations

import re


_SEGMENT_RE = re.compile(r"[^\n。！？!?\.]+(?:[。！？!?\.]+|\n+|$)", re.UNICODE)
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(value: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(value or "")]


def _text_overlap_score(query: str, candidate: str) -> float:
    query_tokens = _tokenize(query)
    candidate_tokens = _tokenize(candidate)
    if not query_tokens or not candidate_tokens:
        return 0.0
    candidate_counts: dict[str, int] = {}
    for token in candidate_tokens:
        candidate_counts[token] = candidate_counts.get(token, 0) + 1
    shared = 0
    consumed: dict[str, int] = {}
    for token in query_tokens:
        used = consumed.get(token, 0)
        if used >= candidate_counts.get(token, 0):
            continue
        consumed[token] = used + 1
        shared += 1
    return shared / max(len(query_tokens), 1)


def build_observation_fragments(content: str, *, max_chars: int = 240) -> list[dict[str, object]]:
    text = str(content or "")
    if not text.strip():
        return []

    raw_segments: list[tuple[int, int, str]] = []
    for match in _SEGMENT_RE.finditer(text):
        segment_text = match.group(0)
        stripped = segment_text.strip()
        if not stripped:
            continue
        leading = len(segment_text) - len(segment_text.lstrip())
        trailing = len(segment_text) - len(segment_text.rstrip())
        start = match.start() + leading
        end = match.end() - trailing
        raw_segments.append((start, end, text[start:end]))

    if not raw_segments:
        stripped = text.strip()
        start = text.find(stripped) if stripped else 0
        end = start + len(stripped)
        raw_segments = [(start, end, stripped)]

    merged: list[tuple[int, int, str]] = []
    current_start, current_end, current_text = raw_segments[0]
    for start, end, excerpt in raw_segments[1:]:
        combined = f"{current_text} {excerpt}".strip()
        if len(combined) <= max_chars:
            current_end = end
            current_text = combined
            continue
        merged.append((current_start, current_end, current_text))
        current_start, current_end, current_text = start, end, excerpt
    merged.append((current_start, current_end, current_text))

    fragments = []
    for ordinal, (start, end, excerpt) in enumerate(merged, start=1):
        fragments.append(
            {
                "fragment_id": f"frag_{ordinal}",
                "ordinal": ordinal,
                "char_start": start,
                "char_end": end,
                "text_excerpt": excerpt,
            }
        )
    return fragments


def select_best_fragment(reference_text: str, fragments: list[dict[str, object]]) -> dict[str, object] | None:
    best_fragment: dict[str, object] | None = None
    best_score = -1.0
    for fragment in fragments:
        excerpt = str(fragment.get("text_excerpt") or "").strip()
        if not excerpt:
            continue
        score = _text_overlap_score(reference_text, excerpt)
        if score > best_score:
            best_score = score
            best_fragment = fragment
    if best_fragment is not None:
        return best_fragment
    return fragments[0] if fragments else None
