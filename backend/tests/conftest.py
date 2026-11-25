import sys
from pathlib import Path
import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolate_services(monkeypatch):
    """测试不读取个人 .env；漏掉 mock 的 HTTP 请求必须立即失败。"""
    from app.config import Settings, get_settings
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)
    get_settings.cache_clear()
    async def blocked_async(*args, **kwargs):
        raise AssertionError("测试禁止真实网络请求")
    def blocked_sync(*args, **kwargs):
        raise AssertionError("测试禁止真实网络请求")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked_sync)
    yield
    get_settings.cache_clear()
