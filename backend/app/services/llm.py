"""统一 LLMProvider 接口。

约束：大模型只负责语义分类、信息提取、趋势解释和回复润色；
销量/价格/利润/合规结论等数值一律由程序规则计算，本模块禁止产出任何编造数值。
默认 RuleLLMProvider 为纯规则实现，可离线运行。
"""
import json
import os


class LLMProvider:
    name = "base"

    def classify(self, text: str, labels: list[str], instructions: str = "") -> str:
        raise NotImplementedError

    def polish_reply(self, reply: str, language: str) -> str:
        """对模板生成的回复做语气润色。不得改变事实内容。"""
        raise NotImplementedError


class RuleLLMProvider(LLMProvider):
    """规则实现：不依赖外部服务，永远可用（错误降级的最终兜底）。"""

    name = "rule"

    def classify(self, text: str, labels: list[str], instructions: str = "") -> str:
        text_low = text.lower()
        for label in labels:
            for kw in _label_keywords(label):
                if kw in text_low:
                    return label
        return labels[0] if labels else "unknown"

    def polish_reply(self, reply: str, language: str) -> str:
        return reply  # 模板本身已符合简洁礼貌要求


def _label_keywords(label: str) -> list[str]:
    return LABEL_KEYWORDS.get(label, [label])


LABEL_KEYWORDS = {
    "size": ["尺寸", "大小", "多少厘米", "inch", "cm", "size", "dimension", "medida"],
    "color": ["颜色", "colour", "color", "color"],
    "packaging": ["几个", "数量", "包装", "一套", "pieces", "pack", "qty", "quantity"],
    "shipping_time": ["发货", "物流", "几天", "多久", "到达", "shipping", "delivery", "arrive", "envío"],
    "usage": ["怎么用", "使用方法", "说明书", "how to use", "instruction"],
    "work_hours": ["工作时间", "上班", "客服时间", "office hours", "working hours"],
    "order_status": ["订单", "物流单号", "tracking", "order", "parcel", "pedido"],
    "refund_compensation": ["退款", "赔偿", "退货", "refund", "compensation", "reembolso"],
    "complaint_escalation": ["投诉", "差评", "举报", "complaint", "report you"],
    "safety": ["受伤", "着火", "安全", "injur", "fire", "danger", "hurt"],
    "legal": ["律师", "起诉", "法律", "lawyer", "lawsuit", "legal"],
    "address_change": ["改地址", "修改地址", "change address", "address change"],
    "human_request": ["人工", "真人客服", "human", "agent please", "real person"],
}


class OpenAICompatProvider(RuleLLMProvider):
    """OpenAI 兼容接口实现（可选）。配置了 LLM_API_BASE/KEY 时启用；
    调用失败时自动降级为规则实现。"""

    name = "openai_compat"

    def __init__(self):
        from ..config import settings

        self.api_base = settings.LLM_API_BASE
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.timeout = settings.HTTP_TIMEOUT_SECONDS

    def classify(self, text: str, labels: list[str], instructions: str = "") -> str:
        try:
            import urllib.request

            payload = json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": (instructions or "你是分类器。只输出一个标签，不要解释。")
                     + f" 可选标签：{labels}。不要输出任何数字或编造事实。"},
                    {"role": "user", "content": text[:2000]},
                ],
                "temperature": 0,
            }).encode()
            req = urllib.request.Request(
                self.api_base.rstrip("/") + "/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            out = data["choices"][0]["message"]["content"].strip()
            return out if out in labels else super().classify(text, labels, instructions)
        except Exception:
            return super().classify(text, labels, instructions)

    def polish_reply(self, reply: str, language: str) -> str:
        try:
            import urllib.request

            payload = json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "润色客服回复，保持原意与所有事实/数字不变，简洁礼貌，"
                     f"用 {language} 回复。只输出润色后的文本。"},
                    {"role": "user", "content": reply},
                ],
                "temperature": 0.3,
            }).encode()
            req = urllib.request.Request(
                self.api_base.rstrip("/") + "/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"].strip() or reply
        except Exception:
            return reply


def get_llm() -> LLMProvider:
    from ..config import settings

    if settings.LLM_PROVIDER == "openai" and settings.LLM_API_BASE:
        return OpenAICompatProvider()
    return RuleLLMProvider()
