from pydantic import BaseModel, ConfigDict, Field


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
    confidence: float = 1.0


class RelationItem(BaseModel):
    local_id: str
    subject_local_id: str
    object_local_id: str
    relation_type: str
    description: str | None = None
    evidence: str
    confidence: float = 1.0


class ExtractionPayload(BaseModel):
    entities: list[EntityItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)


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