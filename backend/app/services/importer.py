"""数据接入层：信号导入、清洗、字段标准化、聚类去重。"""
import datetime as dt

from sqlalchemy.orm import Session

from ..models import ProductSignal, utcnow
from .scoring import _norm_title


def normalize_signal(data: dict) -> dict:
    """字段标准化：缺失默认值、类型转换。"""
    out = {
        "source": data.get("source", "csv"),
        "external_id": str(data.get("external_id", "")),
        "title": (data.get("title") or "").strip(),
        "category": (data.get("category") or "default").strip(),
        "image_url": data.get("image_url"),
        "price": float(data["price"]) if data.get("price") is not None else None,
        "sales_signal": data.get("sales_signal") or {},
        "review_signal": data.get("review_signal") or {},
        "raw_data": data.get("raw_data") or {},
        "captured_at": data.get("captured_at") or utcnow(),
    }
    if isinstance(out["captured_at"], str):
        out["captured_at"] = dt.datetime.fromisoformat(out["captured_at"].replace("Z", "+00:00"))
    if out["captured_at"].tzinfo is None:
        out["captured_at"] = out["captured_at"].replace(tzinfo=dt.timezone.utc)
    return out


def cluster_key(title: str, category: str) -> str:
    """同款聚类键：归一化标题前缀 + 类目。相同键的信号视为同一款/近似同款。"""
    return _norm_title(title)[:80] + "|" + category


def import_signals(db: Session, rows: list[dict]) -> dict:
    """导入商品热度信号（去重：同 source+external_id+captured_at 不重复）。"""
    inserted, skipped = 0, 0
    for raw in rows:
        s = normalize_signal(raw)
        if not s["title"] or not s["external_id"]:
            skipped += 1
            continue
        s["cluster_key"] = cluster_key(s["title"], s["category"])
        exists = (
            db.query(ProductSignal)
            .filter_by(source=s["source"], external_id=s["external_id"], captured_at=s["captured_at"])
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(ProductSignal(**s))
        inserted += 1
    db.commit()
    return {"inserted": inserted, "skipped": skipped}


def import_csv_content(db: Session, content: str, source: str = "csv") -> dict:
    """CSV 导入器。表头支持:
    external_id,title,category,price,image_url,sales_30d,growth_7d,review_count,weight_g,cost,size,material,captured_at
    """
    import csv
    import io

    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for r in reader:
        r = { (k or "").strip().lower(): (v or "").strip() for k, v in r.items() }
        try:
            price = float(r["price"]) if r.get("price") else None
        except ValueError:
            price = None
        raw = {}
        for k in ("weight_g", "cost", "size", "material", "price_low", "price_high", "seasonal"):
            if r.get(k):
                raw[k] = r[k]
        for k in ("weight_g", "cost"):
            if k in raw:
                try:
                    raw[k] = float(raw[k])
                except ValueError:
                    del raw[k]
        rows.append({
            "source": source,
            "external_id": r.get("external_id", ""),
            "title": r.get("title", ""),
            "category": r.get("category", "default"),
            "image_url": r.get("image_url") or None,
            "price": price,
            "sales_signal": {"sales_30d": int(r["sales_30d"]) if r.get("sales_30d", "").isdigit() else None,
                             "growth_7d": float(r["growth_7d"]) if r.get("growth_7d") else None},
            "review_signal": {"count": int(r["review_count"]) if r.get("review_count", "").isdigit() else None},
            "raw_data": raw,
            "captured_at": r.get("captured_at") or None,
        })
    return import_signals(db, rows)
