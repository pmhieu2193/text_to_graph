"""
Benchmark entity resolution tiếng Việt: embedding + RapidFuzz + cosine.

Chạy từ thư mục gốc repository:
    python scripts/benchmark_benchmark_bge_m3.py

Cấu hình DEVICE, BATCH_SIZE, USE_FP16 và ngưỡng ở phần SETTINGS.
Đây là benchmark offline, không gọi API và không ghi database.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import torch
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer


# ============================ SETTINGS ============================

MODEL_NAME = "BAAI/bge-m3"

# "auto": dùng CUDA nếu có, nếu không thì CPU.
# Có thể đặt trực tiếp "cuda" hoặc "cpu".
DEVICE = "auto"

# Batch size gợi ý cho GTX 1050 4 GB:
# BGE-M3: bắt đầu 1-2; E5-small: bắt đầu 8-16.
BATCH_SIZE = 2

# Để False làm mặc định an toàn. Chỉ thử True nếu GPU/driver hỗ trợ ổn định.
USE_FP16 = False

MAX_SEQ_LENGTH = 128
BENCHMARK_REPEATS = 5

FUZZY_WEIGHT = 0.35
COSINE_WEIGHT = 0.65
AUTO_MERGE_THRESHOLD = 0.82
REVIEW_THRESHOLD = 0.74

DATASET_PATH = Path(__file__).parent / "data" / "entity_resolution_2.json"


# ============================ DATA / EMBEDDING ============================

def load_dataset() -> tuple[list[dict[str, Any]], dict[str, str]]:
    payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    entities = payload["entities"]
    # canonical_id chỉ làm nhãn đánh giá; tuyệt đối không đưa vào text embedding.
    labels = {item["id"]: item["canonical_id"] for item in entities}
    return entities, labels


def build_embedding_text(entity: dict[str, Any]) -> str:
    text = (
        f"Tên thực thể: {entity['name']}. "
        f"Loại thực thể: {entity['entity_type']}. "
        f"Mô tả: {entity.get('description') or ''}"
    )

    return text


def sync_device(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def resolve_device() -> str:
    if DEVICE == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if DEVICE == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("DEVICE='cuda' nhưng torch.cuda.is_available() là False.")
    return DEVICE


def encode_entities(model: SentenceTransformer, texts: list[str], device: torch.device) -> tuple[np.ndarray, float]:
    # Warm-up tách riêng, không tính vào inference benchmark.
    model.encode(
        texts[: min(4, len(texts))],
        batch_size=min(BATCH_SIZE, 4),
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    sync_device(device)

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    durations: list[float] = []
    embeddings = None

    for repeat in range(1, BENCHMARK_REPEATS + 1):
        sync_device(device)
        start = time.perf_counter()
        embeddings = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        sync_device(device)
        durations.append(time.perf_counter() - start)
        print(f"  Inference run {repeat}/{BENCHMARK_REPEATS}: {durations[-1]:.4f}s")

    assert embeddings is not None
    avg_time = sum(durations) / len(durations)
    return np.asarray(embeddings, dtype=np.float32), avg_time


# ============================ PAIR SCORING ============================

def score_pairs(
    entities: list[dict[str, Any]],
    embeddings: np.ndarray,
) -> list[dict[str, Any]]:
    # Embeddings đã L2-normalized nên cosine = tích vô hướng.
    similarity_matrix = embeddings @ embeddings.T
    results: list[dict[str, Any]] = []

    for i, j in combinations(range(len(entities)), 2):
        left, right = entities[i], entities[j]
        same_type = left["entity_type"].casefold() == right["entity_type"].casefold()
        fuzzy = fuzz.token_set_ratio(left["name"], right["name"]) / 100.0
        cosine = float(similarity_matrix[i, j])
        combined = FUZZY_WEIGHT * fuzzy + COSINE_WEIGHT * cosine

        if not same_type:
            decision = "BLOCKED_TYPE"
        elif combined >= AUTO_MERGE_THRESHOLD or fuzzy >= 0.96:
            decision = "AUTO_MERGE"
        elif combined >= REVIEW_THRESHOLD:
            decision = "REVIEW"
        else:
            decision = "SEPARATE"

        results.append({
            "left_id": left["id"],
            "right_id": right["id"],
            "left_name": left["name"],
            "right_name": right["name"],
            "same_type": same_type,
            "fuzzy": fuzzy,
            "cosine": cosine,
            "combined": combined,
            "decision": decision,
        })

    return results


# ============================ CLUSTERING / METRICS ============================

class UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {item: item for item in ids}

    def find(self, item: str) -> str:
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def build_predicted_clusters(
    entities: list[dict[str, Any]],
    pair_results: list[dict[str, Any]],
) -> dict[str, str]:
    uf = UnionFind([item["id"] for item in entities])
    for pair in pair_results:
        if pair["decision"] == "AUTO_MERGE":
            uf.union(pair["left_id"], pair["right_id"])
    return {item["id"]: uf.find(item["id"]) for item in entities}


def evaluate_pairwise(
    entities: list[dict[str, Any]],
    true_labels: dict[str, str],
    predicted_labels: dict[str, str],
) -> dict[str, float | int]:
    tp = fp = fn = tn = 0

    for left, right in combinations(entities, 2):
        actual_same = true_labels[left["id"]] == true_labels[right["id"]]
        predicted_same = predicted_labels[left["id"]] == predicted_labels[right["id"]]

        if actual_same and predicted_same:
            tp += 1
        elif not actual_same and predicted_same:
            fp += 1
        elif actual_same and not predicted_same:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    false_merge_rate = fp / (fp + tn) if fp + tn else 0.0

    return {
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_merge_rate": false_merge_rate,
    }


def print_report(
    entities: list[dict[str, Any]],
    labels: dict[str, str],
    pairs: list[dict[str, Any]],
    predicted: dict[str, str],
    inference_seconds: float,
    load_seconds: float,
    device: torch.device,
) -> None:
    metrics = evaluate_pairwise(entities, labels, predicted)
    clusters: dict[str, list[str]] = defaultdict(list)
    for entity in entities:
        clusters[predicted[entity["id"]]].append(entity["name"])

    review_pairs = [p for p in pairs if p["decision"] == "REVIEW"]
    merged_pairs = [p for p in pairs if p["decision"] == "AUTO_MERGE"]

    print("\\n" + "=" * 72)
    print(f"MODEL: {MODEL_NAME}")
    print("=" * 72)
    print(f"Device                    : {device}")
    print(f"Model load time           : {load_seconds:.3f}s")
    print(f"Average inference ({len(entities)} entities): {inference_seconds:.4f}s")
    print(f"Throughput                : {len(entities) / inference_seconds:.1f} entities/s")
    print(f"Average per entity        : {inference_seconds / len(entities) * 1000:.2f} ms")
    print(f"Embedding shape           : ({len(entities)}, {get_embedding_dim(pairs, entities)})")
    print(f"Pair scoring              : {len(pairs)} pairs")
    print(f"Auto-merge links          : {len(merged_pairs)}")
    print(f"Review candidates         : {len(review_pairs)}")
    if device.type == "cuda":
        allocated = torch.cuda.memory_allocated(device) / (1024 ** 3)
        reserved = torch.cuda.memory_reserved(device) / (1024 ** 3)
        peak = torch.cuda.max_memory_allocated(device) / (1024 ** 3)
        print(f"CUDA memory allocated    : {allocated:.2f} GB")
        print(f"CUDA memory reserved     : {reserved:.2f} GB")
        print(f"CUDA peak allocated      : {peak:.2f} GB")

    print("\\n--- PAIRWISE CLUSTERING METRICS ---")
    print(f"TP / FP / FN / TN         : {metrics['TP']} / {metrics['FP']} / {metrics['FN']} / {metrics['TN']}")
    print(f"Precision                 : {metrics['precision']:.4f}")
    print(f"Recall                    : {metrics['recall']:.4f}")
    print(f"F1-score                  : {metrics['f1']:.4f}")
    print(f"False merge rate          : {metrics['false_merge_rate']:.4%}")

    print("\\n--- PREDICTED CLUSTERS ---")
    for number, names in enumerate(sorted(clusters.values(), key=lambda group: (-len(group), group[0])), 1):
        print(f"Cluster {number:02d} ({len(names)}): " + " | ".join(names))

    print("\\n--- REVIEW CANDIDATES (top 20) ---")
    for pair in sorted(review_pairs, key=lambda item: item["combined"], reverse=True)[:20]:
        print(
            f"{pair['left_name']} <-> {pair['right_name']} | "
            f"fuzzy={pair['fuzzy']:.3f}, cosine={pair['cosine']:.4f}, "
            f"combined={pair['combined']:.4f}"
        )

    print("\\n--- INTERPRETATION ---")
    print("Precision thấp / FP cao: ngưỡng đang gộp nhầm; tăng AUTO_MERGE_THRESHOLD.")
    print("Recall thấp / FN cao: bỏ sót alias; cân nhắc hạ ngưỡng hoặc cải thiện mô tả.")
    print("F1 chỉ có ý nghĩa trên bộ dữ liệu và nhãn hiện tại; cần kiểm tra thủ công các FP/FN.")
    print("Union-Find tạo cụm theo liên thông: một cạnh gộp nhầm có thể kéo cả cụm nhập vào nhau.")


def get_embedding_dim(pairs: list[dict[str, Any]], entities: list[dict[str, Any]]) -> str:
    # Kích thước được lấy trực tiếp trong main và gắn vào attribute để in báo cáo.
    return str(getattr(print_report, "embedding_dim", "see output above"))


def main() -> None:
    entities, labels = load_dataset()
    texts = [build_embedding_text(entity) for entity in entities]

    print(f"Dataset: {DATASET_PATH}")
    print(f"Entities: {len(entities)}")
    print(f"Ground-truth clusters: {len(set(labels.values()))}")
    print(f"Device setting: {DEVICE}; batch size: {BATCH_SIZE}; FP16: {USE_FP16}")
    print(f"Loading model: {MODEL_NAME}")
    print("Lần đầu có thể lâu do tải model; lần sau model được đọc từ Hugging Face cache.")

    selected_device = resolve_device()
    start_load = time.perf_counter()
    model = SentenceTransformer(MODEL_NAME, device=selected_device)
    model.max_seq_length = MAX_SEQ_LENGTH
    if USE_FP16 and selected_device == "cuda":
        model.half()
    load_seconds = time.perf_counter() - start_load
    device = torch.device(str(model.device))

    print(f"Loaded on {device}; model load/init: {load_seconds:.3f}s")
    embeddings, inference_seconds = encode_entities(model, texts, device)
    print(f"Embedding shape: {embeddings.shape}")
    setattr(print_report, "embedding_dim", embeddings.shape[1])

    start_scoring = time.perf_counter()
    pair_results = score_pairs(entities, embeddings)
    predicted = build_predicted_clusters(entities, pair_results)
    scoring_seconds = time.perf_counter() - start_scoring

    print_report(
        entities, labels, pair_results, predicted,
        inference_seconds, load_seconds, device
    )
    print(f"Pair scoring + clustering time: {scoring_seconds:.4f}s")
    print(f"Total measured time (load + avg inference + scoring): {load_seconds + inference_seconds + scoring_seconds:.3f}s")
    print("\\nThresholds are experimental starting points, not calibrated production values.")


if __name__ == "__main__":
    main()
