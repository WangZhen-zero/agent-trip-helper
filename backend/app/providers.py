"""第三方 HTTP 适配器：只供 MCP 工具调用，统一校验事实数据和脱敏错误。"""

import logging
import math

import httpx
from pydantic import ValidationError

from .config import Settings
from .errors import ProviderError
from .geo import gcj02_to_wgs84
from .schemas import Geocode, LocalRoute, POI, RouteStep, TransportOption, Weather

# stdio MCP 入口也会导入本模块；关闭 HTTP 请求明细，防止查询参数中的 Key 进入日志。
for logger_name in ("httpx", "httpcore"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)


async def request_json(client: httpx.AsyncClient, service: str, method: str, url: str, **kwargs) -> dict:
    """不把 httpx 异常原文带给用户：其 URL 可能包含 API Key。"""
    try:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError()
        return payload
    except httpx.TimeoutException:
        raise ProviderError(service, "timeout", "请求超时，请稍后重试", retryable=True) from None
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = {401: "密钥无效", 402: "账户额度不足", 403: "无访问权限", 429: "请求过于频繁"}.get(status, "服务请求失败")
        raise ProviderError(service, f"http_{status}", f"{message}（HTTP {status}）", retryable=status == 429 or status >= 500) from None
    except httpx.RequestError:
        raise ProviderError(service, "network", "网络连接失败", retryable=True) from None
    except (ValueError, TypeError):
        raise ProviderError(service, "invalid_response", "响应格式不正确") from None


def location_of(value) -> tuple[float, float] | None:
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 2:
        raise ValueError()
    return float(parts[0]), float(parts[1])


