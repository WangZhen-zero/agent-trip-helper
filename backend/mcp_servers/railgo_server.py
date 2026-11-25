"""RailGo MCP 工具：只接受已验证的国内城市和近期日期。"""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from datetime import datetime

import httpx
from fastmcp import FastMCP

from app.cities import canonical_city
from app.config import Settings, get_settings
from app.errors import ProviderError
from app.railgo import RailGoProvider
from .common import envelope


def create_server(settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> FastMCP:
    server = FastMCP("railgo-travel-trains")

    @asynccontextmanager
    async def provider():
        config = settings or get_settings()
        if client is not None:
            yield RailGoProvider(client, config.provider_timeout_seconds)
        else:
            async with httpx.AsyncClient(trust_env=False) as session:
                yield RailGoProvider(session, config.provider_timeout_seconds)

    @server.tool()
    async def find_trains(origin_city: str, destination_city: str, departure_date: str) -> dict:
        """返回选定日期的少量车次建议，而非票务或余票接口。"""
        async def query():
            origin, destination = canonical_city(origin_city), canonical_city(destination_city)
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
            try:
                target = date.fromisoformat(departure_date)
            except ValueError:
                raise ProviderError("RailGo", "date", "出发日期格式无效") from None
            if not origin or not destination or origin == destination or not today <= target <= today + timedelta(days=15):
                raise ProviderError("RailGo", "request", "仅支持未来 15 天内不同的中国大陆城市")
            async with provider() as api:
                return await api.trains(origin, destination, departure_date)
        return await envelope(query())

    return server


mcp = create_server()
if __name__ == "__main__":
    mcp.run()
