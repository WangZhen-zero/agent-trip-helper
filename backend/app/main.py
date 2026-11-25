"""FastAPI 入口：表单校验由 Pydantic 完成，规划进度通过 SSE 返回。"""
import asyncio
import json
import logging
import time
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from .config import Settings, get_settings
from .cities import canonical_city, province_for
from .errors import ProviderError
from .mcp_gateway import MCPGateway
from .orchestrator import TripOrchestrator
from .schemas import (ChatRequest, CityValidationRequest, CityValidationResult, CityResult,
                      LocalDayRouteRequest, LocalDayRouteResult, TransportPlanRequest, TransportPlanResult, TripRequest,
                      WeatherForecastRequest, WeatherForecastResult, PhotoResolveRequest, PhotoResolveResult)
from .transport_service import RoutePolicy, TransportService
from .route_tokens import verify_day_token
from .photo_tokens import verify_photo_token
from .providers import request_json
from .aviation import search as search_aviation


def create_app(settings: Settings | None = None) -> FastAPI:
    # httpx INFO 日志包含请求 URL，高德把 Key 放在查询参数中，不能直接记录。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    app = FastAPI(title="行知 · 智能旅行助手 API", version="0.2.0")
    route_policy: RoutePolicy | None = None
    local_cache: dict[str, tuple[float, LocalDayRouteResult]] = {}
    local_cache_lock = asyncio.Lock()

    def get_route_policy() -> RoutePolicy:
        nonlocal route_policy
        if route_policy is None:
            route_policy = RoutePolicy(settings or get_settings())
        return route_policy
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/api/v1/health")
    async def health() -> dict:
        config = settings or get_settings()
        return {"status": "ok", "demo_mode": config.demo_mode}

    @app.post("/api/v1/cities/validate", response_model=CityValidationResult)
    async def validate_city(payload: CityValidationRequest) -> CityValidationResult:
        """只在手工添加时调用；真实模式经 MCP 校验，演示模式完全离线。"""
        config = settings or get_settings()
        city = canonical_city(payload.city)
        if city is None:
            return CityValidationResult(valid=False, message="未找到该城市，请选择中国大陆城市级目的地。")
        province = province_for(city)
        if config.demo_mode:
            return CityValidationResult(valid=True, city=city, province=province, message="已由离线城市名录验证")
        if not config.amap_web_service_key:
            raise HTTPException(status_code=503, detail="城市校验服务未配置 AMAP_WEB_SERVICE_KEY")
        try:
            # 校验服务不继承开发机的 HTTP_PROXY：错误代理配置不能让真实城市被误判。
            async with httpx.AsyncClient(trust_env=False) as client:
                async with MCPGateway(config, client) as tools:
                    # 高德返回有效经纬度和 adcode 才算通过，不能把配置/网络故障误报为不存在。
                    await tools.geocode(city)
        except ProviderError as exc:
            status = 503 if exc.code in {"timeout", "network", "connection", "configuration"} else 502
            raise HTTPException(status_code=status, detail=f"城市校验服务暂不可用：{exc}") from None
        return CityValidationResult(valid=True, city=city, province=province, message="已由高德地理服务验证")

    @app.post("/api/v1/trips/plan/stream")
    async def plan_trip(request: TripRequest) -> StreamingResponse:
        return StreamingResponse(TripOrchestrator(settings or get_settings(), route_policy=get_route_policy()).sse(request),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/weather/forecast", response_model=WeatherForecastResult)
    async def weather_forecast(payload: WeatherForecastRequest) -> WeatherForecastResult:
        """独立天气能力同样走 MCP，城市范围先由共享目录限制。"""
        config = settings or get_settings()
        city = canonical_city(payload.city)
        if city is None:
            raise HTTPException(status_code=422, detail="仅支持中国大陆城市级目的地")
        if config.demo_mode:
            from .demo_data import CITY_DATA
            # 未收录演示点位时不借用其他城市坐标，避免离线模式制造错误地理事实。
            location = CITY_DATA.get(city, (None, []))[0]
            from .schemas import Weather
            return WeatherForecastResult(city=city, location=location, forecasts=[Weather(date=payload.start_date or __import__('datetime').date.today(), summary="晴到多云（演示）", temperature="18–25℃", source="演示数据")], source="演示数据")
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                async with MCPGateway(config, client) as tools:
                    geo = await tools.geocode(city)
                    forecast = await tools.weather(geo.location, payload.start_date, payload.end_date)
            return WeatherForecastResult(city=city, location=geo.location, forecasts=forecast)
        except ProviderError as exc:
            raise HTTPException(status_code=503, detail=f"天气服务暂不可用：{exc}") from None

    @app.post("/api/v1/transport/plan", response_model=TransportPlanResult)
    async def transport_plan(payload: TransportPlanRequest) -> TransportPlanResult:
        config = settings or get_settings()
        if config.demo_mode:
            from .schemas import TransportOption
            option = TransportOption(id="demo-rail", mode="rail", summary="铁路与市内接驳示例路线", duration_minutes=180, transfers=0,
                                     cost_cny=180, group_cost_cny=180 * payload.travelers, source="演示数据")
            return TransportPlanResult(**{"from": payload.from_city, "to": payload.to_city, "departure_date": payload.departure_date, "options": [option], "recommended_id": option.id, "notice": "离线演示，不含真实班次或票价。"})
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                async with MCPGateway(config, client) as tools:
                    origin = await tools.geocode(payload.from_city)
                    destination = await tools.geocode(payload.to_city)
                    options, warning = await TransportService(config, tools, get_route_policy()).intercity(
                        origin.location, destination.location, payload.from_city,
                        payload.to_city, str(payload.departure_date), payload.travelers, payload.mode)
            recommended = min(options, key=lambda value: (not value.date_verified,
                value.duration_minutes or 999999, value.transfers or 0), default=None)
            return TransportPlanResult(**{"from": payload.from_city, "to": payload.to_city,
                                          "departure_date": payload.departure_date, "options": options,
                                          "recommended_id": recommended.id if recommended else None,
                                          "notice": warning or "车次为查询时的计划时刻；其他路线和费用仅供参考，请通过官方渠道核对。"})
        except ProviderError as exc:
            raise HTTPException(status_code=503, detail=f"交通服务暂不可用：{exc}") from None

    @app.post("/api/v1/transport/local/day", response_model=LocalDayRouteResult)
    async def local_day_routes(payload: LocalDayRouteRequest) -> LocalDayRouteResult:
        """只接收签名日程凭证，不能以浏览器传来的任意坐标消耗地图额度。"""
        config = settings or get_settings()
        try:
            day = verify_day_token(payload.day_token, config)
        except ValueError as exc:
            raise HTTPException(status_code=410 if "过期" in str(exc) else 422, detail=str(exc)) from None
        async with local_cache_lock:
            now = time.monotonic()
            for key, (expiry, _) in list(local_cache.items()):
                if expiry <= now:
                    local_cache.pop(key, None)
            cached = local_cache.get(payload.day_token)
            if cached:
                return cached[1]
            routes, failures = [], []
            async with httpx.AsyncClient(trust_env=False) as client:
                async with MCPGateway(config, client) as tools:
                    service = TransportService(config, tools, get_route_policy())
                    cycling_checks = 0
                    for pair in day["pairs"]:
                        route, warning = await service.local(pair["a"], pair["b"], day["city"], day["mode"],
                                                             pair["from"], pair["to"], allow_cycling=cycling_checks < 3)
                        cycling_checks += 1
                        if route:
                            routes.append(route)
                        if warning:
                            failures.append(warning)
            warnings = []
            if failures:
                warnings.append(f"{day['city']}有 {len(failures)} 段市内接驳未取得首选路线；原因：{failures[0]}")
            result = LocalDayRouteResult(day=day["day"], status="ready" if routes else "unavailable",
                                         routes=routes, warnings=warnings)
            if len(local_cache) >= 256:
                oldest = min(local_cache, key=lambda key: local_cache[key][0])
                local_cache.pop(oldest, None)
            local_cache[payload.day_token] = (time.monotonic() + 600, result)
            return result

    @app.post("/api/v1/photos/resolve", response_model=PhotoResolveResult)
    async def resolve_photos(payload: PhotoResolveRequest) -> PhotoResolveResult:
        """旧客户端兼容入口：未获国内图片展示授权前一律返回无图。"""
        config = settings or get_settings()
        try:
            context = verify_photo_token(payload.photo_token, config)
        except ValueError as exc:
            raise HTTPException(status_code=410 if "过期" in str(exc) else 422, detail=str(exc)) from None
        return PhotoResolveResult(photos={item["id"]: None for item in context["items"]})

    @app.post("/api/v1/assistant/chat/stream")
    async def assistant_chat(payload: ChatRequest) -> StreamingResponse:
        """无状态建议对话：只接收有限历史，且不允许它直接改变行程事实。"""
        config = settings or get_settings()
        async def chunks():
            if config.demo_mode:
                answer = "演示助手：可先比较相邻城市的交通参考，再根据天气调整户外活动；票价和班次请以官方渠道为准。"
            else:
                if not config.deepseek_api_key:
                    yield "event: error\ndata: " + json.dumps({"message": "未配置 DEEPSEEK_API_KEY"}, ensure_ascii=False) + "\n\n"; return
                context = {"trip": payload.trip.model_dump(mode="json") if payload.trip else None, "summary": payload.result_summary}
                messages = [{"role": "system", "content": "你是中国国内旅行建议助手。只给建议，不声称实时票价、班次、库存，不修改行程。不得自行生成车次号、航班号、计划时刻或票价；上下文没有经过核验的具体交通数据时，只能建议用户去官方渠道查询。"}, *[item.model_dump() for item in payload.messages], {"role": "user", "content": "已验证行程上下文：" + json.dumps(context, ensure_ascii=False)}]
                try:
                    async with httpx.AsyncClient(trust_env=False) as client:
                        data = await request_json(client, "DeepSeek", "POST", config.llm_base_url.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {config.deepseek_api_key}"}, json={"model": config.llm_model_id, "messages": messages, "stream": False, "max_tokens": 900}, timeout=config.llm_timeout_seconds)
                    answer = data["choices"][0]["message"]["content"]
                except (ProviderError, KeyError, TypeError):
                    yield "event: error\ndata: " + json.dumps({"message": "助手服务暂不可用，请稍后再试。"}, ensure_ascii=False) + "\n\n"; return
            for index in range(0, len(answer), 24):
                yield "event: message\ndata: " + json.dumps({"delta": answer[index:index + 24]}, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(0)
            yield "event: complete\ndata: {}\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/v1/aviation/search")
    async def aviation_search(q: str = "", kind: str = "all") -> dict:
        """查询本地 OpenFlights 快照，绝不将静态资料包装为实时航班信息。"""
        if kind not in {"all", "airport", "airline"}:
            raise HTTPException(status_code=422, detail="kind 仅支持 all、airport 或 airline")
        return search_aviation(q, kind)

    return app


app = create_app()
