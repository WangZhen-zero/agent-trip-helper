<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import DayCard from './components/DayCard.vue'
import IntercityLegCard from './components/IntercityLegCard.vue'
import RouteEditor from './components/RouteEditor.vue'
import TripMap from './components/TripMap.vue'
import WelcomeScreen from './components/WelcomeScreen.vue'
import { fetchLocalDayRoutes, streamChat, streamTrip, type Stage, type TripForm } from './api'
import { consumeEvent, initialState, localDate, moveCity, validateForm } from './tripState'

// 城市必须由用户选择或经后端验证手工添加
const form = reactive<TripForm>({ origin_city: '', cities: [], start_date: localDate(7), end_date: localDate(10),
  travelers: 2, budget_cny: 6000, interests: ['历史人文', '美食'], pace: '均衡', accommodation: '舒适', transport: '公共交通' })
const view = ref<'welcome' | 'planner'>('welcome')
const state = reactive(initialState())
const cityError = ref(''), routeEditor = ref<InstanceType<typeof RouteEditor> | null>(null)
const selectedDay = ref(1)
const chatInput = ref(''), chatting = ref(false)
const assistantOpen = ref(false)
const assistantButton = ref<HTMLButtonElement | null>(null)
const chatInputElement = ref<HTMLInputElement | null>(null)
const chatMessages = ref<{ role: 'user' | 'assistant'; content: string }[]>([{ role: 'assistant', content: '你好，我可以帮你比较国内城市、预算、天气和交通参考。' }])
const stages: { type: Stage; label: string; icon: string }[] = [
  { type: 'attractions', label: '景点检索', icon: '⌘' }, { type: 'weather', label: '天气查询', icon: '☼' },
  { type: 'hotels', label: '酒店推荐', icon: '⌂' }, { type: 'planning', label: '智能规划', icon: '✦' }, { type: 'transport', label: '交通路线', icon: '↔' },
]
const interests = ['历史人文', '自然风光', '亲子', '美食', '博物馆', '购物', '城市漫游']
const visibleDays = computed(() => state.result?.itinerary.filter(day => day.day === selectedDay.value) || [])
const dataWarnings = computed(() => state.warnings.filter(item => !item.startsWith('估算费用') && !item.startsWith('部分活动暂无费用')))
const unpricedActivities = computed(() => state.result?.itinerary.reduce((count, day) =>
  count + day.activities.filter(activity => activity.estimated_cost === null).length, 0) || 0)
let controller: AbortController | null = null
let localController: AbortController | null = null
const localLoading = ref(false)

async function loadSelectedDayRoutes() {
  localController?.abort()
  localController = null
  localLoading.value = false
  const trip = state.result
  const day = trip?.itinerary.find(item => item.day === selectedDay.value)
  if (!day || day.local_route_status !== 'deferred' || !day.local_route_token) return
  const request = new AbortController()
  localController = request
  localLoading.value = true
  try {
    const data = await fetchLocalDayRoutes(day.local_route_token, request.signal)
    if (request.signal.aborted || state.result !== trip || data.day !== day.day) return
    day.local_routes = data.routes
    day.local_route_status = data.status
    for (const warning of data.warnings) if (!state.warnings.includes(warning)) state.warnings.push(warning)
  } catch (error) {
    if (!request.signal.aborted && state.result === trip) {
      day.local_route_status = 'unavailable'
      const message = error instanceof Error ? error.message : '市内接驳暂不可用'
      if (!state.warnings.includes(message)) state.warnings.push(message)
    }
  } finally {
    if (localController === request) { localController = null; localLoading.value = false }
  }
}
watch([() => state.result, selectedDay], () => { void loadSelectedDayRoutes() })

