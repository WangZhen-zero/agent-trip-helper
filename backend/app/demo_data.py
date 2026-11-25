"""离线且可重复的样例：与真实模式共用校验和结果装配，不访问外部资源。"""
from datetime import timedelta
from .result_builder import assemble_trip
from .schemas import (ActivityDraft, BudgetBreakdown, CityResult, DayDraft, Hotel, LocalRoute,
                      IntercityLeg, PlanDraft, POI, RouteStep, TransportOption, TransportPlanResult,
                      TripRequest, TripResult, Weather)

CITY_DATA = {
    "北京": ((116.4074, 39.9042), ["故宫博物院", "景山公园", "什刹海"]),
    "西安": ((108.9398, 34.3416), ["秦始皇帝陵博物院", "西安城墙", "大唐不夜城"]),
    "上海": ((121.4737, 31.2304), ["外滩", "豫园", "上海博物馆"]),
    "杭州": ((120.1551, 30.2741), ["西湖", "灵隐寺", "河坊街"]),
}


def build_demo_trip(request: TripRequest) -> TripResult:
    cities, days = [], []
    current_day = 0
    for index, name in enumerate(request.cities):
        center, names = CITY_DATA.get(name.removesuffix("市"), (None, ["城市漫游示例", "文化街区示例", "公园示例"]))
        pois = [POI(id=f"demo-{index}-{j}", name=title, address=f"{name}（演示点位）", location=center, type="演示景点") for j, title in enumerate(names)]
        city = CityResult(name=name, location=center, attractions=pois,
                          hotel=Hotel(id=f"demo-hotel-{index}", name=f"{name}住宿示例", address="演示地址", location=center))
        # 每城至少一天，余数按访问顺序分配；预算不受演示数据的上限截断。
        duration = request.total_days // len(request.cities) + int(index < request.total_days % len(request.cities))
        for local_day in range(duration):
            day_date = request.start_date + timedelta(days=current_day)
            city.forecasts.append(Weather(date=day_date, summary="晴到多云（样例）", temperature="18–25℃", source="演示数据"))
            count = {"悠闲": 1, "均衡": 2, "充实": 3}[request.pace]
            activities = [ActivityDraft(time=f"{9 + j * 3:02d}:30", poi_id=pois[(local_day + j) % len(pois)].id,
                                        description="示例游览安排，请在真实模式中查询目的地信息。", estimated_cost=50 * request.travelers) for j in range(count)]
            current_day += 1
            days.append(DayDraft(day=current_day, date=day_date, city=name, theme=f"{name}城市探索", activities=activities))
        cities.append(city)
    room_price = {"经济": 200, "舒适": 400, "高端": 800}[request.accommodation]
    draft = PlanDraft(summary=f"{' → '.join(request.cities)} · {request.total_days} 天之旅", itinerary=days,
                      budget=BudgetBreakdown(accommodation_cny=room_price * (request.total_days - 1) * ((request.travelers + 1) // 2),
                                             food_cny=120 * request.total_days * request.travelers,
                                             local_transport_cny=40 * request.total_days * request.travelers,
                                             intercity_transport_cny=300 * (len(cities) - 1) * request.travelers))
    origin_center = CITY_DATA.get(request.origin_city.removesuffix("市"), (None, []))[0]
    origin = CityResult(name=request.origin_city, location=origin_center)
    legs = []
    for a, b in zip([origin, *cities], cities):
        option = TransportOption(id=f"demo-{a.name}-{b.name}", mode="rail", summary="铁路参考路线（演示）",
                                 duration_minutes=180, distance_m=300000, transfers=0, cost_cny=180,
                                 group_cost_cny=180 * request.travelers, source="演示数据",
                                 steps=[RouteStep(mode="rail", instruction="铁路示意接驳，非真实车次")])
        plan = TransportPlanResult(**{"from": a.name, "to": b.name, "departure_date": request.start_date,
                                      "options": [option], "recommended_id": option.id,
                                      "notice": "离线固定演示数据，不代表真实线路、车次或票价。"})
        legs.append(IntercityLeg(**{"from": a.name, "to": b.name, "distance_km": None,
                                   "advice": "演示路线仅用于展示，不查询真实班次或票价。", "transport": plan}))
    local_routes = {}
    for day in days:
        city = next(item for item in cities if item.name == day.city)
        chosen = [next(poi for poi in city.attractions if poi.id == activity.poi_id) for activity in day.activities]
        local_routes[day.day] = [LocalRoute(from_point=left.name, to_point=right.name, mode="transit",
                                             distance_m=2500, duration_seconds=900, cost_cny=2,
                                             source="演示数据", notice="离线固定演示路线，不代表真实路况。",
                                             steps=[RouteStep(mode="bus", instruction="公交接驳示例线路")])
                                 for left, right in zip(chosen, chosen[1:])]
    return assemble_trip(request, draft, cities, origin, legs, ["当前为离线演示，地点坐标、酒店、天气、交通及费用均为固定样例。"],
                         mode="demo", local_routes_by_day=local_routes)
