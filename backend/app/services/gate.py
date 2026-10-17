"""第 0 关：硬门槛（评分之前先淘汰）。

为什么要有这一关：打分是"多好"的问题，门槛是"能不能做"的问题。
一个 20 公斤、负毛利、或者需要强制认证却拿不出证书的商品，
热度再高也不该出现在推荐列表里——把它混进加权求和，等于让高分买通门槛。

阈值一律从 app_settings["gate_limits"] 读，且每一项都带 status 字段：
    confirmed  = 已从平台规则核实（本项目目前没有一项是这个状态）
    to_verify  = 合理估计值，**上线前必须核对平台现行规则**
    structural = 逻辑推导出的约束，不依赖平台数值（如负毛利）

绝不假装知道平台的真实数字，是这个模块的底线。
"""
from __future__ import annotations

# 默认门槛。status 全部是 to_verify / structural，没有一项是 confirmed。
DEFAULT_LIMITS: dict[str, dict] = {
    "max_weight_g": {
        "value": 4500, "status": "to_verify",
        "basis": "超重件通常走不了平台小包物流；具体上限随渠道/市场变化，必须查平台现行规定",
    },
    "max_size_sum_cm": {
        "value": 90, "status": "to_verify",
        "basis": "长+宽+高 的常见小包限制量级，需按目标仓与渠道核实",
    },
    "supply_price_ratio": {
        "value": 0.45, "status": "to_verify",
        "basis": "全托管由平台定零售价、卖家拿供货价。供货价 ÷ 同款最低零售价 高于此值，"
                 "核价环节大概率被要求降价；该比例是经验量级，不是平台公布值",
    },
    "min_margin_rate": {
        "value": 0.10, "status": "structural",
        "basis": "低于此毛利率时，运费+退货+罚款损耗足以吞掉利润；属于逻辑下限而非平台规则",
    },
    "closed_categories": {
        "value": [], "status": "to_verify",
        "basis": "不开放全托管的类目清单需从卖家后台实时读取，此处留空表示未核实",
    },
    "cert_required_categories": {
        "value": ["children_product", "food_contact", "battery", "medical"],
        "status": "to_verify",
        "basis": "这些类目普遍要求强制认证（如 CPC/FDA/UN38.3），但具体清单与证书类型须核对",
    },
}

_LEVEL_ORDER = {"OK": 0, "REVIEW": 1, "ELIMINATE": 2}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse_size(size) -> float | None:
    """把 "20x15x3cm" / "20*15*3" 这类字符串解析成三边和。解析不出返回 None。"""
    if not size or not isinstance(size, str):
        return None
    import re

    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", size)]
    if len(nums) < 3:
        return None
    return sum(sorted(nums, reverse=True)[:3])


