import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import App from '../src/App.vue'
import TripMap from '../src/components/TripMap.vue'
import { fetchLocalDayRoutes, resolvePhotos, streamTrip, type StreamEvent } from '../src/api'
import { result } from './fixtures'

vi.mock('../src/api', async importOriginal => ({ ...await importOriginal<object>(), streamTrip: vi.fn(), fetchLocalDayRoutes: vi.fn(), resolvePhotos: vi.fn(), validateCity: vi.fn() }))
afterEach(() => { vi.unstubAllEnvs(); vi.clearAllMocks(); delete (window as any).AMap })

async function enterPlanner(wrapper: VueWrapper) {
  await wrapper.get('.welcome-cta').trigger('click')
  await flushPromises()
}
async function addKnown(wrapper: VueWrapper, city: string) {
  if (!wrapper.find('.city-picker').exists()) {
    await wrapper.get('.route-destinations .route-stop-summary button').trigger('click')
    await flushPromises()
  }
  const option = wrapper.find('.city-picker').findAll('.city-option').find(node => node.text().startsWith(city))
  if (!option) throw new Error(`未找到目录城市：${city}`)
  await option.trigger('mousedown'); await flushPromises()
}
async function addOrigin(wrapper: VueWrapper, city = '上海') {
  const option = wrapper.find('.city-picker').findAll('.city-option').find(node => node.text().startsWith(city))
  if (!option) throw new Error(`未找到出发城市：${city}`)
  await option.trigger('mousedown'); await flushPromises()
}

