from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.entity_resolution import EntityResolutionRun
from app.models.extraction import RawEntity, RawRelation
from app.services.entity_resolution.service import EntityResolutionService
import re
import unicodedata

class Neo4jGraphSyncService:
    """Synchronize one finalized document graph to Neo4j atomically."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _edge_key(subject_id: str, object_id: str, relation_type: str) -> str:
        raw = "\\0".join((subject_id, object_id, " ".join(relation_type.split()).casefold()))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def delete_document_graph(self, document_id: str) -> dict:
        """Delete only one document's Neo4j graph, then clear local sync markers."""
        if self.db.get(Document, document_id) is None:
            raise LookupError("Không tìm thấy tài liệu.")
        runs = self.db.query(EntityResolutionRun).filter(
            EntityResolutionRun.document_id == document_id
        ).all()
        now = datetime.now(timezone.utc)
        for run in runs:
            started = run.sync_started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if run.sync_status == "SYNCING" and started is not None and now - started < timedelta(minutes=10):
                raise ValueError("Document đang được đồng bộ Neo4j; không thể xóa graph lúc này.")
        if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
            raise RuntimeError("Thiếu NEO4J_URI, NEO4J_USERNAME hoặc NEO4J_PASSWORD.")
        driver = None
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
            )
            driver.verify_connectivity()
            with driver.session(database=settings.neo4j_database) as session:
                result = session.execute_write(
                    lambda tx: tx.run(
                        "MATCH (n:Entity {document_id: $document_id}) "
                        "DETACH DELETE n RETURN count(n) AS deleted",
                        document_id=document_id,
                    ).single()
                )
            deleted = result["deleted"] if result else 0
            runs = self.db.query(EntityResolutionRun).filter(
                EntityResolutionRun.document_id == document_id
            ).all()
            for run in runs:
                run.sync_status = "NOT_SYNCED"
                run.sync_started_at = None
                run.synced_at = None
                run.sync_error = None
                run.neo4j_node_count = 0
                run.neo4j_relation_count = 0
            self.db.commit()
            return {"document_id": document_id, "deleted_nodes": deleted, "status": "GRAPH_DELETED"}
        except Exception as exc:
            self.db.rollback()
            raise RuntimeError(f"Không thể xóa graph Neo4j: {exc}") from exc
        finally:
            if driver is not None:
                driver.close()

    @staticmethod
    def _cypher_literal(value) -> str:
        """Serialize a Python value as a safe Cypher literal."""
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, (int, float)):
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _relationship_type(value: str) -> str:
        """Normalize Vietnamese relation types for Neo4j."""
        cleaned = " ".join((value or "").split()).strip()
        if not cleaned:
            raise ValueError("relation_type không được để trống.")
        # Chuyển & thành AND để tránh mất ý nghĩa của R&D
        normalized = cleaned.upper().replace("&", " AND ")
        # Loại bỏ dấu tiếng Việt
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        )
        # Chuẩn hóa khoảng trắng và dấu phân cách
        normalized = re.sub(r"[\s\-]+", "_", normalized)
        normalized = re.sub(r"[^A-Z0-9_]", "", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_")

        if not normalized or not normalized[0].isalpha():
            raise ValueError(
                f"relation_type không hợp lệ để tạo Neo4j relationship type: {value!r}"
            )
        return normalized

    def _build_cypher_export(self, document_id: str, nodes: list[dict], edges: list[dict]) -> str:
        """Build a repeatable Cypher script that replaces only this document graph."""
        statements = [
            "// Generated by text_to_graph after Neo4j synchronization.",
            "// document_id: " + document_id,
            "// Re-running this script replaces only this document's graph.",
            "",
            "MATCH (n:Entity {document_id: " + self._cypher_literal(document_id) + "}) DETACH DELETE n;",
            "",
        ]
        if nodes:
            rows = []
            for node in nodes:
                rows.append(
                    "{id: " + self._cypher_literal(node["id"])
                    + ", document_id: " + self._cypher_literal(node["document_id"])
                    + ", name: " + self._cypher_literal(node["name"])
                    + ", entity_type: " + self._cypher_literal(node["entity_type"])
                    + ", aliases: " + self._cypher_literal(node["aliases"])
                    + ", raw_entity_ids: " + self._cypher_literal(node["raw_entity_ids"]) + "}"
                )
            statements.extend([
                "UNWIND [", "  " + ",\n  ".join(rows), "] AS row",
                "CREATE (:Entity {id: row.id, document_id: row.document_id, name: row.name,",
                "  entity_type: row.entity_type, aliases: row.aliases, raw_entity_ids: row.raw_entity_ids});", "",
            ])
        by_type: dict[str, list[dict]] = {}
        for edge in edges:
            by_type.setdefault(self._relationship_type(edge["relation_type"]), []).append(edge)
        for rel_type, typed_edges in sorted(by_type.items()):
            rows = []
            for edge in typed_edges:
                keys = ("subject_id", "object_id", "edge_key", "relation_type", "description",
                        "evidence", "raw_relation_ids", "raw_relation_count",
                        "raw_subject_entity_ids", "raw_object_entity_ids")
                rows.append("{" + ", ".join(
                    key + ": " + self._cypher_literal(edge[key]) for key in keys
                ) + "}")
            statements.extend([
                "UNWIND [", "  " + ",\n  ".join(rows), "] AS row",
                "MATCH (s:Entity {document_id: " + self._cypher_literal(document_id) + ", id: row.subject_id})",
                "MATCH (o:Entity {document_id: " + self._cypher_literal(document_id) + ", id: row.object_id})",
                "CREATE (s)-[r:`" + rel_type + "` {edge_key: row.edge_key, relation_type: row.relation_type,",
                "  description: row.description, evidence: row.evidence, raw_relation_ids: row.raw_relation_ids,",
                "  raw_relation_count: row.raw_relation_count, raw_subject_entity_ids: row.raw_subject_entity_ids,",
                "  raw_object_entity_ids: row.raw_object_entity_ids}]->(o);", "",
            ])
        return "\n".join(statements).rstrip() + "\n"

    def sync(self, document_id: str) -> dict:
        er_service = EntityResolutionService(self.db)
        run = er_service.get_current_run(document_id)
        run_id = run.id
        if run.status != "FINALIZED":
            raise ValueError("Chỉ được sync một ER run đã FINALIZED.")
        now = datetime.now(timezone.utc)
        started = run.sync_started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if run.sync_status == "SYNCING" and started is not None and now - started < timedelta(minutes=10):
            raise ValueError("Run đang được đồng bộ; không thể chạy sync song song.")
        if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
            raise RuntimeError("Thiếu NEO4J_URI, NEO4J_USERNAME hoặc NEO4J_PASSWORD.")

        entities = er_service._canonical_entities_payload(document_id)
        relations, self_loop_count = er_service._canonical_relations_payload(document_id)

        node_ids = {item["canonical_entity_id"] for item in entities}
        mapped_raw_ids = [
            raw_id for item in entities for raw_id in item.get("raw_entity_ids", [])
        ]
        source_raw_ids = set(self.db.scalars(
            select(RawEntity.id).where(RawEntity.document_id == document_id)
        ).all())
        if len(mapped_raw_ids) != len(set(mapped_raw_ids)) or set(mapped_raw_ids) != source_raw_ids:
            raise ValueError(
                "Canonical membership không bao phủ chính xác toàn bộ raw entities của document."
            )

        for relation in relations:
            if relation["canonical_subject_id"] not in node_ids:
                raise ValueError("Canonical relation có subject không tồn tại trong canonical entities.")
            if relation["canonical_object_id"] not in node_ids:
                raise ValueError("Canonical relation có object không tồn tại trong canonical entities.")

        source_relation_count = len(self.db.scalars(
            select(RawRelation.id).where(RawRelation.document_id == document_id)
        ).all())
        represented_relation_count = sum(
            item.get("raw_relation_count", 0) for item in relations
        )
        if represented_relation_count + self_loop_count != source_relation_count:
            raise ValueError(
                "Canonical relations không bảo toàn số lượng raw relations; từ chối sync để tránh mất cạnh."
            )

        nodes = [
            {
                "id": item["canonical_entity_id"],
                "document_id": document_id,
                "name": item["name"],
                "entity_type": item["entity_type"],
                "aliases": item.get("aliases") or [],
                "raw_entity_ids": item.get("raw_entity_ids") or [],
            }
            for item in entities
        ]
        edges = [
            {
                "edge_key": self._edge_key(
                    item["canonical_subject_id"],
                    item["canonical_object_id"],
                    item["relation_type"],
                ),
                "subject_id": item["canonical_subject_id"],
                "object_id": item["canonical_object_id"],
                "relation_type": item["relation_type"],
                "description": item.get("description") or "",
                "evidence": item.get("evidence") or [],
                "raw_relation_ids": item.get("raw_relation_ids") or [],
                "raw_relation_count": item.get("raw_relation_count", 0),
                "raw_subject_entity_ids": item.get("raw_subject_entity_ids") or [],
                "raw_object_entity_ids": item.get("raw_object_entity_ids") or [],
            }
            for item in relations
        ]

        # Validate relation types and stage the Cypher export before remote writes.
        cypher_text = self._build_cypher_export(document_id, nodes, edges)
        export_dir = Path(settings.er_report_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        cypher_path = export_dir / f"neo4j_sync_{document_id}.cypher.txt"
        temp_path = cypher_path.with_suffix(cypher_path.suffix + ".tmp")
        temp_path.write_text(cypher_text, encoding="utf-8")

        run.sync_status = "SYNCING"
        run.sync_started_at = now
        run.sync_error = None
        self.db.commit()

        driver = None
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
            )
            driver.verify_connectivity()
            with driver.session(database=settings.neo4j_database) as session:
                session.run(
                    "CREATE CONSTRAINT entity_document_id IF NOT EXISTS "
                    "FOR (e:Entity) REQUIRE (e.document_id, e.id) IS UNIQUE"
                ).consume()

                def replace_document_graph(tx):
                    tx.run(
                        "MATCH (n:Entity {document_id: $document_id}) "
                        "DETACH DELETE n",
                        document_id=document_id,
                    ).consume()
                    if nodes:
                        tx.run(
                            """
                            UNWIND $nodes AS row
                            CREATE (e:Entity {
                                id: row.id,
                                document_id: row.document_id,
                                name: row.name,
                                entity_type: row.entity_type,
                                aliases: row.aliases,
                                raw_entity_ids: row.raw_entity_ids
                            })
                            """,
                            nodes=nodes,
                        ).consume()
                    if edges:
                        edges_by_type: dict[str, list[dict]] = {}
                        for edge in edges:
                            edges_by_type.setdefault(
                                self._relationship_type(edge["relation_type"]), []
                            ).append(edge)
                        for relationship_type, typed_edges in edges_by_type.items():
                            # Relationship type is validated and normalized above;
                            # values remain parameterized to avoid Cypher injection.
                            query = (
                                "UNWIND $edges AS row "
                                "MATCH (s:Entity {document_id: $document_id, id: row.subject_id}) "
                                "MATCH (o:Entity {document_id: $document_id, id: row.object_id}) "
                                "CREATE (s)-[r:`" + relationship_type + "` {"
                                "edge_key: row.edge_key, relation_type: row.relation_type, "
                                "description: row.description, evidence: row.evidence, "
                                "raw_relation_ids: row.raw_relation_ids, "
                                "raw_relation_count: row.raw_relation_count, "
                                "raw_subject_entity_ids: row.raw_subject_entity_ids, "
                                "raw_object_entity_ids: row.raw_object_entity_ids"
                                "}]->(o)"
                            )
                            tx.run(
                                query, edges=typed_edges, document_id=document_id
                            ).consume()

                session.execute_write(replace_document_graph)

            run = self.db.get(EntityResolutionRun, run_id)
            run.sync_status = "SYNCED"
            run.sync_started_at = None
            run.synced_at = datetime.now(timezone.utc)
            run.sync_error = None
            run.neo4j_node_count = len(nodes)
            run.neo4j_relation_count = len(edges)
            self.db.commit()
            temp_path.replace(cypher_path)
            return {
                "document_id": document_id,
                "run_id": run_id,
                "sync_status": "SYNCED",
                "node_count": len(nodes),
                "relation_count": len(edges),
                "removed_self_loop_count": self_loop_count,
                "cypher_path": str(cypher_path),
            }
        except Exception as exc:
            self.db.rollback()
            try:
                temp_path.unlink(missing_ok=True)
            except (OSError, UnboundLocalError):
                pass
            failed_run = self.db.get(EntityResolutionRun, run_id)
            if failed_run is not None:
                failed_run.sync_status = "SYNC_FAILED"
                failed_run.sync_started_at = None
                failed_run.sync_error = f"{type(exc).__name__}: {exc}"[:2000]
                self.db.commit()
            raise RuntimeError(f"Neo4j sync thất bại: {exc}") from exc
        finally:
            if driver is not None:
                driver.close()
