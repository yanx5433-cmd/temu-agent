"""演示种子数据：覆盖五大第一阶段类目 + 若干应被合规硬过滤拦截的商品。"""
import datetime as dt

from sqlalchemy.orm import Session

from .appsettings import init_settings, record_audit
from .models import KnowledgeDocument, utcnow
from .services.importer import import_signals

# (external_id, title, category, price, sales_30d, growth_7d, reviews, weight_g, cost, material, size, seasonal)
DEMO_PRODUCTS = [
    ("D001", "DIY 手工流苏挂饰材料包", "diy_party", 5.9, 8200, 0.18, 410, 90, 1.3, "棉线/木质圆环", "15x20cm", True),
    ("D002", "派对铝膜数字气球替代-纸拉旗套装", "diy_party", 3.8, 5400, 0.25, 220, 120, 0.9, "卡纸/棉绳", "每套12面", True),
    ("D003", "生日派对装饰彩纸扇花套装", "diy_party", 6.5, 3100, 0.08, 150, 150, 1.4, "纸", "20cm", True),
    ("D004", "成人韩式珍珠发夹套装", "hair_accessories", 4.2, 12000, 0.32, 980, 35, 0.7, "合金/树脂珍珠", "6cm", False),
    ("D005", "成人宽边布艺发带", "hair_accessories", 3.5, 9600, 0.15, 720, 45, 0.6, "涤纶布", "均码", False),
    ("D006", "成人鲨鱼夹粗发抓夹", "hair_accessories", 2.9, 15000, 0.41, 1900, 40, 0.55, "醋酸板材", "11cm", False),
    ("D007", "抽屉分隔收纳盒三件套", "home_storage", 8.9, 6800, 0.12, 560, 420, 2.6, "无纺布/纸板", "30x15x10cm", False),
    ("D008", "桌面化妆品收纳盒（无盖）", "home_storage", 7.2, 4300, 0.05, 300, 500, 2.2, "PS塑料", "24x15x12cm", False),
    ("D009", "缝隙清洁刷组（硬毛+软毛）", "cleaning_tools", 4.5, 7700, 0.22, 640, 110, 1.1, "PP塑料/尼龙刷毛", "18cm", False),
    ("D010", "可重复使用除尘粘尘垫", "cleaning_tools", 5.5, 2900, 0.10, 180, 200, 1.5, "硅胶", "20x15cm", False),
    ("D011", "百叶窗除尘刷", "cleaning_tools", 3.9, 5200, 0.28, 410, 90, 0.9, "PP/棉纱", "16cm", False),
    ("D012", "手账和纸胶带套装", "stationery_sewing_garden", 2.8, 10500, 0.19, 880, 80, 0.5, "和纸", "每卷1.5m", False),
    ("D013", "缝纫手工针线盒套装（含顶针）", "stationery_sewing_garden", 6.8, 3600, 0.09, 260, 260, 1.8, "塑料盒/钢针", "18x11x4cm", False),
    ("D014", "园艺植物绑扎固定夹50个", "stationery_sewing_garden", 3.2, 6100, 0.35, 470, 70, 0.6, "PP塑料", "4cm", False),
    ("D015", "多肉植物移栽小铲三件套", "stationery_sewing_garden", 5.4, 2400, 0.04, 130, 300, 1.6, "不锈钢/木柄", "18cm", False),
    # ---- 以下应被合规硬过滤 REJECT ----
    ("D016", "儿童卡通拼图玩具100片", "diy_party", 7.9, 9000, 0.20, 500, 300, 2.0, "纸板", "20x20cm", False),
    ("D017", "USB充电迷你台灯", "home_storage", 9.9, 8000, 0.15, 400, 350, 3.0, "ABS塑料", "15cm", False),
    ("D018", "玻璃喷雾瓶清洁剂套装", "cleaning_tools", 8.5, 5000, 0.10, 300, 600, 2.4, "玻璃/液体", "500ml", False),
    ("D019", "漫威联名卡通徽章套装", "diy_party", 4.0, 6000, 0.12, 200, 50, 0.8, "锡合金", "5cm", False),
    ("D020", "维生素便携药盒", "home_storage", 2.5, 4000, 0.08, 150, 60, 0.5, "PP塑料", "8cm", False),
]

# 同款重复信号（模拟不同来源抓到同款，验证去重聚类）
DEMO_DUPLICATES = [
    ("T001", "Adult Shark Claw Hair Clip 11cm", "hair_accessories", 3.1, 14000, 0.38, 1750, 40, 0.55, "acetate", "11cm", False),
]


def seed_demo(db: Session) -> dict:
    init_settings(db)
    now = utcnow()
    rows = []
    for i, p in enumerate(DEMO_PRODUCTS):
        ext_id, title, cat, price, sales, growth, reviews, weight, cost, material, size, seasonal = p
        # 两个历史快照，用于增长与波动计算
        for days_ago, factor in ((14, 0.85), (7, 0.93), (0, 1.0)):
            rows.append({
                "source": "demo", "external_id": f"{ext_id}-{days_ago}d",
                "title": title, "category": cat, "price": price,
                "sales_signal": {"sales_30d": int(sales * factor), "growth_7d": growth if days_ago == 0 else round(growth * (0.9 + 0.1 * factor), 3)},
                "review_signal": {"count": int(reviews * factor)},
                "raw_data": {"weight_g": weight, "cost": cost, "material": material, "size": size, "seasonal": seasonal},
                "captured_at": now - dt.timedelta(days=days_ago),
            })
    for ext_id, title, cat, price, sales, growth, reviews, weight, cost, material, size, seasonal in DEMO_DUPLICATES:
        rows.append({
            "source": "connector", "external_id": ext_id, "title": title, "category": cat,
            "price": price, "sales_signal": {"sales_30d": sales, "growth_7d": growth},
            "review_signal": {"count": reviews},
            "raw_data": {"weight_g": weight, "cost": cost, "material": material, "size": size, "seasonal": seasonal},
            "captured_at": now,
        })
    result = import_signals(db, rows)

    if not db.query(KnowledgeDocument).first():
        db.add_all([
            KnowledgeDocument(type="faq", title="发货时效说明", market="ALL",
                              content="商品在付款后48小时内从仓发出，美国一般7-12个工作日送达。时效以平台页面展示为准。",
                              keywords=["发货", "多久", "shipping", "delivery", "到达"]),
            KnowledgeDocument(type="faq", title="工作时间", market="ALL",
                              content="客服工作时间为周一至周五 9:00-18:00（北京时间）。",
                              keywords=["工作时间", "客服", "hours"]),
            KnowledgeDocument(type="policy", title="退款政策（仅限引用，不得自行承诺）", market="ALL",
                              content="退款仅按 TEMU 平台官方政策处理，卖家客服不得自行承诺退款或赔偿金额。",
                              keywords=["退款", "refund"]),
            KnowledgeDocument(type="product", title="发夹套装规格", market="ALL",
                              content="成人韩式珍珠发夹套装共6件，单件长约6厘米，合金材质电镀，附收纳袋。",
                              keywords=["发夹", "珍珠", "尺寸", "几个", "color", "颜色"]),
            KnowledgeDocument(type="product", title="抽屉收纳盒规格", market="ALL",
                              content="抽屉分隔收纳盒三件套，外尺寸30x15x10cm，无纺布材质，不可水洗只可擦拭。",
                              keywords=["收纳盒", "尺寸", "size", "怎么用"]),
        ])
        db.commit()
        record_audit(db, "seed_demo", "system", "seed", after=result)
    return result
