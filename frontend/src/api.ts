/** 与后端契约保持一致：未知事实为 null，不把缺失数据当作零费用或有效坐标。 */
export type Stage = 'attractions' | 'weather' | 'hotels' | 'planning' | 'transport'
export type Location = [number, number]
export interface TripForm {
  origin_city: string; cities: string[]; start_date: string; end_date: string; travelers: number; budget_cny: number
  interests: string[]; pace: string; accommodation: string; transport: string
}
export interface CityValidationResult { valid: boolean; city: string | null; province: string | null; message: string }
export interface Weather { date: string; summary: string; temperature: string; source: string }
export interface POI { id: string; name: string; address: string; location: Location | null; type: string }
export interface CityResult {
  name: string; location: Location | null; adcode: string | null; attractions: POI[]
  forecasts: Weather[]; weather: Weather | null; hotel: (POI & { note: string; photo: null; photo_token: string | null }) | null
}
export interface Activity { time: string; poi_id: string | null; title: string; description: string; location: Location | null; estimated_cost: number | null; photo: null }
export interface LocalRoute { from_point: string; to_point: string; mode: 'transit' | 'walking' | 'driving' | 'bicycling'; distance_m: number | null; duration_seconds: number | null; cost_cny: number | null; toll_cny: number | null; transfers: number | null; line_names: string[]; cycling_minutes: number | null; source: string; notice: string }
export interface DayPlan { day: number; date: string; city: string; theme: string; weather: Weather | null; activities: Activity[]; local_routes: LocalRoute[]; local_route_status: 'deferred' | 'ready' | 'unavailable'; local_route_token: string | null; photo_token: string | null }
export interface MapMarker { name: string; location: Location; kind: 'origin' | 'city' | 'attraction' | 'hotel'; city: string; day: number | null }
export interface TransportOption { id: string; mode: 'rail' | 'air' | 'coach' | 'bus' | 'subway' | 'transit' | 'other'; summary: string; duration_minutes: number | null; distance_m: number | null; transfers: number | null; cost_cny: number | null; group_cost_cny: number | null; line_names: string[]; service_number: string | null; departure_stop: string | null; arrival_stop: string | null; departure_time: string | null; arrival_time: string | null; arrival_day_offset: number; checked_at: string | null; date_verified: boolean; source: string }
export interface TransportPlan { from: string; to: string; departure_date: string; options: TransportOption[]; recommended_id: string | null; notice: string }
export interface TripResult {
  data_mode: 'demo' | 'live'; summary: string; request: TripForm; origin: CityResult; cities: CityResult[]; itinerary: DayPlan[]
  intercity_legs: { from: string; to: string; distance_km: number | null; advice: string; transport: TransportPlan | null }[]
  budget: { total_cny: number; estimated_cny: number; activities_cny: number; known_intercity_cny: number; unpriced_intercity_legs: number; over_budget_cny: number; note: string; breakdown: Record<string, number> }
  warnings: string[]; map: { city_path: Location[]; markers: MapMarker[] }
}
export type StreamEvent =
  | { type: Stage; status: 'running' | 'done'; message: string }
  | { type: 'warning'; message: string }
  | { type: 'error'; message: string; data?: { code: string } }
  | { type: 'complete'; message: string; data: TripResult }

export interface LocalDayRouteResult { day: number; status: 'ready' | 'unavailable'; routes: LocalRoute[]; warnings: string[] }
export interface PhotoResolveResult { photos: Record<string, null>; warnings: string[] }

/** 仅提交后端签发的地点令牌，图片服务不接受浏览器自报的酒店或景点坐标。 */
export async function resolvePhotos(photoToken: string, signal?: AbortSignal): Promise<PhotoResolveResult> {
  const response = await fetch('/api/v1/photos/resolve', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ photo_token: photoToken }),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `图片查询失败（HTTP ${response.status}）`)
  if (!payload.photos || typeof payload.photos !== 'object' || !Array.isArray(payload.warnings)) throw new Error('图片结果格式无效')
  return payload as PhotoResolveResult
}

/** 只发送服务端签名的日程凭证，不把任意坐标当作可信事实。 */
export async function fetchLocalDayRoutes(dayToken: string, signal?: AbortSignal): Promise<LocalDayRouteResult> {
  const response = await fetch('/api/v1/transport/local/day', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day_token: dayToken }), signal,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `接驳查询失败（HTTP ${response.status}）`)
  if (!Number.isInteger(payload.day) || !['ready', 'unavailable'].includes(payload.status) ||
      !Array.isArray(payload.routes) || !Array.isArray(payload.warnings)) throw new Error('接驳结果格式无效')
  return payload as LocalDayRouteResult
}

