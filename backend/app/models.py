"""核心数据模型（对应需求第九节）。"""
import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ProductSignal(Base):
    """来自各数据源的原始商品热度快照。"""

    __tablename__ = "product_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)  # demo/csv/connector/temu
    external_id: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sales_signal: Mapped[dict] = mapped_column(JSON, default=dict)   # {sales, growth_7d, reviews...}
    review_signal: Mapped[dict] = mapped_column(JSON, default=dict)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    cluster_key: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)


class ProductCandidate(Base):
    """清洗聚类后的候选商品及评分结果。"""

    __tablename__ = "product_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    representative_signal_id: Mapped[int | None] = mapped_column(ForeignKey("product_signals.id"), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_price_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_price_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    seasonal: Mapped[bool] = mapped_column(Boolean, default=False)
    demand_score: Mapped[float] = mapped_column(Float, default=0)
    growth_score: Mapped[float] = mapped_column(Float, default=0)
    competition_score: Mapped[float] = mapped_column(Float, default=0)
    margin_score: Mapped[float] = mapped_column(Float, default=0)
    logistics_score: Mapped[float] = mapped_column(Float, default=0)
    stability_score: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    recommendation: Mapped[str] = mapped_column(String(20), default="PENDING")  # TOP/CONSIDER/PENDING/REJECT
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    differentiation: Mapped[str] = mapped_column(Text, default="")
    score_detail: Mapped[dict] = mapped_column(JSON, default=dict)  # 每个分项的计算依据，保证可追溯
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)  # 供合规缺失检查的 size/material 等字段
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    signals: Mapped[list["ProductSignal"]] = relationship()
    compliance_checks: Mapped[list["ComplianceCheck"]] = relationship(back_populates="candidate")


class ComplianceCheck(Base):
    __tablename__ = "compliance_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("product_candidates.id"), index=True)
    market: Mapped[str] = mapped_column(String(50))  # 目标国家/地区，可配置
    status: Mapped[str] = mapped_column(String(20))  # PASS / REVIEW / REJECT
    matched_rules: Mapped[list] = mapped_column(JSON, default=list)
    missing_information: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    checked_by: Mapped[str] = mapped_column(String(50), default="system")

    candidate: Mapped[ProductCandidate] = relationship(back_populates="compliance_checks")


class CustomerConversation(Base):
    __tablename__ = "customer_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), default="temu")
    external_conversation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    buyer_language: Mapped[str] = mapped_column(String(10), default="zh")  # zh/en/es...
    question: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[str] = mapped_column(String(50), default="unknown")
    risk_level: Mapped[str] = mapped_column(String(20), default="low")  # low/medium/high
    status: Mapped[str] = mapped_column(String(30), default="open")  # open/drafting/waiting_human/closed
    automation_level: Mapped[str] = mapped_column(String(5), default="L1")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReplyDraft(Base):
    __tablename__ = "reply_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("customer_conversations.id"), index=True)
    generated_reply: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    cited_sources: Mapped[list] = mapped_column(JSON, default=list)
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected/sent
    final_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50), index=True)  # policy/faq/shipping/product
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    market: Mapped[str] = mapped_column(String(50), default="ALL")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    effective_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(200), default="manual")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    action: Mapped[str] = mapped_column(String(100))
    object_type: Mapped[str] = mapped_column(String(50))
    object_id: Mapped[str] = mapped_column(String(100), default="")
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AppSetting(Base):
    """键值型配置：评分权重、目标市场、自动化等级等，可在后台调整。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class IntegrationSetting(Base):
    """外部接入配置。密钥只存加密后的密文。"""

    __tablename__ = "integration_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # temu 等
    adapter: Mapped[str] = mapped_column(String(50), default="mock")
    status: Mapped[str] = mapped_column(String(50), default="not_connected")
    config_encrypted: Mapped[dict] = mapped_column(JSON, default=dict)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)  # 各接口可用性与替代方式
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrendSnapshot(Base):
    """候选商品的热度历史（第二阶段趋势图使用，第一阶段随导入产生）。"""

    __tablename__ = "trend_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("product_candidates.id"), index=True)
    heat: Mapped[float] = mapped_column(Float, default=0)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class SelectionOutcome(Base):
    """推荐结果回流：把"当初推了什么"和"后来卖得怎样"配成对。

    没有这张表，权重永远是拍的——AHP 只能保证判断自洽，不能保证判断对。
    只有攒够 (推荐 → 实际动销) 的配对样本，才谈得上回归校准和命中率。
    """

    __tablename__ = "selection_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("product_candidates.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=False)        # 是否真的上架了
    sold: Mapped[bool] = mapped_column(Boolean, default=False)          # 是否动销
    sales_30d: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(200), default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)        # 演示/真实来源标记
    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
