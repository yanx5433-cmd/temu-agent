"""应用配置：全部来自环境变量，禁止在代码中保存密钥。"""
import os


class Settings:
    APP_NAME = "TEMU 全托管选品与客服 Agent"
    DATABASE_URL = os.getenv(
        "DATABASE_URL", "sqlite:///./data/temu_agent.db"
    )
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # LLM：llm_provider=rule 表示纯规则实现；openai 兼容接口通过下面三项配置
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "rule")
    LLM_API_BASE = os.getenv("LLM_API_BASE", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")

    # TEMU 接入方式：mock / csv / manual / official（仅在拿到官方授权后启用）
    TEMU_ADAPTER = os.getenv("TEMU_ADAPTER", "mock")
    TEMU_APP_KEY = os.getenv("TEMU_APP_KEY", "")
    TEMU_APP_SECRET = os.getenv("TEMU_APP_SECRET", "")

    # 对外部接口的统一超时/重试/限流
    HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
    HTTP_MAX_RETRIES = int(os.getenv("HTTP_MAX_RETRIES", "2"))
    HTTP_RATE_LIMIT_PER_MIN = int(os.getenv("HTTP_RATE_LIMIT_PER_MIN", "30"))

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    DEFAULT_ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")

    # 自动化等级：L0 仅草稿 / L1 人工确认 / L2 低风险FAQ自动 / L3 高风险永不自动
    DEFAULT_AUTOMATION_LEVEL = os.getenv("DEFAULT_AUTOMATION_LEVEL", "L1")


settings = Settings()
