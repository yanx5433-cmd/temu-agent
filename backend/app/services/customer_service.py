"""客服 Agent：确定性工作流。

收到问题 → 识别语言 → 识别意图 → 查询知识与订单 → 生成回复 → 风险检查 → 分级处理 → 日志。

自动化等级：
L0 仅草稿；L1 人工确认后发送；L2 低风险FAQ经审核后可自动发送；L3 高风险问题永不自动。
"""
from sqlalchemy.orm import Session

from ..appsettings import get_setting, record_audit
from ..models import KnowledgeDocument, utcnow
from .llm import get_llm

# 必须转人工的意图（高风险）
HIGH_RISK_INTENTS = {
    "refund_compensation": "退款和赔偿承诺",
    "complaint_escalation": "客诉升级",
    "safety": "人身安全问题",
    "legal": "法律问题",
    "address_change": "地址修改",
}
RISKY_KEYWORDS = ["退款", "赔偿", "退货", "投诉", "律师", "起诉", "受伤", "着火",
                  "refund", "compensation", "lawsuit", "injur", "fire", "sue"]

INTENTS = ["size", "color", "packaging", "shipping_time", "usage", "work_hours",
           "order_status", "refund_compensation", "complaint_escalation", "safety",
           "legal", "address_change", "human_request", "unknown"]

INTENT_LABELS_ZH = {
    "size": "商品尺寸", "color": "商品颜色", "packaging": "包装数量",
    "shipping_time": "发货时效", "usage": "使用方法", "work_hours": "工作时间",
    "order_status": "订单/物流状态", "refund_compensation": "退款赔偿",
    "complaint_escalation": "客诉升级", "safety": "人身安全", "legal": "法律问题",
    "address_change": "地址修改", "human_request": "要求人工客服", "unknown": "未识别",
}


