from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.entity_resolution import CandidateDecisionRequest
from app.services.entity_resolution.service import EntityResolutionService
from app.services.entity_resolution.neo4j_sync import Neo4jGraphSyncService

router = APIRouter()


@router.post("/documents/{document_id}/entity-resolution/preview")
def create_er_preview(document_id: str, db: Session = Depends(get_db)):
    try:
        dataframe, report_path, run_id = EntityResolutionService(db).preview(document_id)
        counts = (
            dataframe["classification"].value_counts().to_dict()
            if not dataframe.empty else {}
        )
        return {
            "document_id": document_id,
            "run_id": run_id,
            "candidate_count": len(dataframe),
            "auto_merge_count": counts.get("AUTO_MERGE", 0),
            "review_count": counts.get("REVIEW", 0),
            "reject_count": counts.get("REJECT", 0),
            "report_path": report_path,
            "candidates": dataframe.astype(object).where(
                dataframe.notna(), None
            ).to_dict(orient="records"),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/documents/{document_id}/entity-resolution/runs/{run_id}/candidates")
def list_er_candidates(
    document_id: str, run_id: str, db: Session = Depends(get_db)
):
    try:
        items = EntityResolutionService(db).list_candidates(document_id, run_id)
        return {"document_id": document_id, "run_id": run_id, "items": items}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/documents/{document_id}/entity-resolution/candidates/{pair_id}/decision"
)
def decide_er_candidate(
    document_id: str,
    pair_id: str,
    payload: CandidateDecisionRequest,
    db: Session = Depends(get_db),
):
    try:
        return EntityResolutionService(db).decide(
            document_id, pair_id, payload.decision
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/documents/{document_id}/entity-resolution/runs/{run_id}/auto-merge"
)
def auto_merge_er_candidates(
    document_id: str, run_id: str, db: Session = Depends(get_db)
):
    try:
        return EntityResolutionService(db).auto_merge(document_id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/documents/{document_id}/entity-resolution/runs/{run_id}/finalize"
)
def finalize_er_run(
    document_id: str, run_id: str, db: Session = Depends(get_db)
):
    try:
        return EntityResolutionService(db).finalize(document_id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/documents/{document_id}/entity-resolution/reset")
def reset_er_document(document_id: str, db: Session = Depends(get_db)):
    try:
        return EntityResolutionService(db).reset(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/documents/{document_id}/entity-resolution/runs/{run_id}/sync-neo4j")
def sync_er_run_to_neo4j(document_id: str, run_id: str, db: Session = Depends(get_db)):
    try:
        return Neo4jGraphSyncService(db).sync(document_id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/documents/{document_id}/entity-resolution/canonical-relations")
def get_canonical_relations(document_id: str, db: Session = Depends(get_db)):
    try:
        return {
            "document_id": document_id,
            "items": EntityResolutionService(db).canonical_relations(document_id),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents/{document_id}/entity-resolution/canonical-entities")
def get_canonical_entities(document_id: str, db: Session = Depends(get_db)):
    try:
        return {
            "document_id": document_id,
            "items": EntityResolutionService(db).canonical_entities(document_id),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
