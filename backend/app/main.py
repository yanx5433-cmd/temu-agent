"""FastAPI 主应用：API + 中文管理后台 + 启动时种子数据。"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse

from .config import settings
from .db import Base, SessionLocal, engine
from .models import ProductSignal
from .routers.api import router
from .seed import seed_demo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("temu_agent")

app = FastAPI(title=settings.APP_NAME, version="0.1.0")
app.include_router(router)


@app.on_event("startup")
def startup():
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(engine)  # Alembic 迁移同样可用（见 alembic/）
    db = SessionLocal()
    try:
        if not db.query(ProductSignal).first():
            result = seed_demo(db)
            logger.info("已导入演示数据: %s", result)
    finally:
        db.close()


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


@app.get("/", response_class=HTMLResponse)
def admin_page():
    with open(os.path.join(os.path.dirname(__file__), "..", "templates", "admin.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    return {"status": "ok"}
