"""统一的路线选择、降级和供应商限速；MCP Gateway 仍是唯一外部调用边界。"""
import asyncio
import math
import time
from collections.abc import Awaitable, Callable

from .config import Settings
from .errors import ProviderError
from .schemas import LocalRoute, TransportOption


class RoutePolicy:
    def __init__(self, settings: Settings):
        self.interval = settings.route_min_interval_seconds
        self._next = {"amap": 0.0, "baidu": 0.0}
        self._blocked = {"amap": 0.0, "baidu": 0.0}
        self._lock = asyncio.Lock()

    async def call(self, provider: str, operation: Callable[[], Awaitable]):
        async with self._lock:
            now = time.monotonic()
            if now < self._blocked[provider]:
                raise ProviderError("高德" if provider == "amap" else "百度地图", "cooldown", "供应商限流冷却中")
            scheduled = max(now, self._next[provider])
            self._next[provider] = scheduled + self.interval
        if scheduled > now:
            await asyncio.sleep(scheduled - now)
        # 排队期间其他请求可能已触发配额冷却；出站前再检查一次。
        async with self._lock:
            if time.monotonic() < self._blocked[provider]:
                raise ProviderError("高德" if provider == "amap" else "百度地图", "cooldown", "供应商限流冷却中")
        try:
            return await operation()
        except ProviderError as exc:
            delay = (60 if exc.code in {"amap_10004", "http_429"} else
                     3 if exc.code in {"amap_10021", "baidu_401", "baidu_402"} else
                     6 * 3600 if exc.code in {"amap_10003", "amap_10044", "amap_40000",
                     "baidu_4", "baidu_240", "baidu_301", "baidu_302"} else 0)
            if delay:
                async with self._lock:
                    self._blocked[provider] = max(self._blocked[provider], time.monotonic() + delay)
            raise


class TransportService:
    def __init__(self, settings: Settings, tools, policy: RoutePolicy | None = None):
        self.settings, self.tools = settings, tools
        self.policy = policy or RoutePolicy(settings)

    async def intercity(self, origin, destination, origin_city: str, destination_city: str,
                        departure_date: str, travelers: int, mode: str = "all") -> tuple[list[TransportOption], str | None]:
        failures = []
        trains: list[TransportOption] = []
        if mode in {"all", "rail"} and self.settings.railgo_enabled and hasattr(self.tools, "rail_trains"):
            try:
                trains = await self.tools.rail_trains(origin_city, destination_city, departure_date)
            except ProviderError as exc:
                failures.append(exc)
        if trains and mode == "rail":
            return trains[:3], None
        maps: list[TransportOption] = []
        if self.settings.baidu_map_ak:
            try:
                options = await self.policy.call("baidu", lambda: self.tools.baidu_intercity_routes(
                    origin, destination, departure_date, travelers))
                options = [item for item in options if mode == "all" or item.mode == mode]
                if options:
                    maps = options
            except ProviderError as exc:
                failures.append(exc)
        if not maps:
            try:
                maps = await self.policy.call("amap", lambda: self.tools.intercity_routes(
                    origin, destination, origin_city, destination_city, departure_date, travelers))
                maps = [item for item in maps if mode == "all" or item.mode == mode]
            except ProviderError as exc:
                failures.append(exc)
        # 地图数据只作方式、时间与参考费用建议；车次和计划时刻只能来自日期核验的来源。
        for item in maps:
            if item.steps:
                item.line_names = list(dict.fromkeys(step.line_name for step in item.steps
                                                     if step.mode in {"bus", "subway"} and step.line_name))[:3]
            item.summary = {"rail": "铁路出行参考", "air": "航空出行参考", "coach": "大巴出行参考",
                            "bus": "公交出行参考", "subway": "地铁出行参考"}.get(item.mode, "公共交通参考")
            item.service_number = item.departure_time = item.arrival_time = None
            item.departure_stop = item.arrival_stop = None
            item.date_verified = False
        if trains or maps:
            # RailGo 不提供票价，不把地图路线报价归到具体车次名下。
            return trains[:3] + [item for item in maps if not trains or item.mode != "rail"][:2], None
        if failures:
            return [], "；".join(str(item) for item in failures)
        return [], "两家地图服务均未返回符合条件的路线" if self.settings.baidu_map_ak else "高德未返回符合条件的路线"

    async def local(self, origin, destination, city: str, mode: str,
                    from_point: str, to_point: str, allow_cycling: bool = False) -> tuple[LocalRoute | None, str | None]:
        failures = []
        route = None
        try:
            route = await self.policy.call("amap", lambda: self.tools.local_route(
                origin, destination, city, mode, from_point, to_point))
        except ProviderError as exc:
            failures.append(exc)
        if route is None and self.settings.baidu_map_ak:
            try:
                route = await self.policy.call("baidu", lambda: self.tools.baidu_local_route(
                    origin, destination, mode, from_point, to_point))
            except ProviderError as exc:
                failures.append(exc)
        if allow_cycling and hasattr(self.tools, "bicycling"):
            lon1, lat1 = map(math.radians, origin)
            lon2, lat2 = map(math.radians, destination)
            gap = 6371000 * 2 * math.asin(min(1, math.sqrt(
                math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2)))
            if gap <= 5000:
                try:
                    bike = await self.policy.call("amap", lambda: self.tools.bicycling(
                        origin, destination, from_point, to_point))
                    if bike and bike.duration_seconds:
                        if route:
                            route.cycling_minutes = max(1, round(bike.duration_seconds / 60))
                        else:
                            route = bike
                except ProviderError:
                    # 骑行仅为可选补充；主建议可用时不为备选接口刷告警。
                    pass
        if route:
            return route, None
        if failures:
            return None, "；".join(str(item) for item in failures)
        return None, "地图服务未返回可用路线"
