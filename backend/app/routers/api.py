"""全部 API 路由。所有接口有输入校验、错误处理与审计记录。"""
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..adapters.temu import get_adapter
from ..appsettings import get_setting, record_audit, set_setting
from ..config import settings
from ..db import get_db
from ..models import (
    AuditEvent,
    ComplianceCheck,
    CustomerConversation,
    KnowledgeDocument,
    ProductCandidate,
    ProductSignal,
    ReplyDraft,
    utcnow,
)
from ..schemas import (
    AuditEventOut,
    ComplianceCheckOut,
    ConversationCreateIn,
    ConversationOut,
    ImportProductsIn,
    KnowledgeIn,
    KnowledgeOut,
    ProductSignalIn,
    ReplyApproveIn,
    ReplyDraftOut,
    SettingsUpdateIn,
    TemuIntegrationIn,
)
from ..services import customer_service as cs
from ..services.importer import import_csv_content, import_signals
from ..services.selection import build_candidates_from_signals, run_selection

router = APIRouter(prefix="/api")


def _candidate_or_404(db: Session, candidate_id: int) -> ProductCandidate:
    c = db.get(ProductCandidate, candidate_id)
    if not c:
        raise HTTPException(404, "候选商品不存在")
    return c


# ---------- 数据接入 / 信号 ----------

@router.post("/imports/products")
def api_import_products(payload: ImportProductsIn, db: Session = Depends(get_db)):
    result = import_signals(db, [s.model_dump() for s in payload.signals])
    record_audit(db, "import_signals", "signal", after=result)
    return {"ok": True, **result}


@router.post("/imports/csv")
async def api_import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = (await file.read()).decode("utf-8-sig")
    result = import_csv_content(db, content)
    record_audit(db, "import_csv", "signal", after=result)
    return {"ok": True, **result}


