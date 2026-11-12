from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.extraction_repository import ExtractionRepository
from app.schemas.extraction import (
    DocumentExtractionResultResponse,
    DocumentExtractionSummaryResponse,
)
from app.services.extraction_service import DocumentExtractionService
from app.providers.llm.base import LLMConfigurationError, LLMProviderError

router = APIRouter()


@router.post(
    "/{document_id}/extract",
    response_model=DocumentExtractionSummaryResponse,
)
def extract_document(
    document_id: str,
    force: bool = Query(False, description="Trích xuất lại cả chunk đã hoàn thành."),
    db: Session = Depends(get_db),
):
    try:
        return DocumentExtractionService(db).extract_document(
            document_id=document_id,
            force=force,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{document_id}/result",
    response_model=DocumentExtractionResultResponse,
)
def get_extraction_result(document_id: str, db: Session = Depends(get_db)):
    entities, relations, _runs = ExtractionRepository(db).get_document_result(
        document_id
    )
    return {
        "document_id": document_id,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "entities": entities,
        "relations": relations,
    }

@router.get(
    "/documents/{document_id}/result",
    response_model=DocumentExtractionResultResponse,
    include_in_schema=False,
)
def get_extraction_result_legacy(document_id: str, db: Session = Depends(get_db)):
    """Backward-compatible alias for the former duplicated documents prefix."""
    return get_extraction_result(document_id, db)
