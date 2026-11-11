from pydantic import BaseModel, ConfigDict, Field, model_validator


# ==========================================
# 1. SCHEMAS DÙNG CHO LLM EXTRACTION PAYLOAD
# ==========================================

class EntityItem(BaseModel):
    local_id: str
    name: str
    aliases: list[str] = Field(
        default_factory=list,
        description="Danh sách các bí danh, tên viết tắt hoặc danh xưng khác của thực thể."
    )
    entity_type: str
    description: str | None = None
    evidence: list[str] = Field(
        default_factory=list,
        description="Danh sách các câu/đoạn trích nguyên văn từ nguồn liên quan đến thực thể."
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RelationItem(BaseModel):
    local_id: str
    subject_local_id: str
    object_local_id: str
    relation_type: str
    description: str | None = None
    evidence: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractionPayload(BaseModel):
    entities: list[EntityItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_relation_references(self):
        entity_ids = [entity.local_id for entity in self.entities]
        entity_id_set = set(entity_ids)

        if len(entity_ids) != len(entity_id_set):
            raise ValueError("Entity local_id phải duy nhất trong một payload.")

        relation_ids = [relation.local_id for relation in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("Relation local_id phải duy nhất trong một payload.")

        for relation in self.relations:
            missing = [
                local_id
                for local_id in (
                    relation.subject_local_id,
                    relation.object_local_id,
                )
                if local_id not in entity_id_set
            ]
            if missing:
                missing_ids = ", ".join(sorted(set(missing)))
                raise ValueError(
                    f"Relation '{relation.local_id}' tham chiếu entity "
                    f"không tồn tại: {missing_ids}."
                )

        return self


# ==========================================
# 2. SCHEMAS DÙNG CHO API RESPONSE (FASTAPI)
# ==========================================

class RawEntityResponse(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    local_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    entity_type: str
    description: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float
    provider: str
    model_name: str

    model_config = ConfigDict(from_attributes=True)


class RawRelationResponse(BaseModel):
    id: str
    document_id: str
    chunk_id: str
    local_id: str
    subject_entity_id: str
    object_entity_id: str
    relation_type: str
    description: str | None = None
    evidence: str
    confidence: float
    provider: str
    model_name: str

    model_config = ConfigDict(from_attributes=True)


class DocumentExtractionResultResponse(BaseModel):
    document_id: str
    entity_count: int
    relation_count: int
    entities: list[RawEntityResponse] = Field(default_factory=list)
    relations: list[RawRelationResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