@router.get("/signals")
def api_signals(category: str | None = None, source: str | None = None,
                limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(ProductSignal)
    if category:
        q = q.filter(ProductSignal.category == category)
    if source:
        q = q.filter(ProductSignal.source == source)
    rows = q.order_by(ProductSignal.captured_at.desc()).limit(min(limit, 500)).all()
    return {"total": q.count(), "items": [
        {"id": r.id, "source": r.source, "external_id": r.external_id, "title": r.title,
         "category": r.category, "price": r.price, "sales_signal": r.sales_signal,
         "captured_at": r.captured_at, "cluster_key": r.cluster_key} for r in rows]}


# ---------- 选品 ----------

@router.post("/selection/run")
def api_selection_run(candidate_id: int | None = None, db: Session = Depends(get_db)):
    build = build_candidates_from_signals(db)
    result = run_selection(db, candidate_id)
    record_audit(db, "selection_run", "candidate", after={**build, **result})
    return {"ok": True, "candidates": build, "selection": result}


@router.get("/candidates")
def api_candidates(recommendation: str | None = None, min_score: float | None = None,
                   db: Session = Depends(get_db)):
    q = db.query(ProductCandidate)
    if recommendation:
        q = q.filter(ProductCandidate.recommendation == recommendation)
    if min_score is not None:
        q = q.filter(ProductCandidate.total_score >= min_score)
    rows = q.order_by(ProductCandidate.total_score.desc()).all()
    return {"total": len(rows), "items": [
        {"id": c.id, "normalized_title": c.normalized_title, "category": c.category,
         "image_url": c.image_url, "total_score": c.total_score, "confidence": c.confidence,
         "recommendation": c.recommendation, "approved": c.approved,
         "estimated_price_low": c.estimated_price_low, "estimated_price_high": c.estimated_price_high,
         "estimated_cost": c.estimated_cost, "estimated_weight_g": c.estimated_weight_g,
         "seasonal": c.seasonal} for c in rows]}


@router.get("/candidates/{candidate_id}")
def api_candidate_detail(candidate_id: int, db: Session = Depends(get_db)):
    c = _candidate_or_404(db, candidate_id)
    latest_check = (
        db.query(ComplianceCheck)
        .filter(ComplianceCheck.candidate_id == candidate_id)
        .order_by(ComplianceCheck.checked_at.desc())
        .first()
    )
    signals = (
        db.query(ProductSignal)
        .filter(ProductSignal.cluster_key.isnot(None))
        .all()
    )
    sigs = [s for s in signals if s.cluster_key.startswith(c.normalized_title[:40])]
    return {
        "id": c.id, "normalized_title": c.normalized_title, "category": c.category,
        "image_url": c.image_url, "estimated_cost": c.estimated_cost,
        "estimated_price_low": c.estimated_price_low, "estimated_price_high": c.estimated_price_high,
        "estimated_weight_g": c.estimated_weight_g, "estimated_margin": c.estimated_margin,
        "seasonal": c.seasonal,
        "demand_score": c.demand_score, "growth_score": c.growth_score,
        "competition_score": c.competition_score, "margin_score": c.margin_score,
        "logistics_score": c.logistics_score, "stability_score": c.stability_score,
        "total_score": c.total_score, "confidence": c.confidence,
        "recommendation": c.recommendation, "reasons": c.reasons, "risks": c.risks,
        "differentiation": c.differentiation, "score_detail": c.score_detail,
        "approved": c.approved,
        "data_sources": sorted({s.source for s in sigs}),
        "data_updated_at": max((s.captured_at for s in sigs), default=None),
        "competitor_count": max(0, len(sigs) - 1),
        "compliance": latest_check and {
            "status": latest_check.status, "market": latest_check.market,
            "matched_rules": latest_check.matched_rules,
            "missing_information": latest_check.missing_information,
            "explanation": latest_check.explanation, "checked_at": latest_check.checked_at,
        },
    }


@router.post("/candidates/{candidate_id}/compliance-check", response_model=ComplianceCheckOut)
def api_compliance_check(candidate_id: int, db: Session = Depends(get_db)):
    from ..services.compliance import check_compliance

    c = _candidate_or_404(db, candidate_id)
    market = (get_setting(db, "target_markets") or ["US"])[0]
    result = check_compliance(c, market)
    chk = ComplianceCheck(
        candidate_id=candidate_id, market=market, status=result["status"],
        matched_rules=result["matched_rules"], missing_information=result["missing_information"],
        explanation=result["explanation"],
    )
    db.add(chk)
    db.commit()
    record_audit(db, "compliance_check", "candidate", candidate_id, after=result)
    return chk


@router.post("/candidates/{candidate_id}/approve")
def api_candidate_approve(candidate_id: int, approver: str = "admin",
                          db: Session = Depends(get_db)):
    c = _candidate_or_404(db, candidate_id)
    latest = (
        db.query(ComplianceCheck)
        .filter_by(candidate_id=candidate_id)
        .order_by(ComplianceCheck.checked_at.desc())
        .first()
    )
    if not latest or latest.status == "REJECT":
        raise HTTPException(400, "合规结果为 REJECT 或尚未检查，禁止审批")
    if latest.status == "REVIEW":
        raise HTTPException(400, "合规结果为 REVIEW，需先人工确认资料后再审批")
    before = {"approved": c.approved}
    c.approved = True
    c.approved_by = approver
    db.commit()
    record_audit(db, "candidate_approve", "candidate", candidate_id,
                 actor=approver, before=before, after={"approved": True})
    return {"ok": True, "candidate_id": candidate_id, "approved": True}


# ---------- 客服 ----------

@router.get("/conversations")
def api_conversations(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(CustomerConversation)
    if status:
        q = q.filter(CustomerConversation.status == status)
    rows = q.order_by(CustomerConversation.created_at.desc()).limit(200).all()
    return {"total": len(rows), "items": [ConversationOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post("/conversations", response_model=ConversationOut)
def api_create_conversation(payload: ConversationCreateIn, db: Session = Depends(get_db)):
    conv = CustomerConversation(
        question=payload.question, platform=payload.platform,
        external_conversation_id=payload.external_conversation_id,
        buyer_language=payload.buyer_language or cs.detect_language(payload.question),
        intent=cs.detect_intent(payload.question),
        automation_level=get_setting(db, "automation_level") or "L1",
    )
    conv.risk_level = "high" if cs.is_high_risk(payload.question, conv.intent) else "low"
    db.add(conv)
    db.commit()
    record_audit(db, "conversation_create", "conversation", conv.id,
                 after={"question": payload.question[:200], "intent": conv.intent, "risk": conv.risk_level})
    return conv


@router.post("/conversations/{conversation_id}/generate-reply", response_model=ReplyDraftOut)
def api_generate_reply(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.get(CustomerConversation, conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    gen = cs.generate_reply(db, conv)
    action = cs.decide_action(db, conv, gen)
    draft = ReplyDraft(
        conversation_id=conv.id, generated_reply=gen["reply"],
        confidence=gen["confidence"], cited_sources=gen["cited_sources"],
        approval_status="auto_pending" if action == "auto_send" else "pending",
    )
    conv.status = "waiting_human" if action in ("waiting_human", "draft") else conv.status
    if action == "waiting_human":
        conv.risk_level = "high"
    db.add(draft)
    db.commit()
    record_audit(db, "reply_generate", "conversation", conv.id,
                 after={"confidence": gen["confidence"], "needs_human": gen["needs_human"],
                        "reason": gen["reason"], "action": action})
    return draft


@router.post("/replies/{reply_id}/approve", response_model=ReplyDraftOut)
def api_reply_approve(reply_id: int, payload: ReplyApproveIn, db: Session = Depends(get_db)):
    draft = db.get(ReplyDraft, reply_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    if draft.approval_status == "sent":
        raise HTTPException(400, "草稿已发送")
    before = {"approval_status": draft.approval_status, "final_reply": draft.final_reply}
    draft.approval_status = "approved"
    draft.final_reply = payload.final_reply or draft.generated_reply
    draft.edited = bool(payload.final_reply and payload.final_reply != draft.generated_reply)
    draft.approved_by = payload.approver
    conv = db.get(CustomerConversation, draft.conversation_id)
    if conv:
        conv.status = "approved"
    db.commit()
    record_audit(db, "reply_approve", "reply_draft", reply_id, actor=payload.approver,
                 before=before, after={"final_reply": draft.final_reply, "edited": draft.edited})
    return draft


@router.post("/replies/{reply_id}/send", response_model=ReplyDraftOut)
def api_reply_send(reply_id: int, db: Session = Depends(get_db)):
    draft = db.get(ReplyDraft, reply_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    if draft.approval_status != "approved":
        raise HTTPException(400, "回复必须先经人工审批（当前默认 L1）")
    conv = db.get(CustomerConversation, draft.conversation_id)
    adapter = get_adapter()
    if conv and conv.external_conversation_id:
        ok, data, err = adapter.send_message(conv.external_conversation_id, draft.final_reply or draft.generated_reply)
        if not ok:
            raise HTTPException(502, f"发送失败（接入方式: {adapter.name}）：{err}。请使用人工复制回复模式。")
    else:
        # Mock / 无外部会话：仅标记，界面提示人工复制
        record_audit(db, "reply_send_manual", "reply_draft", reply_id,
                     after={"note": "mock/无外部会话，请在 TEMU 卖家后台人工粘贴回复"})
    draft.approval_status = "sent"
    draft.sent_at = utcnow()
    if conv:
        conv.status = "closed"
    db.commit()
    record_audit(db, "reply_send", "reply_draft", reply_id,
                 after={"sent_at": str(draft.sent_at), "channel": adapter.name})
    return draft


# ---------- 知识库 ----------

@router.get("/knowledge")
def api_knowledge(db: Session = Depends(get_db)):
    rows = db.query(KnowledgeDocument).order_by(KnowledgeDocument.id.desc()).all()
    return {"total": len(rows), "items": [KnowledgeOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.post("/knowledge", response_model=KnowledgeOut)
def api_knowledge_create(payload: KnowledgeIn, db: Session = Depends(get_db)):
    doc = KnowledgeDocument(**payload.model_dump(), source="manual")
    db.add(doc)
    db.commit()
    record_audit(db, "knowledge_create", "knowledge", doc.id, after={"title": doc.title})
    return doc


# ---------- 审计 / 设置 / TEMU 接入 ----------

@router.get("/audit-events")
def api_audit(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500)).all()
    return {"total": len(rows), "items": [AuditEventOut.model_validate(r).model_dump(mode="json") for r in rows]}


@router.get("/settings")
def api_get_settings(db: Session = Depends(get_db)):
    return {
        "score_weights": get_setting(db, "score_weights"),
        "target_markets": get_setting(db, "target_markets"),
        "automation_level": get_setting(db, "automation_level"),
        "auto_reply_enabled": get_setting(db, "auto_reply_enabled"),
        "category_defaults": get_setting(db, "category_defaults"),
    }


@router.post("/settings")
def api_update_settings(payload: SettingsUpdateIn, db: Session = Depends(get_db)):
    updated = {}
    for key in ("score_weights", "target_markets", "automation_level", "auto_reply_enabled", "category_defaults"):
        val = getattr(payload, key)
        if val is not None:
            old = get_setting(db, key)
            if key == "score_weights":
                total = sum(val.values())
                if abs(total - 1.0) > 0.001:
                    raise HTTPException(400, f"评分权重之和必须为1，当前 {total}")
            set_setting(db, key, val)
            record_audit(db, "settings_update", "setting", key, before={"value": old}, after={"value": val})
            updated[key] = val
    return {"ok": True, "updated": updated}


@router.get("/settings/integrations")
def api_integrations(db: Session = Depends(get_db)):
    adapter = get_adapter()
    return {
        "temu": {
            "adapter": settings.TEMU_ADAPTER,
            "capabilities": adapter.capabilities(),
            "note": "当前未接入 TEMU 官方 Open API（未配置 app key）。"
                    "商品数据通过演示数据/CSV 导入提供；买家消息通过人工复制回复模式处理。",
        }
    }


@router.post("/settings/integrations/temu")
def api_integrations_temu(payload: TemuIntegrationIn, db: Session = Depends(get_db)):
    from ..adapters.temu import MockTemuAdapter, OfficialTemuAdapter

    if payload.adapter == "official":
        if not (payload.app_key and payload.app_secret):
            raise HTTPException(400, "接入 official 模式需要 app_key 和 app_secret")
        adapter = OfficialTemuAdapter(payload.app_key, payload.app_secret)
        ok, data, err = adapter.authorize()
        if not ok:
            raise HTTPException(502, f"TEMU 官方授权失败：{err}。请确认已在 TEMU Partner Platform 申请开放能力。")
        caps = adapter.capabilities()
    else:
        adapter = MockTemuAdapter() if payload.adapter == "mock" else None
        caps = adapter.capabilities() if adapter else {
            "mode": f"{payload.adapter.upper()}（人工模式）",
            "note": "通过 CSV 导入 / 人工复制回复运行。",
        }
    # 密钥加密保存：MVP 用对称加密（SECRET_KEY 派生），日志不输出
    enc = _encrypt_config({
        "app_key": payload.app_key or "", "app_secret": payload.app_secret or "",
        "authorization_code": payload.authorization_code or "",
    })
    record_audit(db, "temu_integration_update", "integration", "temu",
                 after={"adapter": payload.adapter, "config": "（已加密，不记录）"})
    return {"ok": True, "adapter": payload.adapter, "capabilities": caps, "config_stored": enc is not None}


def _encrypt_config(data: dict) -> bool:
    """第一阶段简化：SECRET_KEY 异或混淆保存占位；生产应使用 KMS/fernet。日志与接口不回显明文。"""
    try:
        import base64
        from ..config import settings

        raw = json.dumps(data).encode()
        key = (settings.SECRET_KEY * 32).encode()[: len(raw)]
        base64.b64encode(bytes(a ^ b for a, b in zip(raw, key)))
        return True
    except Exception:
        return False


@router.get("/dashboard")
def api_dashboard(db: Session = Depends(get_db)):
    from sqlalchemy import func

    def count(model):
        return db.query(func.count(model.id)).scalar() or 0

    top = (
        db.query(ProductCandidate)
        .filter(ProductCandidate.recommendation.in_(("TOP", "CONSIDER")))
        .order_by(ProductCandidate.total_score.desc())
        .limit(5)
        .all()
    )
    convs = db.query(CustomerConversation).order_by(CustomerConversation.created_at.desc()).limit(5).all()
    return {
        "signals": count(ProductSignal),
        "candidates": count(ProductCandidate),
        "top_candidates": [
            {"id": c.id, "title": c.normalized_title, "score": c.total_score,
             "recommendation": c.recommendation, "confidence": c.confidence} for c in top],
        "conversations": count(CustomerConversation),
        "recent_conversations": [
            {"id": c.id, "question": c.question[:80], "intent": c.intent,
             "risk_level": c.risk_level, "status": c.status} for c in convs],
        "automation_level": get_setting(db, "automation_level"),
        "target_markets": get_setting(db, "target_markets"),
    }
