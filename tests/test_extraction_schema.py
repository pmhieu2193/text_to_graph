import pytest
from pydantic import ValidationError

from app.schemas.extraction import (
    DocumentExtractionResultResponse,
    DocumentExtractionSummaryResponse,
    ExtractionPayload,
)


def test_valid_payload_with_aliases_and_evidence_list():
    payload = ExtractionPayload.model_validate({
        "entities": [
            {
                "local_id": "e1",
                "name": "Công viên Văn hóa Đầm Sen",
                "aliases": ["Đầm Sen", "Công viên Đầm Sen"],
                "entity_type": "Place",
                "evidence": [
                    "Công viên Văn hóa Đầm Sen nằm ở số 3 đường Hòa Bình.",
                    "Đầm Sen là địa điểm vui chơi giải trí.",
                ],
            },
            {
                "local_id": "e2",
                "name": "TP.HCM",
                "entity_type": "Place",
                "evidence": ["Quận 11, TP.HCM"],
            },
        ],
        "relations": [
            {
                "local_id": "r1",
                "subject_local_id": "e1",
                "object_local_id": "e2",
                "relation_type": "LOCATED_IN",
                "evidence": "Công viên Văn hóa Đầm Sen nằm ở Quận 11, TP.HCM.",
            }
        ],
    })

    assert len(payload.entities) == 2
    assert payload.entities[0].name == "Công viên Văn hóa Đầm Sen"
    assert payload.entities[0].aliases == ["Đầm Sen", "Công viên Đầm Sen"]
    assert len(payload.entities[0].evidence) == 2

    # Entity không truyền aliases sẽ mặc định là danh sách rỗng
    assert payload.entities[1].aliases == []
    assert payload.entities[1].evidence == ["Quận 11, TP.HCM"]

    assert len(payload.relations) == 1
    assert payload.relations[0].relation_type == "LOCATED_IN"


def test_entity_evidence_must_be_list():
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate({
            "entities": [
                {
                    "local_id": "e1",
                    "name": "Hà Nội",
                    "entity_type": "Place",
                    "evidence": "Hà Nội là thủ đô Việt Nam.",
                }
            ],
            "relations": [],
        })


def test_empty_result_is_valid():
    payload = ExtractionPayload()

    assert payload.entities == []
    assert payload.relations == []


def test_api_response_schemas():
    result = DocumentExtractionResultResponse.model_validate({
        "document_id": "doc-1",
        "entity_count": 1,
        "relation_count": 0,
        "entities": [
            {
                "id": "uuid-1",
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "local_id": "e1",
                "name": "Hà Nội",
                "aliases": ["Thủ đô Hà Nội"],
                "entity_type": "Place",
                "description": None,
                "evidence": ["Hà Nội là thủ đô Việt Nam."],
                "confidence": 1.0,
                "provider": "gemini",
                "model_name": "gemini-2.5-flash",
            }
        ],
        "relations": [],
    })

    summary = DocumentExtractionSummaryResponse.model_validate({
        "document_id": "doc-1",
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "total_chunks": 2,
        "processed_chunks": 2,
        "skipped_chunks": 0,
        "completed_chunks": 2,
        "failed_chunks": 0,
        "pending_chunks": 0,
        "entity_count": 1,
        "relation_count": 0,
    })

    assert result.entities[0].aliases == ["Thủ đô Hà Nội"]
    assert result.entities[0].evidence == ["Hà Nội là thủ đô Việt Nam."]
    assert summary.using_fallback_key is False