class AmapProvider:
    base_url = "https://restapi.amap.com/v3"

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def _get(self, endpoint: str, **params) -> dict:
        if not self.settings.amap_web_service_key:
            raise ProviderError("高德", "configuration", "未配置 AMAP_WEB_SERVICE_KEY")
        payload = await request_json(self.client, "高德", "GET", self.base_url + endpoint,
                                     params={"key": self.settings.amap_web_service_key, **params},
                                     timeout=self.settings.provider_timeout_seconds)
        if payload.get("status") != "1":
            # 不回传供应商原始 info，避免服务端把请求内容或密钥反射到页面。
            code = str(payload.get("infocode", ""))
            messages = {
                "10001": "Key 无效", "10002": "接口未开通或路径无效", "10003": "日调用量已超限",
                "10004": "分钟调用量已超限", "10005": "IP 白名单不匹配", "10009": "Key 平台类型不匹配",
                "10021": "接口 QPS 已超限", "10041": "接口权限已过期", "10044": "账户日配额已超限",
                "20000": "请求参数无效", "20803": "起终点距离超出可规划范围",
                "40000": "服务余额不足", "40002": "服务已过期",
            }
            safe_code = code if code.isdigit() and len(code) <= 5 else "unknown"
            message = messages.get(safe_code, "上游接口失败")
            raise ProviderError("高德", f"amap_{safe_code}", f"{message}（{safe_code}）",
                                retryable=safe_code in {"10004", "10021"} or safe_code.startswith("3"))
        return payload

    async def geocode(self, city: str) -> Geocode:
        payload = await self._get("/geocode/geo", address=city, city=city)
        try:
            item = payload.get("geocodes", [])[0]
            if item.get("country") not in (None, "中国"):
                raise ValueError()
            return Geocode(name=city, location=location_of(item["location"]), adcode=item["adcode"])
        except (IndexError, KeyError, TypeError, ValueError, AttributeError):
            raise ProviderError("高德", "geocode", "未获取到有效的国内城市坐标") from None

    async def search_pois(self, city: str, keywords: str, types: str = "") -> list[POI]:
        payload = await self._get("/place/text", city=city, citylimit="true", keywords=keywords,
                                  types=types, offset="8", page="1", extensions="base")
        try:
            return [POI(id=item["id"], name=item["name"], address=item.get("address") or city,
                        location=location_of(item.get("location")), type=item.get("type") or "")
                    for item in payload.get("pois", [])]
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ProviderError("高德", "pois", "地点数据格式无效") from None

    async def weather(self, city_adcode: str) -> list[Weather]:
        payload = await self._get("/weather/weatherInfo", city=city_adcode, extensions="all")
        try:
            casts = payload.get("forecasts", [])[0].get("casts", [])
            return [Weather(date=item["date"], summary=f"白天{item['dayweather']} / 夜间{item['nightweather']}",
                            temperature=f"{item['nighttemp']}–{item['daytemp']}℃") for item in casts]
        except (IndexError, KeyError, TypeError, ValueError, AttributeError):
            raise ProviderError("高德", "weather", "天气预报数据不可用") from None

    async def distance(self, origin: list[float], destination: list[float]) -> float:
        payload = await self._get("/distance", origins=",".join(map(str, origin)),
                                  destination=",".join(map(str, destination)), type="1")
        try:
            value = float(payload["results"][0]["distance"]) / 1000
            if value < 0:
                raise ValueError()
            return round(value, 1)
        except (IndexError, KeyError, ValueError, TypeError):
            raise ProviderError("高德", "distance", "城际驾车距离不可用") from None

    @staticmethod
    def _polyline(value) -> list[tuple[float, float]]:
        points = []
        if not isinstance(value, str):
            return points
        for pair in value.split(";")[:300]:
            try:
                lon, lat = map(float, pair.split(",", 1))
                if -180 <= lon <= 180 and -90 <= lat <= 90:
                    points.append((lon, lat))
            except (ValueError, TypeError):
                continue
        return points

    @staticmethod
    def _stop_name(value) -> str | None:
        return str(value.get("name"))[:100] if isinstance(value, dict) and value.get("name") else None

    @staticmethod
    def _positive_int(value) -> int | None:
        if value is None or value == "" or isinstance(value, (list, dict, bool)):
            return None
        try:
            number_float = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number_float) or number_float < 0:
            return None
        number = int(number_float)
        return number

    @staticmethod
    def _money(value) -> float | None:
        if value is None or value == "" or isinstance(value, (list, dict, bool)):
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        return round(amount, 2) if math.isfinite(amount) and amount >= 0 else None

    @classmethod
    def _segment_steps(cls, segment: dict) -> list[RouteStep]:
        """V3 公交返回的 walking/bus/railway 位于 segment 内，步行还嵌套 steps。"""
        steps: list[RouteStep] = []
        walking = segment.get("walking") or {}
        if isinstance(walking, dict):
            for part in walking.get("steps") or []:
                if not isinstance(part, dict):
                    continue
                steps.append(RouteStep(mode="walking", instruction=str(part.get("instruction") or "步行接驳")[:300],
                                       duration_seconds=cls._positive_int(part.get("duration")),
                                       distance_m=cls._positive_int(part.get("distance")),
                                       polyline=cls._polyline(part.get("polyline"))))
            if walking and not steps and walking.get("distance"):
                steps.append(RouteStep(mode="walking", instruction="步行接驳",
                                       duration_seconds=cls._positive_int(walking.get("duration")),
                                       distance_m=cls._positive_int(walking.get("distance"))))
        bus = segment.get("bus") or {}
        if isinstance(bus, dict):
            lines = bus.get("buslines") or []
            if isinstance(lines, list) and lines:
                line = lines[0]
                if isinstance(line, dict):
                    name = str(line.get("name") or "公交接驳")[:100]
                    mode = "subway" if "地铁" in str(line.get("type") or name) else "bus"
                    steps.append(RouteStep(mode=mode, instruction=name, line_name=name,
                                           departure_stop=cls._stop_name(line.get("departure_stop")),
                                           arrival_stop=cls._stop_name(line.get("arrival_stop")),
                                           duration_seconds=cls._positive_int(line.get("duration")),
                                           distance_m=cls._positive_int(line.get("distance")),
                                           polyline=cls._polyline(line.get("polyline"))))
        railway = segment.get("railway") or {}
        if isinstance(railway, dict) and railway:
            name = str(railway.get("name") or "铁路")[:100]
            depart = railway.get("departure_stop") or {}
            arrive = railway.get("arrival_stop") or {}
            steps.append(RouteStep(mode="rail", instruction=name, line_name=name,
                                   train_trip=str(railway["trip"])[:40] if railway.get("trip") else None,
                                   departure_stop=cls._stop_name(depart), arrival_stop=cls._stop_name(arrive),
                                   departure_time=str(depart["time"])[:20] if isinstance(depart, dict) and depart.get("time") else None,
                                   arrival_time=str(arrive["time"])[:20] if isinstance(arrive, dict) and arrive.get("time") else None,
                                   distance_m=cls._positive_int(railway.get("distance"))))
        return steps

    @classmethod
    def _transits(cls, payload: dict, travelers: int = 1) -> list[TransportOption]:
        try:
            routes = payload.get("route", {}).get("transits", [])
            if not isinstance(routes, list):
                raise ValueError()
            options = []
            for index, route in enumerate(routes[:6]):
                try:
                    if not isinstance(route, dict) or not isinstance(route.get("segments"), list):
                        continue
                    segments = route["segments"]
                    steps = [step for segment in segments if isinstance(segment, dict) for step in cls._segment_steps(segment)]
                    if not steps:
                        continue
                    mode = "rail" if any(step.mode == "rail" for step in steps) else "bus" if any(step.mode == "bus" for step in steps) else "subway" if any(step.mode == "subway" for step in steps) else "transit"
                    line_text = " → ".join(step.instruction for step in steps[:4])
                    # V3 的 transit.cost 与 transit.duration 可为空；route.distance 并非线路总里程。
                    duration = cls._positive_int(route.get("duration"))
                    distances = [step.distance_m for step in steps]
                    distance = sum(distances) if distances and all(value is not None for value in distances) else None
                    cost = cls._money(route.get("cost"))
                    options.append(TransportOption(
                        id=f"amap-{index}", mode=mode, summary=line_text[:500],
                        duration_minutes=round(duration / 60) if duration is not None else None,
                        distance_m=distance,
                        transfers=max(0, sum(step.mode != "walking" for step in steps) - 1),
                        cost_cny=cost, group_cost_cny=round(cost * travelers, 2) if cost is not None else None,
                        steps=steps, polyline=[point for step in steps for point in step.polyline]))
                except (TypeError, ValueError, KeyError, AttributeError, ValidationError):
                    continue
            if routes and not options:
                raise ProviderError("高德", "invalid_response", "路线候选均无法解析")
            return options
        except ProviderError:
            raise
        except (TypeError, ValueError, KeyError, AttributeError, ValidationError):
            raise ProviderError("高德", "invalid_response", "路线数据格式无效") from None

    async def transit_routes(self, origin: tuple[float, float], destination: tuple[float, float],
                             origin_city: str, destination_city: str, date: str | None = None,
                             travelers: int = 1) -> list[TransportOption]:
        params = {"origin": ",".join(map(str, origin)), "destination": ",".join(map(str, destination)),
                  "city": origin_city, "extensions": "all", "strategy": "0"}
        if origin_city != destination_city:
            params["cityd"] = destination_city
        if date:
            params.update(date=date, time="09:00")
        payload = await self._get("/direction/transit/integrated", **params)
        return self._transits(payload, travelers)

    async def local_route(self, origin: tuple[float, float], destination: tuple[float, float],
                          city: str, mode: str) -> LocalRoute | None:
        if mode == "walking":
            payload = await self._get("/direction/walking", origin=",".join(map(str, origin)),
                                      destination=",".join(map(str, destination)))
            route = (payload.get("route", {}).get("paths") or [None])[0]
            if not isinstance(route, dict): return None
            steps = [RouteStep(mode="walking", instruction=str(item.get("instruction") or "步行")[:300],
                               duration_seconds=self._positive_int(item.get("duration")),
                               distance_m=self._positive_int(item.get("distance")), polyline=self._polyline(item.get("polyline")))
                     for item in route.get("steps", []) if isinstance(item, dict)]
            return LocalRoute(from_point="起点", to_point="终点", mode=mode,
                              distance_m=self._positive_int(route.get("distance")), duration_seconds=self._positive_int(route.get("duration")),
                              steps=steps, polyline=[p for step in steps for p in step.polyline])
        if mode == "driving":
            payload = await self._get("/direction/driving", origin=",".join(map(str, origin)),
                                      destination=",".join(map(str, destination)), extensions="all", strategy="0")
            route = (payload.get("route", {}).get("paths") or [None])[0]
            if not isinstance(route, dict): return None
            steps = [RouteStep(mode="driving", instruction=str(item.get("instruction") or "驾车")[:300],
                               duration_seconds=self._positive_int(item.get("duration")),
                               distance_m=self._positive_int(item.get("distance")), polyline=self._polyline(item.get("polyline")))
                     for item in route.get("steps", []) if isinstance(item, dict)]
            toll = route.get("tolls")
            return LocalRoute(from_point="起点", to_point="终点", mode=mode,
                              distance_m=self._positive_int(route.get("distance")), duration_seconds=self._positive_int(route.get("duration")),
                              toll_cny=self._money(toll),
                              steps=steps, polyline=[p for step in steps for p in step.polyline])
        options = await self.transit_routes(origin, destination, city, city)
        if not options: return None
        selected = options[0]
        return LocalRoute(from_point="起点", to_point="终点", mode="transit", distance_m=selected.distance_m,
                          duration_seconds=(selected.duration_minutes * 60 if selected.duration_minutes is not None else None),
                          cost_cny=selected.cost_cny, transfers=selected.transfers, steps=selected.steps, polyline=selected.polyline)

    async def bicycling(self, origin: tuple[float, float], destination: tuple[float, float]) -> LocalRoute | None:
        """高德 V5 骑行只读取总耗时，不请求逐转弯导航内容。"""
        if not self.settings.amap_web_service_key:
            raise ProviderError("高德", "configuration", "未配置 AMAP_WEB_SERVICE_KEY")
        payload = await request_json(self.client, "高德", "GET", "https://restapi.amap.com/v5/direction/bicycling",
                                     params={"key": self.settings.amap_web_service_key,
                                             "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
                                             "destination": f"{destination[0]:.6f},{destination[1]:.6f}",
                                             "show_fields": "cost"}, timeout=self.settings.provider_timeout_seconds)
        if payload.get("status") != "1":
            code = str(payload.get("infocode", "unknown"))
            safe_code = code if code.isdigit() and len(code) <= 5 else "unknown"
            raise ProviderError("高德", f"amap_{safe_code}", f"骑行服务不可用（{safe_code}）",
                                retryable=safe_code in {"10004", "10021"})
        paths = (payload.get("route") or {}).get("paths") or []
        if not isinstance(paths, list) or not paths:
            return None
        first = paths[0]
        try:
            seconds = self._positive_int((first.get("cost") or {}).get("duration"))
            distance = self._positive_int(first.get("distance"))
            if seconds is None or seconds <= 0:
                return None
            return LocalRoute(from_point="起点", to_point="终点", mode="bicycling", distance_m=distance,
                              duration_seconds=seconds, source="高德骑行规划",
                              notice="骑行时间为规划参考，骑行服务费用未估算。")
        except (AttributeError, TypeError, ValueError):
            raise ProviderError("高德", "invalid_response", "骑行结果格式无效") from None


