import pytest

from pydantic import ValidationError

from app.schemas.extraction import ExtractionPayload


def test_valid_payload():

    payload = ExtractionPayload.model_validate({
        "entities": [
            {
                "local_id": "e1",
                "name": "Hà Nội",
                "entity_type": "LOCATION",
                "evidence": ["Hà Nội là thủ đô Việt Nam."],
            }
        ],
        "relations": [],
    })

    assert payload.entities[0].name == "Hà Nội"


def test_relation_must_reference_existing_entities():

    with pytest.raises(ValidationError):

        ExtractionPayload.model_validate({
            "entities": [],

            "relations": [
                {
                    "local_id": "r1",
                    "subject_local_id": "e1",
                    "object_local_id": "e2",
                    "relation_type": "LOCATED_IN",
                    "evidence": "A nằm ở B.",
                }
            ],
        })


def test_confidence_must_be_between_zero_and_one():

    with pytest.raises(ValidationError):

        ExtractionPayload.model_validate({
            "entities": [
                {
                    "local_id": "e1",
                    "name": "A",
                    "entity_type": "PERSON",
                    "evidence": ["A"],
                    "confidence": 1.5,
                }
            ],
            "relations": [],
        })


def test_entity_local_id_must_be_unique():

    with pytest.raises(ValidationError):

        ExtractionPayload.model_validate({
            "entities": [
                {
                    "local_id": "e1",
                    "name": "Nguyễn Văn A",
                    "entity_type": "PERSON",
                    "evidence": ["Nguyễn Văn A"],
                },
                {
                    "local_id": "e1",
                    "name": "Trần Văn B",
                    "entity_type": "PERSON",
                    "evidence": ["Trần Văn B"],
                },
            ],
            "relations": [],
        })


def test_empty_result_is_valid():

    payload = ExtractionPayload()

    assert payload.entities == []
    assert payload.relations == []


def test_relation_local_id_must_be_unique():
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate({
            "entities": [
                {
                    "local_id": "e1",
                    "name": "A",
                    "entity_type": "PERSON",
                    "evidence": ["A"],
                },
                {
                    "local_id": "e2",
                    "name": "B",
                    "entity_type": "PERSON",
                    "evidence": ["B"],
                },
            ],
            "relations": [
                {
                    "local_id": "r1",
                    "subject_local_id": "e1",
                    "object_local_id": "e2",
                    "relation_type": "RELATED_TO",
                    "evidence": "A liên quan B.",
                },
                {
                    "local_id": "r1",
                    "subject_local_id": "e2",
                    "object_local_id": "e1",
                    "relation_type": "RELATED_TO",
                    "evidence": "B liên quan A.",
                },
            ],
        })
