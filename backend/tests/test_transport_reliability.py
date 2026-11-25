"""交通供应商响应、回退与按天凭证测试；全部使用虚构密钥和模拟请求。"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo_data import build_demo_trip
from app.errors import ProviderError
from app.main import create_app
from app.mcp_gateway import MCPGateway
from app.providers import AmapProvider, BaiduProvider
from app.route_tokens import issue_day_token, verify_day_token
from app.schemas import LocalRoute, TransportOption, TripRequest
from app.transport_service import RoutePolicy, TransportService
from app.agents import TransportPlanningAgent
from app.schemas import CityResult, PlanDraft, POI


def settings(**values):
    return Settings(_env_file=None, demo_mode=False, amap_web_service_key="FAKE_AMAP_KEY",
                    baidu_map_ak="FAKE_BAIDU_AK", route_min_interval_seconds=0, **values)


def test_amap_skips_bad_candidate_and_accepts_missing_price():
    payload = {"status": "1", "route": {"transits": [
        {"segments": "bad"},
        {"cost": [], "duration": "1200", "segments": [{"bus": {"buslines": [
            {"name": "地铁 1 号线", "type": "地铁", "distance": "5000", "polyline": "116.4,39.9;116.5,39.9"}
        ]}}]},
    ]}}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            return await AmapProvider(settings(), client).transit_routes((116.4, 39.9), (116.5, 39.9), "北京", "北京")

    options = asyncio.run(run())
    assert len(options) == 1 and options[0].mode == "subway"
    assert options[0].cost_cny is None and options[0].duration_minutes == 20


@pytest.mark.parametrize("code,expected", [("10002", "接口未开通"), ("10004", "分钟调用量"),
                                           ("10021", "QPS"), ("10003", "日调用量"),
                                           ("20000", "参数无效")])
def test_amap_error_code_is_safe_and_not_duplicated(code, expected):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
                200, json={"status": "0", "infocode": code, "info": "FAKE_AMAP_KEY"}))) as client:
            async with MCPGateway(settings(), client) as gateway:
                with pytest.raises(ProviderError) as caught:
                    await gateway.intercity_routes((116.4, 39.9), (104.1, 30.7), "北京", "成都")
                return caught.value

    error = asyncio.run(run())
    assert error.code == f"amap_{code}" and expected in str(error)
    assert str(error).count("高德：") == 1 and "FAKE_AMAP_KEY" not in str(error)


@pytest.mark.parametrize("vehicle_type,mode", [(1, "rail"), (2, "air"), (6, "coach")])
def test_baidu_intercity_modes_price_and_gcj02(vehicle_type, mode):
    seen = []
    payload = {"status": 0, "result": {"routes": [{"duration": 7200, "distance": 1000000,
        "price": 350, "steps": [{"schemes": [{"vehicle_info": {"type": vehicle_type,
            "detail": {"name": "G123" if mode == "rail" else "CA123" if mode == "air" else "大巴班次",
                       "departure_station": "北京站", "arrive_station": "成都站", "departure_time": "09:00"}},
            "distance": 1000000, "duration": 7200}]}]}]}}

    async def run():
        def respond(request):
            seen.append(request)
            return httpx.Response(200, json=payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await BaiduProvider(settings(), client).transit_routes(
                (116.4, 39.9), (104.1, 30.7), "2026-09-25", 2)

    options = asyncio.run(run())
    assert options[0].mode == mode and options[0].group_cost_cny == 700
    assert seen[0].url.params["origin"] == "39.900000,116.400000"
    assert seen[0].url.params["coord_type"] == seen[0].url.params["ret_coordtype"] == "gcj02"
    assert options[0].steps[0].departure_stop == "北京站"


def test_baidu_intercity_step_level_substeps_and_numeric_string_type():
    payload = {"status": 0, "result": {"routes": [{"duration": "7200", "price": None, "steps": [
        {"sub_steps": [
            {"vehicle_info": {"type": "5"}, "instructions": "步行至车站"},
            {"vehicle_info": {"type": "1", "detail": {"name": "G123", "departure_station": "北京南站"}}},
        ]},
    ]}]}}
    options = BaiduProvider._options(payload, 2)
    assert len(options) == 1 and options[0].mode == "rail"
    assert [step.mode for step in options[0].steps] == ["walking", "rail"]
    assert options[0].cost_cny is None and options[0].steps[1].train_trip == "G123"


@pytest.mark.parametrize("code,reason", [(2, "参数"), (3, "权限"), (5, "AK"),
                                        (301, "总配额"), (302, "日配额"), (401, "并发")])
def test_baidu_safe_status_mapping(code, reason):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
                200, json={"status": code, "message": "FAKE_BAIDU_AK"}))) as client:
            with pytest.raises(ProviderError) as caught:
                await BaiduProvider(settings(), client).transit_routes((116.4, 39.9), (104.1, 30.7))
            return caught.value
    error = asyncio.run(run())
    assert error.code == f"baidu_{code}" and reason in str(error)
    assert "FAKE_BAIDU_AK" not in str(error)


def test_baidu_failure_falls_back_to_amap_without_inventing_price():
    class Tools:
        async def baidu_intercity_routes(self, *_):
            raise ProviderError("百度地图", "baidu_1", "服务不可用")
        async def intercity_routes(self, *_):
            return [TransportOption(id="amap-0", mode="rail", summary="铁路接驳", cost_cny=None)]

    async def run():
        return await TransportService(settings(), Tools()).intercity((116.4, 39.9), (104.1, 30.7),
                                                                     "北京", "成都", "2026-09-25", 2)

    options, warning = asyncio.run(run())
    assert options[0].cost_cny is None and warning is None


def test_transport_preference_falls_back_when_baidu_has_only_other_mode():
    class Tools:
        async def baidu_intercity_routes(self, *_):
            return [TransportOption(id="baidu-air", mode="air", summary="航空参考")]
        async def intercity_routes(self, *_):
            return [TransportOption(id="amap-rail", mode="rail", summary="铁路参考")]

    async def run():
        return await TransportService(settings(), Tools()).intercity(
            (116.4, 39.9), (104.1, 30.7), "北京", "成都", "2026-09-25", 2, "rail")

    options, warning = asyncio.run(run())
    assert [option.id for option in options] == ["amap-rail"]
    assert warning is None


def test_fourteen_day_generation_never_queries_local_routes():
    class Tools:
        async def distance(self, *_): return 100
        async def intercity_routes(self, *_):
            return [TransportOption(id="route", mode="rail", summary="铁路参考")]
        async def local_route(self, *_):
            raise AssertionError("生成阶段不能批量请求市内路线")

    start = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    request = TripRequest(origin_city="上海", cities=["北京"], start_date=start,
                          end_date=start + timedelta(days=13))
    itinerary = [{"day": i + 1, "date": str(start + timedelta(days=i)), "city": "北京",
                  "theme": "城市游览", "activities": [
                      {"time": "09:00", "poi_id": "p1", "description": "上午", "estimated_cost": 0},
                      {"time": "13:00", "poi_id": "p2", "description": "下午", "estimated_cost": 0},
                  ]} for i in range(14)]
    draft = PlanDraft.model_validate({"summary": "十四天", "itinerary": itinerary,
                                     "budget": {"accommodation_cny": 0, "food_cny": 0,
                                                "local_transport_cny": 0, "intercity_transport_cny": 0}})
    city = CityResult(name="北京", location=(116.4, 39.9), attractions=[
        POI(id="p1", name="景点一", address="北京", location=(116.4, 39.9)),
        POI(id="p2", name="景点二", address="北京", location=(116.5, 39.9)),
    ])
    no_baidu = Settings(_env_file=None, demo_mode=False, amap_web_service_key="FAKE", route_min_interval_seconds=0)
    legs, local, _ = asyncio.run(TransportPlanningAgent(Tools(), no_baidu).run(
        CityResult(name="上海", location=(121.5, 31.2)), [city], draft, request))
    assert len(legs) == 1 and local == {}


def test_amap_minute_limit_stops_followup_requests():
    async def run():
        policy = RoutePolicy(settings())
        calls = 0
        async def failure():
            nonlocal calls
            calls += 1
            raise ProviderError("高德", "amap_10004", "分钟调用量已超限")
        with pytest.raises(ProviderError, match="分钟调用量"):
            await policy.call("amap", failure)
        with pytest.raises(ProviderError, match="冷却"):
            await policy.call("amap", failure)
        return calls
    assert asyncio.run(run()) == 1


def test_baidu_quota_error_stops_followup_requests():
    async def run():
        policy = RoutePolicy(settings())
        calls = 0
        async def failure():
            nonlocal calls
            calls += 1
            raise ProviderError("百度地图", "baidu_302", "日配额已超限")
        with pytest.raises(ProviderError, match="日配额"):
            await policy.call("baidu", failure)
        with pytest.raises(ProviderError, match="冷却"):
            await policy.call("baidu", failure)
        return calls
    assert asyncio.run(run()) == 1


def test_signed_day_token_prevents_tampering_and_local_routes_are_cached(monkeypatch):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    trip = TripRequest(origin_city="上海", cities=["北京"], start_date=today, end_date=today)
    config = settings(route_token_secret="unit-test-secret")
    day = build_demo_trip(trip).itinerary[0]
    token = issue_day_token(day, "transit", config, now=1000)
    assert token and verify_day_token(token, config, now=1001)["city"] == "北京"
    with pytest.raises(ValueError): verify_day_token(token[:-2] + "xx", config, now=1001)
    with pytest.raises(ValueError, match="过期"): verify_day_token(token, config, now=1000 + 24 * 3600 + 1)

    live_token = issue_day_token(day, "transit", config)
    calls = []

    class Gateway:
        def __init__(self, *_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def local_route(self, origin, destination, city, mode, from_point, to_point):
            calls.append((city, from_point, to_point))
            return LocalRoute(from_point=from_point, to_point=to_point, mode=mode, source="测试地图")

    import app.main as main_module
    monkeypatch.setattr(main_module, "MCPGateway", Gateway)
    with TestClient(create_app(config)) as client:
        first = client.post("/api/v1/transport/local/day", json={"day_token": live_token})
        second = client.post("/api/v1/transport/local/day", json={"day_token": live_token})
        bad = client.post("/api/v1/transport/local/day", json={"day_token": live_token[:-2] + "xx"})
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "ready" and first.json() == second.json()
    assert len(calls) == 1 and bad.status_code == 422
