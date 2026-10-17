"""AHP 层次分析法：把"我觉得需求热度挺重要"变成可审计的权重推导。

为什么需要它：原来的权重 {0.30, 0.20, 0.15, 0.15, 0.10, 0.10} 是直接拍的，
问一句"凭什么需求 0.3 物流 0.1"没有任何回答。AHP 不假装客观，
它做的是**把主观判断摊开成两两比较矩阵，然后检验这些判断自不自洽**。

自洽性检验是重点：如果 A>B、B>C，但你把 A 和 C 比的时候给出与传递性矛盾的判断，
一致性比率 CR 会超 0.1，说明这套权重内部打架，得重填。
——"我的判断可能不一致"这件事本身，就是可以被量化检查的。

只用标准库（无 numpy）：几何平均法求权重，幂迭代求最大特征根。
"""
from __future__ import annotations

import math

# 维度顺序固定，矩阵按这个顺序解释
DIMS = ["margin", "competition", "demand", "growth", "logistics", "stability"]

DIM_CN = {
    "margin": "核价存活（利润空间）",
    "competition": "竞争密度（同款多少）",
    "demand": "需求热度",
    "growth": "增长速度",
    "logistics": "物流与退货损耗",
    "stability": "非季节稳定性",
}

# Saaty 1-9 标度下的随机一致性指标 RI（n=6）
RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45}

# 判断矩阵上三角（a[i][j] = 维度i 相对 维度j 的重要度）。
# 填这组数的依据：全托管是"平台定价、卖家拿供货价"的生意，
# 核价过不了就一切免谈，所以 margin 压过所有项；
# 同款密度决定能不能拿到流量，与需求热度同量级；
# 增长速度与物流损耗是"影响幅度"而非"生死"，权重最低。
JUDGMENTS: dict[tuple[str, str], float] = {
    ("margin", "competition"): 2,
    ("margin", "demand"): 2,
    ("margin", "growth"): 4,
    ("margin", "logistics"): 3,
    ("margin", "stability"): 4,
    ("competition", "demand"): 1,
    ("competition", "growth"): 3,
    ("competition", "logistics"): 2,
    ("competition", "stability"): 3,
    ("demand", "growth"): 3,
    ("demand", "logistics"): 2,
    ("demand", "stability"): 2,
    ("growth", "logistics"): 1 / 2,
    ("growth", "stability"): 1,
    ("logistics", "stability"): 1,
}


def build_matrix(dims: list[str] = DIMS, judgments: dict | None = None) -> list[list[float]]:
    j = judgments or JUDGMENTS
    n = len(dims)
    m = [[1.0] * n for _ in range(n)]
    for i in range(n):
        for k in range(i + 1, n):
            v = j.get((dims[i], dims[k])) or 1.0 / j[(dims[k], dims[i])]
            m[i][k] = v
            m[k][i] = 1.0 / v
    return m


def _mat_vec(m, x):
    return [sum(m[i][k] * x[k] for k in range(len(x))) for i in range(len(x))]


def principal_eigenvector(m: list[list[float]], iters: int = 300, tol: float = 1e-12):
    """幂迭代求主特征向量（归一化）与对应的 λmax。"""
    n = len(m)
    v = [1.0 / n] * n
    lam = 0.0
    for _ in range(iters):
        w = _mat_vec(m, v)
        s = sum(w)
        if s == 0:
            break
        nv = [x / s for x in w]
        # Rayleigh 商估计 λ
        av = _mat_vec(m, nv)
        lam_new = sum(av) / sum(nv)
        if max(abs(a - b) for a, b in zip(nv, v)) < tol:
            v, lam = nv, lam_new
            break
        v, lam = nv, lam_new
    return v, lam


def geometric_mean_weights(m: list[list[float]]) -> list[float]:
    """AHP 行几何平均法：w_i = (∏_j a_ij)^(1/n)，再归一化。

    写成独立实现是为了给特征向量法做交叉验证——第一版这里误按列求平均，
    两种方法立刻对不上，也正是这个对不上把 bug 抓出来的。
    """
    n = len(m)
    gm = [math.exp(sum(math.log(row[j]) for j in range(n)) / n) for row in m]
    s = sum(gm)
    return [g / s for g in gm]


def analyze(dims: list[str] = DIMS, judgments: dict | None = None) -> dict:
    """返回权重、一致性指标与结论。CR>0.1 时 consistent=False，权重不可直接用。"""
    m = build_matrix(dims, judgments)
    w_eig, lam = principal_eigenvector(m)
    w_gm = geometric_mean_weights(m)
    n = len(dims)
    ci = (lam - n) / (n - 1) if n > 1 else 0.0
    ri = RI.get(n, 1.24)
    cr = ci / ri if ri else 0.0
    return {
        "dims": dims,
        "matrix": m,
        "weights_eigenvector": [round(x, 4) for x in w_eig],
        "weights_geometric_mean": [round(x, 4) for x in w_gm],
        "lambda_max": round(lam, 5),
        "consistency_index": round(ci, 5),
        "random_index": ri,
        "consistency_ratio": round(cr, 5),
        "consistent": cr <= 0.10,
        "verdict": (
            f"CR={cr:.4f} ≤ 0.10，两两判断自洽，权重可用"
            if cr <= 0.10
            else f"CR={cr:.4f} > 0.10，判断内部矛盾（违反传递性），必须重填矩阵再用"
        ),
    }


def to_setting(an: dict) -> dict:
    """转成 app_settings.score_weights 的形状（保留 2 位小数并修正求和误差）。"""
    w = {d: round(v, 3) for d, v in zip(an["dims"], an["weights_eigenvector"])}
    drift = round(1.0 - sum(w.values()), 3)
    if abs(drift) >= 0.001:
        top = max(w, key=w.get)
        w[top] = round(w[top] + drift, 3)
    return w


if __name__ == "__main__":
    a = analyze()
    print("判断矩阵（行 相对 列）:")
    print("            " + " ".join(f"{d[:6]:>7s}" for d in a["dims"]))
    for i, row in enumerate(a["matrix"]):
        print(f"  {a['dims'][i]:>10s} " + " ".join(f"{v:7.2f}" for v in row))
    print("\n权重（特征向量法）:")
    for d, w in zip(a["dims"], a["weights_eigenvector"]):
        print(f"  {d:<12s} {w:.3f}  {DIM_CN[d]}")
    print("\n权重（几何平均法，交叉验证）:", a["weights_geometric_mean"])
    print(f"λmax={a['lambda_max']}  CI={a['consistency_index']}  RI={a['random_index']}  "
          f"CR={a['consistency_ratio']}")
    print("结论:", a["verdict"])
    print("写入 score_weights 用:", to_setting(a))
