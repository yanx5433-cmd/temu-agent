"""客服 Agent 测试：意图识别、高风险转人工、置信度与引用来源。"""
from app.models import CustomerConversation, KnowledgeDocument
from app.services.customer_service import (
    detect_intent,
    detect_language,
    generate_reply,
    is_high_risk,
)


def test_language_detection():
    assert detect_language("请问这个发夹什么颜色") == "zh"
    assert detect_language("What is the size of this clip?") == "en"
    assert detect_language("Hola, ¿cuándo llegará mi pedido?") == "es"


def test_intent_detection():
    assert detect_intent("这个收纳盒的尺寸是多少") == "size"
    assert detect_intent("When will my order arrive?") == "shipping_time"
    assert detect_intent("我要退款") == "refund_compensation"


def test_high_risk_intents_transfer():
    assert is_high_risk("请给我退款赔偿", "refund_compensation")
    assert is_high_risk("我要投诉你们", "complaint_escalation")
    assert is_high_risk("帮我转人工客服", "human_request")
    assert not is_high_risk("这个多少钱呀", "unknown")


def test_order_status_uses_real_data_only(db):
    conv = CustomerConversation(question="我的订单 20240901123 到哪了", buyer_language="zh",
                                intent="order_status")
    gen = generate_reply(db, conv)
    assert "20240901123" in gen["reply"]
    assert "shipped" in gen["reply"] or "运输中" in gen["reply"]
    assert gen["cited_sources"][0]["type"] == "order"
    assert gen["confidence"] >= 0.8
    assert not gen["needs_human"]


def test_unknown_order_transfers_to_human(db):
    conv = CustomerConversation(question="我的订单 99999999999 到哪了", buyer_language="zh",
                                intent="order_status")
    gen = generate_reply(db, conv)
    assert gen["needs_human"]  # 无法确认的物流状态必须转人工


def test_faq_answer_with_citation(db):
    db.add(KnowledgeDocument(type="faq", title="工作时间FAQ",
                             content="客服工作时间为周一至周五 9:00-18:00。",
                             keywords=["工作时间"]))
    db.commit()
    conv = CustomerConversation(question="请问你们的客服工作时间是几点", buyer_language="zh",
                                intent="work_hours")
    gen = generate_reply(db, conv)
    assert not gen["needs_human"]
    assert "9:00-18:00" in gen["reply"]


def test_no_answer_transfers_to_human(db):
    conv = CustomerConversation(question="这个能不能帮我染色定制", buyer_language="zh",
                                intent="unknown")
    gen = generate_reply(db, conv)
    assert gen["needs_human"]


def test_refund_never_auto(db):
    conv = CustomerConversation(question="商品坏了，要求退款赔偿", buyer_language="zh",
                                intent="refund_compensation")
    gen = generate_reply(db, conv)
    assert gen["needs_human"]
    assert "退款" in gen["reason"] or "高风险" in gen["reason"]
