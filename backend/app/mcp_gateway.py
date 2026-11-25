"""按请求管理 MCP 连接；业务 Agent 不直接调用 HTTP Provider。"""
from contextlib import AsyncExitStack
from typing import Annotated
import warnings
import httpx
from pydantic import Field, TypeAdapter, ValidationError
from .config import Settings
from .errors import ProviderError
from .schemas import Geocode, LocalRoute, POI, TransportOption, Weather


class MCPGateway:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient):
        self.settings, self.http_client = settings, http_client
        self.stack = AsyncExitStack()
        self.clients = {}
        self.calls: list[str] = []

    async def __aenter__(self):
        try:
            # Authlib 导入时会主动将其弃用警告设为 always；先加载警告类型，
            # 再仅对固定版 FastMCP 导入链中的两条已知提示做精确过滤。
            from authlib.deprecate import AuthlibDeprecationWarning
            with warnings.catch_warnings():
                for message in (r"authlib\.jose module is deprecated, please use joserfc instead\.",
                                r"The httpx module is deprecated; please use httpx2 instead\."):
                    warnings.filterwarnings("ignore", message=message, category=AuthlibDeprecationWarning)
                from fastmcp import Client
                from mcp_servers.amap_server import create_server as amap_server
                from mcp_servers.openmeteo_server import create_server as weather_server
                from mcp_servers.baidu_server import create_server as baidu_server
                from mcp_servers.railgo_server import create_server as railgo_server
        except ImportError:
            raise ProviderError("MCP", "dependency", "MCP 运行依赖不完整，请在当前 Conda 环境安装 backend/requirements.txt") from None
        try:
            # 同一任务进入/退出异步上下文，避免取消时跨任务关闭 AnyIO cancel scope。
            for name, factory in (("amap", amap_server), ("openmeteo", weather_server),
                                  ("baidu", baidu_server), ("railgo", railgo_server)):
                server = factory(self.settings, self.http_client)
                self.clients[name] = await self.stack.enter_async_context(Client(server, timeout=self.settings.provider_timeout_seconds + 3))
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *exc):
        return await self.stack.__aexit__(*exc)

    async def _call(self, server: str, name: str, arguments: dict, result_type):
        self.calls.append(name)
        try:
            result = await self.clients[server].call_tool(name, arguments)
            payload = result.data
            if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
                raise ValueError()
            if not payload["ok"]:
                error = payload["error"]
                # 工具已剔除原始异常、密钥和请求 URL。
                raise ProviderError(error["service"], error["code"], error["message"])
            return TypeAdapter(result_type).validate_python(payload["data"])
        except ProviderError:
            raise
        except (ValueError, KeyError, TypeError, ValidationError):
            raise ProviderError("MCP", "invalid_response", "工具返回数据未通过校验") from None
        except Exception:
            raise ProviderError("MCP", "connection", "工具连接失败或调用超时") from None

    async def geocode(self, city: str) -> Geocode:
        return await self._call("amap", "geocode_city", {"city": city}, Geocode)

    async def search_pois(self, city: str, keywords: str, types: str) -> list[POI]:
        return await self._call("amap", "search_pois", {"city": city, "keywords": keywords, "types": types}, list[POI])

    async def weather(self, location, start_date=None, end_date=None) -> list[Weather]:
        return await self._call("openmeteo", "get_forecast", {"location": list(location), "start_date": str(start_date) if start_date else None, "end_date": str(end_date) if end_date else None}, list[Weather])

    async def distance(self, origin, destination) -> float:
        return await self._call("amap", "get_distance", {"origin": origin, "destination": destination}, Annotated[float, Field(ge=0, allow_inf_nan=False)])

    async def rail_trains(self, origin_city: str, destination_city: str,
                          departure_date: str) -> list[TransportOption]:
        return await self._call("railgo", "find_trains", {
            "origin_city": origin_city, "destination_city": destination_city,
            "departure_date": departure_date,
        }, list[TransportOption])

    async def intercity_routes(self, origin, destination, origin_city: str, destination_city: str,
                               departure_date: str | None = None, travelers: int = 1) -> list[TransportOption]:
        return await self._call("amap", "plan_intercity_route", {
            "origin": list(origin), "destination": list(destination), "origin_city": origin_city,
            "destination_city": destination_city, "departure_date": departure_date, "travelers": travelers,
        }, list[TransportOption])

    async def local_route(self, origin, destination, city: str, mode: str, from_point: str, to_point: str) -> LocalRoute | None:
        route = await self._call("amap", "plan_local_route", {
            "origin": list(origin), "destination": list(destination), "city": city, "mode": mode,
        }, LocalRoute | None)
        if route:
            route.from_point, route.to_point = from_point, to_point
        return route

    async def bicycling(self, origin, destination, from_point: str, to_point: str) -> LocalRoute | None:
        route = await self._call("amap", "plan_bicycling", {
            "origin": list(origin), "destination": list(destination),
        }, LocalRoute | None)
        if route:
            route.from_point, route.to_point = from_point, to_point
        return route

    async def baidu_intercity_routes(self, origin, destination, departure_date: str | None,
                                     travelers: int) -> list[TransportOption]:
        return await self._call("baidu", "plan_intercity_route", {
            "origin": list(origin), "destination": list(destination),
            "departure_date": departure_date, "travelers": travelers,
        }, list[TransportOption])

    async def baidu_local_route(self, origin, destination, mode: str,
                                from_point: str, to_point: str) -> LocalRoute | None:
        route = await self._call("baidu", "plan_local_route", {
            "origin": list(origin), "destination": list(destination), "mode": mode,
        }, LocalRoute | None)
        if route:
            route.from_point, route.to_point = from_point, to_point
        return route
