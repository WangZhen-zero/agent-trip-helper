import asyncio

import httpx
import pytest

from app.config import Settings
from app.providers import AmapProvider


def test_amap_transit_route_is_normalized_with_steps_prices_and_geometry():
    payload = {"status": "1", "route": {"transits": [{
        "cost": "220", "duration": "10800", "walking_distance": "300",
        "segments": [
            {"walking": {"distance": "300", "duration": "240", "steps": [{"instruction": "步行至车站", "distance": "300", "duration": "240", "polyline": "116.4,39.9;116.41,39.9"}]}},
            {"railway": {"name": "京沪铁路", "trip": "G1", "distance": "319700",
                          "departure_stop": {"name": "北京南站", "time": "09:00"},
                          "arrival_stop": {"name": "上海虹桥站", "time": "13:30"}}},
        ],
    }]}}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
            return await AmapProvider(Settings(_env_file=None, amap_web_service_key="test"), client).transit_routes(
                (116.4, 39.9), (121.4, 31.2), "北京", "上海", travelers=2)
    routes = asyncio.run(run())
    assert routes[0].mode == "rail"
    assert routes[0].duration_minutes == 180
    assert routes[0].group_cost_cny == 440
    assert routes[0].steps[1].mode == "rail" and routes[0].steps[1].train_trip == "G1"
    assert routes[0].steps[1].departure_stop == "北京南站"
    assert routes[0].distance_m == 320000
    assert len(routes[0].polyline) == 2  # 高德铁路段不提供道路折线，不自行伪造。


def test_amap_empty_transit_routes_return_empty_list():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
                200, json={"status": "1", "route": {"transits": []}}))) as client:
            return await AmapProvider(Settings(_env_file=None, amap_web_service_key="test"), client).transit_routes(
                (116.4, 39.9), (121.4, 31.2), "北京", "上海")
    assert asyncio.run(run()) == []


@pytest.mark.parametrize("mode, endpoint", [("walking", "/v3/direction/walking"), ("driving", "/v3/direction/driving")])
def test_amap_local_routes_include_reference_steps_and_geometry(mode, endpoint):
    payload = {"status": "1", "route": {"paths": [{"distance": "1500", "duration": "600", "tolls": "5",
        "steps": [{"instruction": "沿示例道路前行", "distance": "1500", "duration": "600",
                   "polyline": "116.4,39.9;116.41,39.91"}]}]}}
    async def run():
        def respond(request):
            assert request.url.path == endpoint
            return httpx.Response(200, json=payload)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await AmapProvider(Settings(_env_file=None, amap_web_service_key="test"), client).local_route(
                (116.4, 39.9), (116.41, 39.91), "北京", mode)
    route = asyncio.run(run())
    assert route and route.mode == mode and route.distance_m == 1500
    assert route.polyline == [(116.4, 39.9), (116.41, 39.91)]
    assert route.cost_cny is None
    assert route.toll_cny == (5 if mode == "driving" else None)


def test_amap_bus_route_reads_root_duration_and_nested_busline():
    payload = {"status": "1", "route": {"transits": [{"cost": "4", "duration": "1500", "segments": [{
        "bus": {"buslines": [{"name": "地铁2号线", "type": "地铁线路", "distance": "6000", "duration": "1200",
                             "departure_stop": {"name": "人民广场"}, "arrival_stop": {"name": "陆家嘴"},
                             "polyline": "121.47,31.23;121.5,31.24"}]}}]}]}}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
            return await AmapProvider(Settings(_env_file=None, amap_web_service_key="test"), client).transit_routes(
                (121.47, 31.23), (121.5, 31.24), "上海", "上海")
    options = asyncio.run(run())
    assert options[0].mode == "subway" and options[0].duration_minutes == 25
    assert options[0].cost_cny == 4 and options[0].steps[0].arrival_stop == "陆家嘴"
