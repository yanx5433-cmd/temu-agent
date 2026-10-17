"""选品评分：全部分项由真实字段或明确默认规则计算，禁止大模型打分。

score_detail 保存每个分项的计算依据，保证“每个评分可追溯到计算字段”。
"""
import math

from ..appsettings import get_setting
from .compliance import check_compliance


def _norm_title(title: str) -> str:
    import re

    t = title.lower().strip()
    t = re.sub(r"[^\w\u4e00-\u9fff]+", " ", t)
    # 去掉中文之间的空格（中文无词间空格，标点造成的空格应移除）
    t = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", t)
    return re.sub(r"\s+", " ", t).strip()


def estimate_fields(signal_row: dict, category_defaults: dict) -> dict:
    """从 signal 原始字段 + 类目默认值估计成本/重量/价格区间。"""
    cat = signal_row.get("category", "default")
    defaults = category_defaults.get(cat, category_defaults.get("default", {}))
    price = signal_row.get("price")
    raw = signal_row.get("raw_data", {}) or {}
    cost = raw.get("cost", defaults.get("cost"))
    weight = raw.get("weight_g", defaults.get("weight_g"))
    size = raw.get("size")
    material = raw.get("material")
    price_low = raw.get("price_low") or (round(price * 0.85, 2) if price else None)
    price_high = raw.get("price_high") or (round(price * 1.25, 2) if price else None)
    return {
        "cost": cost,
        "weight_g": weight,
        "size": size,
        "material": material,
        "price_low": price_low,
        "price_high": price_high,
        "seasonal": bool(raw.get("seasonal", defaults.get("seasonal", False))),
    }


def compute_scores(candidate, signals: list[dict], weights: dict, category_defaults: dict) -> dict:
    """signals: 该候选簇内所有快照 [{captured_at, sales_signal, price, raw_data}, ...] 按时间升序。

    每个分项输出 (score 0-100, detail 计算依据文本)。
    """
    latest = signals[-1] if signals else {}
    sales = latest.get("sales_signal", {}) or {}
    raw = latest.get("raw_data", {}) or {}

    # ---- 需求热度：以近30日销量为基础做对数归一（缺数据时给保守默认值） ----
    sales_n = float(sales.get("sales_30d") or sales.get("sales") or 0)
    if sales_n > 0:
        demand = min(100.0, math.log10(sales_n + 1) / 5 * 100)  # 10万件≈100分
        demand_detail = f"近30日销量 {sales_n:.0f}，log 归一化得分"
    else:
        reviews_n = float((latest.get("review_signal", {}) or {}).get("count") or 0)
        if reviews_n > 0:
            demand = min(60.0, math.log10(reviews_n + 1) / 5 * 60)
            demand_detail = f"无销量数据，以评论数 {reviews_n:.0f} 保守估计（上限60）"
        else:
            demand = 20.0
            demand_detail = "无销量/评论数据，使用默认低分20（数据不足）"

    # ---- 增长速度：7日增长率，直接映射 ----
    growth = sales.get("growth_7d")
    if growth is None:
        growth = raw.get("growth_7d")
    if growth is not None:
        g = float(growth)
        growth_score = max(0.0, min(100.0, 50 + g * 250))  # 0%→50, +20%→100, -20%→0
        growth_detail = f"7日增长率 {g:.1%} 线性映射"
    else:
        growth_score = 40.0
        growth_detail = "无增长率数据，使用默认中低分40（数据不足）"

    # ---- 竞争空间：同簇（相似商品）数量越少空间越大 ----
    n_similar = max(0, len(signals) - 1)
    competition = max(0.0, 100.0 - n_similar * 15)
    competition_detail = f"相似商品/同款快照数 {n_similar}，每多1个扣15分"

    # ---- 预计利润：按 (售价×0.75 - 成本)/售价 估计毛利率（TEMU 全托管粗略供货系数） ----
    price = candidate.estimated_price_high or latest.get("price")
    cost = candidate.estimated_cost
    if price and cost is not None and price > 0:
        margin = (price * 0.75 - cost) / price
        margin = max(-1.0, min(1.0, margin))
        margin_score = max(0.0, min(100.0, (margin + 0.1) / 0.7 * 100))  # -10%→0, 60%→100
        margin_detail = f"售价上限 {price}、采购成本 {cost}，按供货系数0.75估算毛利率 {margin:.0%}"
    else:
        margin = None
        margin_score = 30.0
        margin_detail = "缺少价格或成本数据，使用默认低分30（数据不足）"

    # ---- 物流友好度：重量为主，体积简易折算 ----
    weight = candidate.estimated_weight_g
    if weight is not None:
        if weight <= 100:
            logistics = 100.0
        elif weight <= 300:
            logistics = 80.0
        elif weight <= 1000:
            logistics = 55.0
        else:
            logistics = 25.0
        logistics_detail = f"预计重量 {weight}g，分档计分"
    else:
        logistics = 40.0
        logistics_detail = "缺少重量数据，使用默认分40（数据不足）"

    # ---- 非季节稳定性：季节性商品打折 + 增长快照波动惩罚 ----
    if candidate.seasonal:
        stability = 40.0
        stability_detail = "标记为季节性商品，稳定性基础分40"
    else:
        stability = 80.0
        stability_detail = "非季节性商品，稳定性基础分80"
    growths = [float((s.get("sales_signal") or {}).get("growth_7d") or 0) for s in signals if (s.get("sales_signal") or {}).get("growth_7d") is not None]
    if len(growths) >= 2:
        mean = sum(growths) / len(growths)
        var = sum((g - mean) ** 2 for g in growths) / len(growths)
        penalty = min(30.0, math.sqrt(var) * 200)
        stability = max(0.0, stability - penalty)
        stability_detail += f"；{len(growths)} 期增长率波动惩罚 -{penalty:.0f}"

    detail = {
        "demand": {"score": round(demand, 1), "weight": weights["demand"], "detail": demand_detail},
        "growth": {"score": round(growth_score, 1), "weight": weights["growth"], "detail": growth_detail},
        "competition": {"score": round(competition, 1), "weight": weights["competition"], "detail": competition_detail},
        "margin": {"score": round(margin_score, 1), "weight": weights["margin"], "detail": margin_detail},
        "logistics": {"score": round(logistics, 1), "weight": weights["logistics"], "detail": logistics_detail},
        "stability": {"score": round(stability, 1), "weight": weights["stability"], "detail": stability_detail},
    }
    total = sum(detail[k]["score"] * detail[k]["weight"] for k in detail)

    # ---- 数据置信度：关键字段完备度 ----
    fields = [sales_n > 0, growth is not None, len(signals) >= 2, price is not None,
              cost is not None, weight is not None, bool(raw.get("material"))]
    confidence = round(sum(1 for f in fields if f) / len(fields), 2)

    return {
        "scores": {
            "demand_score": round(demand, 1),
            "growth_score": round(growth_score, 1),
            "competition_score": round(competition, 1),
            "margin_score": round(margin_score, 1),
            "logistics_score": round(logistics, 1),
            "stability_score": round(stability, 1),
        },
        "total_score": round(total, 1),
        "confidence": confidence,
        "margin": margin,
        "detail": detail,
    }


