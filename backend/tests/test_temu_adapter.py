"""TEMU 适配器测试：mock 能力如实声明、official 未授权时失败不虚构。"""
from app.adapters.temu import MockTemuAdapter, OfficialTemuAdapter


def test_mock_capabilities_declare_mock():
    caps = MockTemuAdapter().capabilities()
    assert "MOCK" in caps["mode"]
    assert "不得用于真实运营" in caps["note"]


def test_mock_send_message_does_not_send():
    ok, data, err = MockTemuAdapter().send_message("C1", "hello")
    assert ok
    assert data["sent"] is False


def test_official_fails_without_credentials():
    adapter = OfficialTemuAdapter("test_key", "test_secret")
    # 未开放端点：不得虚构成功。此处 base url 无真实服务，必须失败返回 err
    ok, data, err = adapter.list_products()
    assert not ok and err


def test_adapter_isolation():
    """业务逻辑与接入方式隔离：同一接口不同适配器可替换。"""
    for adapter in (MockTemuAdapter(),):
        for method in ("authorize", "refresh_token"):
            assert callable(getattr(adapter, method))
