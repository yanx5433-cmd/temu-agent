"""跑权重敏感性分析 + 新旧权重对比，结果写进 reports/sensitivity.json。

用法（在 backend/ 目录下）：
    python scripts/run_sensitivity.py [--k 5] [--trials 1000] [--band 0.20]

数据来源是库里已存的六个分项分——分项分不依赖权重，所以重新加权排序是合法的，
不需要重跑整个选品流程。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.appsettings import DEFAULT_SCORE_WEIGHTS          # noqa: E402
from app.db import SessionLocal                            # noqa: E402
from app.models import ProductCandidate                    # noqa: E402
from app.services.ahp import analyze as ahp_analyze, to_setting  # noqa: E402
from app.services.sensitivity import DIMS, analyze, compare_weight_sets  # noqa: E402


def load_rows(db):
    rows = []
    for c in db.query(ProductCandidate).order_by(ProductCandidate.total_score.desc()).all():
        sub = {d: float(getattr(c, f"{d}_score") or 0.0) for d in DIMS}
        sub["_label"] = (c.normalized_title or f"#{c.id}")[:22]
        sub["_id"] = c.id
        rows.append(sub)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--trials", type=int, default=1000)
    ap.add_argument("--band", type=float, default=0.20)
    args = ap.parse_args()

    db = SessionLocal()
    rows = load_rows(db)
    db.close()
    if len(rows) < args.k + 1:
        print(f"候选太少（{len(rows)}），至少需要 {args.k + 1} 个才能做排名分析")
        return 2

    current = dict(DEFAULT_SCORE_WEIGHTS)
    ahp = to_setting(ahp_analyze())

    sens = analyze(rows, current, k=args.k, n_trials=args.trials, band=args.band)
    cmp_ = compare_weight_sets(rows, current, ahp, k=args.k)

    print(f"候选 {len(rows)} 个｜扰动 ±{args.band:.0%} × {args.trials} 次（种子 {sens['seed']}）\n")
    print("【一、权重扰动后排名还稳吗】")
    print(f"  平均 Spearman      {sens['mean_spearman']}   （最低 {sens['min_spearman']}）")
    print(f"  平均 Kendall τ     {sens['mean_kendall']}")
    print(f"  TOP-{args.k} 重合度     {sens['mean_topk_jaccard']}")
    print(f"  结论：{sens['verdict']}\n")
    print("【二、换成 AHP 推导的权重，名单会变多少】")
    print(f"  拍的权重  {current}")
    print(f"  AHP 权重  {ahp}")
    print(f"  名次变动 {cmp_['candidates_moved']}/{cmp_['total']} 个｜"
          f"Spearman {cmp_['spearman']}｜TOP-{args.k} 重合度 {cmp_['topk_jaccard']}")
    print(f"  新进 TOP：{cmp_['new_entrants_to_top'] or '无'}")
    print(f"  跌出 TOP：{cmp_['dropped_from_top'] or '无'}\n")
    print(f"【三、每个商品进 TOP-{args.k} 的频率（只看摇摆的）】")
    for f in sens["flip_flopping"][:10]:
        print(f"  {f['label']:<24s} 总分 {f['score']:>5}  进榜率 {f['top_rate']:.0%}")
    print(f"\n  始终在 TOP-{args.k} 的：{sens['stable_top_members'] or '无'}")

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "reports", "sensitivity.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"sensitivity": sens, "weight_comparison": cmp_,
                   "weights_handset": current, "weights_ahp": ahp},
                  fh, ensure_ascii=False, indent=2)
    print(f"\n完整结果已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
