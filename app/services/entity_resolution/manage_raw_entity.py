import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from app.models.extraction import RawEntity


_DEICTIC_ALIASES = {
    "nó", "đó", "này", "kia", "ấy", "ông ấy", "bà ấy",
    "người này", "người đó", "công ty", "tập đoàn",
    "tổ chức", "thành phố", "quốc gia", "dự án",
}
_DEICTIC_SUFFIX = re.compile(r"\b(?:này|đó|kia|ấy)\s*$", re.IGNORECASE)


def normalize_text(value: str) -> str:
    """Normalize text for matching without removing Vietnamese diacritics."""
    value = unicodedata.normalize("NFC", value or "")
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def clean_display_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value or "")
    return re.sub(r"\s+", " ", value).strip()


def is_valid_alias(alias: str) -> bool:
    normalized = normalize_text(alias)
    if not normalized or normalized in _DEICTIC_ALIASES:
        return False
    # Reject contextual references such as "dự án này", but do not
    # reject a proper name merely because it contains a generic word.
    if _DEICTIC_SUFFIX.search(normalized):
        return False
    return True


@dataclass(slots=True)
class RawEntityData:
    id: str
    document_id: str
    chunk_id: str
    entity_type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    valid_variants: list[str] = field(default_factory=list)


class ManageRawEntity:
    """Owns the in-memory snapshot of raw entities for one document ER run."""

    def __init__(self) -> None:
        self.entities: dict[str, RawEntityData] = {}

    def load_from_db(self, rows: Iterable[RawEntity]) -> None:
        self.entities.clear()
        for row in rows:
            entity = RawEntityData(
                id=row.id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                entity_type=row.entity_type,
                name=clean_display_text(row.name),
                aliases=list(row.aliases or []),
            )
            self.entities[entity.id] = entity

    def clean_entities(self) -> None:
        for entity in self.entities.values():
            variants: list[str] = []
            seen: set[str] = set()

            # The entity's primary name is retained; only aliases are filtered.
            candidates = [entity.name, *entity.aliases]
            for index, candidate in enumerate(candidates):
                cleaned = clean_display_text(candidate)
                if not cleaned:
                    continue
                if index > 0 and not is_valid_alias(cleaned):
                    continue

                key = normalize_text(cleaned)
                if key and key not in seen:
                    seen.add(key)
                    variants.append(cleaned)

            entity.valid_variants = variants

    def get_entities(self) -> list[RawEntityData]:
        return list(self.entities.values())

    def get_entity(self, entity_id: str) -> RawEntityData | None:
        return self.entities.get(entity_id)
