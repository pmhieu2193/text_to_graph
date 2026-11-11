from typing import Literal

from pydantic import BaseModel, Field


class CandidateDecisionRequest(BaseModel):
    decision: Literal["MERGE", "KEEP_SEPARATE", "SKIP"]


class CandidateDecisionResponse(BaseModel):
    pair_id: str
    decision: str
    review_status: str
    canonical_entity_id: str | None = None


class EntityResolutionRunResponse(BaseModel):
    run_id: str
    document_id: str
    candidate_count: int
    auto_merge_count: int
    review_count: int
    reject_count: int
    report_path: str | None = None
    candidates: list[dict] = Field(default_factory=list)
