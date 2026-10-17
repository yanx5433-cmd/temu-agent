"""合规 Agent 测试：硬性禁售规则必须正确拦截。"""
from app.models import ProductCandidate
from app.services.compliance import check_compliance


def make_candidate(title, category="default", raw=None, cost=1.0, weight=100):
    return ProductCandidate(
        normalized_title=title, category=category,
        estimated_cost=cost, estimated_weight_g=weight,
        raw_data=raw or {"size": "10cm", "material": "PP塑料"},
    )


def test_child_product_rejected():
    r = check_compliance(make_candidate("儿童卡通拼图玩具"), "US")
    assert r["status"] == "REJECT"
    ids = {m["rule_id"] for m in r["matched_rules"]}
    assert "child_product" in ids and "toy" in ids


def test_battery_product_rejected():
    r = check_compliance(make_candidate("USB充电迷你台灯"), "US")
    assert r["status"] == "REJECT"


def test_liquid_rejected():
    r = check_compliance(make_candidate("玻璃喷雾瓶清洁剂套装"), "US")
    assert r["status"] == "REJECT"


def test_ip_infringement_rejected():
    r = check_compliance(make_candidate("漫威联名卡通徽章套装"), "US")
    assert r["status"] == "REJECT"
    assert any(m["rule_id"] == "ip_infringement" for m in r["matched_rules"])


def test_normal_product_pass():
    r = check_compliance(make_candidate("成人鲨鱼夹粗发抓夹", "hair_accessories"), "US")
    assert r["status"] == "PASS"
    assert "未发现特定品类的复杂准入要求" in r["explanation"]
    assert "不代表免认证" in r["explanation"]


def test_missing_material_review():
    r = check_compliance(make_candidate("桌面收纳盒", raw={"size": "20cm"}), "US")
    assert r["status"] == "REVIEW"
    assert any(m["rule_id"] == "missing_material" for m in r["missing_information"])


def test_missing_weight_review():
    r = check_compliance(make_candidate("桌面收纳盒", weight=None), "US")
    assert r["status"] == "REVIEW"
    assert any(m["rule_id"] == "missing_weight" for m in r["missing_information"])


def test_knife_rejected():
    r = check_compliance(make_candidate("不锈钢美工刀"), "US")
    assert r["status"] == "REJECT"