async function openPlanner() { view.value = 'planner'; await nextTick(); routeEditor.value?.focus() }
async function openAssistant() { assistantOpen.value = true; await nextTick(); chatInputElement.value?.focus() }
function closeAssistant() { assistantOpen.value = false; nextTick(() => assistantButton.value?.focus()) }
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && assistantOpen.value) { closeAssistant(); return }
  if (assistantOpen.value || !state.result || ['INPUT', 'SELECT', 'TEXTAREA'].includes((event.target as HTMLElement)?.tagName)) return
  if (event.key === 'ArrowLeft') previousDay()
  if (event.key === 'ArrowRight') nextDay()
}
function setOrigin(city: string) {
  if (city && form.cities.some(item => item.replace(/市$/, '') === city.replace(/市$/, ''))) {
    cityError.value = '出发城市不能与旅游城市相同'; return
  }
  form.origin_city = city; cityError.value = ''
}
function addCity(city: string) {
  const normalized = city.replace(/市$/, '')
  if (form.origin_city.replace(/市$/, '') === normalized) { cityError.value = '出发城市不能与旅游城市相同'; return }
  if (form.cities.some(value => value.replace(/市$/, '') === normalized)) { cityError.value = '该城市已在行程中'; return }
  if (form.cities.length >= 3) { cityError.value = '最多可安排 3 个旅游城市'; return }
  form.cities.push(city); cityError.value = ''
}
function reorderCity(from: number, to: number) { if (!state.running) moveCity(form.cities, from, to) }
function toggleInterest(interest: string) {
  const index = form.interests.indexOf(interest)
  if (index >= 0) form.interests.splice(index, 1)
  else if (form.interests.length < 4) form.interests.push(interest)
}
async function submit() {
  if (state.running) return
  const error = validateForm(form)
  if (error) { state.error = error; return }
  localController?.abort()
  Object.assign(state, initialState(), { running: true, message: '正在连接规划服务…' })
  selectedDay.value = 1
  controller = new AbortController()
  // 独立快照避免后续编辑城市或偏好时污染已经生成的行程结果。
  const payload: TripForm = JSON.parse(JSON.stringify(form))
  try {
    await streamTrip(payload, event => consumeEvent(state, event), controller.signal)
  } catch (error) {
    state.error = controller.signal.aborted ? '已取消本次规划，可调整后重新提交。' :
      error instanceof Error ? error.message : '规划失败，请重试'
  } finally { state.running = false; controller = null }
}
onUnmounted(() => { controller?.abort(); localController?.abort() })
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
async function sendChat() {
  const question = chatInput.value.trim(); if (!question || chatting.value) return
  chatMessages.value.push({ role: 'user', content: question }); chatInput.value = ''; chatting.value = true
  const reply = { role: 'assistant' as const, content: '' }; chatMessages.value.push(reply)
  try { await streamChat(chatMessages.value.slice(0, -1), form.origin_city ? JSON.parse(JSON.stringify(form)) : null, state.result?.summary || null, delta => { reply.content += delta }) }
  catch (error) { reply.content = error instanceof Error ? error.message : '助手服务暂不可用' }
  finally { chatting.value = false }
}
function previousDay() { selectedDay.value = Math.max(1, selectedDay.value - 1) }
function nextDay() { if (state.result) selectedDay.value = Math.min(state.result.itinerary.length, selectedDay.value + 1) }
</script>

