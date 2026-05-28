from __future__ import annotations

from types import SimpleNamespace

from insight_memory.index.retrieval_index import project_memory


def test_project_memory_includes_entity_identity() -> None:
    entity = SimpleNamespace(
        identity_profile={
            "who": "Grayshore bulletin",
            "surface_forms": ["Grayshore bulletin"],
            "stable_qualifiers": ["bulletin", "archive briefing"],
        }
    )
    memory = SimpleNamespace(
        title="Current rule for berth note filing",
        summary="Current section requires berth note filed before release.",
        content="The appendix adds that every berth note must include quay owner signature.",
    )

    projected = project_memory(memory, entity=entity)

    assert "who: Grayshore bulletin" in projected
    assert "surface_forms: Grayshore bulletin" in projected
    assert "Current rule for berth note filing" in projected
