from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entity_resolution import EntityResolutionRun
from app.services.entity_resolution.service import EntityResolutionService


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
        if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
            raise RuntimeError("Thiếu NEO4J_URI, NEO4J_USERNAME hoặc NEO4J_PASSWORD.")
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
        try:
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
            driver.close()

    def sync(self, document_id: str, run_id: str) -> dict:
        run = self.db.get(EntityResolutionRun, run_id)
        if run is None or run.document_id != document_id:
            raise LookupError("Không tìm thấy ER run thuộc document này.")
        if run.status != "FINALIZED":
            raise ValueError("Chỉ được sync một ER run đã FINALIZED.")
        if run.sync_status == "SYNCING":
            raise ValueError("Run đang được đồng bộ; không thể chạy sync song song.")
        if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
            raise RuntimeError("Thiếu NEO4J_URI, NEO4J_USERNAME hoặc NEO4J_PASSWORD.")

        er_service = EntityResolutionService(self.db)
        entities = er_service._canonical_entities_payload(document_id)
        relations, self_loop_count = er_service._canonical_relations_payload(document_id)

        node_ids = {item["canonical_entity_id"] for item in entities}
        for relation in relations:
            if relation["canonical_subject_id"] not in node_ids:
                raise ValueError("Canonical relation có subject không tồn tại trong canonical entities.")
            if relation["canonical_object_id"] not in node_ids:
                raise ValueError("Canonical relation có object không tồn tại trong canonical entities.")

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

        run.sync_status = "SYNCING"
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
                        tx.run(
                            """
                            UNWIND $edges AS row
                            MATCH (s:Entity {document_id: $document_id, id: row.subject_id})
                            MATCH (o:Entity {document_id: $document_id, id: row.object_id})
                            CREATE (s)-[r:RELATION {
                                edge_key: row.edge_key,
                                relation_type: row.relation_type,
                                description: row.description,
                                evidence: row.evidence,
                                raw_relation_ids: row.raw_relation_ids,
                                raw_relation_count: row.raw_relation_count,
                                raw_subject_entity_ids: row.raw_subject_entity_ids,
                                raw_object_entity_ids: row.raw_object_entity_ids
                            }]->(o)
                            """,
                            edges=edges,
                            document_id=document_id,
                        ).consume()

                session.execute_write(replace_document_graph)

            run = self.db.get(EntityResolutionRun, run_id)
            run.sync_status = "SYNCED"
            run.synced_at = datetime.now(timezone.utc)
            run.sync_error = None
            run.neo4j_node_count = len(nodes)
            run.neo4j_relation_count = len(edges)
            self.db.commit()
            return {
                "document_id": document_id,
                "run_id": run_id,
                "sync_status": "SYNCED",
                "node_count": len(nodes),
                "relation_count": len(edges),
                "removed_self_loop_count": self_loop_count,
            }
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.get(EntityResolutionRun, run_id)
            if failed_run is not None:
                failed_run.sync_status = "SYNC_FAILED"
                failed_run.sync_error = f"{type(exc).__name__}: {exc}"[:2000]
                self.db.commit()
            raise RuntimeError(f"Neo4j sync thất bại: {exc}") from exc
        finally:
            if driver is not None:
                driver.close()
