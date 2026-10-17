"""API 集成测试：CSV 导入→选品→合规→审批→客服全链路 + 审计。"""
import io

DEMO_CSV = """external_id,title,category,price,sales_30d,growth_7d,review_count,weight_g,cost,size,material
C1,成人珍珠发夹套装,hair_accessories,4.2,12000,0.32,980,35,0.7,6cm,合金/树脂珍珠
C2,儿童卡通拼图玩具,diy_party,7.9,9000,0.20,500,300,2.0,20cm,纸板
C3,桌面收纳盒三件套,home_storage,8.9,6800,0.12,560,420,2.6,30x15x10cm,
"""


def test_full_selection_flow(client):
    # 1. CSV 导入
    r = client.post("/api/imports/csv", files={"file": ("demo.csv", io.BytesIO(DEMO_CSV.encode()), "text/csv")})
    assert r.status_code == 200
    assert r.json()["inserted"] == 3

    # 2. 运行选品
    r = client.post("/api/selection/run")
    assert r.status_code == 200
    sel = r.json()["selection"]
    assert sel["evaluated"] == 3
    assert sel["reject"] == 1  # 儿童玩具被硬性拦截

    # 3. 候选列表
    cands = client.get("/api/candidates").json()["items"]
    toy = next(c for c in cands if "拼图" in c["normalized_title"])
    assert toy["recommendation"] == "REJECT"
    clip = next(c for c in cands if "发夹" in c["normalized_title"])
    assert clip["recommendation"] in ("TOP", "CONSIDER", "PENDING")

    # 4. 详情可追溯
    detail = client.get(f"/api/candidates/{clip['id']}").json()
    assert detail["score_detail"]["scoring"]["demand"]["detail"]
    assert detail["compliance"]["status"] == "PASS"
    assert detail["reasons"]

    # 5. REJECT 商品禁止审批
    r = client.post(f"/api/candidates/{toy['id']}/approve")
    assert r.status_code == 400

    # 6. PASS 商品可审批
    r = client.post(f"/api/candidates/{clip['id']}/approve?approver=admin")
    assert r.status_code == 200

    # 7. 审计日志覆盖导入/选品/审批
    events = client.get("/api/audit-events").json()["items"]
    actions = {e["action"] for e in events}
    assert {"import_csv", "selection_run", "candidate_approve"} <= actions


def test_compliance_review_blocks_approval(client):
    csv_data = DEMO_CSV.replace(
        "C3,桌面收纳盒三件套,home_storage,8.9,6800,0.12,560,420,2.6,30x15x10cm,",
        "C3,桌面收纳盒三件套,home_storage,8.9,6800,0.12,560,420,2.6,30x15x10cm,")
    client.post("/api/imports/csv", files={"file": ("d.csv", io.BytesIO(csv_data.encode()), "text/csv")})
    client.post("/api/selection/run")
    cands = client.get("/api/candidates").json()["items"]
    box = next(c for c in cands if "收纳盒" in c["normalized_title"])
    detail = client.get(f"/api/candidates/{box['id']}").json()
    assert detail["compliance"]["status"] == "REVIEW"  # 缺 material
    r = client.post(f"/api/candidates/{box['id']}/approve")
    assert r.status_code == 400


def test_conversation_flow(client):
    # 高风险 → 转人工
    r = client.post("/api/conversations", json={"question": "我要退款赔偿，不然投诉"})
    assert r.status_code == 200
    conv = r.json()
    assert conv["risk_level"] == "high"
    draft = client.post(f"/api/conversations/{conv['id']}/generate-reply").json()
    assert draft["confidence"] >= 0
    assert draft["approval_status"] == "pending"

    # 未审批不能发送
    r = client.post(f"/api/replies/{draft['id']}/send")
    assert r.status_code == 400

    # 人工批准后可发送（mock 模式记录人工发送审计）
    r = client.post(f"/api/replies/{draft['id']}/approve",
                    json={"final_reply": "您好，退款请联系平台客服处理。", "approver": "op1"})
    assert r.status_code == 200
    r = client.post(f"/api/replies/{draft['id']}/send")
    assert r.status_code == 200
    assert r.json()["approval_status"] == "sent"


def test_settings_validation(client):
    r = client.post("/api/settings", json={"score_weights": {"demand": 0.9}})
    assert r.status_code == 400  # 权重和不为1
    r = client.post("/api/settings", json={"automation_level": "L2"})
    assert r.status_code == 200


def test_temu_integration_status(client):
    r = client.get("/api/settings/integrations")
    assert r.status_code == 200
    temu = r.json()["temu"]
    assert "未接入 TEMU 官方 Open API" in temu["note"]