it('欢迎页不预置城市，进入规划器后可选择、排序并返回首页保留内容', async () => {
  const wrapper = mount(App)
  expect(wrapper.text()).toContain('把旅行的期待')
  expect(wrapper.findAll('.city-chip')).toHaveLength(0)
  await enterPlanner(wrapper); await addOrigin(wrapper); await addKnown(wrapper, '北京'); await addKnown(wrapper, '西安')
  expect(wrapper.findAll('.route-editor')).toHaveLength(1)
  expect(wrapper.findAll('.city-picker')).toHaveLength(0)
  expect(wrapper.find('.route-origin').text()).toContain('上海')
  expect(wrapper.find('.route-destinations .city-chip').attributes('draggable')).toBe('true')
  const chips = wrapper.findAll('.city-chip')
  await chips[0].trigger('dragstart'); await chips[1].trigger('drop')
  expect(wrapper.findAll('.city-chip strong').map(node => node.text())).toEqual(['西安', '北京'])
  await wrapper.get('.planner-nav button:last-child').trigger('click')
  await enterPlanner(wrapper)
  expect(wrapper.findAll('.city-chip strong').map(node => node.text())).toEqual(['西安', '北京'])
  wrapper.unmount()
})
it('AI 助手默认收起，可由浮动入口打开并通过 Escape 关闭', async () => {
  const wrapper = mount(App)
  await enterPlanner(wrapper)
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  await wrapper.get('.assistant-trigger').trigger('click')
  await flushPromises()
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await flushPromises()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  wrapper.unmount()
})
it('分阶段进度、告警独立显示，空字段与日期筛选均可展示', async () => {
  let listener!: (event: StreamEvent) => void; let finish!: () => void
  vi.mocked(streamTrip).mockImplementation(async (_form, onEvent) => { listener = onEvent; await new Promise<void>(resolve => { finish = resolve }) })
  const wrapper = mount(App); await enterPlanner(wrapper); await addOrigin(wrapper); await addKnown(wrapper, '北京'); await addKnown(wrapper, '西安')
  await wrapper.find('form').trigger('submit'); listener({ type: 'hotels', status: 'running', message: '正在查询酒店' }); listener({ type: 'warning', message: '暂无酒店信息' }); await flushPromises()
  expect(wrapper.find('.stage.current').text()).toContain('酒店推荐'); expect(wrapper.find('.live-message').text()).toBe('正在查询酒店'); expect(wrapper.find('.warnings').text()).toContain('暂无酒店信息')
  listener({ type: 'complete', message: '完成', data: result() }); finish(); await flushPromises()
  expect(wrapper.text()).toContain('暂无酒店推荐'); expect(wrapper.text()).toContain('费用待定'); expect(wrapper.findAll('.day-card')).toHaveLength(1)
  expect(wrapper.find('.day-connections').text()).toContain('12路')
  expect(wrapper.find('.day-connections').text()).toContain('骑行约 9 分钟')
  await wrapper.find('[aria-label="筛选行程日期"]').setValue('2'); expect(wrapper.findAll('.day-card')).toHaveLength(1); expect(wrapper.find('.day-card').text()).toContain('西安')
  expect(wrapper.find('.day-connections').exists()).toBe(false)
  await wrapper.findAll('input[type="number"]')[0].setValue(4); expect(wrapper.find('.result-intro').text()).toContain('2 人同行'); expect(document.querySelector('script[src*="amap"]')).toBeNull()
  wrapper.unmount()
})
it('取消后可以重新提交', async () => {
  vi.mocked(streamTrip).mockImplementation(async (_form, _listener, signal) => new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))))
  const wrapper = mount(App); await enterPlanner(wrapper); await addOrigin(wrapper); await addKnown(wrapper, '北京'); await addKnown(wrapper, '西安')
  await wrapper.find('form').trigger('submit'); await wrapper.find('.cancel-button').trigger('click'); await flushPromises()
  expect(wrapper.find('.error-banner').text()).toContain('已取消'); expect(wrapper.find('fieldset').attributes('disabled')).toBeUndefined()
  await wrapper.find('form').trigger('submit'); expect(streamTrip).toHaveBeenCalledTimes(2)
  wrapper.unmount(); await flushPromises()
})
it('仅在打开某天时查询市内接驳，切换日期取消旧请求', async () => {
  const trip = result()
  trip.data_mode = 'live'
  trip.itinerary[0].local_routes = []
  trip.itinerary[0].local_route_status = 'deferred'
  trip.itinerary[0].local_route_token = 'first-day-token'
  trip.itinerary[1].local_route_status = 'deferred'
  trip.itinerary[1].local_route_token = 'second-day-token'
  let firstSignal: AbortSignal | undefined
  vi.mocked(fetchLocalDayRoutes).mockImplementation((token, signal) => {
    if (token === 'first-day-token') {
      firstSignal = signal
      return new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
    }
    return Promise.resolve({ day: 2, status: 'ready', warnings: [], routes: [{
      from_point: '景点甲', to_point: '景点乙', mode: 'walking', distance_m: 500, duration_seconds: 420,
      cost_cny: null, toll_cny: null, transfers: null, line_names: [], cycling_minutes: null, source: '测试地图', notice: '参考',
    }] })
  })
  vi.mocked(streamTrip).mockImplementation(async (_form, onEvent) => { onEvent({ type: 'complete', message: '完成', data: trip }) })
  const wrapper = mount(App); await enterPlanner(wrapper); await addOrigin(wrapper); await addKnown(wrapper, '北京')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(fetchLocalDayRoutes).toHaveBeenCalledTimes(1)
  expect(wrapper.find('.route-load-state').text()).toContain('正在查询')
  await wrapper.find('[aria-label="筛选行程日期"]').setValue('2'); await flushPromises()
  expect(firstSignal?.aborted).toBe(true)
  expect(fetchLocalDayRoutes).toHaveBeenCalledTimes(2)
  expect(wrapper.find('.day-connections').text()).toContain('步行')
  wrapper.unmount()
})
it('未获图片授权时只展示占位和地点入口，不发图片查询', async () => {
  const trip = result()
  trip.data_mode = 'live'
  trip.itinerary[0].activities[0].poi_id = 'poi-one'
  trip.itinerary[0].activities[0].title = '故宫博物院'
  trip.cities[0].hotel = { id: 'hotel-one', name: '北京测试酒店', address: '北京', location: [116.4, 39.9], type: '酒店',
    note: '住宿参考', photo: null, photo_token: null }
  vi.mocked(streamTrip).mockImplementation(async (_form, onEvent) => { onEvent({ type: 'complete', message: '完成', data: trip }) })
  const wrapper = mount(App); await enterPlanner(wrapper); await addOrigin(wrapper); await addKnown(wrapper, '北京')
  await wrapper.find('form').trigger('submit'); await flushPromises()
  expect(resolvePhotos).not.toHaveBeenCalled()
  expect(wrapper.find('.activity-media img').exists()).toBe(false)
  expect(wrapper.find('.activity-copy a').attributes('href')).toContain('uri.amap.com/search')
  expect(wrapper.findAll('.hotel-placeholder')).toHaveLength(2)
  wrapper.unmount()
})
it('地图标签使用文本节点，切日重新渲染且卸载时销毁', async () => {
  vi.stubEnv('VITE_AMAP_JS_KEY', 'FAKE_BROWSER_KEY')
  const add = vi.fn(), destroy = vi.fn(), clearMap = vi.fn(); const markers: any[] = []
  ;(window as any).AMap = { Map: class { add = add; destroy = destroy; clearMap = clearMap; setFitView = vi.fn() }, Marker: class { constructor(options: any) { markers.push(options) } }, Polyline: class {}, Pixel: class {} }
  const data = result(); data.data_mode = 'live'; const wrapper = mount(TripMap, { props: { result: data, day: 0 } }); await flushPromises()
  expect(markers).toHaveLength(2) // 全部行程不堆叠景点标签
  await wrapper.setProps({ day: 1 })
  const pin = markers.find(marker => marker.title === '<img onerror=alert(1)>').content as HTMLElement
  expect(pin.textContent).toContain('<img onerror=')
  expect(pin.querySelector('img')).toBeNull()
  expect(pin.textContent).not.toContain('[object HTMLSpanElement]')
  await wrapper.setProps({ day: 2 }); expect(clearMap).toHaveBeenCalledTimes(3); wrapper.unmount(); expect(destroy).toHaveBeenCalledOnce()
})