/** 手工城市只有得到后端确认后才能加入表单；服务异常不能伪装成“不存在”。 */
export async function validateCity(city: string, signal?: AbortSignal): Promise<CityValidationResult> {
  const response = await fetch('/api/v1/cities/validate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ city }), signal,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`
    throw new Error(detail)
  }
  if (typeof payload.valid !== 'boolean' || typeof payload.message !== 'string') throw new Error('城市校验结果格式无效')
  return payload as CityValidationResult
}

export function parseEvent(block: string): StreamEvent | null {
  const lines = block.split('\n')
  const eventName = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
  const raw = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
  if (!raw) return null // SSE 注释心跳没有 data，不改变页面进度。
  const value = JSON.parse(raw)
  if (!value || value.type !== eventName || typeof value.message !== 'string') throw new Error('进度数据格式无效')
  if (['attractions', 'weather', 'hotels', 'transport', 'planning'].includes(value.type)) {
    if (!['running', 'done'].includes(value.status)) throw new Error('阶段状态无效')
  } else if (value.type === 'complete') {
    const r = value.data
    if (!r || !['demo', 'live'].includes(r.data_mode) || !r.request || !r.origin || !Array.isArray(r.cities) ||
        !Array.isArray(r.itinerary) || !Array.isArray(r.warnings) || !Array.isArray(r.intercity_legs) ||
        !Array.isArray(r.map?.markers) || !Array.isArray(r.map?.city_path) || !Number.isFinite(r.budget?.estimated_cny)) {
      throw new Error('行程结果不完整，请重新生成')
    }
  } else if (!['warning', 'error'].includes(value.type)) throw new Error('未知进度事件')
  return value as StreamEvent
}

/** 对话采用独立 SSE 流，不污染行程 SSE 的状态机。 */
export async function streamChat(messages: { role: 'user' | 'assistant'; content: string }[], trip: TripForm | null,
                                 resultSummary: string | null, onDelta: (delta: string) => void, signal?: AbortSignal): Promise<void> {
  const response = await fetch('/api/v1/assistant/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ messages: messages.slice(-10), trip, result_summary: resultSummary }) })
  if (!response.ok || !response.body) throw new Error('助手服务暂不可用')
  const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = ''
  try { while (true) { const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    const blocks = buffer.split('\n\n'); buffer = blocks.pop() || ''
    for (const block of blocks) { const event = block.match(/^event:\s*(.+)$/m)?.[1]; const data = block.match(/^data:\s*(.+)$/m)?.[1]
      if (event === 'message' && data) onDelta(JSON.parse(data).delta || ''); if (event === 'error') throw new Error('助手服务暂不可用') }
    if (done) break
  }} finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
}

export async function streamTrip(payload: TripForm, onEvent: (event: StreamEvent) => void,
                                 signal?: AbortSignal, idleTimeoutMs = 45_000): Promise<void> {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  let timedOut = false
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  const cancel = () => controller.abort()
  signal?.addEventListener('abort', cancel, { once: true })
  if (signal?.aborted) cancel()
  const touch = () => {
    clearTimeout(timer)
    timer = setTimeout(() => { timedOut = true; controller.abort() }, idleTimeoutMs)
  }
  touch()
  try {
    const response = await fetch('/api/v1/trips/plan/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: controller.signal,
    })
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      const details = Array.isArray(error.detail) ? error.detail.map((item: { loc?: string[]; msg: string }) =>
        `${item.loc?.slice(1).join('.') || '表单'}：${item.msg}`).join('；') : ''
      throw new Error(details || `请求失败（HTTP ${response.status}）`)
    }
    if (!response.body) throw new Error('浏览器未收到进度流')
    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = '', terminal = false
    const consume = (block: string) => {
      if (terminal) return
      const event = parseEvent(block)
      if (event) {
        onEvent(event)
        terminal = event.type === 'complete' || event.type === 'error'
      }
    }
    while (!terminal) {
      const { value, done } = await reader.read()
      touch()
      // 网络分片可能切在中文 UTF-8 字节或 CRLF 中间，必须保留解码器和尾部缓存。
      pending = (pending + decoder.decode(value, { stream: !done })).replace(/\r\n/g, '\n')
      const blocks = pending.split('\n\n')
      pending = blocks.pop() || ''
      blocks.forEach(consume)
      if (done) {
        if (pending.trim()) consume(pending)
        if (!terminal) throw new Error('连接提前结束，未收到完整行程，请重试')
        break
      }
    }
  } catch (error) {
    if (timedOut) throw new Error('等待服务响应超时，请检查后端后重试')
    throw error
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
    await reader?.cancel().catch(() => undefined)
    reader?.releaseLock()
  }
}
