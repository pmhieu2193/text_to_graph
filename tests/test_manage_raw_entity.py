from app.services.entity_resolution.manage_raw_entity import (
    ManageRawEntity,
    RawEntityData,
    normalize_text,
)


def test_clean_entities_filters_contextual_aliases_and_preserves_raw_aliases():
    manager = ManageRawEntity()
    entity = RawEntityData(
        id="E1",
        document_id="D1",
        chunk_id="C1",
        entity_type="Organization",
        name=" Tập đoàn   Nvidia ",
        aliases=["NVIDIA", "công ty này", "nó", "Nvidia"],
    )
    manager.entities[entity.id] = entity

    manager.clean_entities()

    assert entity.aliases == ["NVIDIA", "công ty này", "nó", "Nvidia"]
    assert entity.valid_variants == ["Tập đoàn Nvidia", "NVIDIA"]
    assert normalize_text("  NVIDIA  ") == "nvidia"


def test_manager_loads_entities_by_primary_key():
    class Row:
        id = "E1"
        document_id = "D1"
        chunk_id = "C1"
        entity_type = "Person"
        name = "Jensen Huang"
        aliases = ["Huang"]
        evidence = ["evidence1", "evidence2"]

    manager = ManageRawEntity()
    manager.load_from_db([Row()])

    assert list(manager.entities) == ["E1"]
    assert manager.get_entity("E1").name == "Jensen Huang"
