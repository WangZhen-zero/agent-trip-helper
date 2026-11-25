"""铁路车次、建议式公开契约及天气／骑行修复的离线回归。"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.mcp_gateway import MCPGateway
from app.providers import AmapProvider, OpenMeteoProvider
from app.railgo import RailGoProvider, parse_trains
from app.schemas import LocalRoute, RouteStep, TransportOption
from app.transport_service import TransportService
from app.licensed_collector import collect_approved
from app.errors import ProviderError
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.agents import TransportPlanningAgent
from app.schemas import CityResult, PlanDraft, TripRequest
from app.transport_service import RoutePolicy


TODAY = datetime.now(ZoneInfo("Asia/Shanghai")).date()


def row(number="G123", *, day=0, from_station="北京南", to_station="上海虹桥", runs=True):
    return {"number": number, "rundays": [TODAY.strftime("%Y%m%d")] if runs else [],
            "fromPos": 0, "toPos": 1,
            "timetable": [{"station": from_station, "depart": "08:00", "day": 0},
                          {"station": to_station, "arrive": "13:00", "day": day}]}


def test_railgo_filters_date_station_and_overnight():
    options = parse_trains([row(), row("G456", day=1), row("G888", from_station="天津南"),
                            row("G999", runs=False)], "北京", "上海", str(TODAY), "checked")
    assert [item.service_number for item in options] == ["G123", "G456"]
    assert options[0].arrival_day_offset == 0 and options[1].arrival_day_offset == 1
    assert all(item.cost_cny is None and item.date_verified for item in options)
    assert "timetable" not in options[0].model_dump(mode="json")


def test_railgo_skips_malformed_rows_without_losing_valid_train():
    missing_days = row("G111")
    missing_days["rundays"] = None
    reversed_stops = row("G222")
    reversed_stops["fromPos"], reversed_stops["toPos"] = 1, 0
    options = parse_trains([missing_days, reversed_stops, row("G333")],
                           "北京", "上海", str(TODAY), "checked")
    assert [item.service_number for item in options] == ["G333"]


def test_railgo_mcp_uses_city_and_date_without_exposing_raw_data():
    seen = []
    def respond(request):
        if request.url.host == "data.railgo.zenglingkun.cn":
            seen.append(request)
            return httpx.Response(200, json=[row()])
        raise AssertionError("不应访问其他上游")
    config = Settings(_env_file=None, demo_mode=False, route_min_interval_seconds=0)
    RailGoProvider._cache.clear()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async with MCPGateway(config, client) as tools:
                result = await tools.rail_trains("北京", "上海", str(TODAY))
                return result, tools.calls
    trains, calls = asyncio.run(run())
    assert calls == ["find_trains"] and trains[0].service_number == "G123"
    assert seen[0].url.params["city"] == "true" and seen[0].url.params["date"] == TODAY.strftime("%Y%m%d")
    assert trains[0].steps == [] and trains[0].cost_cny is None


def test_public_route_serialization_has_no_steps_or_polyline():
    option = TransportOption(id="test", mode="rail", summary="铁路参考", steps=[RouteStep(mode="rail", instruction="先到车站")])
    route = LocalRoute(from_point="甲", to_point="乙", mode="transit",
                       steps=[RouteStep(mode="bus", instruction="逐站导航", line_name="12路")],
                       polyline=[(116.4, 39.9), (116.5, 39.9)])
    assert "steps" not in option.model_dump(mode="json")
    assert "steps" not in route.model_dump(mode="json") and "polyline" not in route.model_dump(mode="json")
    assert route.line_names == ["12路"]


def test_open_meteo_requests_sixteen_days_and_wgs84():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"daily": {"time": [str(TODAY)], "weather_code": [0],
            "temperature_2m_min": [10], "temperature_2m_max": [20], "precipitation_probability_max": [0]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await OpenMeteoProvider(Settings(_env_file=None), client).forecast((116.403, 39.915))
    forecast = asyncio.run(run())
    assert forecast[0].date == TODAY
    assert seen[0].url.params["forecast_days"] == "16"
    assert seen[0].url.params["timezone"] == "Asia/Shanghai"
    assert float(seen[0].url.params["longitude"]) < 116.403


def test_short_trip_can_add_supplier_cycling_duration():
    class Tools:
        async def local_route(self, *_):
            return LocalRoute(from_point="甲", to_point="乙", mode="transit", duration_seconds=900)
        async def bicycling(self, *_):
            return LocalRoute(from_point="甲", to_point="乙", mode="bicycling", duration_seconds=660)
    config = Settings(_env_file=None, demo_mode=False, route_min_interval_seconds=0)
    async def run():
        return await TransportService(config, Tools()).local((116.4, 39.9), (116.41, 39.91),
            "北京", "transit", "甲", "乙", allow_cycling=True)
    route, warning = asyncio.run(run())
    assert route.cycling_minutes == 11 and warning is None


def test_bicycling_api_reads_only_supplier_duration():
    payload = {"status": "1", "route": {"paths": [{"distance": "2400", "cost": {"duration": "720"}}]}}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
            return await AmapProvider(Settings(_env_file=None, amap_web_service_key="FAKE"), client).bicycling(
                (116.4, 39.9), (116.41, 39.91))
    route = asyncio.run(run())
    assert route.mode == "bicycling" and route.duration_seconds == 720 and route.cost_cny is None


def test_unapproved_page_collector_fails_closed():
    async def run():
        with pytest.raises(ProviderError, match="尚无获准"):
            await collect_approved("unknown", "北京", "上海", str(TODAY))
    asyncio.run(run())


def test_railgo_timeout_falls_back_to_map_without_inventing_train():
    class Tools:
        async def rail_trains(self, *_):
            raise ProviderError("RailGo", "timeout", "铁路时刻查询超时")
        async def intercity_routes(self, *_):
            return [TransportOption(id="map", mode="rail", summary="G999 09:00", cost_cny=None)]
    config = Settings(_env_file=None, demo_mode=False, route_min_interval_seconds=0)
    async def run():
        return await TransportService(config, Tools()).intercity((116.4, 39.9), (121.5, 31.2),
            "北京", "上海", str(TODAY), 2)
    options, warning = asyncio.run(run())
    assert warning is None and options[0].summary == "铁路出行参考"
    assert options[0].service_number is None and options[0].cost_cny is None


def test_baidu_240_enters_cooldown():
    async def run():
        policy = RoutePolicy(Settings(_env_file=None, route_min_interval_seconds=0))
        calls = 0
        async def failure():
            nonlocal calls
            calls += 1
            raise ProviderError("百度地图", "baidu_240", "路线服务未开通")
        with pytest.raises(ProviderError):
            await policy.call("baidu", failure)
        with pytest.raises(ProviderError, match="冷却"):
            await policy.call("baidu", failure)
        return calls
    assert asyncio.run(run()) == 1


def test_arrival_after_first_activity_is_not_recommended():
    class Tools:
        async def distance(self, *_): return 100.0
        async def rail_trains(self, *_):
            return [TransportOption(id="late", mode="rail", summary="计划车次", service_number="G123",
                departure_time="08:00", arrival_time="13:00", date_verified=True, source="RailGo")]
        async def intercity_routes(self, *_):
            return [TransportOption(id="map", mode="bus", summary="地图参考")]
    request = TripRequest(origin_city="北京", cities=["上海"], start_date=TODAY, end_date=TODAY)
    draft = PlanDraft.model_validate({"summary": "一日游", "itinerary": [{"day": 1, "date": str(TODAY),
        "city": "上海", "theme": "游览", "activities": [{"time": "09:00", "poi_id": "p1",
        "description": "上午", "estimated_cost": 0}]}],
        "budget": {"accommodation_cny": 0, "food_cny": 0, "local_transport_cny": 0,
                   "intercity_transport_cny": 0}})
    config = Settings(_env_file=None, demo_mode=False, route_min_interval_seconds=0)
    async def run():
        return await TransportPlanningAgent(Tools(), config).run(
            CityResult(name="北京", location=(116.4, 39.9)),
            [CityResult(name="上海", location=(121.5, 31.2))], draft, request)
    legs, _, _ = asyncio.run(run())
    assert legs[0].transport.options[0].id == "map"


def test_public_demo_transport_omits_navigation_details():
    config = Settings(_env_file=None, demo_mode=True)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/transport/plan", json={"from": "北京", "to": "上海",
            "departure_date": str(TODAY), "travelers": 2})
    assert response.status_code == 200
    option = response.json()["options"][0]
    assert "steps" not in option and "polyline" not in option
