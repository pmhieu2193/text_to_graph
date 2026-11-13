import numpy as np
import pytest

faiss = pytest.importorskip("faiss")

from app.services.entity_resolution.embedding_matcher import EmbeddingMatcher
from app.services.entity_resolution.manage_raw_entity import (
    ManageRawEntity,
    RawEntityData,
)


class FakeEncoder:
    def __init__(self):
        self.calls = 0

    def encode(self, texts, **kwargs):
        self.calls += 1
        vectors = np.array(
            [[1.0 - i * 0.001, i * 0.001] for i in range(len(texts))],
            dtype=np.float32,
        )
        return {"dense_vecs": vectors}


def test_embedding_matcher_encodes_all_variants_once_and_maps_back_to_entities(
    tmp_path,
):
    manager = ManageRawEntity()
    manager.entities = {
        "E1": RawEntityData(
            id="E1",
            document_id="D1",
            chunk_id="C1",
            entity_type="Organization",
            name="Nvidia",
            aliases=["NVIDIA"],
            valid_variants=["Nvidia", "NVIDIA"],
        ),
        "E2": RawEntityData(
            id="E2",
            document_id="D1",
            chunk_id="C2",
            entity_type="Organization",
            name="Nvidia Corporation",
            aliases=[],
            valid_variants=["Nvidia Corporation"],
        ),
    }
    encoder = FakeEncoder()
    matcher = EmbeddingMatcher(
        top_k=10,
        candidate_limit=10,
        encoder=encoder,
        index_dir=tmp_path,
    )

    candidates = matcher.generate(manager)

    assert encoder.calls == 1
    assert ("E1", "E2") in candidates
    assert candidates[("E1", "E2")].embedding_score > 0.99


def test_second_run_loads_existing_index_without_encoding(
    tmp_path,
):
    manager = ManageRawEntity()
    manager.entities = {
        "E1": RawEntityData(
            id="E1",
            document_id="D1",
            chunk_id="C1",
            entity_type="Organization",
            name="Nvidia",
            valid_variants=["Nvidia"],
        ),
        "E2": RawEntityData(
            id="E2",
            document_id="D1",
            chunk_id="C2",
            entity_type="Organization",
            name="NVIDIA Corporation",
            valid_variants=["NVIDIA Corporation"],
        ),
    }

    encoder = FakeEncoder()

    first_matcher = EmbeddingMatcher(
        top_k=10,
        candidate_limit=10,
        encoder=encoder,
        index_dir=tmp_path,
    )

    first_result = first_matcher.generate(manager)

    assert encoder.calls == 1
    assert (tmp_path / "D1.index").is_file()
    assert (tmp_path / "D1.meta.json").is_file()

    # Matcher thứ hai không được phép gọi encoder.
    def encoder_must_not_run(*args, **kwargs):
        raise AssertionError("Index cache đáng lẽ phải được sử dụng.")

    second_matcher = EmbeddingMatcher(
        top_k=10,
        candidate_limit=10,
        encoder=encoder_must_not_run,
        index_dir=tmp_path,
    )

    second_result = second_matcher.generate(manager)

    assert first_result.keys() == second_result.keys()


def test_empty_index_is_not_reused(tmp_path):
    manager = ManageRawEntity()
    manager.entities = {
        "E1": RawEntityData(
            id="E1",
            document_id="D1",
            chunk_id="C1",
            entity_type="Organization",
            name="Nvidia",
            valid_variants=["Nvidia"],
        ),
        "E2": RawEntityData(
            id="E2",
            document_id="D1",
            chunk_id="C2",
            entity_type="Organization",
            name="NVIDIA Corporation",
            valid_variants=["NVIDIA Corporation"],
        ),
    }

    # Giả lập index rỗng và metadata cũ.
    (tmp_path / "D1.index").parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    (tmp_path / "D1.index").write_bytes(b"")

    encoder = FakeEncoder()

    matcher = EmbeddingMatcher(
        encoder=encoder,
        index_dir=tmp_path,
    )

    matcher.generate(manager)

    assert encoder.calls == 1
    assert (tmp_path / "D1.index").stat().st_size > 0