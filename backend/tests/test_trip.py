"""使用模拟 HTTP + 真正的进程内 MCP 验证工作流，不消耗真实 API 额度。"""
import asyncio
import copy
import json
from contextlib import aclosing
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents import DeepSeekPlanner, TransportPlanningAgent
from app.config import Settings
from app.demo_data import build_demo_trip
from app.errors import ProviderError
from app.main import create_app
from app.mcp_gateway import MCPGateway
from app.orchestrator import TripOrchestrator
from app.providers import AmapProvider
from app.schemas import CityResult, PlanDraft, POI, TripRequest, TripResult

TEST_START = date.today() + timedelta(days=1)
TEST_END = TEST_START + timedelta(days=3)


def request(**overrides):
    return TripRequest(**{"origin_city": "上海", "cities": ["北京", "西安"], "start_date": str(TEST_START), "end_date": str(TEST_END), **overrides})


def config(**overrides):
    return Settings(_env_file=None, **{"demo_mode": False, "deepseek_api_key": "FAKE_DEEPSEEK_SECRET",
                                      "amap_web_service_key": "FAKE_AMAP_SECRET", **overrides})


def draft_data():
    return {"summary": "北京至西安", "itinerary": [
        {"day": i + 1, "date": str(TEST_START + timedelta(days=i)), "city": "北京" if i < 2 else "西安", "theme": "城市探索",
         "activities": [{"time": "09:30", "poi_id": "110000-p1" if i < 2 else "610100-p1", "description": "建议游览", "estimated_cost": 100}]} for i in range(4)],
        "budget": {"accommodation_cny": 1200, "food_cny": 800, "local_transport_cny": 200, "intercity_transport_cny": 1000}}


class MockServices:
    def __init__(self, *, fail=None, models=None):
        self.fail = fail or set()
        self.models = models or [draft_data()]
        self.model_calls = 0
        self.requests = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        path, params = req.url.path, req.url.params
        if path == "/chat/completions":
            body = json.loads(req.content)
            assert body["response_format"] == {"type": "json_object"}
            assert req.headers["authorization"] == "Bearer FAKE_DEEPSEEK_SECRET"
            result = self.models[min(self.model_calls, len(self.models) - 1)]
            self.model_calls += 1
            if isinstance(result, int):
                return httpx.Response(result)
            if result == "timeout":
                raise httpx.ReadTimeout("FAKE_DEEPSEEK_SECRET", request=req)
            if isinstance(result, str) and result in {"empty_content", "truncated_content"}:
                return httpx.Response(200, json={"choices": [{
                    "finish_reason": "length" if result == "truncated_content" else "stop",
                    "message": {"content": "{}" if result == "truncated_content" else ""},
                }]})
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]})
        if path == "/v3/geocode/geo":
            name = params["address"]
            if "city" in self.fail and name == "西安":
                return httpx.Response(403)
            if "all_cities" in self.fail:
                return httpx.Response(503)
            return httpx.Response(200, json={"status": "1", "geocodes": [{"country": "中国", "adcode": "110000" if name == "北京" else "610100", "location": "116.4,39.9" if name == "北京" else "108.9,34.3"}]})
        if path == "/v3/place/text":
            hotel = params["types"] == "100000"
            if hotel and "hotel" in self.fail:
                return httpx.Response(503)
            return httpx.Response(200, json={"status": "1", "pois": [{"id": params["city"] + ("-h1" if hotel else "-p1"), "name": "酒店事实" if hotel else "景点事实", "address": "真实来源地址", "location": "116.4,39.9", "type": "酒店" if hotel else "景点"}]})
        if path == "/v3/weather/weatherInfo":
            if "weather" in self.fail:
                return httpx.Response(200, json={"status": "1", "forecasts": [{"casts": []}]})
            return httpx.Response(200, json={"status": "1", "forecasts": [{"casts": [{"date": str(TEST_START), "dayweather": "晴", "nightweather": "多云", "daytemp": "25", "nighttemp": "18"}]}]})
        if path == "/v1/forecast":
            if "weather" in self.fail:
                return httpx.Response(200, json={"daily": {"time": [], "weather_code": [], "temperature_2m_max": [], "temperature_2m_min": [], "precipitation_probability_max": []}})
            return httpx.Response(200, json={"daily": {"time": [str(TEST_START)], "weather_code": [0], "temperature_2m_max": [25], "temperature_2m_min": [18], "precipitation_probability_max": [0]}})
        if path == "/v3/distance":
            return httpx.Response(200, json={"status": "1", "results": [{"distance": "100000"}]})
        if path == "/v3/direction/transit/integrated":
            if "routes" in self.fail:
                return httpx.Response(429)
            return httpx.Response(200, json={"status": "1", "route": {"transits": [{
                "cost": "180", "duration": "7200",
                "segments": [{"railway": {"name": "铁路示例", "trip": "G示例", "distance": "300000",
                                          "departure_stop": {"name": "起点站"}, "arrival_stop": {"name": "终点站"}}},
                             {"walking": {"steps": [{"instruction": "步行接驳", "polyline": "117,40;108.9,34.3"}]}}]}]}})
        if path == "/direction/v2/transit":
            assert params["ak"] == "FAKE_BAIDU_SECRET"
            assert params["coord_type"] == params["ret_coordtype"] == "gcj02"
            return httpx.Response(200, json={"status": 0, "result": {"routes": [{
                "price": 260, "duration": 8000, "steps": [{"schemes": [{"vehicle_info": {
                    "type": 1, "detail": {"name": "G测试", "departure_station": "出发站", "arrive_station": "到达站"}},
                    "distance": 800000, "duration": 8000}]}],
            }]}})
        if path == "/v3/direction/walking":
            return httpx.Response(200, json={"status": "1", "route": {"paths": []}})
        if path == "/v3/direction/driving":
            return httpx.Response(200, json={"status": "1", "route": {"paths": []}})
        raise AssertionError(f"未模拟的地址路径: {path}")


