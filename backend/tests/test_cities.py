"""城市目录与手工校验接口：测试中不读取真实 .env，也不调用真实高德。"""
import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.cities import canonical_city, province_for
from app.config import Settings
from app.errors import ProviderError
from app.main import create_app
from app.schemas import TripRequest


def test_catalog_normalizes_city_and_common_autonomous_prefecture_aliases():
    assert canonical_city(" 北京市 ") == "北京"
    assert canonical_city("大理") == "大理白族自治州"
    assert province_for("大理白族自治州") == "云南"
    assert canonical_city("故宫") is None


def test_trip_request_rejects_non_city_and_canonicalizes_input():
    start, end = date.today() + timedelta(days=1), date.today() + timedelta(days=4)
    request = TripRequest(origin_city="上海", cities=["北京市", "西安市"], start_date=start, end_date=end)
    assert request.cities == ["北京", "西安"]
    with pytest.raises(ValidationError, match="城市级目的地"):
        TripRequest(origin_city="上海", cities=["故宫", "西安"], start_date=start, end_date=end)


def test_demo_city_validation_is_offline_and_returns_canonical_city():
    with TestClient(create_app(Settings(_env_file=None, demo_mode=True))) as client:
        assert client.post("/api/v1/cities/validate", json={"city": "杭州"}).json() == {
            "valid": True, "city": "杭州", "province": "浙江", "message": "已由离线城市名录验证"}
        invalid = client.post("/api/v1/cities/validate", json={"city": "西湖"})
        assert invalid.status_code == 200 and invalid.json()["valid"] is False
        assert client.post("/api/v1/cities/validate", json={"city": " "}).status_code == 422


def test_live_validation_uses_mcp_and_differentiates_service_failure(monkeypatch):
    calls = []

    class FakeGateway:
        failure = None
        def __init__(self, *_args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
        async def geocode(self, city):
            calls.append(city)
            if self.failure:
                raise self.failure
            return object()

    monkeypatch.setattr("app.main.MCPGateway", FakeGateway)
    settings = Settings(_env_file=None, demo_mode=False, amap_web_service_key="FAKE_AMAP_SECRET")
    with TestClient(create_app(settings)) as client:
        ok = client.post("/api/v1/cities/validate", json={"city": "杭州市"})
        assert ok.status_code == 200 and ok.json()["city"] == "杭州" and calls == ["杭州"]
        FakeGateway.failure = ProviderError("高德", "timeout", "请求超时，请稍后重试", retryable=True)
        failed = client.post("/api/v1/cities/validate", json={"city": "南京"})
        assert failed.status_code == 503 and "高德" in failed.json()["detail"]
        assert "FAKE_AMAP_SECRET" not in failed.text