class BaiduProvider:
    """百度路线适配器；输入和输出均指定 GCJ-02，以便与高德地图坐标对齐。"""
    base_url = "https://api.map.baidu.com/direction/v2"

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def _get(self, endpoint: str, **params) -> dict:
        if not self.settings.baidu_map_ak:
            raise ProviderError("百度地图", "configuration", "未配置 BAIDU_MAP_AK")
        payload = await request_json(self.client, "百度地图", "GET", self.base_url + endpoint,
                                     params={"ak": self.settings.baidu_map_ak, "output": "json",
                                             "coord_type": "gcj02", "ret_coordtype": "gcj02", **params},
                                     timeout=self.settings.provider_timeout_seconds)
        status = payload.get("status")
        if status in {7, 1001}:
            return {"result": {"routes": []}}
        if status != 0:
            code = str(status) if isinstance(status, int) and 0 <= status <= 99999 else "unknown"
            reason = {
                "2": "请求参数无效", "3": "服务权限不足", "4": "配额校验失败",
                "5": "AK 无效", "301": "总配额已超限", "302": "日配额已超限",
                "240": "路线服务未开通或权限不足", "401": "并发配额已超限", "402": "并发配额已超限",
            }.get(code, "路线接口不可用")
            raise ProviderError("百度地图", f"baidu_{code}", f"{reason}（{code}）",
                                retryable=code in {"1", "401", "402"})
        return payload

    @staticmethod
    def _coord(value: tuple[float, float]) -> str:
        # 百度接口入参顺序为纬度、经度；高德保存顺序为经度、纬度。
        return f"{value[1]:.6f},{value[0]:.6f}"

    @classmethod
    def _route_steps(cls, route: dict) -> list[RouteStep]:
        steps: list[RouteStep] = []
        for segment in route.get("steps") or []:
            if not isinstance(segment, dict):
                continue
            # 跨城响应可能将 sub_steps 直接放在 step，也可能嵌在 scheme 中。
            # 每一层 schemes 是互斥候选，只取首项；sub_steps 则是连续接驳步骤。
            nested = segment.get("sub_steps") or segment.get("sub_step") or []
            schemes = segment.get("schemes") or []
            pending = list(nested) if isinstance(nested, list) and nested else list(schemes[:1]) if isinstance(schemes, list) else []
            while pending and len(steps) < 30:
                scheme = pending.pop(0)
                if not isinstance(scheme, dict):
                    continue
                alternatives = scheme.get("schemes") or []
                if isinstance(alternatives, list) and alternatives:
                    pending = alternatives[:1] + pending
                    continue
                nested = scheme.get("sub_steps") or scheme.get("sub_step") or []
                if isinstance(nested, list) and nested:
                    pending = nested + pending
                    continue
                vehicle = scheme.get("vehicle_info") or {}
                if not isinstance(vehicle, dict):
                    vehicle = {}
                detail = vehicle.get("detail") or {}
                if isinstance(detail, list):
                    detail = detail[0] if detail and isinstance(detail[0], dict) else {}
                if not isinstance(detail, dict):
                    detail = {}
                vehicle_type = AmapProvider._positive_int(vehicle.get("type"))
                mode = {1: "rail", 2: "air", 3: "bus", 4: "driving", 5: "walking", 6: "coach"}.get(vehicle_type, "other")
                if mode == "bus" and AmapProvider._positive_int(detail.get("type")) == 1:
                    mode = "subway"
                name = str(detail.get("name") or scheme.get("instructions") or "交通接驳")[:300]
                if not name.strip():
                    continue
                steps.append(RouteStep(
                    mode=mode, instruction=name, line_name=str(detail.get("name"))[:100] if detail.get("name") else None,
                    train_trip=str(detail.get("name"))[:40] if mode == "rail" and detail.get("name") else None,
                    flight_number=str(detail.get("name"))[:40] if mode == "air" and detail.get("name") else None,
                    departure_stop=str(detail.get("departure_station") or detail.get("on_station"))[:100] if detail.get("departure_station") or detail.get("on_station") else None,
                    arrival_stop=str(detail.get("arrive_station") or detail.get("off_station"))[:100] if detail.get("arrive_station") or detail.get("off_station") else None,
                    departure_time=str(detail.get("departure_time"))[:20] if detail.get("departure_time") else None,
                    arrival_time=str(detail.get("arrive_time"))[:20] if detail.get("arrive_time") else None,
                    duration_seconds=AmapProvider._positive_int(scheme.get("duration")),
                    distance_m=AmapProvider._positive_int(scheme.get("distance")),
                    polyline=AmapProvider._polyline(scheme.get("path")),
                ))
        return steps

    @classmethod
    def _options(cls, payload: dict, travelers: int) -> list[TransportOption]:
        routes = (payload.get("result") or {}).get("routes") or []
        if not isinstance(routes, list):
            raise ProviderError("百度地图", "invalid_response", "路线列表格式无效")
        options = []
        for index, route in enumerate(routes[:6]):
            try:
                if not isinstance(route, dict):
                    continue
                steps = cls._route_steps(route)
                if not steps:
                    continue
                modes = [step.mode for step in steps]
                mode = next((name for name in ("air", "rail", "coach", "bus", "subway") if name in modes), "transit")
                price = AmapProvider._money(route.get("price"))
                duration = AmapProvider._positive_int(route.get("duration"))
                options.append(TransportOption(
                    id=f"baidu-{index}", mode=mode, summary=" → ".join(step.instruction for step in steps[:4])[:500],
                    duration_minutes=round(duration / 60) if duration is not None else None,
                    distance_m=AmapProvider._positive_int(route.get("distance")),
                    transfers=max(0, sum(step.mode not in {"walking", "driving"} for step in steps) - 1),
                    cost_cny=price, group_cost_cny=round(price * travelers, 2) if price is not None else None,
                    steps=steps, polyline=[point for step in steps for point in step.polyline], source="百度地图路线规划",
                ))
            except (TypeError, ValueError, KeyError, AttributeError, ValidationError):
                continue
        if routes and not options:
            raise ProviderError("百度地图", "invalid_response", "路线候选均无法解析")
        return options

    async def transit_routes(self, origin: tuple[float, float], destination: tuple[float, float],
                             date: str | None = None, travelers: int = 1) -> list[TransportOption]:
        params = {"origin": self._coord(origin), "destination": self._coord(destination), "page_size": 6}
        if date:
            params["departure_date"] = date
        payload = await self._get("/transit", **params)
        return self._options(payload, travelers)

    async def local_route(self, origin: tuple[float, float], destination: tuple[float, float], mode: str) -> LocalRoute | None:
        if mode == "transit":
            options = await self.transit_routes(origin, destination)
            if not options:
                return None
            chosen = options[0]
            return LocalRoute(from_point="起点", to_point="终点", mode="transit", distance_m=chosen.distance_m,
                              duration_seconds=chosen.duration_minutes * 60 if chosen.duration_minutes is not None else None,
                              cost_cny=chosen.cost_cny, transfers=chosen.transfers, steps=chosen.steps,
                              polyline=chosen.polyline, source=chosen.source)
        if mode not in {"walking", "driving"}:
            raise ProviderError("百度地图", "invalid_mode", "不支持的市内交通方式")
        payload = await self._get("/" + mode, origin=self._coord(origin), destination=self._coord(destination))
        routes = (payload.get("result") or {}).get("routes") or []
        if not isinstance(routes, list) or not routes:
            return None
        route = routes[0]
        if not isinstance(route, dict):
            raise ProviderError("百度地图", "invalid_response", "市内路线格式无效")
        steps = [RouteStep(mode=mode, instruction=str(step.get("instruction") or step.get("instructions") or "路线接驳")[:300],
                           distance_m=AmapProvider._positive_int(step.get("distance")),
                           duration_seconds=AmapProvider._positive_int(step.get("duration")),
                           polyline=AmapProvider._polyline(step.get("path")))
                 for step in route.get("steps") or [] if isinstance(step, dict)]
        return LocalRoute(from_point="起点", to_point="终点", mode=mode,
                          distance_m=AmapProvider._positive_int(route.get("distance")),
                          duration_seconds=AmapProvider._positive_int(route.get("duration")),
                          steps=steps, polyline=[p for step in steps for p in step.polyline], source="百度地图路线规划")


