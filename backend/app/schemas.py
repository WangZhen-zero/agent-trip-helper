"""前后端契约：输入、模型草稿和最终事实数据分开校验。"""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cities import canonical_city

Interest = Literal["历史人文", "自然风光", "亲子", "美食", "博物馆", "购物", "城市漫游"]
Pace = Literal["悠闲", "均衡", "充实"]
Accommodation = Literal["经济", "舒适", "高端"]
Transport = Literal["公共交通", "步行优先", "驾车"]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Location = tuple[Longitude, Latitude]
Money = Annotated[float, Field(ge=0, le=10_000_000, allow_inf_nan=False)]
Text = Annotated[str, Field(min_length=1, max_length=1000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TripRequest(Contract):
    origin_city: Annotated[str, Field(min_length=1, max_length=40)]
    cities: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(min_length=1, max_length=3)
    start_date: date
    end_date: date
    travelers: int = Field(default=2, ge=1, le=10)
    budget_cny: int = Field(default=6000, ge=500, le=200_000)
    interests: list[Interest] = Field(default_factory=lambda: ["城市漫游", "美食"], min_length=1, max_length=4)
    pace: Pace = "均衡"
    accommodation: Accommodation = "舒适"
    transport: Transport = "公共交通"

    @field_validator("cities")
    @classmethod
    def normalize_cities(cls, cities: list[str]) -> list[str]:
        # API 也必须校验，避免绕过前端把县区、景点或不存在地点送入规划工作流。
        normalized = [canonical_city(city) for city in cities]
        if any(city is None for city in normalized):
            raise ValueError("城市必须是中国大陆真实存在的城市级目的地")
        if len(set(normalized)) != len(normalized):
            raise ValueError("城市不能重复")
        return normalized

    @field_validator("origin_city")
    @classmethod
    def normalize_origin(cls, city: str) -> str:
        normalized = canonical_city(city)
        if normalized is None:
            raise ValueError("出发城市必须是中国大陆真实存在的城市级目的地")
        return normalized

    @field_validator("interests")
    @classmethod
    def unique_interests(cls, values: list[Interest]) -> list[Interest]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_dates(self) -> "TripRequest":
        if self.start_date < datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("出发日期必须是今天或未来")
        if self.start_date > datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=15):
            raise ValueError("出发日期最多可提前 15 天安排")
        if not 1 <= self.total_days <= 14:
            raise ValueError("行程必须为 1–14 天")
        if self.total_days < len(self.cities):
            raise ValueError("每个城市至少安排一天，总天数不能少于城市数")
        if self.origin_city in self.cities:
            raise ValueError("出发城市仅用于交通起点，不能同时作为旅游城市")
        return self

    @property
    def total_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


class Geocode(Contract):
    name: Text
    location: Location
    adcode: Annotated[str, Field(pattern=r"^\d{6}$")]


class CityValidationRequest(Contract):
    """手工输入先走此契约；无效名称用业务结果表示，空输入仍由 422 拒绝。"""
    city: Annotated[str, Field(min_length=1, max_length=40)]


class CityValidationResult(Contract):
    valid: bool
    city: str | None = None
    province: str | None = None
    message: str


class POI(Contract):
    id: Text
    name: Text
    address: str
    location: Location | None
    type: str = ""


class Weather(Contract):
    date: date
    summary: Text
    temperature: Text
    source: str = "高德天气"


class WeatherForecastRequest(Contract):
    city: Annotated[str, Field(min_length=1, max_length=40)]
    start_date: date | None = None
    end_date: date | None = None


class WeatherForecastResult(Contract):
    city: str
    location: Location | None
    forecasts: list[Weather]
    source: str = "Open-Meteo"


TransportMode = Literal["all", "rail", "air", "coach", "bus"]


class TransportPlanRequest(Contract):
    from_city: Annotated[str, Field(alias="from", min_length=1, max_length=40)]
    to_city: Annotated[str, Field(alias="to", min_length=1, max_length=40)]
    departure_date: date
    travelers: int = Field(ge=1, le=10)
    mode: TransportMode = "all"

    @model_validator(mode="after")
    def validate_domestic_trip(self) -> "TransportPlanRequest":
        self.from_city, self.to_city = canonical_city(self.from_city) or "", canonical_city(self.to_city) or ""
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        if not self.from_city or not self.to_city or self.from_city == self.to_city:
            raise ValueError("起点和终点必须为不同的中国大陆城市")
        if not today <= self.departure_date <= today + timedelta(days=15):
            raise ValueError("出发日期必须在未来 15 天内")
        return self


class RouteStep(Contract):
    mode: Literal["walking", "bus", "subway", "rail", "air", "coach", "driving", "transit", "other"]
    instruction: Text
    line_name: str | None = None
    train_trip: str | None = None
    flight_number: str | None = None
    departure_stop: str | None = None
    arrival_stop: str | None = None
    departure_time: str | None = None
    arrival_time: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    distance_m: int | None = Field(default=None, ge=0)
    polyline: list[Location] = Field(default_factory=list)


class TransportOption(Contract):
    id: Text
    mode: Literal["rail", "air", "coach", "bus", "subway", "transit", "other"]
    summary: Text
    duration_minutes: int | None = Field(default=None, ge=0)
    distance_m: int | None = Field(default=None, ge=0)
    transfers: int | None = Field(default=None, ge=0)
    cost_cny: Money | None = None
    group_cost_cny: Money | None = None
    # 供应商步骤仅供后端提炼线路名称；公开 JSON 不提供逐站导航与道路折线。
    steps: list[RouteStep] = Field(default_factory=list, exclude=True)
    polyline: list[Location] = Field(default_factory=list, exclude=True)
    line_names: list[str] = Field(default_factory=list)
    service_number: str | None = None
    departure_stop: str | None = None
    arrival_stop: str | None = None
    departure_time: str | None = None
    arrival_time: str | None = None
    arrival_day_offset: int = Field(default=0, ge=0, le=2)
    checked_at: str | None = None
    date_verified: bool = False
    source: str = "高德路线规划"

    @model_validator(mode="after")
    def summarize_lines(self) -> "TransportOption":
        if not self.line_names:
            self.line_names = list(dict.fromkeys(step.line_name for step in self.steps
                                                  if step.mode in {"bus", "subway"} and step.line_name))[:3]
        return self


class TransportPlanResult(Contract):
    from_city: str = Field(alias="from")
    to_city: str = Field(alias="to")
    departure_date: date
    options: list[TransportOption] = Field(default_factory=list)
    recommended_id: str | None = None
    notice: str = "车次为查询时的计划时刻；路线与费用仅供参考，不代表实时开行、余票或可预订价格。"


class LocalRoute(Contract):
    from_point: Text
    to_point: Text
    mode: Literal["transit", "walking", "driving", "bicycling"]
    distance_m: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    cost_cny: Money | None = None
    toll_cny: Money | None = None
    transfers: int | None = Field(default=None, ge=0)
    steps: list[RouteStep] = Field(default_factory=list, exclude=True)
    polyline: list[Location] = Field(default_factory=list, exclude=True)
    line_names: list[str] = Field(default_factory=list)
    cycling_minutes: int | None = Field(default=None, ge=1)
    source: str = "高德路线规划"
    notice: str = "市内路线参考信息，请以现场交通情况为准。"

    @model_validator(mode="after")
    def summarize_lines(self) -> "LocalRoute":
        if not self.line_names:
            self.line_names = list(dict.fromkeys(step.line_name for step in self.steps
                                                  if step.mode in {"bus", "subway"} and step.line_name))[:3]
        return self


class Hotel(POI):
    note: str = "基于位置和 POI 信息推荐；请在预订平台确认房价、库存及取消政策。"
    photo: None = None
    photo_token: str | None = None


class CityResult(Contract):
    name: Text
    location: Location | None = None
    adcode: str | None = None
    attractions: list[POI] = Field(default_factory=list)
    forecasts: list[Weather] = Field(default_factory=list)
    weather: Weather | None = None
    hotel: Hotel | None = None


class ActivityDraft(Contract):
    # 模型只选择 POI ID，地点名称和坐标由服务器关联，防止伪造地图点位。
    time: Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
    poi_id: str | None
    description: Text
    estimated_cost: Money | None


class DayDraft(Contract):
    day: int = Field(ge=1, le=14)
    date: date
    city: Text
    theme: Text
    activities: list[ActivityDraft] = Field(min_length=1, max_length=6)


class BudgetBreakdown(Contract):
    accommodation_cny: Money
    food_cny: Money
    local_transport_cny: Money
    intercity_transport_cny: Money


class PlanDraft(Contract):
    summary: Text
    itinerary: list[DayDraft] = Field(min_length=1, max_length=14)
    budget: BudgetBreakdown


def validate_schedule(days: list, request: TripRequest) -> None:
    """同时检查日期连续、城市顺序和每城覆盖，避免合法 JSON 中的业务错误。"""
    if len(days) != request.total_days:
        raise ValueError("模型返回的总天数不匹配")
    visited: list[str] = []
    for index, day in enumerate(days):
        if day.day != index + 1 or day.date != request.start_date + timedelta(days=index):
            raise ValueError("日程编号或日期不连续")
        if not visited or visited[-1] != day.city:
            visited.append(day.city)
        times = [activity.time for activity in day.activities]
        if times != sorted(set(times)):
            raise ValueError("同一天的活动时间必须递增且不能重复")
    if visited != request.cities:
        raise ValueError("日程必须按输入顺序覆盖全部城市")


class Activity(ActivityDraft):
    title: Text
    location: Location | None
    photo: None = None


class DayPlan(DayDraft):
    weather: Weather | None
    activities: list[Activity] = Field(min_length=1, max_length=6)
    local_routes: list[LocalRoute] = Field(default_factory=list)
    local_route_status: Literal["deferred", "ready", "unavailable"] = "ready"
    local_route_token: str | None = None
    photo_token: str | None = None


class PhotoResolveRequest(Contract):
    photo_token: str = Field(min_length=10, max_length=12000)


class PhotoResolveResult(Contract):
    photos: dict[str, None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class LocalDayRouteRequest(Contract):
    day_token: str = Field(min_length=10, max_length=12000)


class LocalDayRouteResult(Contract):
    day: int = Field(ge=1, le=14)
    status: Literal["ready", "unavailable"]
    routes: list[LocalRoute] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class IntercityLeg(Contract):
    from_city: str = Field(alias="from")
    to_city: str = Field(alias="to")
    distance_km: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    advice: str
    transport: TransportPlanResult | None = None


class Budget(Contract):
    total_cny: Money
    estimated_cny: Money
    breakdown: BudgetBreakdown
    activities_cny: Money
    note: str
    known_intercity_cny: Money = 0
    unpriced_intercity_legs: int = Field(default=0, ge=0)
    over_budget_cny: Money = 0


class MapMarker(Contract):
    name: str
    location: Location
    kind: Literal["origin", "city", "attraction", "hotel"]
    city: str
    day: int | None = None


class MapData(Contract):
    city_path: list[Location]
    markers: list[MapMarker]


class TripResult(Contract):
    data_mode: Literal["demo", "live"]
    summary: Text
    request: TripRequest
    origin: CityResult
    cities: list[CityResult]
    itinerary: list[DayPlan]
    intercity_legs: list[IntercityLeg]
    budget: Budget
    warnings: list[str]
    map: MapData

    @model_validator(mode="after")
    def consistent_trip(self) -> "TripResult":
        validate_schedule(self.itinerary, self.request)
        if [city.name for city in self.cities] != self.request.cities:
            raise ValueError("返回城市不能缺失或重排")
        if self.origin.name != self.request.origin_city:
            raise ValueError("返回出发城市不匹配")
        return self


Stage = Literal["attractions", "weather", "hotels", "planning", "transport"]


class StreamEvent(Contract):
    type: Literal["attractions", "weather", "hotels", "planning", "transport", "warning", "complete", "error"]
    message: str
    status: Literal["running", "done"] | None = None
    data: dict | None = None


class ChatMessage(Contract):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=1200)]


class ChatRequest(Contract):
    messages: list[ChatMessage] = Field(min_length=1, max_length=10)
    trip: TripRequest | None = None
    result_summary: str | None = Field(default=None, max_length=4000)
