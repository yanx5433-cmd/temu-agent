"""TEMU 官方 API 适配层。

原则：
- 只对接 TEMU 官方 Partner Platform / Open API；禁止调用私有接口、绕过登录或验证码；
- 未获授权的能力一律用 Mock / CSV / 人工模式代替，并在 capabilities 中如实声明；
- 所有网络调用统一超时、重试、限流；失败自动降级，不影响离线选品。
"""
import datetime as dt
import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger("temu_adapter")


class TemuAdapter:
    """统一适配器接口。所有方法返回 (ok: bool, data | None, error: str | None)。"""

    name = "base"

    def authorize(self) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def refresh_token(self) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def list_products(self, page: int = 1) -> tuple[bool, list | None, str | None]:
        raise NotImplementedError

    def get_product(self, product_id: str) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def list_orders(self, page: int = 1) -> tuple[bool, list | None, str | None]:
        raise NotImplementedError

    def get_order(self, order_id: str) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def get_inventory(self, product_id: str) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def get_logistics(self, order_id: str) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def list_messages(self, page: int = 1) -> tuple[bool, list | None, str | None]:
        raise NotImplementedError

    def send_message(self, conversation_id: str, content: str) -> tuple[bool, dict | None, str | None]:
        raise NotImplementedError

    def capabilities(self) -> dict:
        """如实声明各能力的接入状态：available / fallback 方式。"""
        raise NotImplementedError


class MockTemuAdapter(TemuAdapter):
    """演示适配器：返回固定的演示数据，明确标记为 mock。"""

    name = "mock"

    def _mock(self, data):
        return True, data, None

    def authorize(self):
        return self._mock({"status": "mock_authorized", "note": "演示授权，非真实 TEMU 授权"})

    def refresh_token(self):
        return self._mock({"status": "mock_refreshed"})

    def list_products(self, page=1):
        return self._mock([{"product_id": "MOCK-P1", "title": "演示商品A", "stock": 100}])

    def get_product(self, product_id):
        return self._mock({"product_id": product_id, "title": "演示商品", "note": "mock 数据"})

    def list_orders(self, page=1):
        return self._mock([{"order_id": "20240901123", "status": "shipped"}])

    def get_order(self, order_id):
        return self._mock({"order_id": order_id, "status": "shipped", "note": "mock 数据"})

    def get_inventory(self, product_id):
        return self._mock({"product_id": product_id, "stock": 100, "note": "mock 数据"})

    def get_logistics(self, order_id):
        return self._mock({"order_id": order_id, "logistics_status": "运输中", "note": "mock 数据"})

    def list_messages(self, page=1):
        return self._mock([{"conversation_id": "C1", "question": "演示买家消息"}])

    def send_message(self, conversation_id, content):
        return self._mock({"conversation_id": conversation_id, "sent": False,
                           "note": "mock 模式不会真实发送，请在界面使用人工复制回复模式"})

    def capabilities(self):
        return {
            "mode": "MOCK（演示数据，非真实 TEMU 接口）",
            "authorize": {"available": True, "fallback": "mock"},
            "list_products": {"available": True, "fallback": "mock/csv导入"},
            "list_orders": {"available": True, "fallback": "mock/人工"},
            "send_message": {"available": True, "fallback": "人工复制回复"},
            "note": "当前未接入 TEMU 官方 Open API。以上全部为演示数据，不得用于真实运营。",
        }


class OfficialTemuAdapter(TemuAdapter):
    """官方 Open API 适配器骨架：仅在取得 TEMU Partner Platform 授权后可用。

    接口端点以 TEMU 官方文档为准，这里实现统一的带超时/重试/限流的请求通道，
    未开放的具体端点保持 not_available，不得虚构接口可用。
    """

    name = "official"
    BASE_URL = "https://openapi.temu.com"  # 以官方文档公布的域名为准

    def __init__(self, app_key: str, app_secret: str, access_token: str | None = None):
        from ..config import settings

        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.timeout = settings.HTTP_TIMEOUT_SECONDS
        self.max_retries = settings.HTTP_MAX_RETRIES
        self._last_request_ts = 0.0
        self._min_interval = 60.0 / max(1, settings.HTTP_RATE_LIMIT_PER_MIN)

    def _request(self, path: str, payload: dict) -> tuple[bool, dict | None, str | None]:
        # 限流
        wait = self._min_interval - (time.time() - self._last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.time()

        body = json.dumps({"appKey": self.app_key, "accessToken": self.access_token, **payload}).encode()
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    self.BASE_URL + path, data=body,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return True, json.loads(resp.read().decode()), None
            except urllib.error.HTTPError as e:
                last_err = f"TEMU API HTTP {e.code}"
                if e.code < 500:
                    break  # 4xx 不重试
            except Exception as e:  # 超时、网络错误 → 重试
                last_err = f"TEMU API 请求失败: {type(e).__name__}"
            time.sleep(0.5 * (attempt + 1))
        logger.warning("TEMU API %s 失败: %s", path, last_err)
        return False, None, last_err

    def _not_available(self, capability: str):
        return False, None, (
            f"{capability}：TEMU 官方 Open API 能力未开放或未申请。"
            "请使用 CSV 导入或人工模式，禁止使用私有接口。"
        )

    def capabilities(self):
        return {
            "mode": "OFFICIAL（TEMU Partner Platform）",
            "note": "各能力是否可用取决于 TEMU 官方授权范围，未开放的一律走人工/CSV模式。",
        }

    def authorize(self):
        ok, data, err = self._request("/oauth/authorize", {"appSecret": self.app_secret})
        if ok and data:
            self.access_token = data.get("accessToken")
        return ok, data, err

    def refresh_token(self):
        return self._request("/oauth/refreshToken", {})

    def list_products(self, page=1):
        return self._request("/bg.product.list", {"page": page})

    def get_product(self, product_id):
        return self._request("/bg.product.get", {"productId": product_id})

    def list_orders(self, page=1):
        return self._request("/bg.order.list", {"page": page})

    def get_order(self, order_id):
        return self._request("/bg.order.get", {"orderSn": order_id})

    def get_inventory(self, product_id):
        return self._request("/bg.stock.get", {"productId": product_id})

    def get_logistics(self, order_id):
        return self._request("/bg.logistics.get", {"orderSn": order_id})

    def list_messages(self, page=1):
        return self._request("/bg.message.list", {"page": page})

    def send_message(self, conversation_id, content):
        return self._request("/bg.message.send", {"conversationId": conversation_id, "content": content})


def get_adapter(db=None) -> TemuAdapter:
    from ..config import settings

    if settings.TEMU_ADAPTER == "official" and settings.TEMU_APP_KEY:
        return OfficialTemuAdapter(settings.TEMU_APP_KEY, settings.TEMU_APP_SECRET)
    return MockTemuAdapter()
