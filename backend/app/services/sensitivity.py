"""权重敏感性分析：换一组差不多合理的权重，推荐名单会不会整个换掉？

这一步的价值不在于得到一个好看的数字，而在于**如果名单一点都不稳，
就说明这套评分的排序基本是被权重决定的，而不是被商品本身决定的**——
那"算法"其实是摆设。这个结论哪怕难看也必须跑出来。

做法：对每个分项权重施加 ±20% 的随机扰动，重新归一化后重算总分并重新排序，
重复 N 次（固定随机种子，结果可复现），统计：
  - 平均 Spearman ρ / Kendall τ：整体排序稳不稳
  - TOP-K 集合的平均 Jaccard：头部名单稳不稳
  - 每个候选进入 TOP-K 的频率：具体哪几个商品是"权重一吹就倒"的
只用标准库。
"""
from __future__ import annotations

import random
from typing import Sequence

DIMS = ("margin", "competition", "demand", "growth", "logistics", "stability")


def total_of(sub: dict[str, float], weights: dict[str, float]) -> float:
    return sum(float(sub.get(d, 0.0)) * float(weights.get(d, 0.0)) for d in DIMS)


def rank_order(rows: list[dict], weights: dict[str, float]) -> list[int]:
    """按加权总分从高到低返回下标；同分按原下标稳定排序。"""
    return sorted(range(len(rows)), key=lambda i: (-total_of(rows[i], weights), i))


def spearman(a: Sequence[int], b: Sequence[int]) -> float:
    n = len(a)
    if n < 2:
        return 1.0
    pos_a = {item: i for i, item in enumerate(a)}
    pos_b = {item: i for i, item in enumerate(b)}
    d2 = sum((pos_a[i] - pos_b[i]) ** 2 for i in pos_a)
    return 1 - 6 * d2 / (n * (n ** 2 - 1))


def kendall_tau(a: Sequence[int], b: Sequence[int]) -> float:
    n = len(a)
    if n < 2:
        return 1.0
    rank_b = {item: i for i, item in enumerate(b)}
    conc = disc = 0
    for i in range(n):
        for k in range(i + 1, n):
            pair = (a[i], a[k])
            if rank_b[pair[0]] < rank_b[pair[1]]:
                conc += 1
            else:
                disc += 1
    total = n * (n - 1) / 2
    return (conc - disc) / total if total else 1.0


def jaccard(x: set, y: set) -> float:
    return len(x & y) / len(x | y) if (x | y) else 1.0


def perturb(weights: dict[str, float], rng: random.Random, band: float) -> dict[str, float]:
    w = {d: max(1e-6, weights[d] * rng.uniform(1 - band, 1 + band)) for d in DIMS}
    s = sum(w.values())
    return {d: v / s for d, v in w.items()}


def analyze(rows: list[dict], baseline_weights: dict[str, float], k: int = 5,
            n_trials: int = 1000, band: float = 0.20, seed: int = 20261017) -> dict:
    """rows: [{"margin":..,"competition":..,...,"_label": 可读名字}]，值为 0-100 分项分。"""
    rng = random.Random(seed)
    base_rank = rank_order(rows, baseline_weights)
    base_top = set(base_rank[:k])

    rhos, taus, jacs = [], [], []
    in_top = [0] * len(rows)
    totals = [total_of(r, baseline_weights) for r in rows]

    for _ in range(n_trials):
        w = perturb(baseline_weights, rng, band)
        r = rank_order(rows, w)
        rhos.append(spearman(base_rank, r))
        taus.append(kendall_tau(base_rank, r))
        jacs.append(jaccard(base_top, set(r[:k])))
        for i in r[:k]:
            in_top[i] += 1

    n = max(len(rhos), 1)
    fragile = sorted(
        ({"label": rows[i].get("_label", f"#{i}"), "score": round(totals[i], 1),
          "top_rate": round(in_top[i] / n_trials, 3)}
         for i in range(len(rows))),
        key=lambda x: -x["top_rate"],
    )
    always = [f["label"] for f in fragile if f["top_rate"] >= 0.95]
    never = [f["label"] for f in fragile if f["top_rate"] <= 0.05 and f["label"] in
             {rows[i].get("_label", f"#{i}") for i in base_top}]
    return {
        "n_candidates": len(rows), "k": k, "trials": n_trials, "band": band, "seed": seed,
        "mean_spearman": round(sum(rhos) / n, 4),
        "mean_kendall": round(sum(taus) / n, 4),
        "mean_topk_jaccard": round(sum(jacs) / n, 4),
        "min_spearman": round(min(rhos), 4),
        "stable_top_members": always,
        "flip_flopping": [f for f in fragile if 0.05 < f["top_rate"] < 0.95],
        "lost_from_top": never,
        "top_rate_table": fragile,
        "verdict": _verdict(sum(jacs) / n, sum(rhos) / n, k),
    }


def _verdict(jac: float, rho: float, k: int) -> str:
    if jac >= 0.8 and rho >= 0.9:
        return f"排序稳健（TOP-{k} 重合度 {jac:.0%}，Spearman {rho:.3f}）：权重在小范围内摆动不改变结论"
    if jac >= 0.5:
        return (f"排序中等敏感（TOP 重合度仅 {jac:.0%}，Spearman {rho:.3f}）："
                "头部名单有一半会在权重微调后换人，推荐结果不能当硬结论用")
    return (f"排序高度不稳定（TOP 重合度 {jac:.0%}，Spearman {rho:.3f}）："
            "名次主要由权重决定而非商品本身，这套评分目前只能当粗筛，不能当排序依据")


def compare_weight_sets(rows: list[dict], old: dict[str, float], new: dict[str, float],
                        k: int = 5) -> dict:
    """两组权重各自排名，看差异有多大（例如"拍的权重"换成"AHP 推导的权重"）。"""
    ro, rn = rank_order(rows, old), rank_order(rows, new)
    # rn 是「新名次 → 商品下标」的列表，必须成对取 (位置, 下标) 再比。
    # 之前写成 enumerate(rn) 只拿位置当下标，导致变动数恒为 0；
    # 这个 bug 是靠「名次 0 变动但 Spearman 只有 0.983」自相矛盾才发现的。
    moved = sum(1 for pos, cid in enumerate(rn) if ro.index(cid) != pos)
    return {
        "spearman": round(spearman(ro, rn), 4),
        "kendall": round(kendall_tau(ro, rn), 4),
        "topk_jaccard": round(jaccard(set(ro[:k]), set(rn[:k])), 4),
        "candidates_moved": moved,
        "total": len(rows),
        "new_entrants_to_top": [rows[i].get("_label", f"#{i}") for i in rn[:k] if i not in ro[:k]],
        "dropped_from_top": [rows[i].get("_label", f"#{i}") for i in ro[:k] if i not in rn[:k]],
    }