<template>
  <WelcomeScreen v-if="view === 'welcome'" @start="openPlanner" />
  <main v-else class="planner-page">
    <nav class="planner-nav"><a class="brand" href="#" @click.prevent="view = 'welcome'"><i>✦</i> 行知</a><span>国内多城市旅行规划</span><button ref="assistantButton" type="button" class="assistant-trigger" aria-label="打开 AI 助手" :aria-expanded="assistantOpen" @click="openAssistant">✦ <span>AI 助手</span></button><button type="button" @click="view = 'welcome'">← 返回首页</button></nav>
    <section class="planner-shell planner-shell-top">
      <form class="planner-card" @submit.prevent="submit">
        <fieldset :disabled="state.running">
          <RouteEditor ref="routeEditor" :origin="form.origin_city" :cities="form.cities" :disabled="state.running" :error="cityError" @origin="setOrigin" @add="addCity" @remove="form.cities.splice($event, 1)" @move="reorderCity" />
          <div class="form-grid"><label>出发日期<input v-model="form.start_date" :min="localDate()" :max="localDate(15)" type="date" required /></label><label>返程日期<input v-model="form.end_date" :min="form.start_date" type="date" required /></label><label>同行人数<input v-model.number="form.travelers" type="number" min="1" max="10" required /></label><label>总预算（元）<input v-model.number="form.budget_cny" type="number" min="500" max="200000" step="1" required /></label></div>
          <div class="choice-row"><span>旅行偏好 <small>选择 1–4 项</small></span><div class="pills"><button v-for="item in interests" :key="item" type="button" :aria-pressed="form.interests.includes(item)" :class="{ active: form.interests.includes(item) }" @click="toggleInterest(item)">{{ item }}</button></div></div>
          <div class="select-grid"><label>行程节奏<select v-model="form.pace"><option>悠闲</option><option>均衡</option><option>充实</option></select></label><label>住宿档次<select v-model="form.accommodation"><option>经济</option><option>舒适</option><option>高端</option></select></label><label>市内交通<select v-model="form.transport"><option>公共交通</option><option>步行优先</option><option>驾车</option></select></label></div>
          <button class="generate" type="submit"><span>{{ state.running ? '正在为你规划…' : '开始生成我的行程' }}</span><b>→</b></button>
        </fieldset>
        <button v-if="state.running" type="button" class="cancel-button" @click="controller?.abort()">取消规划</button><p class="form-note">不含实时票价、酒店库存与预订服务；建议结果仅供出行参考。</p>
      </form>
    </section>
    <Teleport to="body"><Transition name="drawer"><div v-if="assistantOpen" class="assistant-layer"><button class="assistant-backdrop" aria-label="关闭助手面板" @click="closeAssistant"></button><aside class="assistant-drawer" aria-label="旅行 AI 助手" role="dialog" aria-modal="true"><header><div><span class="eyebrow">TRAVEL AGENT</span><h2>旅途灵感助手</h2></div><button type="button" class="assistant-close" aria-label="关闭 AI 助手" @click="closeAssistant">×</button></header><p class="assistant-intro">可以问我路线、天气、预算或每日安排建议。</p><div class="chat-history"><p v-for="(message, index) in chatMessages" :key="index" :class="message.role">{{ message.content || '正在思考…' }}</p></div><form class="chat-form" @submit.prevent="sendChat"><input ref="chatInputElement" v-model="chatInput" :disabled="chatting" maxlength="600" placeholder="例如：这天可以安排得轻松些吗？" /><button :disabled="chatting || !chatInput.trim()">发送</button></form><small>建议不会直接修改表单或已生成行程；路线时间与费用仅供参考。</small></aside></div></Transition></Teleport>
    <section v-if="state.message" class="progress-wrap" aria-live="polite"><div class="progress-card"><div v-for="stage in stages" :key="stage.type" class="stage" :class="{ done: state.completed.includes(stage.type), current: state.running && stage.type === state.current && !state.completed.includes(stage.type) }"><i>{{ stage.icon }}</i><span>{{ stage.label }}</span></div></div><p class="live-message">{{ state.message }}</p></section>
    <p v-if="state.error" class="error-banner" role="alert">{{ state.error }}</p><section v-if="dataWarnings.length" class="warnings warning-panel" aria-label="数据提示"><strong>数据提示</strong><p v-for="warning in dataWarnings" :key="warning">{{ warning }}</p></section>
    <section v-if="state.result" class="results"><header class="result-intro"><span class="eyebrow">{{ state.result.data_mode === 'demo' ? 'OFFLINE DEMO · 离线演示' : 'YOUR ITINERARY' }}</span><h2>{{ state.result.summary }}</h2><p>{{ state.result.request.start_date }} — {{ state.result.request.end_date }} · {{ state.result.request.travelers }} 人同行 · {{ state.result.request.budget_cny.toLocaleString() }} 元预算</p></header>
      <div class="result-workspace"><div class="result-primary">
      <section class="itinerary"><div class="section-heading"><div><span class="eyebrow">DAY BY DAY</span><h2>每日安排</h2></div><span class="budget-pill">规划估算 ¥{{ state.result.budget.estimated_cny.toLocaleString() }}</span></div><div class="budget-detail"><span v-if="state.result.intercity_legs.length > state.result.budget.unpriced_intercity_legs">供应商已报价城际参考：¥{{ state.result.budget.known_intercity_cny.toLocaleString() }}</span><span v-else>暂无供应商城际报价</span><span v-if="state.result.budget.unpriced_intercity_legs">{{ state.result.budget.unpriced_intercity_legs }} 段城际交通尚无报价</span><span v-if="unpricedActivities">{{ unpricedActivities }} 项活动费用待定</span><strong v-if="state.result.budget.over_budget_cny">超出预算 ¥{{ state.result.budget.over_budget_cny.toLocaleString() }}</strong></div><p class="field-hint">{{ state.result.budget.note }}</p><div class="day-switch"><button type="button" :disabled="selectedDay <= 1" @click="previousDay">← 上一天</button><button v-for="item in state.result.itinerary" :key="item.day" :class="{ active: selectedDay === item.day }" type="button" @click="selectedDay = item.day">D{{ item.day }}</button><button type="button" :disabled="selectedDay >= state.result.itinerary.length" @click="nextDay">下一天 →</button></div><TransitionGroup name="day-slide" tag="div"><DayCard v-for="day in visibleDays" :key="day.day" :day="day" :loading="localLoading" :demo="state.result.data_mode === 'demo'" /></TransitionGroup></section>
      <section class="city-overview"><article v-for="city in state.result.cities" :key="city.name" class="city-card"><div class="hotel-image"><div class="hotel-placeholder" aria-label="酒店外景图片占位">⌂<small>暂无获授权的酒店外景照片</small></div></div><div class="city-card-content"><span class="eyebrow">{{ city.weather?.summary || '暂无行程日天气' }}</span><h3>{{ city.name }}</h3><p>{{ city.weather?.temperature }}</p><strong>{{ city.hotel?.name || '暂无酒店推荐' }}</strong><small>{{ city.hotel?.note }}</small></div></article></section>
      </div><aside class="result-side"><TripMap v-model:day="selectedDay" :result="state.result" />
      <section class="legs"><div class="section-heading"><div><span class="eyebrow">TRANSPORT REFERENCE</span><h2>国内城际交通</h2></div></div><IntercityLegCard v-for="leg in state.result.intercity_legs" :key="leg.from + leg.to" :leg="leg" /></section></aside></div>
    </section>
  </main>
</template>
