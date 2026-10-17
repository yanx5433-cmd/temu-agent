"""合规 Agent：选品前置门槛（硬性淘汰规则），纯程序规则，不经过大模型。

注意：合规结果 PASS 仅表示“未发现特定品类的复杂准入要求”，
最终是否可在目标市场销售仍需人工确认平台与当地法规。
"""
import re

# 硬性淘汰规则：命中即 REJECT
REJECT_RULES = [
    {"id": "child_product", "name": "儿童/婴童用品", "patterns": [r"儿童", r"婴[儿童]", r"宝宝", r"kids?\b", r"baby\b", r"toddler", r"儿童玩具"]},
    {"id": "toy", "name": "玩具", "patterns": [r"玩具", r"\btoy\b", r"\blego\b", r"玩偶", r"毛绒", r"手办"]},
    {"id": "food_supplement", "name": "食品/保健品", "patterns": [r"食品", r"保健品", r"\bvitamin", r"胶囊", r"口服", r"蛋白粉", r"\bfood\b", r"零食"]},
    {"id": "cosmetics", "name": "化妆品", "patterns": [r"化妆品", r"美妆", r"口红", r"粉底", r"面[霜膜]", r"精华", r"\bcosmetic", r"染发", r"指甲油"]},
    {"id": "medical_claim", "name": "医疗/矫正/保健功效", "patterns": [r"医疗", r"矫正", r"治疗", r"减肥", r"瘦身", r"降压", r"矫正带", r"保健器械", r"医用"]},
    {"id": "battery_electric", "name": "带电池/插电/无线产品", "patterns": [r"电池", r"充电", r"\busb\b", r"插电", r"电动", r"无线充电", r"蓝牙", r"锂电", r"\bled\s*灯", r"带灯"]},
    {"id": "liquid_powder_spray", "name": "液体/粉末/喷雾", "patterns": [r"液体", r"喷雾", r"粉末", r"清洁剂", r"洗衣液", r"香水", r"精油", r"胶水", r"油漆"]},
    {"id": "knife", "name": "刀具", "patterns": [r"刀[具刃片]", r"\bknife\b", r"剪刀", r"美工刀", r"菜刀"]},
    {"id": "safety_gear", "name": "安全防护用品", "patterns": [r"安全[帽带扣]", r"头盔", r"防护[罩衣镜]", r"救生", r"灭火"]},
    {"id": "load_bearing", "name": "承重/安全关键部件", "patterns": [r"承重", r"吊[钩索]", r"攀爬", r"支架承重", r"汽车配件"]},
    {"id": "food_contact", "name": "直接接触食品", "patterns": [r"餐具", r"厨具", r"食品级", r"水杯", r"保温杯", r"奶瓶", r"烘焙模具", r"砧板"]},
    {"id": "pet_risk", "name": "宠物食品/高风险宠物用品", "patterns": [r"宠物[食粮零]", r"狗粮", r"猫粮", r"宠物玩具", r"宠物用品"]},
    {"id": "ip_infringement", "name": "疑似侵权元素", "patterns": [r"迪士尼", r"漫威", r"hello\s*kitty", r"宝可梦", r"皮卡丘", r"\bnfl\b", r"\bnba\b", r"动漫", r"卡通联名", r"影视同款", r"变形金刚"]},
]

# 资料不足规则：命中即 REVIEW（资料缺失不会直接 REJECT 缺材料类，由下方缺失检查处理）
MISSING_INFO_CHECKS = [
    {"id": "missing_weight", "name": "缺少重量", "field": "weight_g"},
    {"id": "missing_size", "name": "缺少尺寸", "field": "size"},
    {"id": "missing_material", "name": "无法说明主要材料", "field": "material"},
    {"id": "missing_supplier_cost", "name": "缺少供应/采购信息", "field": "cost"},
]


def _text_of(candidate) -> str:
    raw = getattr(candidate, "raw_data", None) or {}
    parts = [candidate.normalized_title, candidate.category, str(raw.get("material", "")), str(raw.get("description", ""))]
    return " ".join(p for p in parts if p).lower()


def check_compliance(candidate, market: str) -> dict:
    """返回合规结果 dict：status / matched_rules / missing_information / explanation。

    candidate 需要 normalized_title/category/estimated_weight_g/raw_data/estimated_cost。
    """
    text = _text_of(candidate)
    matched = []
    for rule in REJECT_RULES:
        for pat in rule["patterns"]:
            if re.search(pat, text, flags=re.IGNORECASE):
                matched.append({"rule_id": rule["id"], "rule_name": rule["name"], "hit_pattern": pat})
                break

    raw = getattr(candidate, "raw_data", None) or {}
    missing = []
    for chk in MISSING_INFO_CHECKS:
        val = raw.get(chk["field"])
        if chk["field"] == "weight_g":
            val = val if val is not None else candidate.estimated_weight_g
        if chk["field"] == "cost":
            val = val if val not in (None, "", 0) else candidate.estimated_cost
        if val in (None, "", 0):
            missing.append({"rule_id": chk["id"], "name": chk["name"]})

    if matched:
        status = "REJECT"
        explanation = (
            f"命中 {len(matched)} 条硬性禁售规则："
            + "、".join(m["rule_name"] for m in matched)
            + "。该商品被禁止推荐，与目标市场无关。"
        )
    elif missing:
        status = "REVIEW"
        explanation = (
            "未发现命中硬性禁售规则，但资料不足需人工确认："
            + "、".join(m["name"] for m in missing)
            + f"。目标市场 {market}：以上仅为规则筛查，未发现特定品类的复杂准入要求不代表免认证，"
            "最终以 TEMU 平台规则与目标市场法规人工确认为准。"
        )
    else:
        status = "PASS"
        explanation = (
            f"未命中硬性禁售规则，主要信息完整。目标市场 {market}：表示“未发现特定品类的复杂准入要求”，"
            "不代表免认证，上架前仍需人工确认 TEMU 平台规则与当地法规。"
        )

    return {
        "status": status,
        "matched_rules": matched,
        "missing_information": missing,
        "explanation": explanation,
    }
