"""固定阶段编排与 SSE 生命周期；心跳等待不会取消仍在进行的模型请求。"""
import asyncio
import importlib.util
from contextlib import aclosing, suppress
from collections.abc import AsyncIterator, Callable

import httpx

from .agents import AttractionSearchAgent, DeepSeekPlanner, HotelRecommendationAgent, TransportPlanningAgent, WeatherAgent
from .config import Settings
from .demo_data import build_demo_trip
from .errors import ProviderError
from .mcp_gateway import MCPGateway
from .result_builder import assemble_trip
from .schemas import StreamEvent, TripRequest
from .route_tokens import issue_day_token
from .transport_service import RoutePolicy

STAGES = (("attractions", "景点搜索"), ("weather", "天气查询"), ("hotels", "酒店推荐"), ("planning", "行程规划"), ("transport", "交通路线"))


class TripOrchestrator:
    def __init__(self, settings: Settings, client_factory: Callable = httpx.AsyncClient,
                 gateway_factory: Callable = MCPGateway, route_policy: RoutePolicy | None = None):
        self.settings, self.client_factory, self.gateway_factory = settings, client_factory, gateway_factory
        self.route_policy = route_policy or RoutePolicy(settings)

    async def events(self, request: TripRequest) -> AsyncIterator[StreamEvent]:
        """事件层保证只产生一个终态；所有查询告警在最终结果中仍可查阅。"""
        try:
            if self.settings.demo_mode:
                for stage, title in STAGES:
                    yield StreamEvent(type=stage, status="running", message=f"{title}：载入离线样例")
                    await asyncio.sleep(0)
                    yield StreamEvent(type=stage, status="done", message=f"{title}已完成")
                result = build_demo_trip(request)
            else:
                missing = self.settings.missing_provider_keys()
                if missing:
                    raise ProviderError("配置", "configuration", "真实模式缺少：" + ", ".join(missing))
                if importlib.util.find_spec("fastmcp") is None:
                    raise ProviderError("MCP", "dependency", "未安装 fastmcp，请安装 backend/requirements.txt")
                warnings = []
                async with self.client_factory() as client:
                    async with self.gateway_factory(self.settings, client) as tools:
                        yield StreamEvent(type="attractions", status="running", message="正在查询城市与景点")
                        cities, found_warnings = await AttractionSearchAgent(tools).run(request)
                        origin, origin_warnings = await AttractionSearchAgent(tools).run(request.model_copy(update={"cities": [request.origin_city]}))
                        origin = origin[0]
                        warnings.extend(found_warnings)
                        warnings.extend(origin_warnings)
                        yield StreamEvent(type="attractions", status="done", message="景点查询已完成")
                        if not any(city.location for city in cities):
                            raise ProviderError("高德", "no_cities", "全部目的地均缺少有效坐标，无法生成可信行程")
                        yield StreamEvent(type="weather", status="running", message="正在查询可用日期的天气")
                        warnings.extend(await WeatherAgent(tools).run(cities))
                        yield StreamEvent(type="weather", status="done", message="天气查询已完成")
                        yield StreamEvent(type="hotels", status="running", message="正在查询酒店推荐")
                        warnings.extend(await HotelRecommendationAgent(tools, self.settings).run(cities, request.accommodation))
                        yield StreamEvent(type="hotels", status="done", message="酒店查询已完成")
                        for warning in dict.fromkeys(warnings):
                            yield StreamEvent(type="warning", message=warning)
                        yield StreamEvent(type="planning", status="running", message="正在生成并校验完整行程")
                        planner = DeepSeekPlanner(self.settings, tools, client)
                        draft = await planner.run(request, cities, [])
                        yield StreamEvent(type="planning", status="done", message="行程校验已完成")
                        yield StreamEvent(type="transport", status="running", message="正在查询城际路线；市内接驳将在查看当天时按需查询")
                        legs, local_routes, leg_warnings = await TransportPlanningAgent(tools, self.settings, self.route_policy).run(origin, cities, draft, request)
                        warnings.extend(leg_warnings)
                        result = assemble_trip(request, draft, cities, origin, legs, warnings, local_routes_by_day=local_routes)
                        mode = {"公共交通": "transit", "步行优先": "walking", "驾车": "driving"}[request.transport]
                        for day in result.itinerary:
                            day.local_route_token = issue_day_token(day, mode, self.settings)
                            day.local_route_status = "deferred" if day.local_route_token else "ready"
                        yield StreamEvent(type="transport", status="done", message="交通路线参考已完成")
                # MCP 与 HTTP 资源先释放，再通知浏览器任务完成。
            for warning in result.warnings:
                yield StreamEvent(type="warning", message=warning)
            yield StreamEvent(type="complete", message="行程已生成", data=result.model_dump(mode="json", by_alias=True))
        except ProviderError as exc:
            yield StreamEvent(type="error", message=str(exc), data={"code": exc.code})
        except Exception:
            # CancelledError 不属于 Exception；断开连接将向下游自然传播取消信号。
            yield StreamEvent(type="error", message="行程处理失败，请稍后重试。", data={"code": "internal"})

    async def sse(self, request: TripRequest) -> AsyncIterator[str]:
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=32)

        async def produce():
            async def collect():
                async with aclosing(self.events(request)) as events:
                    async for event in events:
                        await queue.put(event)
            try:
                await asyncio.wait_for(collect(), self.settings.trip_timeout_seconds)
            except asyncio.TimeoutError:
                await queue.put(StreamEvent(type="error", message="规划总耗时超限，请减少城市或稍后重试。", data={"code": "timeout"}))
            await queue.put(None)

        worker = asyncio.create_task(produce())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), self.settings.sse_heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
                    break
                yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
        finally:
            # StreamingResponse 在客户端断开时取消生成器；等待 worker 清理所有连接。
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
