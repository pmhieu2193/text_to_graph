from dataclasses import dataclass
from itertools import combinations

from rapidfuzz import fuzz

from app.services.entity_resolution.manage_raw_entity import (
    ManageRawEntity,
    normalize_text,
)


@dataclass(slots=True)
class StringCandidate:
    entity_a: str
    entity_b: str
    fuzzy_score: float
    is_exact: bool
    matched_variants: tuple[str, str]


class StringMatcher:
    def __init__(self, top_k: int = 10) -> None:
        self.top_k = top_k

    @staticmethod
    def _compatible(a, b) -> bool:
        return (
            a.id != b.id
            and a.document_id == b.document_id
            and a.chunk_id != b.chunk_id
            and a.entity_type.strip().casefold()
            == b.entity_type.strip().casefold()
        )

    @staticmethod
    def _compare_variants(a, b) -> tuple[float, bool, tuple[str, str]]:
        best_score = -1.0
        best_pair = ("", "")
        exact = False

        for value_a in a.valid_variants:
            normalized_a = normalize_text(value_a)
            for value_b in b.valid_variants:
                normalized_value_b = normalize_text(value_b)
                score = float(fuzz.WRatio(normalized_a, normalized_value_b))
                is_pair_exact = bool(normalized_a and normalized_a == normalized_value_b)

                if score > best_score:
                    best_score = score
                    best_pair = (value_a, value_b)
                exact = exact or is_pair_exact

        return max(best_score, 0.0), exact, best_pair

    def generate(self, manager: ManageRawEntity) -> dict[tuple[str, str], StringCandidate]:
        entities = manager.get_entities()
        per_entity: dict[str, list[StringCandidate]] = {
            entity.id: [] for entity in entities
        }

        for a, b in combinations(entities, 2):
            if not self._compatible(a, b):
                continue
            if not a.valid_variants or not b.valid_variants:
                continue

            score, is_exact, matched = self._compare_variants(a, b)
            candidate = StringCandidate(
                entity_a=a.id,
                entity_b=b.id,
                fuzzy_score=score / 100.0,
                is_exact=is_exact,
                matched_variants=matched,
            )
            per_entity[a.id].append(candidate)
            per_entity[b.id].append(candidate)

        # Keep Top-K distinct entity candidates for each source entity.
        selected_pairs: dict[tuple[str, str], StringCandidate] = {}
        for candidates in per_entity.values():
            candidates.sort(
                key=lambda item: (item.is_exact, item.fuzzy_score),
                reverse=True,
            )
            for candidate in candidates[: self.top_k]:
                key = tuple(sorted((candidate.entity_a, candidate.entity_b)))
                selected_pairs[key] = candidate

        return selected_pairs
