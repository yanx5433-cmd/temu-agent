"""AHP 权重推导的测试：重点测自洽性检验真的会拒绝矛盾判断。"""
from app.services.ahp import (DIMS, analyze, build_matrix, principal_eigenvector,
                              to_setting)


class TestMatrix:
    def test_diagonal_is_one(self):
        m = build_matrix()
        for i in range(len(DIMS)):
            assert m[i][i] == 1.0

    def test_reciprocal_symmetry(self):
        m = build_matrix()
        for i in range(len(DIMS)):
            for j in range(len(DIMS)):
                assert abs(m[i][j] * m[j][i] - 1.0) < 1e-9

    def test_all_pairs_given(self):
        """六维应有 15 对上三角判断，缺一项会静默按 1 处理（等于偷偷降维）。"""
        assert len(DIMS) * (len(DIMS) - 1) // 2 == 15


class TestWeights:
    def test_weights_sum_to_one(self):
        # analyze() 的输出保留 4 位小数，六项之和只能逼近 1；
        # 要求精确等于 1 的是 to_setting()，在那里单独测。
        a = analyze()
        assert abs(sum(a["weights_eigenvector"]) - 1.0) < 1e-3
        assert abs(sum(a["weights_geometric_mean"]) - 1.0) < 1e-3

    def test_two_methods_agree(self):
        """两种独立解法必须吻合，否则至少一个写错了（这里曾写反过行列）。"""
        a = analyze()
        worst = max(abs(x - y) for x, y in
                    zip(a["weights_eigenvector"], a["weights_geometric_mean"]))
        assert worst < 0.005, f"两法偏差 {worst:.4f}，疑似实现有误"

    def test_shipped_judgments_are_consistent(self):
        a = analyze()
        assert a["consistent"], a["verdict"]
        assert a["consistency_ratio"] <= 0.10

    def test_margin_outranks_everything(self):
        w = dict(zip(DIMS, analyze()["weights_eigenvector"]))
        assert max(w, key=w.get) == "margin"

    def test_to_setting_sums_exactly_one(self):
        w = to_setting(analyze())
        assert abs(sum(w.values()) - 1.0) < 1e-9
        assert set(w) == set(DIMS)


class TestConsistencyRejection:
    def test_cyclical_judgments_are_rejected(self):
        """A>B, B>C 却声称 C>>A，违反传递性，CR 必须超线。"""
        bad = {
            ("margin", "competition"): 5,
            ("competition", "demand"): 5,
            ("margin", "demand"): 1 / 9,
            ("margin", "growth"): 3, ("competition", "growth"): 3,
            ("demand", "growth"): 1 / 3,
            ("margin", "logistics"): 3, ("competition", "logistics"): 3,
            ("demand", "logistics"): 3, ("growth", "logistics"): 1,
            ("margin", "stability"): 3, ("competition", "stability"): 3,
            ("demand", "stability"): 3, ("growth", "stability"): 1,
            ("logistics", "stability"): 1,
        }
        a = analyze(judgments=bad)
        assert not a["consistent"], "矛盾判断竟通过了一致性检验"
        assert a["consistency_ratio"] > 0.10

    def test_perfectly_consistent_matrix_has_zero_ci(self):
        w = [4.0, 2.0, 1.0]
        dims = DIMS[:3]
        j = {}
        for i in range(3):
            for k in range(i + 1, 3):
                j[(dims[i], dims[k])] = w[i] / w[k]
        v, lam = principal_eigenvector(build_matrix(dims, j))
        assert abs(lam - 3.0) < 1e-6
        assert abs(v[0] - 4 / 7) < 1e-6