class OpenMeteoProvider:
    """天气 API 无需密钥；只接受已经由高德核实过的中国城市坐标。"""
    url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def forecast(self, location: tuple[float, float], start_date=None, end_date=None) -> list[Weather]:
        longitude, latitude = gcj02_to_wgs84(*location)
        params = {"latitude": latitude, "longitude": longitude, "timezone": "Asia/Shanghai", "forecast_days": 16,
                  "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
        if start_date: params["start_date"] = str(start_date)
        if end_date: params["end_date"] = str(end_date)
        payload = await request_json(self.client, "Open-Meteo", "GET", self.url, params=params,
                                     timeout=self.settings.provider_timeout_seconds)
        try:
            daily = payload["daily"]
            codes = daily["weather_code"]
            words = {0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 51: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 73: "中雪", 75: "大雪", 80: "阵雨", 95: "雷暴"}
            return [Weather(date=value, summary=f"{words.get(int(codes[i]), '天气变化')}，降水概率 {daily['precipitation_probability_max'][i]}%",
                            temperature=f"{daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}℃", source="Open-Meteo")
                    for i, value in enumerate(daily["time"])]
        except (KeyError, TypeError, ValueError, IndexError):
            raise ProviderError("Open-Meteo", "invalid_response", "天气预报数据格式无效") from None
