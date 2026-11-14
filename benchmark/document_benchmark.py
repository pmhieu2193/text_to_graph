"""Read-only per-document benchmark exporter. Run: python -m benchmark.document_benchmark --document-id UUID"""
import argparse, csv, json, re
from collections import Counter
from itertools import combinations
from pathlib import Path
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.document import Document
from app.models.chunk import DocumentChunk
from app.models.extraction import ChunkExtractionRun, RawEntity, RawRelation
from app.models.entity_resolution import EntityResolutionRun, EntityCandidate, CanonicalEntity, CanonicalEntityMember


def norm(value):
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def prf(predicted, expected):
    tp, fp, fn = len(predicted & expected), len(predicted - expected), len(expected - predicted)
    p, r = (tp / (tp + fp) if tp + fp else 0.0), (tp / (tp + fn) if tp + fn else 0.0)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r, 4),
            "f1": round(2*p*r/(p+r), 4) if p+r else 0.0}


def pair_set(groups):
    return {tuple(sorted(pair)) for group in groups for pair in combinations(sorted(set(group)), 2)}


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export(document_id, output_root, ground_truth=None):
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            raise SystemExit(f"Document not found: {document_id}")
        chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)))
        runs = list(db.scalars(select(ChunkExtractionRun).where(ChunkExtractionRun.document_id == document_id)))
        entities = list(db.scalars(select(RawEntity).where(RawEntity.document_id == document_id)))
        relations = list(db.scalars(select(RawRelation).where(RawRelation.document_id == document_id)))
        er = db.scalar(select(EntityResolutionRun).where(EntityResolutionRun.document_id == document_id).order_by(EntityResolutionRun.created_at.desc()).limit(1))
        candidates = list(db.scalars(select(EntityCandidate).where(EntityCandidate.document_id == document_id)))
        canonical = list(db.scalars(select(CanonicalEntity).where(CanonicalEntity.document_id == document_id)))
        members = list(db.scalars(select(CanonicalEntityMember).where(CanonicalEntityMember.document_id == document_id)))
        out = Path(output_root) / document_id
        out.mkdir(parents=True, exist_ok=True)
        run_by_chunk = {x.chunk_id: x for x in runs}
        entity_by_id = {x.id: x for x in entities}
        canonical_by_id = {x.id: x for x in canonical}
        member_map = {x.raw_entity_id: x.canonical_entity_id for x in members}
        chunk_rows, durations = [], []
        for chunk in chunks:
            run = run_by_chunk.get(chunk.id)
            seconds = None
            if run and run.started_at and run.completed_at:
                start, end = run.started_at, run.completed_at
                if start.tzinfo is None and end.tzinfo: start = start.replace(tzinfo=end.tzinfo)
                if end.tzinfo is None and start.tzinfo: end = end.replace(tzinfo=start.tzinfo)
                seconds = max(0.0, (end-start).total_seconds())
                durations.append(seconds)
            chunk_rows.append({"chunk_id":chunk.id,"chunk_index":chunk.chunk_index,"char_count":chunk.char_count,
                "page_start":chunk.page_start,"page_end":chunk.page_end,"status":run.status if run else "NOT_STARTED",
                "attempt_count":run.attempt_count if run else 0,"provider":run.provider if run else "",
                "model":run.model_name if run else "","duration_seconds":round(seconds,3) if seconds is not None else "",
                "error_message":run.error_message if run else ""})
        states = Counter(x["status"] for x in chunk_rows)
        entity_types, relation_types = Counter(x.entity_type for x in entities), Counter(x.relation_type for x in relations)
        active_canonical = [x for x in canonical if x.merged_into_id is None]
        invalid_endpoints = sum(x.subject_entity_id not in entity_by_id or x.object_entity_id not in entity_by_id for x in relations)
        summary = {
            "document":{"id":doc.id,"filename":doc.original_filename,"status":doc.status.value,
                "uploaded_at":str(doc.uploaded_at),"updated_at":str(doc.updated_at),"processed_at":str(doc.processed_at),
                "pages":doc.page_count,"chunks":doc.chunk_count,"file_size_bytes":doc.file_size,"sha256":doc.sha256},
            "processing":{"chunk_rows":len(chunks),"total_characters":sum(x.char_count for x in chunks)},
            "extraction":{"total_chunks":len(chunks),"completed_chunks":states["COMPLETED"],"failed_chunks":states["FAILED"],
                "running_chunks":states["RUNNING"],"pending_or_not_started":states["PENDING"]+states["NOT_STARTED"],
                "remaining_chunks":len(chunks)-states["COMPLETED"],"chunk_status_counts":dict(states),
                "raw_entity_count":len(entities),"raw_relation_count":len(relations),"entity_type_counts":dict(entity_types),
                "relation_type_counts":dict(relation_types),"total_attempts":sum(x["attempt_count"] for x in chunk_rows),
                "mean_chunk_duration_seconds":round(sum(durations)/len(durations),3) if durations else None,
                "median_chunk_duration_seconds":round(sorted(durations)[len(durations)//2],3) if durations else None},
            "entity_resolution":{"run_id":er.id if er else None,"run_status":er.status if er else None,
                "candidate_count":len(candidates),"candidate_classifications":dict(Counter(x.classification for x in candidates)),
                "candidate_review_statuses":dict(Counter(x.review_status for x in candidates)),
                "candidate_methods":dict(Counter(x.match_method for x in candidates)),
                "canonical_entities_all":len(canonical),"canonical_entities_active":len(active_canonical),
                "canonical_members":len(members),
                "entity_reduction_count":len(entities)-len(active_canonical) if er and er.status=="FINALIZED" else None,
                "entity_reduction_percent":round((len(entities)-len(active_canonical))/len(entities)*100,2) if entities and er and er.status=="FINALIZED" else None},
            "graph_integrity":{"raw_relation_missing_endpoint_count":invalid_endpoints,
                "unassigned_raw_entities_after_finalize":sum(x.id not in member_map for x in entities) if er and er.status=="FINALIZED" else None,
                "neo4j_sync_status":er.sync_status if er else None,"neo4j_node_count":er.neo4j_node_count if er else None,
                "neo4j_relation_count":er.neo4j_relation_count if er else None},
            "interpretation":["Counts and reduction are operational metrics, not accuracy scores.",
                "Precision/Recall/F1 require manually curated ground truth.","This is a point-in-time snapshot, not a historical event log."]}
        entity_rows = [{"raw_entity_id":x.id,"chunk_id":x.chunk_id,"local_id":x.local_id,"name":x.name,
            "entity_type":x.entity_type,"aliases":json.dumps(x.aliases or [],ensure_ascii=False),
            "description":x.description or "","evidence":json.dumps(x.evidence or [],ensure_ascii=False),
            "confidence":x.confidence,"provider":x.provider,"model":x.model_name,
            "canonical_entity_id":member_map.get(x.id,""),
            "canonical_name":canonical_by_id[member_map[x.id]].name if x.id in member_map and member_map[x.id] in canonical_by_id else ""} for x in entities]
        relation_rows = [{"raw_relation_id":x.id,"chunk_id":x.chunk_id,"local_id":x.local_id,
            "subject_entity_id":x.subject_entity_id,"subject_name":entity_by_id[x.subject_entity_id].name if x.subject_entity_id in entity_by_id else "",
            "relation_type":x.relation_type,"object_entity_id":x.object_entity_id,
            "object_name":entity_by_id[x.object_entity_id].name if x.object_entity_id in entity_by_id else "",
            "evidence":x.evidence,"confidence":x.confidence} for x in relations]
        candidate_rows = [{"candidate_id":x.id,"entity_a_id":x.entity_a_id,
            "entity_a_name":entity_by_id[x.entity_a_id].name if x.entity_a_id in entity_by_id else "",
            "entity_b_id":x.entity_b_id,"entity_b_name":entity_by_id[x.entity_b_id].name if x.entity_b_id in entity_by_id else "",
            "fuzzy_score":x.fuzzy_score,"embedding_score":x.embedding_score,"final_score":x.final_score,
            "match_method":x.match_method,"classification":x.classification,"decision":x.decision,
            "review_status":x.review_status,"reviewed_at":str(x.reviewed_at) if x.reviewed_at else ""} for x in candidates]
        if ground_truth:
            gt=json.loads(Path(ground_truth).read_text(encoding="utf-8"))
            expected_e={(norm(x["name"]),norm(x.get("entity_type"))) for x in gt.get("entities",[])}
            predicted_e={(norm(x.name),norm(x.entity_type)) for x in entities}
            expected_r={(norm(x["subject"]),norm(x["relation_type"]),norm(x["object"])) for x in gt.get("relations",[])}
            predicted_r={(norm(entity_by_id[x.subject_entity_id].name if x.subject_entity_id in entity_by_id else ""),
                norm(x.relation_type),norm(entity_by_id[x.object_entity_id].name if x.object_entity_id in entity_by_id else "")) for x in relations}
            summary["ground_truth"]={"matching":"normalized exact entity name/type and normalized subject/relation/object",
                "entity_extraction":prf(predicted_e,expected_e),"relation_extraction":prf(predicted_r,expected_r)}
            if gt.get("entity_clusters") and er and er.status=="FINALIZED":
                groups={}
                for raw_id,canonical_id in member_map.items(): groups.setdefault(canonical_id,[]).append(raw_id)
                summary["ground_truth"]["final_er_pairwise"]=prf(pair_set(groups.values()),pair_set(gt["entity_clusters"]))
        (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
        write_csv(out/"chunks.csv",chunk_rows,["chunk_id","chunk_index","char_count","page_start","page_end","status","attempt_count","provider","model","duration_seconds","error_message"])
        write_csv(out/"entities.csv",entity_rows,["raw_entity_id","chunk_id","local_id","name","entity_type","aliases","description","evidence","confidence","provider","model","canonical_entity_id","canonical_name"])
        write_csv(out/"relations.csv",relation_rows,["raw_relation_id","chunk_id","local_id","subject_entity_id","subject_name","relation_type","object_entity_id","object_name","evidence","confidence"])
        write_csv(out/"candidates.csv",candidate_rows,["candidate_id","entity_a_id","entity_a_name","entity_b_id","entity_b_name","fuzzy_score","embedding_score","final_score","match_method","classification","decision","review_status","reviewed_at"])
        md=[f"# Benchmark: {doc.original_filename}","",f"- Document ID: `{doc.id}`",f"- Status: **{doc.status.value}**",
            f"- Pages / chunks: {doc.page_count or 0} / {len(chunks)}","","## Extraction",
            f"- Completed chunks: {states['COMPLETED']} / {len(chunks)}",f"- Failed chunks: {states['FAILED']}",
            f"- Raw entities / relations: {len(entities)} / {len(relations)}",f"- Total attempts: {summary['extraction']['total_attempts']}",
            "","## Entity Resolution",f"- ER run: {er.status if er else 'Not run'}",f"- Candidates: {len(candidates)}",
            f"- Active canonical entities: {len(active_canonical) if er and er.status=='FINALIZED' else 'Not finalized'}",
            f"- Entity reduction: {summary['entity_resolution']['entity_reduction_percent']}%","","## Graph integrity",
            f"- Raw relations with missing endpoint: {invalid_endpoints}","","Counts/reduction are not accuracy metrics; see CSV files for row-level comparison."]
        (out/"benchmark.md").write_text("\n".join(md)+"\n",encoding="utf-8")
        return out


def main():
    parser=argparse.ArgumentParser(description="Export per-document VietGraph benchmark data.")
    parser.add_argument("--document-id",required=True)
    parser.add_argument("--output-dir",default="benchmark/results")
    parser.add_argument("--ground-truth",default=None)
    args=parser.parse_args()
    print(f"Benchmark export written to: {export(args.document_id,args.output_dir,args.ground_truth).resolve()}")


if __name__=="__main__":
    main()
