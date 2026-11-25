import { afterEach, expect, it, vi } from 'vitest'
import { parseEvent, streamTrip, type StreamEvent } from '../src/api'
import { form, result } from './fixtures'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const frame = (event: StreamEvent) => `event: ${event.type}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`
function mockStream(text: string, fragment = 1) {
  const bytes = new TextEncoder().encode(text)
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index += fragment) controller.enqueue(bytes.slice(index, index + fragment))
    controller.close()
  } }), { headers: { 'Content-Type': 'text/event-stream' } })))
}
it('中文 UTF-8 / CRLF 每字节分片仍能正确解析，忽略心跳', async () => {
  mockStream(': heartbeat\r\n\r\n' + frame({ type: 'attractions', status: 'running', message: '中文景点' }) +
    frame({ type: 'complete', message: '完成', data: result() }))
  const events: StreamEvent[] = []
  await streamTrip(form, event => events.push(event))
  expect(events.map(e => e.type)).toEqual(['attractions', 'complete'])
  expect(events[0].message).toBe('中文景点')
})
it('支持多行 data，拒绝不一致事件与不完整结果', () => {
  expect(parseEvent('event: warning\ndata: {"type":"warning",\ndata: "message":"提示"}')?.message).toBe('提示')
  expect(() => parseEvent('event: error\ndata: {"type":"warning","message":"bad"}')).toThrow()
  expect(() => parseEvent('event: complete\ndata: {"type":"complete","message":"bad","data":{}}')).toThrow()
})
it('EOF 没有终态时提示断流', async () => {
  mockStream(frame({ type: 'weather', status: 'done', message: '天气完成' }))
  await expect(streamTrip(form, vi.fn())).rejects.toThrow('连接提前结束')
})
it('error 事件即终态，不会当作成功结果', async () => {
  mockStream(frame({ type: 'error', message: '模型不可用' }))
  const listener = vi.fn()
  await streamTrip(form, listener)
  expect(listener).toHaveBeenCalledTimes(1)
  expect(listener).toHaveBeenCalledWith({ type: 'error', message: '模型不可用' })
})
it('展示 422 的字段详情', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'cities'], msg: '城市不能重复' }] }), { status: 422 })))
  await expect(streamTrip(form, vi.fn())).rejects.toThrow('cities：城市不能重复')
})
function pendingFetch() {
  vi.stubGlobal('fetch', vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })))
}
it('用户取消终止 HTTP 请求', async () => {
  pendingFetch()
  const controller = new AbortController()
  const pending = streamTrip(form, vi.fn(), controller.signal)
  controller.abort()
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
})
it('长时间无响应提示超时', async () => {
  vi.useFakeTimers(); pendingFetch()
  const expectation = expect(streamTrip(form, vi.fn(), undefined, 100)).rejects.toThrow('响应超时')
  await vi.advanceTimersByTimeAsync(101)
  await expectation
})
