"""Pydantic 请求/响应模型。"""
import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class ProductSignalIn(BaseModel):
    source: str = Field(default="csv", max_length=50)
    external_id: str = Field(max_length=200)
    title: str = Field(min_length=1, max_length=500)
    category: str = Field(max_length=100)
    image_url: str | None = None
    price: float | None = Field(default=None, ge=0)
    sales_signal: dict[str, Any] = Field(default_factory=dict)
    review_signal: dict[str, Any] = Field(default_factory=dict)
    captured_at: dt.datetime | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class ImportProductsIn(BaseModel):
    signals: list[ProductSignalIn] = Field(min_length=1)


class CandidateOut(BaseModel):
    id: int
    normalized_title: str
    category: str
    image_url: str | None
    estimated_cost: float | None
    estimated_price_low: float | None
    estimated_price_high: float | None
    estimated_weight_g: float | None
    estimated_margin: float | None
    seasonal: bool
    demand_score: float
    growth_score: float
    competition_score: float
    margin_score: float
    logistics_score: float
    stability_score: float
    total_score: float
    confidence: float
    recommendation: str
    reasons: list
    risks: list
    differentiation: str
    score_detail: dict
    approved: bool

    class Config:
        from_attributes = True


class ComplianceCheckOut(BaseModel):
    id: int
    candidate_id: int
    market: str
    status: str
    matched_rules: list
    missing_information: list
    explanation: str
    checked_at: dt.datetime
    checked_by: str

    class Config:
        from_attributes = True


class ConversationCreateIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    platform: str = "temu"
    external_conversation_id: str | None = None
    buyer_language: str | None = None  # 不填则自动识别


class ConversationOut(BaseModel):
    id: int
    platform: str
    external_conversation_id: str | None
    buyer_language: str
    question: str
    intent: str
    risk_level: str
    status: str
    automation_level: str
    created_at: dt.datetime

    class Config:
        from_attributes = True


class ReplyDraftOut(BaseModel):
    id: int
    conversation_id: int
    generated_reply: str
    confidence: float
    cited_sources: list
    approval_status: str
    final_reply: str | None
    edited: bool
    approved_by: str | None
    sent_at: dt.datetime | None
    created_at: dt.datetime

    class Config:
        from_attributes = True


class ReplyApproveIn(BaseModel):
    final_reply: str | None = None  # 允许人工修改后确认
    approver: str = "admin"


class KnowledgeIn(BaseModel):
    type: str = Field(max_length=50)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    market: str = "ALL"
    keywords: list[str] = Field(default_factory=list)


class KnowledgeOut(KnowledgeIn):
    id: int
    effective_at: dt.datetime | None
    expires_at: dt.datetime | None
    source: str
    created_at: dt.datetime

    class Config:
        from_attributes = True


class TemuIntegrationIn(BaseModel):
    adapter: str = Field(pattern="^(mock|csv|manual|official)$")
    app_key: str | None = None
    app_secret: str | None = None
    authorization_code: str | None = None


class SettingsUpdateIn(BaseModel):
    score_weights: dict[str, float] | None = None
    target_markets: list[str] | None = None
    automation_level: str | None = Field(default=None, pattern="^(L0|L1|L2|L3)$")
    auto_reply_enabled: bool | None = None
    category_defaults: dict[str, dict[str, float]] | None = None


class AuditEventOut(BaseModel):
    id: int
    actor: str
    action: str
    object_type: str
    object_id: str
    before_data: dict
    after_data: dict
    created_at: dt.datetime

    class Config:
        from_attributes = True


class WhatIfIn(BaseModel):
    """权重实验台：传一组权重，返回重排名结果（不落库）。"""

    weights: dict[str, float]
    k: int = Field(default=5, ge=1, le=50)


class OutcomeImportOut(BaseModel):
    ok: bool
    created: int = 0
    updated: int = 0
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None

