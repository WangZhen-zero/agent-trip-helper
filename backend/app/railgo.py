"""RailGo 时刻表适配器；只提取公开展示所需的少量事实，不转发上游原始数据。"""
import asyncio
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .errors import ProviderError
from .schemas import TransportOption


RAILGO_URL = "https://data.railgo.zenglingkun.cn/api/train/sts_query"
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
NUMBER_RE = re.compile(r"^[A-Z]\d{1,5}(?:/[A-Z]?\d{1,5})?$", re.I)


def _station_in_city(station: str, city: str) -> bool:
    """无可靠同城映射时宁可丢弃车次，不把邻县车站当成市中心车站。"""
    short = city.removesuffix("市")
    return bool(short and station.startswith(short))


def parse_trains(payload: object, origin_city: str, destination_city: str,
                 departure_date: str, checked_at: str) -> list[TransportOption]:
    """校验运行日期和车站归属后，最多输出三个建议，不包含经停表。"""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ProviderError("RailGo", "invalid_response", "铁路时刻数据格式无效")
    date_key = date.fromisoformat(departure_date).strftime("%Y%m%d")
    choices: list[TransportOption] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        rundays = row.get("rundays")
        # 上游字段可为空或类型异常；只有明确列出所选日期才视为已核验班次。
        if not isinstance(rundays, list) or date_key not in rundays:
            continue
        try:
            timetable = row["timetable"]
            from_pos, to_pos = int(row["fromPos"]), int(row["toPos"])
            if not isinstance(timetable, list) or not 0 <= from_pos < to_pos < len(timetable):
                continue
            start, end = timetable[from_pos], timetable[to_pos]
            number = str(row["number"]).upper()
            from_station, to_station = str(start["station"]), str(end["station"])
            depart, arrive = str(start["depart"]), str(end["arrive"])
            day_offset = int(end.get("day", row.get("dayDiff", 0))) - int(start.get("day", 0))
            if (not NUMBER_RE.fullmatch(number) or not TIME_RE.fullmatch(depart) or
                    not TIME_RE.fullmatch(arrive) or not 0 <= day_offset <= 2 or
                    not _station_in_city(from_station, origin_city) or
                    not _station_in_city(to_station, destination_city)):
                continue
            depart_dt = datetime.combine(date.fromisoformat(departure_date), datetime.strptime(depart, "%H:%M").time())
            arrive_dt = datetime.combine(depart_dt.date() + timedelta(days=day_offset), datetime.strptime(arrive, "%H:%M").time())
            minutes = round((arrive_dt - depart_dt).total_seconds() / 60)
            if not 0 < minutes <= 2880:
                continue
            identity = number, from_station, to_station
            if identity in seen:
                continue
            seen.add(identity)
            choices.append(TransportOption(
                id=f"railgo-{number}-{from_station}-{to_station}", mode="rail",
                summary=f"建议乘坐 {number}，计划 {depart} 从{from_station}出发、{arrive} 到达{to_station}",
                duration_minutes=minutes, service_number=number,
                departure_stop=from_station, arrival_stop=to_station,
                departure_time=depart, arrival_time=arrive, arrival_day_offset=day_offset,
                checked_at=checked_at, date_verified=True, source="RailGo",
            ))
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            continue
    return sorted(choices, key=lambda item: (item.duration_minutes or 99999, item.departure_time or ""))[:3]


class RailGoProvider:
    """单进程限速与缓存，避免公开页面每次刷新都击打免费上游。"""
    _cache: dict[tuple[str, str, str], tuple[float, list[TransportOption]]] = {}
    _lock = asyncio.Lock()
    _next_request = 0.0

    def __init__(self, client: httpx.AsyncClient, timeout: float = 12):
        self.client, self.timeout = client, timeout

    async def trains(self, origin_city: str, destination_city: str,
                     departure_date: str) -> list[TransportOption]:
        key = origin_city, destination_city, departure_date
        async with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return [item.model_copy(deep=True) for item in cached[1]]
            delay = self._next_request - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            type(self)._next_request = time.monotonic() + 1.0
            try:
                response = await self.client.get(RAILGO_URL, params={"from": origin_city, "to": destination_city,
                                                                       "date": departure_date.replace("-", ""), "city": "true"},
                                                 timeout=self.timeout)
                response.raise_for_status()
                if len(response.content) > 5_000_000:
                    raise ValueError("oversize")
                payload = response.json()
            except httpx.TimeoutException:
                raise ProviderError("RailGo", "timeout", "铁路时刻查询超时", retryable=True) from None
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                raise ProviderError("RailGo", f"http_{code}", f"铁路时刻服务不可用（HTTP {code}）",
                                    retryable=code == 429 or code >= 500) from None
            except (httpx.RequestError, ValueError):
                raise ProviderError("RailGo", "network", "铁路时刻服务暂不可用", retryable=True) from None
            checked_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="minutes")
            result = parse_trains(payload, origin_city, destination_city, departure_date, checked_at)
            if len(self._cache) >= 256:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest, None)
            self._cache[key] = (time.monotonic() + (1800 if result else 300), result)
            return [item.model_copy(deep=True) for item in result]
