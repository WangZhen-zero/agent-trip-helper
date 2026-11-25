import type { TripForm, TripResult } from '../src/api'

export const form: TripForm = {
  origin_city: '上海', cities: ['北京', '西安'], start_date: (() => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10) })(), end_date: (() => { const d = new Date(); d.setDate(d.getDate() + 2); return d.toISOString().slice(0, 10) })(), travelers: 2,
  budget_cny: 6000, interests: ['美食'], pace: '均衡', accommodation: '舒适', transport: '公共交通',
}
export function result(): TripResult {
  return {
    data_mode: 'demo', summary: '北京至西安离线示例', request: structuredClone(form), origin: { name: form.origin_city, location: null, adcode: null, attractions: [], forecasts: [], weather: null, hotel: null },
    cities: form.cities.map(name => ({ name, location: null, adcode: null, attractions: [], forecasts: [], weather: null, hotel: null })),
    itinerary: form.cities.map((city, i) => ({ day: i + 1, date: `2099-05-0${i + 1}`, city, theme: '城市探索', weather: null, local_route_status: 'ready', local_route_token: null, photo_token: null, local_routes: i === 0 ? [{ from_point: '景点甲', to_point: '景点乙', mode: 'transit', distance_m: 1200, duration_seconds: 600, cost_cny: 2, toll_cny: null, transfers: 0, source: '高德路线规划', notice: '路线参考', line_names: ['12路'], cycling_minutes: 9 }] : [],
      activities: [{ time: '10:00', poi_id: null, title: '自由探索', description: '资料待补充', location: null, estimated_cost: null, photo: null }] })),
    budget: { total_cny: 6000, estimated_cny: 1000, activities_cny: 0, known_intercity_cny: 0, unpriced_intercity_legs: 2, over_budget_cny: 0, breakdown: { food_cny: 1000 }, note: '仅供参考' },
    warnings: ['暂无天气'], intercity_legs: [{ from: '上海', to: '北京', distance_km: null, advice: '请自行核实', transport: null }, { from: '北京', to: '西安', distance_km: null, advice: '请自行核实', transport: null }],
    map: { city_path: [[116, 39], [108, 34]], markers: [
      { name: '北京', city: '北京', location: [116, 39], kind: 'city', day: null },
      { name: '西安', city: '西安', location: [108, 34], kind: 'city', day: null },
      { name: '<img onerror=alert(1)>', city: '北京', location: [116, 39], kind: 'attraction', day: 1 },
    ] },
  }
}
