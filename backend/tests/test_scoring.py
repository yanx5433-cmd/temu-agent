"""评分与选品流程测试：每个评分可追溯到计算字段。"""
import datetime as dt

from app.models import ProductCandidate, ProductSignal, utcnow
from app.services.importer import cluster_key
from app.services.scoring import _norm_title, compute_scores, run_selection_for_candidate


def _sig(days_ago, sales, growth, price=5.0):
    return {
        "captured_at": (utcnow() - dt.timedelta(days=days_ago)).isoformat(),
        "price": price,
        "sales_signal": {"sales_30d": sales, "growth_7d": growth},
        "review_signal": {"count": 100},
        "raw_data": {"weight_g": 40, "cost": 0.6, "material": "合金", "size": "6cm"},
    }


def make_candidate(monkeypatch):
    cand = ProductCandidate(
        normalized_title="成人鲨鱼夹粗发抓夹", category="hair_accessories",
        estimated_cost=0.6, estimated_price_low=3.0, estimated_price_high=5.0,
        estimated_weight_g=40, seasonal=False,
        raw_data={"size": "11cm", "material": "醋酸板材"},
    )
    return cand


def test_scores_traceable():
    cand = make_candidate(None)
    signals = [_sig(14, 10000, 0.1), _sig(7, 11500, 0.2), _sig(0, 13000, 0.32)]
    weights = {"demand": 0.3, "growth": 0.2, "competition": 0.15, "margin": 0.15, "logistics": 0.1, "stability": 0.1}
    result = compute_scores(cand, signals, weights, {})
    assert 0 <= result["total_score"] <= 100
    # 每个分项都有计算依据
    for k, v in result["detail"].items():
        assert v["detail"], f"分项 {k} 缺少计算依据"
    # 明确的字段值进入依据文本
    assert "13000" in result["detail"]["demand"]["detail"]
    assert "32" in result["detail"]["growth"]["detail"] or "0.32" in result["detail"]["growth"]["detail"]


def test_low_confidence_when_data_missing():
    cand = make_candidate(None)
    result = compute_scores(cand, [_sig(0, 0, None)], {"demand": .3, "growth": .2, "competition": .15, "margin": .15, "logistics": .1, "stability": .1}, {})
    assert result["confidence"] < 0.6


def test_cluster_key_dedup():
    assert cluster_key("成人 鲨鱼夹！粗发抓夹～", "hair") == cluster_key("成人鲨鱼夹粗发抓夹", "hair")
    assert cluster_key("A 商品", "cat1") != cluster_key("A 商品", "cat2")


def test_full_selection_rejects_before_scoring(db):
    cand = ProductCandidate(
        normalized_title="儿童玩具积木", category="diy_party",
        estimated_cost=2.0, estimated_weight_g=300,
        raw_data={"size": "20cm", "material": "塑料"},
    )
    db.add(cand)
    db.commit()
    res = run_selection_for_candidate(db, cand)
    assert cand.recommendation == "REJECT"
    assert res["scores"] is None


def test_full_selection_top_flow(db):
    cand = ProductCandidate(
        normalized_title="成人鲨鱼夹粗发抓夹", category="hair_accessories",
        estimated_cost=0.6, estimated_price_low=3.0, estimated_price_high=5.0,
        estimated_weight_g=40, seasonal=False,
        raw_data={"size": "11cm", "material": "醋酸板材"},
    )
    db.add(cand)
    db.flush()
    for args in [(14, 10000, 0.10), (7, 11500, 0.20), (0, 13000, 0.32)]:
        d, sales, g = args
        db.add(ProductSignal(
            source="demo", external_id=f"S{d}", title="成人鲨鱼夹粗发抓夹",
            category="hair_accessories", price=5.0,
            sales_signal={"sales_30d": sales, "growth_7d": g},
            review_signal={"count": 1500},
            raw_data={"weight_g": 40, "cost": 0.6, "material": "醋酸板材", "size": "11cm"},
            captured_at=utcnow() - dt.timedelta(days=d),
            cluster_key=cluster_key("成人鲨鱼夹粗发抓夹", "hair_accessories"),
        ))
    db.commit()
    res = run_selection_for_candidate(db, cand)
    assert res["compliance"]["status"] == "PASS"
    assert cand.confidence >= 0.6
    assert cand.recommendation in ("TOP", "CONSIDER")
    assert cand.reasons and cand.total_score > 50
