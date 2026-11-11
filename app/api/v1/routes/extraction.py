from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.document import Document
from app.providers.llm.base import LLMConfigurationError
from app.repositories.extraction_repository import ExtractionRepository
from app.schemas.extraction import DocumentExtractionResultResponse
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


@router.get(
    "/documents/{document_id}/result",
    response_model=DocumentExtractionResultResponse, 
)
def get_extraction_result(document_id: str, db: Session = Depends(get_db)):
    repo = ExtractionRepository(db)
    entities, relations, runs = repo.get_document_result(document_id)
    
    return {
        "document_id": document_id,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "entities": entities,
        "relations": relations,
    }

@router.post("/{document_id}/resolve/preview")
def preview_entity_resolution(
    document_id: str,
    db: Session = Depends(get_db),
):
    """Generate ER candidates in memory; does not write or merge graph data."""
    from app.services.entity_resolution.service import EntityResolutionService

    try:
        dataframe = EntityResolutionService(db).preview(document_id)
        return {
            "document_id": document_id,
            "candidate_count": len(dataframe),
            "candidates": dataframe.astype(object).where(
                dataframe.notna(), None
            ).to_dict(orient="records"),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