def detect_language(text: str) -> str:
    """轻量语言识别：CJK→zh，含西语特征词→es，否则 en。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk > len(text) * 0.1:
        return "zh"
    low = text.lower()
    if any(w in low for w in [" hola", "gracias", "dónde", "cuándo", "pedido", "envío", " ¿"]):
        return "es"
    return "en"


def detect_intent(text: str) -> str:
    llm = get_llm()
    return llm.classify(text.lower(), INTENTS)


def is_high_risk(text: str, intent: str) -> bool:
    low = text.lower()
    if intent in HIGH_RISK_INTENTS or intent == "human_request":
        return True
    return any(k in low for k in RISKY_KEYWORDS)


def lookup_knowledge(db: Session, question: str, intent: str, language: str) -> tuple[str | None, list]:
    """关键词检索知识库（第一阶段用关键词匹配；第二阶段升级 pgvector 语义检索）。"""
    docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.type.in_(["faq", "policy", "shipping", "product"]))
        .all()
    )
    now = utcnow()
    q_low = question.lower()
    scored: list[tuple[int, KnowledgeDocument]] = []
    for d in docs:
        if d.expires_at and d.expires_at < now:
            continue
        if d.effective_at and d.effective_at > now:
            continue
        score = sum(1 for kw in (d.keywords or []) if kw.lower() in q_low)
        if score:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return None, []
    best = scored[0][1]
    cited = [{"type": "knowledge", "id": best.id, "title": best.title}]
    return best.content.strip(), cited


def lookup_order(db: Session, question: str) -> tuple[dict | None, list]:
    """已知订单查询：仅当问题中出现已导入订单号时返回（不得编造订单状态）。"""
    import re

    m = re.search(r"\b(?:PO|SO|ORD|order)?[-\s]?(\d{8,12})\b", question, flags=re.IGNORECASE)
    if not m:
        return None, []
    order_id = m.group(1)
    order = ORDERS.get(order_id)
    if not order:
        return None, []
    return order, [{"type": "order", "id": order_id, "fields": ["status", "logistics_status"]}]


# 演示订单数据（第三阶段由 TEMU API 同步替换）
ORDERS = {
    "20240901123": {"status": "shipped", "logistics_status": "运输中，预计3-5天送达", "item": "发饰套装"},
    "20240901456": {"status": "delivered", "logistics_status": "已签收", "item": "收纳盒"},
}

REPLY_TEMPLATES = {
    "zh": {
        "opening": "您好，感谢您的咨询！",
        "closing": "如有其他问题欢迎随时联系我们，祝您购物愉快！",
        "work_hours": "我们的客服工作时间为周一至周五 9:00-18:00（北京时间）。",
        "no_answer": "您的问题需要进一步确认，我们会在核实后尽快回复您。",
    },
    "en": {
        "opening": "Hello, thank you for reaching out!",
        "closing": "Feel free to contact us if you have any other questions. Happy shopping!",
        "work_hours": "Our customer service hours are Monday-Friday 9:00-18:00 (GMT+8).",
        "no_answer": "We need to double-check your question and will get back to you shortly.",
    },
    "es": {
        "opening": "Hola, ¡gracias por su consulta!",
        "closing": "No dude en contactarnos si tiene más preguntas. ¡Feliz compra!",
        "work_hours": "Nuestro horario de atención es de lunes a viernes 9:00-18:00 (GMT+8).",
        "no_answer": "Necesitamos verificar su pregunta y le responderemos pronto.",
    },
}


def generate_reply(db: Session, conversation) -> dict:
    """生成回复草稿。返回 {reply, confidence, cited_sources, needs_human, reason}。

    规则：
    - 不编造订单/物流信息，只有查到真实记录才引用；
    - 高风险意图一律转人工（L3 语义）；
    - 知识库无答案或置信度低 → 转人工。
    """
    question = conversation.question or ""
    intent = conversation.intent
    language = conversation.buyer_language
    cited: list = []
    body = None
    confidence = 0.0

    t = REPLY_TEMPLATES.get(language, REPLY_TEMPLATES["en"])

    if intent == "work_hours":
        body, confidence, cited = t["work_hours"], 0.9, [{"type": "knowledge", "title": "固定FAQ：工作时间"}]
    elif intent == "order_status":
        order, oc = lookup_order(db, question)
        if order:
            oid = oc[0]["id"]
            order_text = {
                "zh": f"您的订单（{oid}）当前状态：{order['status']}，{order['logistics_status']}。",
                "en": f"Your order ({oid}) current status: {order['status']}. {order['logistics_status']}",
                "es": f"Su pedido ({oid}) estado actual: {order['status']}. {order['logistics_status']}",
            }.get(language, f"Your order ({oid}) current status: {order['status']}. {order['logistics_status']}")
            body = f"{t['opening']}{order_text}{t['closing']}"
            confidence, cited = 0.85, oc
        else:
            confidence = 0.0
    elif intent in ("size", "color", "packaging", "usage", "shipping_time"):
        ans, kc = lookup_knowledge(db, question, intent, language)
        if ans:
            body = f"{t['opening']}{ans}{t['closing']}"
            confidence, cited = 0.8, kc
        else:
            confidence = 0.0
    else:
        ans, kc = lookup_knowledge(db, question, intent, language)
        if ans:
            body, confidence, cited = f"{t['opening']}{ans}{t['closing']}", 0.7, kc

    needs_human = False
    reason = ""
    if is_high_risk(question, intent):
        needs_human = True
        reason = HIGH_RISK_INTENTS.get(intent, "包含高风险关键词") if intent in HIGH_RISK_INTENTS else "包含高风险关键词"
    elif body is None or confidence < 0.6:
        needs_human = True
        reason = "知识库中没有答案或置信度低"

    if needs_human:
        body = body or t["no_answer"]
        status_action = "transfer_human"
    else:
        status_action = "ready"

    llm = get_llm()
    final_text = llm.polish_reply(body, language)

    return {
        "reply": final_text,
        "confidence": round(confidence, 2),
        "cited_sources": cited,
        "needs_human": needs_human,
        "reason": reason,
        "action": status_action,
    }


def decide_action(db: Session, conversation, gen: dict) -> str:
    """按自动化等级与风险决定处理动作：draft / waiting_human / auto_send。"""
    level = conversation.automation_level or get_setting(db, "automation_level") or "L1"
    auto_enabled = bool(get_setting(db, "auto_reply_enabled"))
    if gen["needs_human"]:
        return "waiting_human"  # L3：高风险永不自动
    if level == "L2" and auto_enabled and gen["confidence"] >= 0.8 and gen["action"] == "ready":
        return "auto_send"
    return "draft" if level in ("L0", "L1") else "draft"
