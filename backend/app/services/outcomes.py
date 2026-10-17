"""推荐结果回流：算命中率，并回答"到底哪个分项真的预测得准"。

这套系统的权重现在是 AHP 推出来的，但 AHP 只保证**判断自洽**，
不保证**判断正确**。要验证正确性，必须有 (当初推荐 → 后来实际动销) 的配对样本。
本模块就是那个样本的入口和算法。

样本量不足时明确拒绝给结论——小样本算出来的"命中率 80%"是噪声，
写进报告比不写更有害。
"""
from __future__ import annotations

import csv
import io
import math
from typing import Any

from ..models import ProductCandidate, SelectionOutcome
from .sensitivity import DIMS, total_of

MIN_SAMPLES = 30  # 低于这个配对样本数，只报覆盖情况，不报命中率结论


def import_outcomes(db, content: str, is_demo: bool = True) -> dict:
    """CSV 列：candidate_id 或 external_id，listed，sold，sales_30d，note。

    返回导入统计。找不到对应候选的行会被跳过并列出来，不静默丢弃。
    """
    reader = csv.DictReader(io.StringIO(content.strip()))
    need = {"sold"}
    missing_cols = need - set(reader.fieldnames or [])
    if missing_cols:
        return {"ok": False, "error": f"CSV 缺少必需列：{', '.join(sorted(need))}",
                "columns": reader.fieldnames or []}

    created = updated = 0
    skipped: list[dict] = []
    for ln, row in enumerate(reader, start=2):
        cid = (row.get("candidate_id") or "").strip()
        ext = (row.get("external_id") or "").strip()
        cand = _find_candidate(db, cid, ext)
        if cand is None:
            skipped.append({"line": ln, "reason": "找不到对应候选商品",
                            "candidate_id": cid, "external_id": ext})
            continue

        sold = _truthy(row.get("sold"))
        listed = _truthy(row.get("listed")) if row.get("listed") is not None else sold
        try:
            sales = int(float(row.get("sales_30d") or 0))
        except ValueError:
            sales = 0
        note = (row.get("note") or "").strip()[:200]

        ex = db.query(SelectionOutcome).filter_by(candidate_id=cand.id).first()
        if ex:
            ex.sold, ex.listed, ex.sales_30d, ex.note = sold, listed, sales, note
            ex.is_demo = is_demo
            updated += 1
        else:
            db.add(SelectionOutcome(candidate_id=cand.id, external_id=ext, listed=listed,
                                    sold=sold, sales_30d=sales, note=note, is_demo=is_demo))
            created += 1
    db.commit()
    return {"ok": True, "created": created, "updated": updated, "skipped": skipped}


def _find_candidate(db, cid: str, ext: str):
    """按 candidate_id 精确找；找不到再顺着代表信号反查。

    反查这条路径必须走 representative_signal_id，因为候选表本身不存 external_id，
    外部系统回来的结果只带得回商品编号。
    """
    if cid.isdigit():
        cand = db.get(ProductCandidate, int(cid))
        if cand is not None:
            return cand
    if not ext:
        return None
    from ..models import ProductSignal

    srow = db.query(ProductSignal).filter_by(external_id=ext).first()
    if srow is None:
        return None
    return db.query(ProductCandidate).filter_by(representative_signal_id=srow.id).first()


def _truthy(v) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "是", "sold"}


def evaluate(db, k: int = 5) -> dict:
    """算命中率与维度判别力。样本不足时明确拒绝下结论。"""
    rows = (db.query(SelectionOutcome, ProductCandidate)
            .join(ProductCandidate, ProductCandidate.id == SelectionOutcome.candidate_id)
            .all())
    n = len(rows)
    out: dict[str, Any] = {"paired_samples": n, "min_samples": MIN_SAMPLES,
                           "demo_only": all(o.is_demo for o, _ in rows) if rows else None}
    if n == 0:
        out["usable"] = False
        out["reason"] = "还没有任何推荐与结果的配对样本，命中率无法计算"
        return out
    if n < MIN_SAMPLES:
        out["usable"] = False
        out["reason"] = (f"配对样本仅 {n} 条，低于最低要求 {MIN_SAMPLES} 条。"
                         "此时算出的命中率主要由噪声决定，故不给结论。")
        out["descriptive"] = {
            "sold_rate": round(sum(1 for o, _ in rows if o.sold) / n, 3),
            "avg_sales_30d": round(sum(o.sales_30d for o, _ in rows) / n, 1),
        }
        return out

    scored = []
    for o, c in rows:
        sub = {d: float(getattr(c, f"{d}_score") or 0.0) for d in DIMS}
        scored.append({"sold": o.sold, "rec": c.recommendation, "sub": sub,
                       "total": total_of(sub, _weights(db))})
    out["usable"] = True

    ranked = sorted(range(len(scored)), key=lambda i: -scored[i]["total"])
    topk = [scored[i] for i in ranked[:k]]
    hits = sum(1 for s in topk if s["sold"])
    out["precision_at_k"] = {"k": k, "hits": hits, "value": round(hits / k, 3)}

    rec_group = [s for s in scored if s["rec"] == "TOP"]
    other = [s for s in scored if s["rec"] != "TOP"]
    r_rate = sum(1 for s in rec_group if s["sold"]) / len(rec_group) if rec_group else None
    o_rate = sum(1 for s in other if s["sold"]) / len(other) if other else None
    out["lift"] = {
        "top_group_sold_rate": round(r_rate, 3) if r_rate is not None else None,
        "other_group_sold_rate": round(o_rate, 3) if o_rate is not None else None,
        "value": round(r_rate - o_rate, 3) if r_rate is not None and o_rate is not None else None,
    }

    # 维度判别力：动销组与未动销组在各分项上的均值差（Cohen's d 简化版）
    sold_g = [s for s in scored if s["sold"]]
    miss_g = [s for s in scored if not s["sold"]]
    disc = {}
    for d in DIMS:
        a = [s["sub"][d] for s in sold_g]
        b = [s["sub"][d] for s in miss_g]
        if len(a) >= 3 and len(b) >= 3:
            ma, mb = sum(a) / len(a), sum(b) / len(b)
            va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
            vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
            pooled = math.sqrt((va + vb) / 2) or 1e-9
            disc[d] = round((ma - mb) / pooled, 3)
        else:
            disc[d] = None
    out["dimension_effect_size"] = disc
    usable_dims = {d: v for d, v in disc.items() if v is not None}
    if usable_dims:
        best = max(usable_dims, key=lambda d: abs(usable_dims[d]))
        weakest = min(usable_dims, key=lambda d: abs(usable_dims[d]))
        out["dimension_read"] = (
            f"区分动销/滞销最强的是 {best}（效应量 {usable_dims[best]:+.2f}），"
            f"最弱的是 {weakest}（{usable_dims[weakest]:+.2f}）。"
            "效应量接近 0 的分项，说明它对结果没有预测力，权重应下调。"
        )
    return out


def _weights(db) -> dict:
    from ..appsettings import get_setting

    return get_setting(db, "score_weights") or {}
