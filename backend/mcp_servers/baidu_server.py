"""百度地图路线 MCP 工具；只在配置 AK 后发起 HTTP 请求。"""
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP

from app.config import Settings, get_settings
from app.providers import BaiduProvider
from .common import envelope


def create_server(settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> FastMCP:
    server = FastMCP("baidu-travel-routes")

    @asynccontextmanager
    async def provider():
        config = settings or get_settings()
        if client is not None:
            yield BaiduProvider(config, client)
        else:
            async with httpx.AsyncClient(trust_env=False) as session:
                yield BaiduProvider(config, session)

    @server.tool()
    async def plan_intercity_route(origin: list[float], destination: list[float],
                                   departure_date: str | None = None, travelers: int = 1) -> dict:
        async with provider() as api:
            return await envelope(api.transit_routes(tuple(origin), tuple(destination), departure_date, travelers))

    @server.tool()
    async def plan_local_route(origin: list[float], destination: list[float], mode: str) -> dict:
        async with provider() as api:
            return await envelope(api.local_route(tuple(origin), tuple(destination), mode))

    return server


mcp = create_server()
if __name__ == "__main__":
    mcp.run()
