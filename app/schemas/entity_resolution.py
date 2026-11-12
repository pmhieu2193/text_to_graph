from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateDecisionRequest(BaseModel):
    decision: Literal["MERGE", "KEEP_SEPARATE", "SKIP"]


class CandidateDecisionResponse(BaseModel):
    pair_id: str
    decision: str
    review_status: str
    canonical_entity_id: str | None = None


class ERCandidateResponse(BaseModel):
    pair_id: str
    run_id: str
    entity_a_id: str
    entity_a: str | None = None
    evidence_a: list[str] = Field(default_factory=list)
    entity_b_id: str
    entity_b: str | None = None
    evidence_b: list[str] = Field(default_factory=list)
    fuzzy_score: float | None = None
    embedding_score: float | None = None
    final_score: float | None = None
    match_method: str
    fuzzy_exact: bool = False
    fuzzy_match: list[str] | None = None
    embedding_match: list[str] | None = None
    classification: str
    decision: str | None = None
    review_status: str


class ERPreviewResponse(BaseModel):
    document_id: str
    run_id: str
    candidate_count: int
    auto_merge_count: int
    review_count: int
    reject_count: int
    report_path: str | None = None
    candidates: list[ERCandidateResponse] = Field(default_factory=list)


class ERCandidateListResponse(BaseModel):
    document_id: str
    run_id: str
    items: list[ERCandidateResponse] = Field(default_factory=list)


class AutoMergeResponse(BaseModel):
    document_id: str
    run_id: str
    auto_candidates: int
    merged_or_already_same_cluster: int
    blocked_by_keep_separate: int


class CanonicalEntityResponse(BaseModel):
    canonical_entity_id: str
    name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    raw_entity_ids: list[str] = Field(default_factory=list)


class CanonicalRelationResponse(BaseModel):
    canonical_subject_id: str
    canonical_subject_name: str
    canonical_object_id: str
    canonical_object_name: str
    relation_type: str
    description: str = ""
    evidence: list[str] = Field(default_factory=list)
    raw_relation_ids: list[str] = Field(default_factory=list)
    raw_subject_entity_ids: list[str] = Field(default_factory=list)
    raw_object_entity_ids: list[str] = Field(default_factory=list)
    raw_subject_entity_id: str | None = None
    raw_object_entity_id: str | None = None
    raw_relation_count: int = 0


class CanonicalEntityListResponse(BaseModel):
    document_id: str
    items: list[CanonicalEntityResponse] = Field(default_factory=list)


class CanonicalRelationListResponse(BaseModel):
    document_id: str
    items: list[CanonicalRelationResponse] = Field(default_factory=list)


class FinalizeERResponse(BaseModel):
    document_id: str
    run_id: str
    status: str
    candidate_count: int
    merged_count: int
    kept_separate_count: int
    skipped_count: int
    blocked_conflict_count: int
    canonical_entity_count: int
    canonical_relation_count: int
    deduplicated_relation_count: int
    removed_self_loop_count: int
    auto_candidates: int
    merged_or_already_same_cluster: int
    blocked_by_keep_separate: int
    defaulted_to_skip: int
    report_path: str | None = None
    canonical_entities: list[CanonicalEntityResponse] = Field(default_factory=list)
    canonical_relations: list[CanonicalRelationResponse] = Field(default_factory=list)


class Neo4jSyncResponse(BaseModel):
    document_id: str
    run_id: str
    sync_status: str
    node_count: int
    relation_count: int
    removed_self_loop_count: int
    cypher_path: str


class ERResetResponse(BaseModel):
    document_id: str
    status: str
    deleted_runs: int
    preserved: list[str] = Field(default_factory=list)


class Neo4jDeleteResponse(BaseModel):
    document_id: str
    deleted_nodes: int
    status: str


class EntityResolutionRunResponse(BaseModel):
    run_id: str
    document_id: str
    candidate_count: int
    auto_merge_count: int
    review_count: int
    reject_count: int
    report_path: str | None = None
    candidates: list[ERCandidateResponse] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")
