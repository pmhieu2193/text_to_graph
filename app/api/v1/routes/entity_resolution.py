from fastapi import APIRouter, Depends, HTTPException, Query
from pathlib import Path
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.entity_resolution import (
    AutoMergeResponse,
    CandidateDecisionRequest,
    CandidateDecisionResponse,
    CanonicalEntityListResponse,
    CanonicalRelationListResponse,
    ERCandidateListResponse,
    ERPreviewResponse,
    ERResetResponse,
    FinalizeERResponse,
    Neo4jDeleteResponse,
    Neo4jSyncResponse,
)
from app.services.entity_resolution.service import EntityResolutionService
from app.services.entity_resolution.neo4j_sync import Neo4jGraphSyncService
from app.models.document import Document, DocumentStatus

router = APIRouter()


@router.post(
    "/documents/{document_id}/entity-resolution/preview",
    response_model=ERPreviewResponse,
)
def create_er_preview(document_id: str, db: Session = Depends(get_db)):
    try:
        dataframe, report_path, run_id = EntityResolutionService(db).preview(document_id)
        document = db.get(Document, document_id)
        document.status = DocumentStatus.ENTITY_RESOLUTION
        document.error_message = None
        db.commit()
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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/documents/{document_id}/entity-resolution/candidates",
    response_model=ERCandidateListResponse,
)
def list_er_candidates(
    document_id: str,
    classification: str | None = Query(None),
    review_status: str | None = Query(None),
    decision: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        service = EntityResolutionService(db)
        run = service.get_current_run(document_id)
        items = service.list_candidates(document_id)
        if classification:
            items = [x for x in items if x['classification'] == classification.upper()]
        if review_status:
            items = [x for x in items if x['review_status'] == review_status.upper()]
        if decision:
            items = [x for x in items if (x['decision'] or '').upper() == decision.upper()]
        if search:
            needle = search.strip().casefold()
            items = [x for x in items if needle in (x['entity_a'] or '').casefold() or needle in (x['entity_b'] or '').casefold()]
        total = len(items)
        start = (page - 1) * page_size
        return {'document_id': document_id, 'run_id': run.id, 'items': items[start:start + page_size], 'total': total, 'page': page, 'page_size': page_size}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post(
    "/documents/{document_id}/entity-resolution/candidates/{pair_id}/decision",
    response_model=CandidateDecisionResponse,
)
def decide_er_candidate(
    document_id: str,
    pair_id: str,
    payload: CandidateDecisionRequest,
    db: Session = Depends(get_db),
):
    try:
        result = EntityResolutionService(db).decide(document_id, pair_id, payload.decision)
        document = db.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.HUMAN_REVIEW
            db.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc



@router.post(
    "/documents/{document_id}/entity-resolution/candidates/{pair_id}/keep-separate",
    response_model=CandidateDecisionResponse,
)
def keep_candidate_separate(document_id: str, pair_id: str, db: Session = Depends(get_db)):
    try:
        result = EntityResolutionService(db).decide(document_id, pair_id, "KEEP_SEPARATE")
        document = db.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.HUMAN_REVIEW
            db.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
@router.post(
    "/documents/{document_id}/entity-resolution/auto-merge",
    response_model=AutoMergeResponse,
)
def auto_merge_er_candidates(document_id: str, db: Session = Depends(get_db)):
    try:
        result = EntityResolutionService(db).auto_merge(document_id)
        document = db.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.HUMAN_REVIEW
            db.commit()
        return {"document_id": document_id, **result}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/documents/{document_id}/entity-resolution/finalize",
    response_model=FinalizeERResponse,
)
def finalize_er_run(
    document_id: str,
    auto_merge: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    try:
        result = EntityResolutionService(db).finalize(
            document_id, apply_auto_merge=auto_merge
        )
        document = db.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.FINALIZED
            db.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete(
    "/documents/{document_id}/entity-resolution/reset",
    response_model=ERResetResponse,
)
def reset_er_document(document_id: str, db: Session = Depends(get_db)):
    try:
        return EntityResolutionService(db).reset(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/documents/{document_id}/neo4j-graph",
    response_model=Neo4jDeleteResponse,
)
def delete_document_neo4j_graph(document_id: str, db: Session = Depends(get_db)):
    try:
        return Neo4jGraphSyncService(db).delete_document_graph(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/documents/{document_id}/entity-resolution/sync-neo4j",
    response_model=Neo4jSyncResponse,
)
def sync_er_run_to_neo4j(document_id: str, db: Session = Depends(get_db)):
    try:
        result = Neo4jGraphSyncService(db).sync(document_id)
        document = db.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.NEO4J_SYNCED
            db.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/documents/{document_id}/entity-resolution/canonical-relations",
    response_model=CanonicalRelationListResponse,
)
def get_canonical_relations(document_id: str, db: Session = Depends(get_db)):
    try:
        return {
            "document_id": document_id,
            "items": EntityResolutionService(db).canonical_relations(document_id),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/documents/{document_id}/entity-resolution/canonical-entities",
    response_model=CanonicalEntityListResponse,
)
def get_canonical_entities(document_id: str, db: Session = Depends(get_db)):
    try:
        return {
            "document_id": document_id,
            "items": EntityResolutionService(db).canonical_entities(document_id),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



@router.get("/documents/{document_id}/entity-resolution/summary")
def get_er_summary(document_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import func, select
    from app.models.entity_resolution import EntityCandidate, EntityResolutionRun
    service = EntityResolutionService(db)
    run = service.get_current_run(document_id)
    rows = db.execute(
        select(EntityCandidate.review_status, EntityCandidate.decision, EntityCandidate.classification)
        .where(EntityCandidate.run_id == run.id)
    ).all()
    return {
        "run_status": run.status,
        "candidate_count": len(rows),
        "pending_count": sum(1 for status, _, _ in rows if status == "PENDING"),
        "merged_count": sum(1 for status, decision, _ in rows if status == "MERGED" or decision == "MERGE"),
        "kept_separate_count": sum(1 for _, decision, _ in rows if decision == "KEEP_SEPARATE"),
        "skipped_count": sum(1 for status, decision, _ in rows if status == "SKIPPED" or decision == "SKIP"),
        "blocked_count": sum(1 for status, _, _ in rows if status == "BLOCKED_CONFLICT"),
        "auto_merge_count": sum(1 for _, _, classification in rows if classification == "AUTO_MERGE"),
        "review_count": sum(1 for _, _, classification in rows if classification == "REVIEW"),
        "reject_count": sum(1 for _, _, classification in rows if classification == "REJECT"),
    }


@router.get("/documents/{document_id}/entity-resolution/candidates/{pair_id}")
def get_er_candidate_detail(document_id: str, pair_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import select
    from app.models.entity_resolution import EntityCandidate
    from app.models.extraction import RawEntity
    from fastapi import HTTPException
    candidate = db.get(EntityCandidate, pair_id)
    if candidate is None or candidate.document_id != document_id:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    a = db.get(RawEntity, candidate.entity_a_id)
    b = db.get(RawEntity, candidate.entity_b_id)
    def serialize(entity):
        return {
            "name": entity.name, "entity_type": entity.entity_type,
            "aliases": entity.aliases or [], "description": entity.description,
            "evidence": entity.evidence or [], "confidence": entity.confidence,
            "chunk_id": entity.chunk_id,
        }
    return {
        "pair_id": candidate.id, "classification": candidate.classification,
        "decision": candidate.decision, "review_status": candidate.review_status,
        "match_method": candidate.match_method, "fuzzy_score": candidate.fuzzy_score,
        "embedding_score": candidate.embedding_score, "final_score": candidate.final_score,
        "fuzzy_match": candidate.fuzzy_match, "embedding_match": candidate.embedding_match,
        "entity_a": serialize(a) if a else None, "entity_b": serialize(b) if b else None,
        "evidence_a": candidate.evidence_a or [], "evidence_b": candidate.evidence_b or [],
    }


@router.get("/documents/{document_id}/reports/{report_type}/download")
def download_document_report(document_id: str, report_type: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException
    from app.core.config import settings
    from app.models.entity_resolution import EntityResolutionRun
    from app.models.extraction import RawEntity, RawRelation
    import pandas as pd
    from app.services.entity_resolution.report_writer import EntityResolutionReportWriter
    from app.services.entity_resolution.service import EntityResolutionService

    if report_type not in {"preview", "final", "cypher"}:
        raise HTTPException(status_code=400, detail="Report type must be preview, final or cypher.")
    service = EntityResolutionService(db)
    try:
        run = service.get_current_run(document_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if report_type == "preview":
        if run.status == "FINALIZED":
            raise HTTPException(status_code=409, detail="Preview report is no longer available after finalize.")
        rows = service.list_candidates(document_id)
        path = service.report_writer.write(document_id, pd.DataFrame.from_records(rows))
    elif report_type == "final":
        if run.status != "FINALIZED":
            raise HTTPException(status_code=409, detail="Finalize the document before exporting the final report.")
        candidates = service.list_candidates(document_id)
        entities = service._canonical_entities_payload(document_id)
        relations, loops = service._canonical_relations_payload(document_id)
        path = service.report_writer.write_final(
            document_id, run.id, candidates, entities, relations,
            {"candidate_count": len(candidates), "canonical_entity_count": len(entities),
             "canonical_relation_count": len(relations), "removed_self_loop_count": loops},
        )
    else:
        if run.status != "FINALIZED":
            raise HTTPException(status_code=409, detail="Finalize the document before exporting Cypher.")
        sync_service = Neo4jGraphSyncService(db)
        entities = service._canonical_entities_payload(document_id)
        relations, _ = service._canonical_relations_payload(document_id)
        nodes = [{"id": e["canonical_entity_id"], "document_id": document_id,
                  "name": e["name"], "entity_type": e["entity_type"],
                  "aliases": e.get("aliases") or [], "raw_entity_ids": e.get("raw_entity_ids") or []}
                 for e in entities]
        edges = [{
            "edge_key": sync_service._edge_key(r["canonical_subject_id"], r["canonical_object_id"], r["relation_type"]),
            "subject_id": r["canonical_subject_id"], "object_id": r["canonical_object_id"],
            "relation_type": r["relation_type"], "description": r.get("description") or "",
            "evidence": r.get("evidence") or [], "raw_relation_ids": r.get("raw_relation_ids") or [],
            "raw_relation_count": r.get("raw_relation_count", 0),
            "raw_subject_entity_ids": r.get("raw_subject_entity_ids") or [],
            "raw_object_entity_ids": r.get("raw_object_entity_ids") or [],
        } for r in relations]
        text = sync_service._build_cypher_export(document_id, nodes, edges)
        path = Path(settings.er_report_dir) / f"neo4j_sync_{document_id}.cypher.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    media = "text/plain" if path.suffix == ".txt" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(path, filename=path.name, media_type=media)


@router.get("/neo4j/health")
def check_neo4j_connection():
    from app.core.config import settings
    if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
        return {"connected": False, "message": "Neo4j credentials are not configured."}
    driver = None
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password))
        driver.verify_connectivity()
        return {"connected": True, "message": "Neo4j connection verified."}
    except Exception as exc:
        return {"connected": False, "message": str(exc)}
    finally:
        if driver is not None:
            driver.close()