def evaluate_gate(candidate, limits: dict | None = None) -> dict:
    """返回 {"level": OK|REVIEW|ELIMINATE, "blockers": [...], "warnings": [...], "limits_used": [...]}

    blockers  = 命中即淘汰（第 0 关不放行）
    warnings  = 不淘汰但要人工确认（含 to_verify 阈值的固有不确定性）
    limits_used = 本次实际用到的阈值及其 status，供前端标"此判定基于待核实阈值"
    """
    cfg = {k: dict(v) for k, v in DEFAULT_LIMITS.items()}
    for k, v in (limits or {}).items():
        if k in cfg and v is not None:
            cfg[k]["value"] = v if not isinstance(v, dict) else v.get("value", cfg[k]["value"])

    raw = getattr(candidate, "raw_data", None) or {}
    blockers: list[dict] = []
    warnings: list[dict] = []
    used: list[dict] = []

    def note(key: str) -> None:
        used.append({"key": key, "value": cfg[key]["value"], "status": cfg[key]["status"],
                     "basis": cfg[key]["basis"]})

    # ---- 1. 重量超限 ----
    w = _num(getattr(candidate, "estimated_weight_g", None))
    note("max_weight_g")
    if w is None:
        warnings.append({"id": "weight_unknown", "name": "重量未知", "kind": "data_gap",
                         "advice": "没有重量就无法判断能否走平台物流，也无法算运费，先补数据"})
    elif w > cfg["max_weight_g"]["value"]:
        blockers.append({"id": "weight_over", "name": "超重",
                         "detail": f"{w:g}g > 上限 {cfg['max_weight_g']['value']:g}g",
                         "advice": "改小规格/拆分销售单元，或改走海外仓大件渠道"})

    # ---- 2. 尺寸超限 ----
    size_sum = _parse_size(raw.get("size"))
    note("max_size_sum_cm")
    if size_sum is not None and size_sum > cfg["max_size_sum_cm"]["value"]:
        blockers.append({"id": "size_over", "name": "超尺寸",
                         "detail": f"三边和 {size_sum:g}cm > 上限 {cfg['max_size_sum_cm']['value']:g}cm",
                         "advice": "压缩包装或改折叠结构"})

    # ---- 3. 负毛利 / 毛利过薄（结构性，不依赖平台数值） ----
    price_high = _num(getattr(candidate, "estimated_price_high", None))
    cost = _num(getattr(candidate, "estimated_cost", None))
    supply_ratio = 0.75  # 与 scoring 里同一系数，改动要同步
    note("min_margin_rate")
    if price_high and cost is not None:
        margin = (price_high * supply_ratio - cost) / price_high
        if margin <= 0:
            blockers.append({"id": "negative_margin", "name": "负毛利",
                             "detail": f"按供货系数 {supply_ratio} 估算毛利率 {margin:.0%}，卖一件亏一件",
                             "advice": "压成本或放弃该品"})
        elif margin < cfg["min_margin_rate"]["value"]:
            warnings.append({"id": "thin_margin", "name": "毛利过薄", "kind": "risk",
                             "detail": f"毛利率 {margin:.0%} < {cfg['min_margin_rate']['value']:.0%}",
                             "advice": "运费与退货损耗波动即可吞掉利润，慎入"})

    # ---- 4. 供货价相对同款最低价过高（核价大概率被驳回） ----
    note("supply_price_ratio")
    lowest = _num(raw.get("similar_lowest_price"))
    if lowest and cost is not None and lowest > 0:
        ratio = cost / lowest
        if ratio > cfg["supply_price_ratio"]["value"]:
            blockers.append({"id": "price_uncompetitive", "name": "价格无空间",
                             "detail": f"供货成本 ÷ 同款最低售价 = {ratio:.0%} > "
                                       f"{cfg['supply_price_ratio']['value']:.0%}，核价环节大概率被要求降价",
                             "advice": "找更低货源，或换差异化款；硬上会在核价时被卡"})
    else:
        # 这是**数据缺口**不是商品风险：没有比价基准，这条门槛根本没参与判定。
        # 把它标成 data_gap 而不是 risk，否则缺字段的商品会被集体推到 REVIEW，
        # 而"全部待人工确认"和"没有门槛"是一样的——都是让判定失效。
        warnings.append({"id": "no_competitor_price", "name": "缺同款最低价，本项未评估", "kind": "data_gap",
                         "advice": "补上 similar_lowest_price 字段后核价门槛才会生效；"
                                   "当前演示数据没有这一列，所以这条门槛在演示集上一次都没触发过"})

    # ---- 5. 类目不开放 ----
    note("closed_categories")
    if candidate.category in (cfg["closed_categories"]["value"] or []):
        blockers.append({"id": "category_closed", "name": "类目不开放全托管",
                         "detail": f"类目 {candidate.category} 在不开放清单内",
                         "advice": "确认清单是否最新；该清单应来自卖家后台而非硬编码"})

    # ---- 6. 需要强制认证但没有资质记录 ----
    note("cert_required_categories")
    certs = raw.get("certifications") or []
    hit_cert_cats = [c for c in (cfg["cert_required_categories"]["value"] or [])
                     if c in (candidate.category or "")]
    if hit_cert_cats and not certs:
        blockers.append({"id": "missing_cert", "name": "缺强制认证",
                         "detail": f"类目命中 {hit_cert_cats}，但未登记任何证书",
                         "advice": "补齐对应认证后再评估；无证书上架会被下架并可能罚款"})
    elif hit_cert_cats and certs:
        warnings.append({"id": "cert_to_verify", "name": "证书有效性待核", "kind": "risk",
                         "detail": f"已登记 {certs}",
                         "advice": "确认证书在有效期内且覆盖目标市场"})

    # 只有 kind=risk 的警告才升级成 REVIEW；data_gap 只提示，不改变档位
    risky = [w for w in warnings if w.get("kind", "risk") == "risk"]
    level = "ELIMINATE" if blockers else ("REVIEW" if risky else "OK")
    # 阈值未核实是**整套配置的性质**，不是某个商品的性质。
    # 早期版本把它塞进每个商品的 warnings，结果 21 个候选全部变 REVIEW、
    # TOP 一个不剩——永远成立的警告既淹没真问题，又把判定档位压死。
    # 现在它作为全局 caveat 由调用方展示一次（设置页/页头横幅）。
    caveats = []
    unverified = [u["key"] for u in used if u["status"] == "to_verify"]
    if unverified:
        caveats.append({
            "id": "thresholds_unverified", "name": "门槛阈值未核实",
            "detail": f"这些阈值仍是待核实的估计值：{', '.join(unverified)}",
            "advice": "上线前必须用平台现行规则替换，否则淘汰判定不可信",
        })

    return {"level": level, "blockers": blockers, "warnings": warnings,
            "caveats": caveats, "limits_used": used, "supply_ratio": supply_ratio}


def worse(a: str, b: str) -> str:
    return a if _LEVEL_ORDER[a] >= _LEVEL_ORDER[b] else b
