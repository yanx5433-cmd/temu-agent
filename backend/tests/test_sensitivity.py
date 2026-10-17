"""敏感性分析的测试：统计量本身必须正确，否则结论没有意义。"""
from app.services.sensitivity import (analyze, compare_weight_sets, jaccard, kendall_tau,
                                      rank_order, spearman)

W0 = {"margin": 0.343, "competition": 0.205, "demand": 0.192,
      "growth": 0.07, "logistics": 0.106, "stability": 0.084}
FLIP = {"margin": 0.07, "competition": 0.07, "demand": 0.06,
        "growth": 0.06, "logistics": 0.34, "stability": 0.40}


def rows():
    return [
        {"margin": 90, "competition": 80, "demand": 70, "growth": 60,
         "logistics": 50, "stability": 40, "_label": "a"},
        {"margin": 80, "competition": 90, "demand": 60, "growth": 70,
         "logistics": 40, "stability": 50, "_label": "b"},
        {"margin": 10, "competition": 20, "demand": 30, "growth": 40,
         "logistics": 90, "stability": 95, "_label": "c"},
    ]


class TestRankCorrelation:
    def test_identity_is_one(self):
        r = [0, 1, 2, 3]
        assert spearman(r, r) == 1.0
        assert kendall_tau(r, r) == 1.0

    def test_reversed_is_minus_one(self):
        assert spearman([0, 1, 2, 3], [3, 2, 1, 0]) == -1.0
        assert kendall_tau([0, 1, 2, 3], [3, 2, 1, 0]) == -1.0

    def test_jaccard_bounds(self):
        assert jaccard({1, 2}, {1, 2}) == 1.0
        assert jaccard({1, 2}, {3, 4}) == 0.0
        assert abs(jaccard({1, 2}, {2, 3}) - 1 / 3) < 1e-9

    def test_single_element_is_perfect(self):
        assert spearman([0], [0]) == 1.0
        assert kendall_tau([0], [0]) == 1.0


class TestRanking:
    def test_order_follows_weighted_total(self):
        order = rank_order(rows(), W0)
        assert order[0] == 0 and order[-1] == 2

    def test_stable_tie_break_by_index(self):
        same = [{"margin": 1} for _ in range(3)]
        assert rank_order(same, {"margin": 1.0}) == [0, 1, 2]


class TestCompareWeightSets:
    def test_same_weights_move_nobody(self):
        c = compare_weight_sets(rows(), W0, dict(W0), k=2)
        assert c["candidates_moved"] == 0 and c["spearman"] == 1.0

    def test_moved_count_matches_reality(self):
        """回归：曾把"位置"当成"商品下标"比较，导致变动数恒为 0，
        而同一份数据里 Spearman 只有 0.98 —— 两个数互相矛盾才发现。"""
        c = compare_weight_sets(rows(), W0, FLIP, k=1)
        assert c["candidates_moved"] > 0, "排序明显变了却报 0 变动"
        assert c["spearman"] < 1.0


class TestAnalyze:
    def test_deterministic_given_seed(self):
        a1 = analyze(rows(), W0, k=2, n_trials=60, seed=99)
        a2 = analyze(rows(), W0, k=2, n_trials=60, seed=99)
        assert a1["mean_spearman"] == a2["mean_spearman"]
        assert a1["top_rate_table"] == a2["top_rate_table"]

    def test_zero_band_keeps_ranking_identical(self):
        a = analyze(rows(), W0, k=2, n_trials=20, band=0.0)
        assert a["mean_spearman"] == 1.0
        assert a["mean_topk_jaccard"] == 1.0

    def test_extreme_band_breaks_ranking(self):
        a = analyze(rows(), W0, k=1, n_trials=60, band=0.95, seed=3)
        assert a["mean_topk_jaccard"] < 1.0

    def test_verdict_is_explanatory_text(self):
        v = analyze(rows(), W0, k=2, n_trials=20)["verdict"]
        assert isinstance(v, str) and len(v) > 10
