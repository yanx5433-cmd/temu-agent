"""把后台 API 的真实响应录成静态快照，供 GitHub Pages 离线演示回放。

只读地复制一份 SQLite 库再跑，绝不改动 backend/data/temu_agent.db。

    cd backend
    python scripts/capture_demo_snapshot.py        # → demo/snapshot.json
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SRC_DB = BACKEND / "data" / "temu_agent.db"

# 演示要问的问题：覆盖知识库命中、订单查询、高风险转人工与多语言。
# 客服工作台按 created_at 倒序展示，所以数组最后一条会排在最前——把最完整的例子放后面。
QUESTIONS = [
    "这个能带上飞机吗",
    "¿Cuánto tarda el envío a España?",
    "How long does shipping take to the US?",
    "帮我转人工",
    "我要投诉，东西收到就是坏的",
    "这个电池会不会着火，孩子能用吗",
    "我要退款",
    "这个怎么用，需要充电吗",
    "包装是什么样的，会不会压坏",
    "你们客服几点上班",
    "我的订单 20240901123 现在到哪里了",
    "这款包包的尺寸是多少",
    "这个发夹有哪些颜色可以选",
]


def main() -> int:
    if not SRC_DB.exists():
        print(f"缺少演示库 {SRC_DB}，请先启动一次服务生成演示数据", file=sys.stderr)
        return 1

    tmp_dir = Path(tempfile.mkdtemp(prefix="temu_demo_capture_"))
    work_db = tmp_dir / "capture.db"
    shutil.copyfile(SRC_DB, work_db)
    os.environ["DATABASE_URL"] = f"sqlite:///{work_db.as_posix()}"
    os.environ["LLM_PROVIDER"] = "rule"
    sys.path.insert(0, str(BACKEND))

    from fastapi.testclient import TestClient  # noqa: E402

    from app.main import app  # noqa: E402

    client = TestClient(app)
    gets: dict[str, object] = {}
    posts: dict[str, object] = {}

    def get(path: str):
        r = client.get(f"/api{path}")
        r.raise_for_status()
        gets[path] = r.json()
        return gets[path]

    def post(path: str, body: dict | None = None):
        r = client.post(f"/api{path}", json=body if body is not None else {})
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        return {"status": r.status_code, "body": payload}

    candidates = get("/candidates")["items"]
    ids = [c["id"] for c in candidates]

    # 1) 选品分析：演示里点「▶ 运行选品分析」的回放响应
    posts["/selection/run"] = post("/selection/run")

    # 2) 每个候选的合规复查响应（界面「重新检查」按钮逐条回放）
    posts["/candidates/{id}/compliance-check"] = {str(i): post(f"/candidates/{i}/compliance-check")["body"] for i in ids}

    # 3) 审批：只录一个 TOP 候选，其余由前端做状态变更
    top = next((c["id"] for c in candidates if c["recommendation"] == "TOP"), ids[0])
    posts["/candidates/{id}/approve"] = {"candidate_id": top, "body": post(f"/candidates/{top}/approve?approver=admin")["body"]}

    # 4) 客服：问题 → 会话 + 草稿，成对录制
    convos = []
    for q in QUESTIONS:
        conv = post("/conversations", {"question": q})
        if conv["status"] != 200 or not conv["body"]:
            continue
        draft = post(f"/conversations/{conv['body']['id']}/generate-reply")
        convos.append({"question": q, "conversation": conv["body"], "reply": draft["body"] if draft["status"] == 200 else None})
    posts["/conversations"] = convos
    # 会话列表里已存在的种子会话也要能点「生成/查看回复草稿」，按会话 id 逐条录
    reply_by_conv = {str(c["conversation"]["id"]): c["reply"] for c in convos}
    for cid in [i["id"] for i in client.get("/api/conversations").json()["items"]]:
        if str(cid) not in reply_by_conv:
            reply_by_conv[str(cid)] = post(f"/conversations/{cid}/generate-reply")["body"]
    posts["/conversations/{id}/generate-reply"] = reply_by_conv

    # 5) 接入方式切换：mock / csv / manual 各录一次能力声明
    caps = {}
    for adapter in ("mock", "csv", "manual"):
        res = post("/settings/integrations/temu", {"adapter": adapter})
        caps[adapter] = res["body"] if res["status"] == 200 else {"error": res["status"]}
    posts["/settings/integrations/temu"] = caps
    posts["/settings/integrations/temu/official_without_keys"] = post(
        "/settings/integrations/temu", {"adapter": "official"}
    )

    # 6) 规则配置保存（权重和不为 1 必须被拒，和演示里输入框的校验一致）
    weights = get("/settings")["score_weights"]
    posts["/settings"] = {
        "ok": post("/settings", {"score_weights": weights})["body"],
        "bad_sum": post("/settings", {"score_weights": {k: 0.5 for k in weights}})["body"],
    }

    # 7) 知识库新增回放（前端会真的把它插进列表）
    posts["/knowledge"] = post("/knowledge", {
        "type": "faq", "title": "演示：发夹材质与尺寸", "content": "合金发夹，长约 8cm，单只装 OPP 袋。",
        "keywords": ["发夹", "材质", "尺寸"],
    })["body"]

    # 8) 详情与其余只读页（放在写操作之后，审计页才有完整执行痕迹）
    for i in ids:
        get(f"/candidates/{i}")
    get("/dashboard")
    get("/signals?limit=200")
    get("/conversations")
    get("/knowledge")
    get("/settings")
    get("/settings/integrations")
    get("/audit-events?limit=100")
    get("/scoring/weights-derivation")
    get("/scoring/sensitivity?trials=400&k=5")
    get("/outcomes/report?k=5")

    payload = {
        "captured_at": sqlite3.connect(work_db).execute("select datetime('now')").fetchone()[0],
        "gets": gets,
        "posts": posts,
    }
    out = REPO / "demo"
    out.mkdir(exist_ok=True)
    (out / "snapshot.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    shutil.rmtree(tmp_dir, ignore_errors=True)
    size_kb = (out / "snapshot.json").stat().st_size / 1024
    print(f"已写入 demo/snapshot.json（{size_kb:.0f} KB）· GET {len(gets)} 项 · 候选 {len(ids)} 个 · 客服样例 {len(convos)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
