"""高德 MCP 工具。工厂允许请求级注入客户端，测试和真实调用走相同协议。"""
from contextlib import asynccontextmanager
import httpx
from fastmcp import FastMCP
from app.config import Settings, get_settings
from app.providers import AmapProvider
from .common import envelope


def create_server(settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> FastMCP:
    server = FastMCP("amap-travel-tools")

    @asynccontextmanager
    async def provider():
        config = settings or get_settings()
        if client is not None:
            yield AmapProvider(config, client)
        else:
            async with httpx.AsyncClient() as session:
                yield AmapProvider(config, session)

    @server.tool()
    async def geocode_city(city: str) -> dict:
        """将国内城市解析为坐标和行政区划代码。"""
        async with provider() as api:
            return await envelope(api.geocode(city))

    @server.tool()
    async def search_pois(city: str, keywords: str, types: str = "") -> dict:
        """只在指定城市检索景点或酒店，保留供应商 POI 标识。"""
        async with provider() as api:
            return await envelope(api.search_pois(city, keywords, types))

    @server.tool()
    async def get_weather(city_adcode: str) -> dict:
        """返回全部可用日期的预报，不将今日天气当作未来旅行天气。"""
        async with provider() as api:
            return await envelope(api.weather(city_adcode))

    @server.tool()
    async def get_distance(origin: list[float], destination: list[float]) -> dict:
        """返回城际驾车距离（公里），不代表铁路或飞行距离。"""
        async with provider() as api:
            return await envelope(api.distance(origin, destination))

    @server.tool()
    async def plan_intercity_route(origin: list[float], destination: list[float], origin_city: str,
                                   destination_city: str, departure_date: str | None = None,
                                   travelers: int = 1) -> dict:
        """基于城市中心坐标查询高德国内公交/铁路组合路线，只返回参考方案。"""
        async with provider() as api:
            return await envelope(api.transit_routes(tuple(origin), tuple(destination), origin_city,
                                                     destination_city, departure_date, travelers))

    @server.tool()
    async def plan_local_route(origin: list[float], destination: list[float], city: str, mode: str) -> dict:
        """查询同城公共交通、步行或驾车路线，返回结构化步骤与折线。"""
        async with provider() as api:
            return await envelope(api.local_route(tuple(origin), tuple(destination), city, mode))

    @server.tool()
    async def plan_bicycling(origin: list[float], destination: list[float]) -> dict:
        """只返回骑行估计时长与距离，不返回逐转弯导航内容。"""
        async with provider() as api:
            return await envelope(api.bicycling(tuple(origin), tuple(destination)))

    return server


mcp = create_server()
if __name__ == "__main__":
    mcp.run()
