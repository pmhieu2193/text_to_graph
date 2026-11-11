from app.services.entity_resolution.manage_raw_entity import (
    ManageRawEntity,
    RawEntityData,
)
from app.services.entity_resolution.string_matcher import StringMatcher


def _entity(entity_id, chunk_id, name, aliases=None, entity_type="Organization"):
    return RawEntityData(
        id=entity_id,
        document_id="D1",
        chunk_id=chunk_id,
        entity_type=entity_type,
        name=name,
        aliases=aliases or [],
        valid_variants=[name, *(aliases or [])],
    )


def test_string_matcher_compares_variants_and_returns_unordered_pairs():
    manager = ManageRawEntity()
    manager.entities = {
        "E1": _entity("E1", "C1", "Nvidia"),
        "E2": _entity("E2", "C2", "NVIDIA Corporation", ["Nvidia"]),
        "E3": _entity("E3", "C3", "Apple Inc."),
        "E4": _entity("E4", "C4", "Nvidia", entity_type="Person"),
        "E5": _entity("E5", "C1", "Nvidia"),  # same chunk as E1
    }

    candidates = StringMatcher(top_k=10).generate(manager)

    assert ("E1", "E2") in candidates
    assert candidates[("E1", "E2")].is_exact is True
    assert candidates[("E1", "E2")].fuzzy_score == 1.0
    assert ("E1", "E4") not in candidates
    assert ("E1", "E5") not in candidates
