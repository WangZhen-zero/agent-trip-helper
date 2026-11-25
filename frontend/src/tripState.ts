/** 表单与进度的纯逻辑，供组件和测试共享。告警不会覆盖当前阶段。 */
import type { MapMarker, Stage, StreamEvent, TripForm, TripResult } from './api'

export function localDate(offset = 0): string {
  const date = new Date()
  date.setDate(date.getDate() + offset)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export function validateForm(form: TripForm): string | null {
  if (!form.origin_city.trim()) return '请选择已验证的出发城市'
  if (form.cities.length < 1 || form.cities.length > 3) return '请选择 1–3 个旅游城市'
  const cities = form.cities.map(city => city.trim().replace(/市$/, ''))
  if (cities.some(city => !city) || new Set(cities).size !== cities.length) return '城市不能为空或重复'
  if (cities.includes(form.origin_city.trim().replace(/市$/, ''))) return '出发城市不能同时作为旅游城市'
  const days = (Date.parse(form.end_date) - Date.parse(form.start_date)) / 86400000 + 1
  if (!Number.isFinite(days) || days < 1 || days > 14) return '行程必须为 1–14 天'
  if (form.start_date < localDate() || form.start_date > localDate(15)) return '出发日期必须在未来 15 天内'
  if (days < cities.length) return '每个城市至少安排一天，总天数不能少于城市数'
  if (!Number.isInteger(form.travelers) || form.travelers < 1 || form.travelers > 10) return '同行人数必须为 1–10 人'
  if (!Number.isInteger(form.budget_cny) || form.budget_cny < 500 || form.budget_cny > 200000) return '总预算须为 500–200000 元的整数'
  if (!form.interests.length || form.interests.length > 4) return '请选择 1–4 项旅行偏好'
  return null
}

export function moveCity(cities: string[], from: number, to: number): void {
  if (from === to || from < 0 || to < 0 || from >= cities.length || to >= cities.length) return
  cities.splice(to, 0, cities.splice(from, 1)[0])
}

export interface ProgressState {
  running: boolean; current: Stage | null; completed: Stage[]; warnings: string[]
  message: string; error: string; result: TripResult | null
}
export function initialState(): ProgressState {
  return { running: false, current: null, completed: [], warnings: [], message: '', error: '', result: null }
}
export function consumeEvent(state: ProgressState, event: StreamEvent): void {
  if (event.type === 'warning') {
    if (!state.warnings.includes(event.message)) state.warnings.push(event.message)
    return
  }
  state.message = event.message
  if (event.type === 'error') { state.error = event.message; state.running = false; return }
  if (event.type === 'complete') {
    state.result = event.data; state.running = false
    state.warnings = [...new Set([...state.warnings, ...event.data.warnings])]
    return
  }
  state.current = event.type
  if (event.status === 'done' && !state.completed.includes(event.type)) state.completed.push(event.type)
}

export function filterMarkers(result: TripResult, day: number): MapMarker[] {
  const city = result.itinerary.find(item => item.day === day)?.city
  // 总览只看城市访问顺序；景点和住宿留在单日视图，避免全国地图挤满标签。
  return result.map.markers.filter(marker => day === 0
    ? marker.kind === 'origin' || marker.kind === 'city'
    : marker.day === day || (marker.kind === 'city' && marker.city === city))
}
