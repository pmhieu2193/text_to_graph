
import hashlib
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np

from app.core.config import settings
from app.services.entity_resolution.manage_raw_entity import ManageRawEntity


INDEX_VERSION = 1


@dataclass(slots=True)
class EmbeddingCandidate:
    entity_a: str
    entity_b: str
    embedding_score: float
    matched_variants: tuple[str, str]


@lru_cache(maxsize=2)
def _load_bge_model(model_name: str):
    """Dùng chung model giữa các lần gọi API trong cùng process."""
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu FlagEmbedding. Cài requirements-er.txt."
        ) from exc

    return BGEM3FlagModel(model_name, use_fp16=False)


class EmbeddingMatcher:
    def __init__(
        self,
        model_name: str | None = None,
        top_k: int | None = None,
        candidate_limit: int | None = None,
        batch_size: int | None = None,
        encoder: Callable | None = None,
        index_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name or settings.er_embedding_model
        self.top_k = top_k or settings.er_faiss_top_k
        self.candidate_limit = (
            candidate_limit or settings.er_embedding_candidate_limit
        )
        self.batch_size = batch_size or settings.er_embedding_batch_size
        self.max_length = settings.er_embedding_max_length

        self.encoder = encoder
        self.index_dir = Path(index_dir or settings.er_index_dir)

    @staticmethod
    def _safe_document_id(document_id: str) -> str:
        # Không cho phép document_id tạo đường dẫn ra ngoài thư mục index.
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", document_id)
        if not safe_id:
            raise ValueError("document_id không hợp lệ.")
        return safe_id

    def _paths(self, document_id: str) -> tuple[Path, Path]:
        safe_id = self._safe_document_id(document_id)
        return (
            self.index_dir / f"{safe_id}.index",
            self.index_dir / f"{safe_id}.meta.json",
        )

    @staticmethod
    def _build_metadata(manager: ManageRawEntity) -> list[dict]:
        metadata = []

        for entity in manager.get_entities():
            for text in entity.valid_variants:
                metadata.append({
                    "entity_id": entity.id,
                    "document_id": entity.document_id,
                    "chunk_id": entity.chunk_id,
                    "entity_type": entity.entity_type,
                    "text": text,
                })

        return metadata

    def _fingerprint(self, metadata: list[dict]) -> str:
        payload = {
            "index_version": INDEX_VERSION,
            "model_name": self.model_name,
            "max_length": self.max_length,
            "metadata": metadata,
        }

        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(raw).hexdigest()

    def _load_valid_index(
        self,
        index_path: Path,
        metadata_path: Path,
        fingerprint: str,
        expected_count: int,
    ):
        import faiss

        if not index_path.is_file() or not metadata_path.is_file():
            return None

        if index_path.stat().st_size <= 0:
            return None

        try:
            with metadata_path.open("r", encoding="utf-8") as file:
                saved_metadata = json.load(file)

            if saved_metadata.get("index_version") != INDEX_VERSION:
                return None

            if saved_metadata.get("fingerprint") != fingerprint:
                return None

            if saved_metadata.get("model_name") != self.model_name:
                return None

            rows = saved_metadata.get("rows", [])

            if len(rows) != expected_count:
                return None

            index = faiss.read_index(str(index_path))

            if index.ntotal <= 0 or index.ntotal != expected_count:
                return None

            if index.d <= 0:
                return None

            return index, rows

        except (OSError, ValueError, RuntimeError, KeyError):
            # File hỏng, JSON hỏng hoặc FAISS không đọc được:
            # bỏ qua cache và xây dựng lại.
            return None

    def _load_encoder(self):
        if self.encoder is not None:
            return self.encoder

        self.encoder = _load_bge_model(self.model_name)
        return self.encoder

    def _build_index(
        self,
        metadata: list[dict],
        index_path: Path,
        metadata_path: Path,
        fingerprint: str,
    ):
        import faiss

        texts = [item["text"] for item in metadata]
        encoder = self._load_encoder()

        encoded = encoder.encode(
            texts,
            batch_size=self.batch_size,
            max_length=self.max_length,
            return_dense=True,
        )

        vectors = np.asarray(
            encoded["dense_vecs"],
            dtype=np.float32,
        )

        if vectors.ndim != 2:
            raise ValueError("Embedding phải là ma trận 2 chiều.")

        if vectors.shape[0] != len(metadata):
            raise ValueError("Số vector không khớp số metadata.")

        if vectors.shape[1] <= 0:
            raise ValueError("Embedding dimension không hợp lệ.")

        if not np.isfinite(vectors).all():
            raise ValueError("Embedding chứa NaN hoặc Infinity.")

        faiss.normalize_L2(vectors)

        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        # Ghi ra file tạm. Chỉ đổi tên sau khi ghi thành công.
        index_tmp = index_path.with_name(index_path.name + ".tmp")
        metadata_tmp = metadata_path.with_name(
            metadata_path.name + ".tmp"
        )

        try:
            faiss.write_index(index, str(index_tmp))

            saved_metadata = {
                "index_version": INDEX_VERSION,
                "model_name": self.model_name,
                "fingerprint": fingerprint,
                "vector_count": index.ntotal,
                "dimension": index.d,
                "rows": metadata,
            }

            with metadata_tmp.open("w", encoding="utf-8") as file:
                json.dump(
                    saved_metadata,
                    file,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                file.flush()
                os.fsync(file.fileno())

            # Metadata được thay cuối cùng.
            # Nếu tiến trình lỗi giữa hai thao tác replace,
            # lần chạy tiếp theo sẽ phát hiện fingerprint không khớp.
            os.replace(index_tmp, index_path)
            os.replace(metadata_tmp, metadata_path)

        finally:
            # Dọn file tạm nếu có lỗi.
            index_tmp.unlink(missing_ok=True)
            metadata_tmp.unlink(missing_ok=True)

        return index, metadata

    def _get_or_build_index(self, manager: ManageRawEntity):
        entities = manager.get_entities()

        if not entities:
            return None, []

        document_ids = {entity.document_id for entity in entities}

        if len(document_ids) != 1:
            raise ValueError(
                "EmbeddingMatcher chỉ xử lý một document mỗi lần."
            )

        document_id = next(iter(document_ids))
        metadata = self._build_metadata(manager)

        if not metadata:
            return None, []

        fingerprint = self._fingerprint(metadata)
        index_path, metadata_path = self._paths(document_id)

        self.index_dir.mkdir(parents=True, exist_ok=True)

        cached = self._load_valid_index(
            index_path=index_path,
            metadata_path=metadata_path,
            fingerprint=fingerprint,
            expected_count=len(metadata),
        )

        if cached is not None:
            return cached

        return self._build_index(
            metadata=metadata,
            index_path=index_path,
            metadata_path=metadata_path,
            fingerprint=fingerprint,
        )

    def generate(
        self,
        manager: ManageRawEntity,
    ) -> dict[tuple[str, str], EmbeddingCandidate]:
        import faiss

        index, metadata = self._get_or_build_index(manager)

        if index is None or index.ntotal < 2:
            return {}

        k = min(self.top_k + 1, index.ntotal)

        # Lưu Top-K entity khác nhau cho từng entity nguồn.
        per_entity: dict[str, dict[str, EmbeddingCandidate]] = {
            entity.id: {} for entity in manager.get_entities()
        }

        # Không reconstruct toàn bộ vector thành một ma trận lớn.
        # Chỉ lấy từng batch từ FAISS để tiết kiệm RAM tạm.
        for start in range(0, index.ntotal, self.batch_size):
            count = min(self.batch_size, index.ntotal - start)

            query_vectors = index.reconstruct_n(start, count)
            scores, vector_ids = index.search(query_vectors, k)

            for local_idx, (score_row, id_row) in enumerate(
                zip(scores, vector_ids)
            ):
                query_idx = start + local_idx
                source = metadata[query_idx]
                source_id = source["entity_id"]

                for score, vector_id in zip(score_row, id_row):
                    if vector_id < 0 or vector_id == query_idx:
                        continue

                    target = metadata[int(vector_id)]
                    target_id = target["entity_id"]

                    if source_id == target_id:
                        continue

                    if source["document_id"] != target["document_id"]:
                        continue

                    if source["chunk_id"] == target["chunk_id"]:
                        continue

                    if (
                        source["entity_type"].strip().casefold()
                        != target["entity_type"].strip().casefold()
                    ):
                        continue

                    pair = tuple(sorted((source_id, target_id)))

                    if source_id == pair[0]:
                        matched = (source["text"], target["text"])
                    else:
                        matched = (target["text"], source["text"])

                    candidate = EmbeddingCandidate(
                        entity_a=pair[0],
                        entity_b=pair[1],
                        embedding_score=float(score),
                        matched_variants=matched,
                    )

                    current = per_entity[source_id].get(target_id)

                    if (
                        current is None
                        or candidate.embedding_score
                        > current.embedding_score
                    ):
                        per_entity[source_id][target_id] = candidate

        # Giữ Top-K entity khác nhau, không phải Top-K alias.
        selected = {}

        for candidates in per_entity.values():
            ranked = sorted(
                candidates.values(),
                key=lambda item: item.embedding_score,
                reverse=True,
            )[:self.candidate_limit]

            for candidate in ranked:
                key = (candidate.entity_a, candidate.entity_b)
                previous = selected.get(key)

                if (
                    previous is None
                    or candidate.embedding_score
                    > previous.embedding_score
                ):
                    selected[key] = candidate

        return selected
