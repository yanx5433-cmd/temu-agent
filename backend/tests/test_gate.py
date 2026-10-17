"""第 0 关硬门槛的测试：门槛必须真的拦得住，也不能乱拦。"""
from types import SimpleNamespace

from app.services.gate import DEFAULT_LIMITS, _parse_size, evaluate_gate

ALLOWED_STATUS = ("to_verify", "structural")


def cand(weight=200.0, cost=1.0, price_high=5.0, category="home_storage", raw=None,
         title="测试商品"):
    return SimpleNamespace(estimated_weight_g=weight, estimated_cost=cost,
                           estimated_price_high=price_high, category=category,
                           raw_data=raw or {}, normalized_title=title)


class TestSizeParsing:
    def test_three_dimensions_sum(self):
        assert _parse_size("20x15x3cm") == 38

    def test_only_top_three_counted(self):
        assert _parse_size("30x20x10x2") == 60

    def test_returns_none_when_incomplete(self):
        assert _parse_size("20x15") is None
        assert _parse_size(None) is None
        assert _parse_size("没有数字") is None


class TestEliminations:
    def test_overweight_is_eliminated(self):
        g = evaluate_gate(cand(weight=9000))
        assert g["level"] == "ELIMINATE"
        assert any(b["id"] == "weight_over" for b in g["blockers"])

    def test_negative_margin_is_eliminated(self):
        # 成本 6 元高于 售价上限 5 乘 0.75 等于 3.75，卖一件亏一件
        g = evaluate_gate(cand(cost=6.0, price_high=5.0))
        assert any(b["id"] == "negative_margin" for b in g["blockers"])

    def test_uncompetitive_supply_price_is_eliminated(self):
        g = evaluate_gate(cand(cost=4.0, price_high=10.0,
                               raw={"similar_lowest_price": 5.0}))
        assert "price_uncompetitive" in [b["id"] for b in g["blockers"]]

    def test_missing_cert_for_regulated_category(self):
        g = evaluate_gate(cand(category="children_product"))
        assert any(b["id"] == "missing_cert" for b in g["blockers"])

    def test_cert_present_downgrades_to_warning(self):
        g = evaluate_gate(cand(category="children_product",
                               raw={"certifications": ["CPC"]}))
        assert not any(b["id"] == "missing_cert" for b in g["blockers"])

    def test_closed_category_eliminated(self):
        g = evaluate_gate(cand(category="tobacco"),
                          limits={"closed_categories": ["tobacco"]})
        assert any(b["id"] == "category_closed" for b in g["blockers"])


class TestNonEliminating:
    def test_clean_candidate_passes(self):
        g = evaluate_gate(cand(weight=120, cost=1.0, price_high=6.0,
                               raw={"similar_lowest_price": 6.0}))
        assert g["level"] == "OK", g

    def test_missing_competitor_price_is_data_gap_not_review(self):
        """缺字段是这项没评估，不该把商品推到人工复核。

        早期版本把它算成 warning，导致 21 个候选全部 REVIEW、TOP 清零，
        等于用全都待确认实现了没有门槛。
        """
        g = evaluate_gate(cand(raw={}))
        gaps = [w for w in g["warnings"] if w["id"] == "no_competitor_price"]
        assert gaps and gaps[0]["kind"] == "data_gap"
        assert g["level"] == "OK"

    def test_thin_margin_escalates_to_review(self):
        # 毛利率约 5%，低于 10% 的结构下限但尚未为负
        g = evaluate_gate(cand(cost=4.6, price_high=6.66,
                               raw={"similar_lowest_price": 20.0}))
        assert g["level"] == "REVIEW"
        assert any(w["id"] == "thin_margin" for w in g["warnings"])

    def test_unknown_weight_is_flagged_not_eliminated(self):
        g = evaluate_gate(cand(weight=None, raw={"similar_lowest_price": 9.0}))
        assert g["level"] != "ELIMINATE"
        assert any(w["id"] == "weight_unknown" for w in g["warnings"])


class TestHonestThresholds:
    def test_no_threshold_is_claimed_as_confirmed(self):
        """当前一个阈值都没核实过，代码里就不许出现 confirmed，否则是在假装权威。"""
        for key, meta in DEFAULT_LIMITS.items():
            assert meta["status"] in ALLOWED_STATUS, key

    def test_unverified_caveat_is_global_not_per_candidate(self):
        g = evaluate_gate(cand())
        assert any(c["id"] == "thresholds_unverified" for c in g["caveats"])
        assert not any(w["id"] == "thresholds_unverified" for w in g["warnings"])
        assert g["level"] == "OK"

    def test_limits_used_reports_status_of_each(self):
        g = evaluate_gate(cand())
        for used in g["limits_used"]:
            assert used["status"] in ALLOWED_STATUS

    def test_override_from_settings_is_honoured(self):
        g = evaluate_gate(cand(weight=3000), limits={"max_weight_g": 2000})
        assert any(b["id"] == "weight_over" for b in g["blockers"])
