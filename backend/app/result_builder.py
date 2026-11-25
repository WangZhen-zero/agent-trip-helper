"""将模型草稿与工具事实关联，生成前端可直接展示的完整结果。"""
from .schemas import (Activity, Budget, CityResult, DayPlan, IntercityLeg, LocalRoute, MapData,
                      MapMarker, PlanDraft, TripRequest, TripResult, validate_schedule)


def validate_draft(draft: PlanDraft, request: TripRequest, cities: list[CityResult]) -> None:
    validate_schedule(draft.itinerary, request)
    known = {city.name: {poi.id for poi in city.attractions} for city in cities}
    for day in draft.itinerary:
        poi_backed = 0
        free = 0
        for activity in day.activities:
            if activity.poi_id is not None and activity.poi_id not in known.get(day.city, set()):
                raise ValueError("活动引用了未知或不属于当前城市的 POI")
            poi_backed += int(activity.poi_id is not None)
            free += int(activity.poi_id is None)
        if known.get(day.city) and free > 1:
            raise ValueError("有景点数据时每天最多安排一个自由活动")
        if known.get(day.city) and poi_backed == 0:
            raise ValueError("有景点数据时每天至少安排一个已核实 POI")
    available = [item for day in draft.itinerary if known.get(day.city) for item in day.activities]
    if available and sum(item.poi_id is None for item in available) > max(1, len(available) // 5):
        raise ValueError("自由活动超过可用景点日程的 20%")


def assemble_trip(request: TripRequest, draft: PlanDraft, cities: list[CityResult], origin: CityResult,
                  legs: list[IntercityLeg], warnings: list[str], *, mode="live",
                  local_routes_by_day: dict[int, list[LocalRoute]] | None = None) -> TripResult:
    validate_draft(draft, request, cities)
    warnings = list(warnings)
    city_by_name = {city.name: city.model_copy(deep=True) for city in cities}
    days, markers = [], []
    missing_weather: dict[str, list[str]] = {}
    if origin.location is not None:
        markers.append(MapMarker(name=origin.name, location=origin.location, kind="origin", city=origin.name))
    for city in cities:
        if city.location is not None:
            markers.append(MapMarker(name=city.name, location=city.location, kind="city", city=city.name))
    for day in draft.itinerary:
        city = city_by_name[day.city]
        weather = next((item for item in city.forecasts if item.date == day.date), None)
        if weather is None:
            missing_weather.setdefault(day.city, []).append(str(day.date))
        # 城市摘要取该城首个行程日的天气，不拿其他日期预报代替。
        if not any(previous.city == day.city for previous in days):
            city.weather = weather
        pois = {poi.id: poi for poi in city.attractions}
        activities = []
        for activity in day.activities:
            poi = pois.get(activity.poi_id)
            item = Activity(**activity.model_dump(), title=poi.name if poi else "自由安排（无已核实点位）",
                            location=poi.location if poi else None)
            activities.append(item)
            if poi and poi.location:
                markers.append(MapMarker(name=poi.name, location=poi.location, kind="attraction", city=day.city, day=day.day))
        if city.hotel and city.hotel.location:
            markers.append(MapMarker(name=city.hotel.name, location=city.hotel.location, kind="hotel", city=day.city, day=day.day))
        days.append(DayPlan(**day.model_dump(exclude={"activities"}), activities=activities, weather=weather,
                            local_routes=(local_routes_by_day or {}).get(day.day, [])))
    for city_name, dates in missing_weather.items():
        period = dates[0] if len(dates) == 1 else f"{dates[0]} 至 {dates[-1]}"
        warnings.append(f"{city_name} {period} 暂无该日期预报，请临近出行时查询。")
    activities_cny = round(sum(a.estimated_cost or 0 for day in days for a in day.activities), 2)
    estimated = round(sum(draft.budget.model_dump().values()) + activities_cny, 2)
    priced_legs = []
    for leg in legs:
        plan = leg.transport
        chosen = next((option for option in plan.options if option.id == plan.recommended_id), None) if plan else None
        priced_legs.append(chosen.group_cost_cny if chosen else None)
    known_intercity = round(sum(value for value in priced_legs if value is not None), 2)
    unpriced_legs = sum(value is None for value in priced_legs)
    if estimated > request.budget_cny:
        warnings.append(f"估算费用 ¥{estimated:,.0f} 超出总预算，请调整住宿、交通或游玩项目。")
    if any(a.estimated_cost is None for day in days for a in day.activities):
        warnings.append("部分活动暂无费用估算，总额仅汇总已估算项目。")
    return TripResult(data_mode=mode, summary=draft.summary, request=request, origin=origin,
                      cities=list(city_by_name.values()), itinerary=days, intercity_legs=legs,
                      budget=Budget(total_cny=request.budget_cny, estimated_cny=estimated,
                                    breakdown=draft.budget, activities_cny=activities_cny,
                                    known_intercity_cny=known_intercity, unpriced_intercity_legs=unpriced_legs,
                                    over_budget_cny=max(0, round(estimated - request.budget_cny, 2)),
                                    note="规划估算与供应商交通参考价分开显示，不重复计入总额；未知价格不按零元报价。"),
                      warnings=list(dict.fromkeys(warnings)),
                      map=MapData(city_path=[location for location in [origin.location, *(city.location for city in cities)] if location], markers=markers))
