"""结果回流：样本不足时必须拒绝下结论，这是本模块存在的理由。"""
import random

from app.models import ProductCandidate, ProductSignal, SelectionOutcome
from app.services.outcomes import MIN_SAMPLES, evaluate, import_outcomes

DIMS = ("margin", "competition", "demand", "growth", "logistics", "stability")


def make_candidate(db, title, rec="TOP", base=80):
    c = ProductCandidate(normalized_title=title, category="hair_accessories",
                         estimated_cost=1.0, estimated_weight_g=100.0,
                         estimated_price_high=5.0, recommendation=rec)
    for d in DIMS:
        setattr(c, f"{d}_score", float(base))
    db.add(c)
    db.flush()
    return c


class TestImport:
    def test_import_by_candidate_id(self, db):
        c = make_candidate(db, "商品甲")
        r = import_outcomes(db, f"candidate_id,sold,sales_30d\n{c.id},1,820\n")
        assert r["ok"] and r["created"] == 1 and not r["skipped"]

    def test_import_by_external_id_via_representative_signal(self, db):
        sig = ProductSignal(source="csv", external_id="X9", title="商品乙",
                            category="hair_accessories", price=5.0)
        db.add(sig)
        db.flush()
        c = make_candidate(db, "商品乙")
        c.representative_signal_id = sig.id
        db.commit()
        r = import_outcomes(db, "external_id,sold\nX9,1\n")
        assert r["created"] == 1 and not r["skipped"]

    def test_unknown_rows_are_reported_not_dropped(self, db):
        r = import_outcomes(db, "candidate_id,sold\n999999,1\n")
        assert r["created"] == 0 and len(r["skipped"]) == 1
        assert r["skipped"][0]["reason"]

    def test_reimport_updates_instead_of_duplicating(self, db):
        c = make_candidate(db, "商品丙")
        import_outcomes(db, f"candidate_id,sold\n{c.id},0\n")
        import_outcomes(db, f"candidate_id,sold\n{c.id},1\n")
        assert db.query(SelectionOutcome).count() == 1
        assert db.query(SelectionOutcome).first().sold is True

    def test_missing_required_column_is_rejected(self, db):
        r = import_outcomes(db, "candidate_id,note\n1,ok\n")
        assert not r["ok"] and "sold" in r["error"]


class TestReport:
    def test_no_samples_refuses_conclusion(self, db):
        rep = evaluate(db)
        assert rep["paired_samples"] == 0
        assert rep["usable"] is False and rep["reason"]

    def test_small_sample_refuses_precision_claim(self, db):
        for i in range(3):
            c = make_candidate(db, f"小样本{i}")
            db.add(SelectionOutcome(candidate_id=c.id, sold=bool(i % 2)))
        db.commit()
        rep = evaluate(db)
        assert rep["usable"] is False
        assert rep["paired_samples"] == 3
        assert "precision_at_k" not in rep
        assert "descriptive" in rep

    def test_enough_samples_yields_precision_and_effect_sizes(self, db):
        rng = random.Random(5)
        for i in range(MIN_SAMPLES):
            sold = i % 2 == 0
            c = make_candidate(db, f"样本{i}", rec="TOP" if sold else "PENDING",
                               base=80 if sold else 40)
            for d in DIMS:
                cur = getattr(c, f"{d}_score")
                setattr(c, f"{d}_score", cur + rng.uniform(-5, 5))
            db.add(SelectionOutcome(candidate_id=c.id, sold=sold,
                                    sales_30d=rng.randint(0, 900)))
        db.commit()
        rep = evaluate(db, k=5)
        assert rep["usable"] is True
        assert rep["precision_at_k"]["k"] == 5
        assert 0.0 <= rep["precision_at_k"]["value"] <= 1.0
        eff = rep["dimension_effect_size"]
        assert any(v is not None and v > 0 for v in eff.values()), eff
        assert rep["dimension_read"]

    def test_demo_flag_is_tracked(self, db):
        c = make_candidate(db, "演示标记")
        import_outcomes(db, f"candidate_id,sold\n{c.id},1\n", is_demo=True)
        assert db.query(SelectionOutcome).first().is_demo is True