def collect(services, *, settings=None):
    gateways = []
    class TrackedGateway(MCPGateway):
        async def __aenter__(self):
            gateways.append(self)
            self.closed = False
            return await super().__aenter__()
        async def __aexit__(self, *exc):
            try:
                return await super().__aexit__(*exc)
            finally:
                self.closed = True
    async def run():
        runner = TripOrchestrator(settings or config(),
                                  lambda: httpx.AsyncClient(transport=httpx.MockTransport(services)), TrackedGateway)
        return [event async for event in runner.events(request())]
    return asyncio.run(run()), gateways


@pytest.mark.parametrize("changes", [
    {"cities": []}, {"cities": ["北京", "北京市"]}, {"cities": ["北京", " "]},
    {"cities": ["北京", "西安", "上海"], "end_date": "2099-05-02"},
    {"end_date": "2099-05-15"}, {"end_date": "2099-04-30"},
    {"start_date": "2000-01-01"}, {"travelers": 0}, {"travelers": 11},
    {"budget_cny": 499}, {"budget_cny": 200001}, {"interests": []},
])
def test_input_validation(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_normalization_and_offline_result():
    req = request(cities=[" 北京 ", " 西安 "], budget_cny=500)
    result = build_demo_trip(req)
    assert req.cities == ["北京", "西安"]
    assert result == build_demo_trip(req)
    assert result.data_mode == "demo"
    assert result.budget.estimated_cny > req.budget_cny
    assert "https://" not in result.model_dump_json()
    assert all(city.hotel.photo is None for city in result.cities)


def test_health_validation_and_sse():
    with TestClient(create_app(Settings(_env_file=None, demo_mode=True))) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok", "demo_mode": True}
        bad = request().model_dump(mode="json")
        bad["end_date"] = bad["start_date"]
        assert client.post("/api/v1/trips/plan/stream", json=bad).status_code == 422
        response = client.post("/api/v1/trips/plan/stream", json=request().model_dump(mode="json"))
        assert response.status_code == 200
        events = [json.loads(block.split("data: ")[1]) for block in response.text.strip().split("\n\n")]
        assert [event["type"] for event in events if event["status"] == "running"] == ["attractions", "weather", "hotels", "planning", "transport"]
        assert events[-1]["type"] == "complete"
        TripResult.model_validate(events[-1]["data"])


def test_missing_required_config_fails_before_any_query():
    async def run():
        return [e async for e in TripOrchestrator(Settings(_env_file=None, demo_mode=False)).events(request())]
    events = asyncio.run(run())
    assert len(events) == 1 and events[0].type == "error"
    assert "DEEPSEEK_API_KEY" in events[0].message


def test_full_workflow_uses_mcp_and_validates_result():
    service = MockServices()
    events, gateways = collect(service)
    assert events[-1].type == "complete"
    result = TripResult.model_validate(events[-1].data)
    assert result.budget.estimated_cny == 3600
    assert result.itinerary[0].weather.date == TEST_START
    assert result.itinerary[1].weather is None
    assert result.itinerary[0].activities[0].title == "景点事实"
    assert result.cities[0].hotel.photo is None
    assert result.cities[0].hotel.photo_token is None
    assert result.itinerary[0].photo_token is None
    assert result.intercity_legs[0].distance_km == 100
    assert result.intercity_legs[0].transport.options[0].mode == "rail"
    assert result.intercity_legs[0].transport.options[0].group_cost_cny == 360
    assert result.budget.known_intercity_cny == 720
    assert result.budget.unpriced_intercity_legs == 0
    assert result.intercity_legs[1].transport.departure_date == TEST_START + timedelta(days=2)
    assert set(gateways[0].calls) == {"geocode_city", "search_pois", "get_forecast", "get_distance", "plan_intercity_route", "find_trains"}
    assert not any(item.url.host in {"www.wikidata.org", "commons.wikimedia.org"} for item in service.requests)
    assert gateways[0].closed
    assert service.model_calls == 1
    for warning in [e.message for e in events if e.type == "warning"]:
        assert warning in result.warnings


def test_planned_poi_pairs_are_deferred_until_day_is_opened():
    draft = draft_data()
    second = copy.deepcopy(draft["itinerary"][0]["activities"][0])
    second.update(time="13:30", description="下午参观")
    draft["itinerary"][0]["activities"].append(second)
    service = MockServices(models=[draft])
    events, gateways = collect(service)
    result = TripResult.model_validate(events[-1].data)
    assert events[-1].type == "complete"
    assert result.itinerary[0].local_routes == []
    assert result.itinerary[0].local_route_status == "deferred"
    assert result.itinerary[0].local_route_token
    assert "plan_local_route" not in gateways[0].calls


def test_full_workflow_prefers_baidu_routes_through_mcp():
    service = MockServices()
    events, gateways = collect(service, settings=config(baidu_map_ak="FAKE_BAIDU_SECRET"))
    result = TripResult.model_validate(events[-1].data)
    assert events[-1].type == "complete"
    assert result.intercity_legs[0].transport.options[0].source == "百度地图路线规划"
    assert "plan_intercity_route" in gateways[0].calls
    assert any(item.url.path == "/direction/v2/transit" for item in service.requests)
    assert not any(item.url.path == "/v3/direction/transit/integrated" for item in service.requests)


def test_local_route_does_not_bridge_over_free_activity():
    class Routes:
        local_calls = 0

        async def distance(self, *_args): return 100
        async def intercity_routes(self, *_args): return []
        async def local_route(self, *_args):
            self.local_calls += 1
            return None

    trip = TripRequest(origin_city="上海", cities=["北京"], start_date=TEST_START, end_date=TEST_START)
    draft = PlanDraft.model_validate({"summary": "北京一天", "itinerary": [{
        "day": 1, "date": str(TEST_START), "city": "北京", "theme": "城市探索",
        "activities": [
            {"time": "09:00", "poi_id": "p1", "description": "上午", "estimated_cost": 0},
            {"time": "12:00", "poi_id": None, "description": "自由活动", "estimated_cost": 0},
            {"time": "15:00", "poi_id": "p2", "description": "下午", "estimated_cost": 0},
        ]}], "budget": {"accommodation_cny": 0, "food_cny": 0,
                        "local_transport_cny": 0, "intercity_transport_cny": 0}})
    destination = CityResult(name="北京", location=(116.4, 39.9), attractions=[
        POI(id="p1", name="景点一", address="北京", location=(116.4, 39.9)),
        POI(id="p2", name="景点二", address="北京", location=(116.5, 39.9)),
    ])
    routes = Routes()
    _, local, _ = asyncio.run(TransportPlanningAgent(routes).run(
        CityResult(name="上海", location=(121.5, 31.2)), [destination], draft, trip))
    assert local == {}
    assert routes.local_calls == 0


def test_amap_route_rate_limit_keeps_itinerary_with_warning():
    events, _ = collect(MockServices(fail={"routes"}))
    result = TripResult.model_validate(events[-1].data)
    assert events[-1].type == "complete"
    assert all(leg.transport is None for leg in result.intercity_legs)
    assert result.budget.known_intercity_cny == 0 and result.budget.unpriced_intercity_legs == 2
    assert any("请求过于频繁" in warning or "冷却" in warning for warning in result.warnings)
    assert "FAKE_AMAP_SECRET" not in events[-1].model_dump_json()


@pytest.mark.parametrize("failure", ["weather", "hotel"])
def test_partial_provider_failure_keeps_trip_and_warnings(failure):
    events, _ = collect(MockServices(fail={failure}))
    assert events[-1].type == "complete"
    assert events[-1].data["warnings"]
    assert [c["name"] for c in events[-1].data["cities"]] == request().cities


def test_failed_city_is_preserved_without_invented_coordinates():
    draft = draft_data()
    for day in draft["itinerary"][2:]:
        day["activities"][0]["poi_id"] = None
    events, _ = collect(MockServices(fail={"city"}, models=[draft]))
    result = events[-1].data
    assert events[-1].type == "complete"
    assert result["cities"][1]["name"] == "西安" and result["cities"][1]["location"] is None
    assert result["itinerary"][2]["activities"][0]["location"] is None


def test_no_cities_fails_without_model_call():
    service = MockServices(fail={"all_cities"})
    events, gateways = collect(service)
    assert events[-1].type == "error" and service.model_calls == 0
    assert gateways[0].closed


def test_images_are_lazy():
    service = MockServices()
    events, gateway = collect(service, settings=config())
    assert events[-1].type == "complete"
    assert "resolve_place_photo" not in gateway[0].calls
    assert all(city["hotel"]["photo"] is None for city in events[-1].data["cities"])


@pytest.mark.parametrize("kind", ["empty", "field", "date", "city_order", "poi", "coordinate", "negative_budget"])
def test_bad_llm_outputs_are_rejected_with_two_attempt_cap(kind):
    bad = draft_data()
    if kind == "empty": bad = {}
    elif kind == "field": del bad["budget"]
    elif kind == "date": bad["itinerary"][0]["date"] = str(TEST_START + timedelta(days=1))
    elif kind == "city_order": bad["itinerary"][0]["city"] = "西安"
    elif kind == "poi": bad["itinerary"][0]["activities"][0]["poi_id"] = "invented"
    elif kind == "coordinate": bad["itinerary"][0]["activities"][0]["location"] = [999, 999]
    else: bad["budget"]["food_cny"] = -1
    service = MockServices(models=[bad])
    events, gateways = collect(service)
    assert events[-1].type == "error"
    assert service.model_calls == 2
    assert not any(event.type == "complete" for event in events)
    assert gateways[0].closed


def test_extra_day_annotation_is_ignored_without_second_model_call():
    draft = draft_data()
    draft["itinerary"][0]["summary_placeholder_removed"] = True
    service = MockServices(models=[draft])
    events, _ = collect(service)
    assert events[-1].type == "complete" and service.model_calls == 1
    assert "summary_placeholder_removed" not in events[-1].model_dump_json()


def test_ignored_day_annotation_does_not_hide_invalid_poi():
    draft = draft_data()
    draft["itinerary"][0]["summary_placeholder_removed"] = True
    draft["itinerary"][0]["activities"][0]["poi_id"] = "invented"
    service = MockServices(models=[draft])
    events, _ = collect(service)
    assert events[-1].type == "error" and service.model_calls == 2
    assert "未知或不属于当前城市" in events[-1].message


@pytest.mark.parametrize("first", [{}, 429, "timeout", "empty_content", "truncated_content"])
def test_model_repair_or_transient_retry(first):
    service = MockServices(models=[first, draft_data()])
    events, _ = collect(service)
    assert service.model_calls == 2 and events[-1].type == "complete"


def test_model_receives_verified_day_and_poi_template_and_specific_retry_reason():
    service = MockServices(models=[{}, draft_data()])
    events, _ = collect(service)
    assert events[-1].type == "complete"
    requests = [json.loads(item.content) for item in service.requests if item.url.path == "/chat/completions"]
    first_context = json.loads(requests[0]["messages"][1]["content"])
    assert [item["date"] for item in first_context["day_template"]] == [
        str(TEST_START + timedelta(days=offset)) for offset in range(4)]
    assert [item["city"] for item in first_context["day_template"]] == ["北京", "北京", "西安", "西安"]
    assert first_context["verified_cities"][0]["available_pois"][0]["poi_id"] == "110000-p1"
    assert "缺少字段" in requests[1]["messages"][-1]["content"]


def test_invalid_plan_reports_safe_actionable_reason():
    invalid = draft_data()
    invalid["itinerary"][0]["date"] = str(TEST_START + timedelta(days=1))
    service = MockServices(models=[invalid])
    events, _ = collect(service)
    assert events[-1].type == "error"
    assert "日程编号或日期不连续" in events[-1].message
    assert "FAKE_" not in events[-1].message


@pytest.mark.parametrize("value, count", [(401, 1), (402, 1), (503, 2), ("timeout", 2)])
def test_model_terminal_errors_are_sanitized(value, count, caplog):
    service = MockServices(models=[value])
    events, _ = collect(service)
    assert events[-1].type == "error" and service.model_calls == count
    assert "FAKE_" not in "".join(event.model_dump_json() for event in events) + caplog.text


def test_http_error_does_not_leak_key(caplog):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as client:
            with pytest.raises(ProviderError) as error:
                await AmapProvider(config(), client).geocode("北京")
            return str(error.value)
    assert "FAKE_AMAP_SECRET" not in asyncio.run(run()) + caplog.text


def test_invalid_coordinates_rejected_by_mcp():
    async def run():
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "1", "geocodes": [{"adcode": "110000", "location": "999,999"}]}))
        async with httpx.AsyncClient(transport=transport) as client:
            async with MCPGateway(config(), client) as tools:
                with pytest.raises(ProviderError):
                    await tools.geocode("北京")
    asyncio.run(run())


def test_heartbeat_timeout_and_client_disconnect_release_worker():
    class SlowOrchestrator(TripOrchestrator):
        closed = False
        async def events(self, req):
            try:
                await asyncio.sleep(10)
                yield
            finally:
                self.closed = True
    async def run():
        runner = SlowOrchestrator(config(sse_heartbeat_seconds=0.01, trip_timeout_seconds=0.06))
        items = [item async for item in runner.sse(request())]
        assert any(item.startswith(": heartbeat") for item in items)
        assert sum("event: error" in item for item in items) == 1
        assert runner.closed
        runner = SlowOrchestrator(config(sse_heartbeat_seconds=0.01))
        async with aclosing(runner.sse(request())) as stream:
            assert (await anext(stream)).startswith(": heartbeat")
        assert runner.closed
    asyncio.run(run())
