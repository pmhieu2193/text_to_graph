"""
Standalone experiment: RapidFuzz + BGE-M3 entity clustering.

Run from the repository root:
    python scripts/test_entity_clustering.py

The script:
1. Embeds each entity with BAAI/bge-m3.
2. Uses RapidFuzz token_set_ratio for lexical similarity.
3. Uses cosine similarity for semantic similarity.
4. Blocks matches across different entity types.
5. Automatically groups only high-confidence matches.
6. Prints medium-confidence pairs for manual review.

This is an experiment, not the production EntityResolutionService.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer


MODEL_NAME = "BAAI/bge-m3"

# Candidate-generation thresholds: a pair is inspected if either condition passes.
CANDIDATE_COSINE_THRESHOLD = 0.72
CANDIDATE_FUZZY_THRESHOLD = 65.0

# Conservative decision thresholds.
AUTO_MERGE_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.78

# Combined score weights. Keep these configurable while experimenting.
FUZZY_WEIGHT = 0.35
COSINE_WEIGHT = 0.65


SAMPLE_ENTITIES: list[dict[str, Any]] = [
    {
        "id": "E01",
        "name": "Hồ Chí Minh",
        "entity_type": "PERSON",
        "description": "Lãnh tụ cách mạng Việt Nam, Chủ tịch nước Việt Nam Dân chủ Cộng hòa.",
    },
    {
        "id": "E02",
        "name": "Nguyễn Ái Quốc",
        "entity_type": "PERSON",
        "description": "Tên hoạt động cách mạng của Hồ Chí Minh trong thời kỳ hoạt động ở nước ngoài.",
    },
    {
        "id": "E03",
        "name": "Bác Hồ",
        "entity_type": "PERSON",
        "description": "Cách gọi thân mật dành cho Chủ tịch Hồ Chí Minh.",
    },
    {
        "id": "E04",
        "name": "Võ Nguyên Giáp",
        "entity_type": "PERSON",
        "description": "Đại tướng Quân đội nhân dân Việt Nam, Tổng tư lệnh trong kháng chiến.",
    },
    {
        "id": "E05",
        "name": "Đại tướng Võ Nguyên Giáp",
        "entity_type": "PERSON",
        "description": "Vị tướng chỉ huy chiến dịch Điện Biên Phủ năm 1954.",
    },
    {
        "id": "E06",
        "name": "Điện Biên Phủ",
        "entity_type": "LOCATION",
        "description": "Thành phố thuộc tỉnh Điện Biên, địa điểm diễn ra chiến dịch lịch sử năm 1954.",
    },
    {
        "id": "E07",
        "name": "Chiến dịch Điện Biên Phủ",
        "entity_type": "EVENT",
        "description": "Chiến dịch quân sự kết thúc ngày 7 tháng 5 năm 1954.",
    },
    {
        "id": "E08",
        "name": "Hà Nội",
        "entity_type": "LOCATION",
        "description": "Thủ đô của nước Cộng hòa xã hội chủ nghĩa Việt Nam.",
    },
    {
        "id": "E09",
        "name": "Thủ đô Hà Nội",
        "entity_type": "LOCATION",
        "description": "Thủ đô, trung tâm chính trị và hành chính quốc gia của Việt Nam.",
    },
    {
        "id": "E10",
        "name": "Đại học Quốc gia Hà Nội",
        "entity_type": "ORGANIZATION",
        "description": "Cơ sở giáo dục đại học và nghiên cứu đa ngành tại Việt Nam.",
    },
    {
        "id": "E11",
        "name": "ĐHQGHN",
        "entity_type": "ORGANIZATION",
        "description": "Tên viết tắt của Đại học Quốc gia Hà Nội.",
    },
    {
        "id": "E12",
        "name": "Nguyễn Du",
        "entity_type": "PERSON",
        "description": "Đại thi hào Việt Nam, tác giả Truyện Kiều.",
    },
    {
        "id": "E13",
        "name": "Truyện Kiều",
        "entity_type": "WORK",
        "description": "Tác phẩm thơ Nôm nổi tiếng do Nguyễn Du sáng tác.",
    },
    {
        "id": "E14",
        "name": "Đường Nguyễn Huệ",
        "entity_type": "LOCATION",
        "description": "Phố đi bộ Nguyễn Huệ nằm tại trung tâm Thành phố Hồ Chí Minh.",
    },
    {
        "id": "E15",
        "name": "Nguyễn Huệ",
        "entity_type": "PERSON",
        "description": "Vua Quang Trung, lãnh tụ phong trào Tây Sơn.",
    },
]


def build_embedding_text(entity: dict[str, Any]) -> str:
    """Include type and description so embeddings have entity context."""
    return (
        f"Tên thực thể: {entity['name']}. "
        f"Loại thực thể: {entity['entity_type']}. "
        f"Mô tả: {entity.get('description') or ''}"
    )


def cosine_similarity_from_normalized(
    vector_a: np.ndarray,
    vector_b: np.ndarray,
) -> float:
    """Dot product equals cosine similarity for L2-normalized vectors."""
    return float(np.dot(vector_a, vector_b))


def compare_entities(
    entity_a: dict[str, Any],
    entity_b: dict[str, Any],
    vector_a: np.ndarray,
    vector_b: np.ndarray,
) -> dict[str, Any]:
    # Entity-type gate: do not compare entities from different categories.
    same_type = (
        entity_a["entity_type"].strip().casefold()
        == entity_b["entity_type"].strip().casefold()
    )

    fuzzy_score = float(
        fuzz.token_set_ratio(entity_a["name"], entity_b["name"])
    )
    cosine_score = cosine_similarity_from_normalized(vector_a, vector_b)

    combined_score = (
        FUZZY_WEIGHT * (fuzzy_score / 100.0)
        + COSINE_WEIGHT * cosine_score
    )

    if not same_type:
        decision = "BLOCKED_TYPE_MISMATCH"
    elif (
        cosine_score >= CANDIDATE_COSINE_THRESHOLD
        or fuzzy_score >= CANDIDATE_FUZZY_THRESHOLD
    ):
        if combined_score >= AUTO_MERGE_THRESHOLD:
            decision = "AUTO_MERGE"
        elif combined_score >= REVIEW_THRESHOLD:
            decision = "REVIEW"
        else:
            decision = "KEEP_SEPARATE"
    else:
        decision = "KEEP_SEPARATE"

    return {
        "left": entity_a["id"],
        "right": entity_b["id"],
        "left_name": entity_a["name"],
        "right_name": entity_b["name"],
        "same_type": same_type,
        "fuzzy": fuzzy_score,
        "cosine": cosine_score,
        "combined": combined_score,
        "decision": decision,
    }


def cluster_entities(
    entities: list[dict[str, Any]],
    embeddings: np.ndarray,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """
    Conservative representative-based clustering.

    Each entity is compared with existing cluster representatives. It joins
    the best matching cluster only when the combined score reaches the
    AUTO_MERGE threshold. This avoids unrestricted transitive chaining.
    """
    clusters: list[list[dict[str, Any]]] = []
    representatives: list[dict[str, Any]] = []
    review_pairs: list[dict[str, Any]] = []

    for index, entity in enumerate(entities):
        best_cluster_index: int | None = None
        best_score = -1.0

        for cluster_index, representative in enumerate(representatives):
            representative_index = entities.index(representative)
            result = compare_entities(
                entity,
                representative,
                embeddings[index],
                embeddings[representative_index],
            )

            if result["decision"] == "REVIEW":
                review_pairs.append(result)

            if result["decision"] == "AUTO_MERGE":
                if result["combined"] > best_score:
                    best_score = result["combined"]
                    best_cluster_index = cluster_index

        if best_cluster_index is None:
            clusters.append([entity])
            representatives.append(entity)
        else:
            clusters[best_cluster_index].append(entity)

    return clusters, review_pairs


def main() -> None:
    print(f"Loading embedding model: {MODEL_NAME}")
    print("Lần chạy đầu tiên có thể tải model về máy (model khá lớn).")

    model = SentenceTransformer(MODEL_NAME)

    texts = [build_embedding_text(entity) for entity in SAMPLE_ENTITIES]
    embeddings = model.encode(
        texts,
        batch_size=8,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)

    print(f"\nEntities: {len(SAMPLE_ENTITIES)}")
    print(f"Embedding shape: {embeddings.shape}")
    print(
        "Scoring: "
        f"{FUZZY_WEIGHT:.2f} * RapidFuzz + "
        f"{COSINE_WEIGHT:.2f} * cosine"
    )

    # Show all same-type candidate pairs, including pairs not auto-merged.
    pair_results: list[dict[str, Any]] = []
    for i in range(len(SAMPLE_ENTITIES)):
        for j in range(i + 1, len(SAMPLE_ENTITIES)):
            result = compare_entities(
                SAMPLE_ENTITIES[i],
                SAMPLE_ENTITIES[j],
                embeddings[i],
                embeddings[j],
            )
            if result["decision"] != "KEEP_SEPARATE":
                pair_results.append(result)

    pair_results.sort(key=lambda item: item["combined"], reverse=True)

    print("\n=== PAIR COMPARISON ===")
    for item in pair_results:
        print(
            f"[{item['decision']:<20}] "
            f"{item['left_name']} <-> {item['right_name']} | "
            f"fuzzy={item['fuzzy']:.1f} "
            f"cosine={item['cosine']:.4f} "
            f"combined={item['combined']:.4f}"
        )

    clusters, review_pairs = cluster_entities(
        SAMPLE_ENTITIES,
        embeddings,
    )

    print("\n=== AUTO-MERGED CLUSTERS ===")
    for cluster_number, cluster in enumerate(clusters, start=1):
        names = [entity["name"] for entity in cluster]
        print(f"Cluster {cluster_number}: {names}")

    print("\n=== MANUAL REVIEW ===")
    if not review_pairs:
        print("Không có cặp nào nằm trong vùng cần xem xét.")
    else:
        seen: set[tuple[str, str]] = set()
        for item in sorted(
            review_pairs,
            key=lambda value: value["combined"],
            reverse=True,
        ):
            key = (item["left"], item["right"])
            if key in seen:
                continue
            seen.add(key)
            print(
                f"{item['left_name']} <-> {item['right_name']} | "
                f"combined={item['combined']:.4f}"
            )

    print("\n=== SUMMARY ===")
    print(f"Input entities : {len(SAMPLE_ENTITIES)}")
    print(f"Output clusters: {len(clusters)}")
    print(
        "Entities in multi-item clusters: "
        f"{sum(len(cluster) for cluster in clusters if len(cluster) > 1)}"
    )
    print(f"Pairs for review: {len(review_pairs)}")


if __name__ == "__main__":
    main()
