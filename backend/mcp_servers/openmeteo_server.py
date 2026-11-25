"""Open-Meteo MCP 工具：天气服务不保存用户位置，坐标只在单次请求内使用。"""
from contextlib import asynccontextmanager
import httpx
from fastmcp import FastMCP
from app.config import Settings, get_settings
from app.providers import OpenMeteoProvider
from .common import envelope


def create_server(settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> FastMCP:
    server = FastMCP("openmeteo-travel-tools")
    @asynccontextmanager
    async def provider():
        if client is not None:
            yield OpenMeteoProvider(settings or get_settings(), client)
        else:
            async with httpx.AsyncClient(trust_env=False) as session:
                yield OpenMeteoProvider(settings or get_settings(), session)
    @server.tool()
    async def get_forecast(location: list[float], start_date: str | None = None, end_date: str | None = None) -> dict:
        """按经纬度返回逐日预报，日期超出供应商范围时返回可用日期。"""
        async with provider() as api:
            return await envelope(api.forecast((float(location[0]), float(location[1])), start_date, end_date))
    return server


mcp = create_server()
if __name__ == "__main__": mcp.run()
