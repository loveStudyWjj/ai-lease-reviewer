from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ExtractResponse(BaseModel):
    doc_id: str
    text: str


RiskLevel = Literal["high", "medium", "low"]


class ReviewRequest(BaseModel):
    doc_id: str
    text: str
    city: Optional[str] = None


class ClauseReview(BaseModel):
    clause_id: str
    clause_type: str = Field(description="押金/违约/维修/解约/其他")
    risk_level: RiskLevel
    clause_text: str
    risk_reason: str
    legal_basis: str
    suggestion: str
    negotiation_tip: str


class ReviewResponse(BaseModel):
    overall_risk_score: float = Field(ge=0, le=100)
    clauses: list[ClauseReview]

