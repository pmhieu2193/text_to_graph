from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chunk import DocumentChunk

from app.models.extraction import (
    ChunkExtractionRun,
    RawEntity,
    RawRelation,
)

from app.schemas.extraction import ExtractionPayload


class ExtractionRepository:

    def __init__(self, db: Session):
        self.db = db

    def list_chunks(self, document_id: str):

        stmt = (
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id
            )
            .order_by(
                DocumentChunk.chunk_index
            )
        )

        return list(
            self.db.scalars(stmt).all()
        )

    def get_run(self, chunk_id: str):

        stmt = select(
            ChunkExtractionRun
        ).where(
            ChunkExtractionRun.chunk_id == chunk_id
        )

        return self.db.scalar(stmt)

    def mark_running(
        self,
        document_id: str,
        chunk_id: str,
        provider: str,
        model: str,
    ):

        run = self.get_run(chunk_id)

        if run is None:

            run = ChunkExtractionRun(
                document_id=document_id,
                chunk_id=chunk_id,
                provider=provider,
                model_name=model,
            )

            self.db.add(run)

        run.provider = provider
        run.model_name = model
        run.status = "RUNNING"
        run.attempt_count = (run.attempt_count or 0) + 1
        run.error_message = None

        run.started_at = datetime.now(timezone.utc)
        run.completed_at = None

        self.db.commit()

        return run

    def mark_failed(
        self,
        chunk_id: str,
        message: str,
    ):

        run = self.get_run(chunk_id)

        if run is None:
            return

        run.status = "FAILED"
        run.error_message = message[:2000]

        run.completed_at = datetime.now(timezone.utc)

        self.db.commit()

    def save_result(
        self,
        document_id: str,
        chunk_id: str,
        provider: str,
        model: str,
        payload: ExtractionPayload,
    ):

        try:

            # Xóa kết quả cũ của chunk này.
            # Chỉ thực hiện khi muốn ghi kết quả mới.

            self.db.execute(
                delete(RawRelation).where(
                    RawRelation.chunk_id == chunk_id
                )
            )

            self.db.execute(
                delete(RawEntity).where(
                    RawEntity.chunk_id == chunk_id
                )
            )

            # Map local_id -> RawEntity ORM object.

            entity_map = {}

            entities = []

            for item in payload.entities:

                entity = RawEntity(
                    document_id=document_id,
                    chunk_id=chunk_id,

                    local_id=item.local_id,

                    name=item.name,
                    entity_type=item.entity_type,
                    description=item.description,

                    evidence=item.evidence,
                    confidence=item.confidence,

                    provider=provider,
                    model_name=model,
                )

                entities.append(entity)

                entity_map[item.local_id] = entity

            self.db.add_all(entities)

            # Flush để SQLAlchemy thực thi INSERT và sinh UUID.
            # Chưa commit transaction.

            self.db.flush()

            relations = []

            for item in payload.relations:

                subject = entity_map[
                    item.subject_local_id
                ]

                obj = entity_map[
                    item.object_local_id
                ]

                relation = RawRelation(
                    document_id=document_id,
                    chunk_id=chunk_id,

                    local_id=item.local_id,

                    subject_entity_id=subject.id,
                    object_entity_id=obj.id,

                    relation_type=item.relation_type,
                    description=item.description,

                    evidence=item.evidence,
                    confidence=item.confidence,

                    provider=provider,
                    model_name=model,
                )

                relations.append(relation)

            self.db.add_all(relations)

            run = self.get_run(chunk_id)

            run.status = "COMPLETED"
            run.error_message = None
            run.completed_at = datetime.now(timezone.utc)

            # Commit toàn bộ kết quả của chunk trong một transaction.

            self.db.commit()

        except Exception:

            self.db.rollback()
            raise

    def get_document_result(self, document_id: str):

        entities = list(
            self.db.scalars(
                select(RawEntity)
                .where(
                    RawEntity.document_id == document_id
                )
                .order_by(
                    RawEntity.chunk_id,
                    RawEntity.name,
                )
            ).all()
        )

        relations = list(
            self.db.scalars(
                select(RawRelation)
                .where(
                    RawRelation.document_id == document_id
                )
                .order_by(
                    RawRelation.chunk_id,
                    RawRelation.relation_type,
                )
            ).all()
        )

        runs = list(
            self.db.scalars(
                select(ChunkExtractionRun)
                .where(
                    ChunkExtractionRun.document_id == document_id
                )
                .order_by(
                    ChunkExtractionRun.started_at
                )
            ).all()
        )

        return entities, relations, runs

    @staticmethod
    def is_stale_running(run, stale_minutes: int = 30) -> bool:

        if run is None or run.status != "RUNNING":
            return False

        if run.started_at is None:
            return True

        started_at = run.started_at

        # SQLite có thể trả datetime không có timezone.
        if started_at.tzinfo is None:
            started_at = started_at.replace(
                tzinfo=timezone.utc
            )

        deadline = datetime.now(timezone.utc) - timedelta(
            minutes=stale_minutes
        )

        return started_at < deadline