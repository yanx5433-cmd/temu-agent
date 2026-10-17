"""审计与系统设置辅助。"""
import functools

from sqlalchemy.orm import Session

from .models import AppSetting, AuditEvent, utcnow

DEFAULT_SCORE_WEIGHTS = {
    "demand": 0.30,
    "growth": 0.20,
    "competition": 0.15,
    "margin": 0.15,
    "logistics": 0.10,
    "stability": 0.10,
}

DEFAULT_SETTINGS = {
    "score_weights": DEFAULT_SCORE_WEIGHTS,
    "target_markets": ["US"],
    "automation_level": "L1",
    "auto_reply_enabled": False,
    # 第 0 关硬门槛的阈值覆盖。留空 = 用 gate.DEFAULT_LIMITS 里的默认值，
    # 而那些默认值全部标着 to_verify —— 上线前必须换成从平台规则/卖家后台核实过的数字。
    "gate_limits": {},
    "category_defaults": {
        # 各类目的默认采购成本(USD)、默认重量(g)、季节性标记。
        # 注意：这些是**拍的占位值**，不是实测。用了它们的字段会被标成
        # provenance=default，在详情页显示为"类目默认值（拍的）"，
        # 免得看的人把兜底值当成真实报价。
        "diy_party": {"cost": 1.2, "weight_g": 120, "seasonal": True},
        "hair_accessories": {"cost": 0.8, "weight_g": 40, "seasonal": False},
        "home_storage": {"cost": 2.5, "weight_g": 400, "seasonal": False},
        "cleaning_tools": {"cost": 1.5, "weight_g": 200, "seasonal": False},
        "stationery_sewing_garden": {"cost": 1.0, "weight_g": 90, "seasonal": False},
        "default": {"cost": 1.5, "weight_g": 200, "seasonal": False},
    },
}


def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row:
        return row.value
    return DEFAULT_SETTINGS.get(key)


def set_setting(db: Session, key: str, value):
    row = db.get(AppSetting, key)
    if row:
        row.value = value
        row.updated_at = utcnow()
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def init_settings(db: Session):
    for key, value in DEFAULT_SETTINGS.items():
        if not db.get(AppSetting, key):
            db.add(AppSetting(key=key, value=value))
    db.commit()


def record_audit(db: Session, action: str, object_type: str, object_id="",
                 actor: str = "system", before=None, after=None):
    """所有审批/修改/发送/配置变更都必须调用。"""
    db.add(AuditEvent(
        actor=actor, action=action, object_type=object_type,
        object_id=str(object_id), before_data=before or {}, after_data=after or {},
    ))
    db.commit()
