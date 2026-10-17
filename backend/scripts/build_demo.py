"""由 backend/templates/admin.html 生成在线演示页 demo/index.html。

演示页与本机跑起来的是同一份 UI 代码，这里只做四处替换：
CDN 样式换成本地编译好的 tailwind.css、补一个空 favicon、注入演示横幅、在业务脚本前挂上回放层 shim.js。

    cd backend
    python scripts/build_demo.py
    npx tailwindcss@3.4 -i ../demo/tailwind.input.css -o ../demo/tailwind.css --content "../demo/index.html" --minify
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SRC = BACKEND / "templates" / "admin.html"
OUT = REPO / "demo" / "index.html"

CDN = '<script src="https://cdn.tailwindcss.com"></script>'

BANNER = """<div style="background:#0f172a;color:#e2e8f0;padding:8px 16px;font-size:13px;line-height:1.6">
  <b>在线演示 · 只读回放</b>
  界面与接口响应来自本机真实运行录制（<a style="color:#7dd3fc" href="https://github.com/yanx5433-cmd/temu-agent/blob/main/backend/scripts/capture_demo_snapshot.py">录制脚本</a>），
  数据为脚本生成的演示数据，<b>未接入 TEMU 官方 API</b>，不写库、不发起外部请求。
  评分实验台的重排名是前端真算的，与 <code>services/sensitivity.py</code> 同式。
  <a style="color:#7dd3fc;margin-left:6px" href="https://github.com/yanx5433-cmd/temu-agent">仓库 ↗</a>
</div>"""

SHIM = '<script src="./shim.js"></script>'
STYLES = '<link rel="stylesheet" href="./tailwind.css">'
FAVICON = '<link rel="icon" href="data:,">'


def main() -> int:
    if not SRC.exists():
        print(f"找不到 {SRC}", file=sys.stderr)
        return 1
    html = SRC.read_text(encoding="utf-8")
    if CDN not in html:
        print("admin.html 里的 Tailwind CDN 引用变了，请同步 build_demo.py", file=sys.stderr)
        return 1
    html = html.replace(CDN, STYLES).replace("<head>", "<head>\n" + FAVICON, 1)
    # 横幅紧贴 body 开头，回放层必须在业务脚本之前定义 window.fetch
    html = html.replace('<body class="bg-slate-100 text-slate-800">',
                        '<body class="bg-slate-100 text-slate-800">\n' + BANNER + "\n" + SHIM, 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"已生成 demo/index.html（{OUT.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
