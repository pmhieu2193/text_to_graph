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
            [
                [1.0, 0.0],
                [0.99, 0.01],
                [0.0, 1.0],
            ],
            dtype=np.float32,
        )
        return {"dense_vecs": vectors}


def test_embedding_matcher_encodes_all_variants_once_and_maps_back_to_entities():
    manager = ManageRawEntity()
    manager.entities = {
        "E1": RawEntityData(
            id="E1", document_id="D1", chunk_id="C1",
            entity_type="Organization", name="Nvidia",
            aliases=["NVIDIA"], valid_variants=["Nvidia", "NVIDIA"],
        ),
        "E2": RawEntityData(
            id="E2", document_id="D1", chunk_id="C2",
            entity_type="Organization", name="Nvidia Corporation",
            aliases=[], valid_variants=["Nvidia Corporation"],
        ),
    }
    encoder = FakeEncoder()
    matcher = EmbeddingMatcher(
        top_k=10,
        candidate_limit=10,
        encoder=encoder,
    )

    candidates = matcher.generate(manager)

    assert encoder.calls == 1
    assert ("E1", "E2") in candidates
    assert candidates[("E1", "E2")].embedding_score > 0.99
