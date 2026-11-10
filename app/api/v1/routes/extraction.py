from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.document import Document
from app.providers.llm.base import LLMConfigurationError
from app.repositories.extraction_repository import ExtractionRepository
from app.services.extraction_service import DocumentExtractionService
from app.providers.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
)

router = APIRouter()

#Chưa tạo reponse model nên tạm thời trả về dict 
@router.post("/{document_id}/extract")
def extract_document(

    document_id: str,

    force: bool = Query(
        False,
        description="Trích xuất lại cả chunk đã hoàn thành.",
    ),

    db: Session = Depends(get_db),

):

    try:

        service = DocumentExtractionService(db)

        return service.extract_document(
            document_id=document_id,
            force=force,
        )

    except LookupError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except LLMConfigurationError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except ValueError as exc:

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
        
    except LLMProviderError as exc:

        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc


@router.get("/{document_id}/extraction")
def get_extraction(

    document_id: str,

    db: Session = Depends(get_db),

):

    if db.get(Document, document_id) is None:

        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy tài liệu.",
        )

    repository = ExtractionRepository(db)

    entities, relations, runs = (
        repository.get_document_result(
            document_id
        )
    )

    return {
        "document_id": document_id,

        "entity_count": len(entities),
        "relation_count": len(relations),

        "entities": [
            {
                "id": row.id,
                "chunk_id": row.chunk_id,
                "local_id": row.local_id,

                "name": row.name,
                "entity_type": row.entity_type,
                "description": row.description,

                "evidence": row.evidence,
                "confidence": row.confidence,

                "provider": row.provider,
                "model_name": row.model_name,
            }
            for row in entities
        ],

        "relations": [
            {
                "id": row.id,
                "chunk_id": row.chunk_id,
                "local_id": row.local_id,

                "subject_entity_id": row.subject_entity_id,
                "object_entity_id": row.object_entity_id,

                "relation_type": row.relation_type,
                "description": row.description,

                "evidence": row.evidence,
                "confidence": row.confidence,

                "provider": row.provider,
                "model_name": row.model_name,
            }
            for row in relations
        ],

        "runs": [
            {
                "chunk_id": row.chunk_id,
                "status": row.status,

                "provider": row.provider,
                "model_name": row.model_name,

                "attempt_count": row.attempt_count,
                "error_message": row.error_message,
            }
            for row in runs
        ],
    }