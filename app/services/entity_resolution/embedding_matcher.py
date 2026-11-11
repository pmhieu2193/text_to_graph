from dataclasses import dataclass
from typing import Callable

import numpy as np

from app.services.entity_resolution.manage_raw_entity import ManageRawEntity


@dataclass(slots=True)
class EmbeddingCandidate:
    entity_a: str
    entity_b: str
    embedding_score: float
    matched_variants: tuple[str, str]


class EmbeddingMatcher:
    """Build one dense-vector index and search all valid variants in batches."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        top_k: int = 50,
        candidate_limit: int = 10,
        batch_size: int = 16,
        encoder: Callable | None = None,
    ) -> None:
        self.model_name = model_name
        self.top_k = top_k
        self.candidate_limit = candidate_limit
        self.batch_size = batch_size
        self.encoder = encoder

    def _load_encoder(self):
        if self.encoder is not None:
            return self.encoder

        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError(
                "Thiếu FlagEmbedding. Cài dependencies trong requirements.txt."
            ) from exc

        # Lazy-load: model chỉ được khởi tạo khi thực sự chạy ER.
        self.encoder = BGEM3FlagModel(
            self.model_name,
            use_fp16=False,
        )
        return self.encoder

    def generate(self, manager: ManageRawEntity) -> dict[tuple[str, str], EmbeddingCandidate]:
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError(
                "Thiếu faiss-cpu. Cài dependencies trong requirements.txt."
            ) from exc

        texts: list[str] = []
        metadata: list[tuple[str, str, str, str, str]] = []

        for entity in manager.get_entities():
            for index, text in enumerate(entity.valid_variants):
                texts.append(text)
                metadata.append(
                    (
                        entity.id,
                        entity.document_id,
                        entity.chunk_id,
                        entity.entity_type,
                        text,
                    )
                )

        if len(texts) < 2:
            return {}

        encoder = self._load_encoder()
        encoded = encoder.encode(
            texts,
            batch_size=self.batch_size,
            max_length=8192,
            return_dense=True,
        )
        vectors = np.asarray(
            encoded["dense_vecs"],
            dtype=np.float32,
        )
        if vectors.ndim != 2 or vectors.shape[0] != len(metadata):
            raise ValueError("BGE-M3 trả về ma trận embedding không hợp lệ.")

        faiss.normalize_L2(vectors)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        # Query all variants at once. FAISS returns vector IDs, not entity IDs.
        k = min(self.top_k + 1, len(metadata))
        scores, vector_ids = index.search(vectors, k)

        per_entity: dict[str, dict[str, EmbeddingCandidate]] = {
            entity.id: {} for entity in manager.get_entities()
        }

        for query_idx, (query_score_row, result_id_row) in enumerate(
            zip(scores, vector_ids)
        ):
            source_id, source_doc, source_chunk, source_type, source_text = metadata[query_idx]

            for score, vector_id in zip(query_score_row, result_id_row):
                if vector_id < 0 or vector_id == query_idx:
                    continue

                target_id, target_doc, target_chunk, target_type, target_text = metadata[int(vector_id)]

                if source_id == target_id:
                    continue
                if source_doc != target_doc or source_chunk == target_chunk:
                    continue
                if source_type.casefold() != target_type.casefold():
                    continue

                # Keep one unordered entity pair; do not count A->B and B->A twice.
                pair = tuple(sorted((source_id, target_id)))
                left_text, right_text = (
                    (source_text, target_text)
                    if source_id == pair[0]
                    else (target_text, source_text)
                )
                candidate = EmbeddingCandidate(
                    entity_a=pair[0],
                    entity_b=pair[1],
                    embedding_score=float(score),
                    matched_variants=(left_text, right_text),
                )

                current = per_entity[source_id].get(target_id)
                if current is None or candidate.embedding_score > current.embedding_score:
                    per_entity[source_id][target_id] = candidate

        # Retain Top-K distinct entities per source; union both directions.
        selected: dict[tuple[str, str], EmbeddingCandidate] = {}
        for candidates in per_entity.values():
            ranked = sorted(
                candidates.values(),
                key=lambda item: item.embedding_score,
                reverse=True,
            )[: self.candidate_limit]
            for candidate in ranked:
                key = (candidate.entity_a, candidate.entity_b)
                previous = selected.get(key)
                if previous is None or candidate.embedding_score > previous.embedding_score:
                    selected[key] = candidate

        return selected
