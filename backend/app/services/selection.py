"""选品工作流编排：从信号簇构建候选 → 合规门槛 → 评分 → 落库。确定性流程。"""
from sqlalchemy.orm import Session

from ..models import ProductCandidate, ProductSignal, TrendSnapshot, utcnow
from .compliance import check_compliance
from .scoring import _cluster_key_of, estimate_fields, run_selection_for_candidate


def build_candidates_from_signals(db: Session) -> dict:
    """按 cluster_key 聚合信号，每个簇生成/更新一个候选商品。"""
    signals = db.query(ProductSignal).order_by(ProductSignal.captured_at.asc()).all()
    clusters: dict[str, list] = {}
    for s in signals:
        if s.cluster_key:
            clusters.setdefault(s.cluster_key, []).append(s)

    created, updated = 0, 0
    for key, group in clusters.items():
        rep = group[-1]  # 最新快照作为代表
        est = estimate_fields(
            {"category": rep.category, "price": rep.price, "raw_data": rep.raw_data or {}},
            _category_defaults(db),
        )
        candidate = db.query(ProductCandidate).filter_by(normalized_title=_norm_key(rep.title), category=rep.category).first()
        if not candidate:
            candidate = ProductCandidate(normalized_title=_norm_key(rep.title), category=rep.category)
            db.add(candidate)
            db.flush()
            created += 1
        else:
            updated += 1
        candidate.representative_signal_id = rep.id
        candidate.image_url = rep.image_url
        candidate.estimated_cost = est["cost"]
        candidate.estimated_price_low = est["price_low"]
        candidate.estimated_price_high = est["price_high"]
        candidate.estimated_weight_g = est["weight_g"]
        candidate.seasonal = est["seasonal"]
        # raw 字段挂到 candidate 上供合规缺失检查（size/material 等）
        # _provenance 记录每个字段是实测还是兜底，供详情页标徽章
        candidate.raw_data = {"size": est["size"], "material": est["material"],
                              "_provenance": est["_provenance"],
                              **(rep.raw_data or {})}
    db.commit()
    return {"created": created, "updated": updated}


def _norm_key(title: str) -> str:
    from .scoring import _norm_title

    return _norm_title(title)[:120]


def _category_defaults(db: Session) -> dict:
    from ..appsettings import get_setting

    return get_setting(db, "category_defaults")


def run_selection(db: Session, candidate_id: int | None = None) -> dict:
    """执行选品 Agent 主流程。candidate_id 为空则全量重跑。"""
    q = db.query(ProductCandidate)
    if candidate_id:
        q = q.filter(ProductCandidate.id == candidate_id)
    candidates = q.all()

    from ..appsettings import get_setting

    weights = get_setting(db, "score_weights")
    defaults = get_setting(db, "category_defaults")
    market = (get_setting(db, "target_markets") or ["US"])[0]

    results = {"evaluated": 0, "reject": 0, "review": 0, "pass": 0}
    for cand in candidates:
        res = run_selection_for_candidate(db, cand, weights, defaults)
        compliance = res["compliance"]
        # 保存合规检查记录
        cand_id = cand.id
        db.add(_make_compliance_check(cand_id, market, compliance))
        results["evaluated"] += 1
        if compliance["status"] == "REJECT":
            results["reject"] += 1
        elif compliance["status"] == "REVIEW":
            results["review"] += 1
        else:
            results["pass"] += 1
        # 记录趋势快照供历史图使用
        if res.get("scores"):
            db.add(TrendSnapshot(candidate_id=cand_id, heat=cand.total_score, captured_at=utcnow()))
        db.commit()
    return results


def _make_compliance_check(candidate_id: int, market: str, compliance: dict):
    from ..models import ComplianceCheck

    return ComplianceCheck(
        candidate_id=candidate_id,
        market=market,
        status=compliance["status"],
        matched_rules=compliance["matched_rules"],
        missing_information=compliance["missing_information"],
        explanation=compliance["explanation"],
    )