def build_reasons(candidate, scores: dict) -> tuple[list, list, str]:
    """生成可解释推荐理由 / 风险 / 差异化方向（模板化，不使用大模型编造）。"""
    d = scores["detail"]
    reasons = []
    if scores["scores"]["demand_score"] >= 60:
        reasons.append(f"需求热度较高（{d['demand']['detail']}）")
    if scores["scores"]["growth_score"] >= 60:
        reasons.append(f"增长势头好（{d['growth']['detail']}）")
    if scores["scores"]["competition_score"] >= 70:
        reasons.append(f"竞争空间大（{d['competition']['detail']}）")
    if scores["scores"]["margin_score"] >= 60:
        reasons.append(f"利润空间可观（{d['margin']['detail']}）")
    if scores["scores"]["logistics_score"] >= 80:
        reasons.append(f"物流友好（{d['logistics']['detail']}）")
    if not reasons:
        reasons.append("各分项表现平淡，建议观望或补充数据后重新评估")

    risks = []
    if scores["confidence"] < 0.6:
        risks.append(f"数据置信度低（{scores['confidence']:.0%}），建议人工核实后再决定")
    if scores["scores"]["growth_score"] and "数据不足" in d["growth"]["detail"]:
        risks.append("缺少增长率数据，无法判断趋势方向")
    if candidate.seasonal:
        risks.append("季节性商品，过季后需求可能快速回落")
    if scores["margin"] is not None and scores["margin"] < 0.25:
        risks.append(f"估算毛利率仅 {scores['margin']:.0%}，对供货价敏感")

    diff = "建议从材质升级、颜色/套装组合或包装形式做差异化，避免与现有低价同款正面竞争。"
    return reasons, risks, diff


def run_selection_for_candidate(db, candidate, weights=None, category_defaults=None) -> dict:
    """对单个候选执行：合规门槛 → 评分 → 理由。合规 REJECT 直接淘汰不打分。"""
    from ..models import ProductSignal

    weights = weights or get_setting(db, "score_weights")
    category_defaults = category_defaults or get_setting(db, "category_defaults")
    market = (get_setting(db, "target_markets") or ["US"])[0]

    compliance = check_compliance(candidate, market)
    if compliance["status"] == "REJECT":
        candidate.recommendation = "REJECT"
        candidate.score_detail = {"compliance": compliance}
        return {"compliance": compliance, "scores": None}

    sig_rows = (
        db.query(ProductSignal)
        .filter(ProductSignal.cluster_key == _cluster_key_of(candidate))
        .order_by(ProductSignal.captured_at.asc())
        .all()
    )
    signals = [
        {
            "captured_at": s.captured_at.isoformat(),
            "price": s.price,
            "sales_signal": s.sales_signal or {},
            "review_signal": s.review_signal or {},
            "raw_data": s.raw_data or {},
        }
        for s in sig_rows
    ]
    result = compute_scores(candidate, signals, weights, category_defaults)
    reasons, risks, diff = build_reasons(candidate, result)

    for k, v in result["scores"].items():
        setattr(candidate, k, v)
    candidate.total_score = result["total_score"]
    candidate.confidence = result["confidence"]
    candidate.estimated_margin = round(result["margin"], 3) if result["margin"] is not None else None
    candidate.reasons = reasons
    candidate.risks = risks
    candidate.differentiation = diff
    candidate.score_detail = {"compliance": compliance, "scoring": result["detail"], "market": market}
    candidate.recommendation = (
        "TOP" if result["total_score"] >= 65 and result["confidence"] >= 0.6
        else "CONSIDER" if result["total_score"] >= 50
        else "PENDING"
    )
    return {"compliance": compliance, "scores": result}


def _cluster_key_of(candidate) -> str:
    return candidate.normalized_title[:80] + "|" + candidate.category
