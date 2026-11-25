<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MapMarker, TripResult } from '../api'
import { filterMarkers } from '../tripState'

const props = defineProps<{ result: TripResult; day: number }>()
const emit = defineEmits<{ 'update:day': [value: number] }>()
const mapElement = ref<HTMLDivElement | null>(null)
const unavailable = ref('')
// 演示模式永不加载高德 SDK；没有浏览器 Key 时同样展示本地路线示意。
const useSdk = props.result.data_mode === 'live' && Boolean(import.meta.env.VITE_AMAP_JS_KEY)
const markers = computed(() => filterMarkers(props.result, props.day))
const labels = computed(() => props.day === 0 ? [props.result.origin.name, ...props.result.cities.map(city => city.name)] :
  props.result.itinerary.find(day => day.day === props.day)?.activities.map(activity => activity.title) || [])
const viewCaption = computed(() => props.day === 0
  ? `从 ${props.result.origin.name} 出发 · ${props.result.cities.length} 座旅游城市`
  : `第 ${props.day} 天 · ${props.result.itinerary.find(item => item.day === props.day)?.city || '当日景点'}`)
let map: any
let disposed = false
let script: HTMLScriptElement | null = null
let loadTimer: ReturnType<typeof setTimeout> | undefined
let rejectLoad: ((reason: Error) => void) | undefined

function markerContent(marker: MapMarker): HTMLDivElement {
  // 高德 label.content 对 HTMLElement 的处理可能变成字符串；自定义 Marker.content 明确支持 DOM。
  // 所有来自 POI 和模型的文字都只写入 textContent，绝不拼入 HTML。
  const root = document.createElement('div')
  root.className = `trip-map-pin trip-map-pin--${marker.kind}`
  const dot = document.createElement('span')
  dot.className = 'trip-map-pin__dot'
  dot.textContent = marker.kind === 'origin' ? '起' : marker.kind === 'hotel' ? '宿' :
    marker.kind === 'attraction' ? '景' : String(props.result.cities.findIndex(city => city.name === marker.city) + 1)
  const name = document.createElement('span')
  name.className = 'trip-map-pin__name'
  name.textContent = marker.name
  root.append(dot, name)
  return root
}

function renderMap() {
  const api = (window as any).AMap
  if (!map || !api) return
  map.clearMap()
  markers.value.forEach(marker => {
    map.add(new api.Marker({ position: marker.location, title: marker.name,
      content: markerContent(marker), offset: new api.Pixel(-14, -14),
      zIndex: marker.kind === 'origin' || marker.kind === 'city' ? 20 : 15 }))
  })
  // 仅画城市间示意连线；不把供应商逐转弯导航几何发送到浏览器。
  if (props.day === 0 && props.result.map.city_path.length > 1) map.add(new api.Polyline({
    path: props.result.map.city_path, strokeColor: '#d49a31', strokeWeight: 3,
    strokeOpacity: 0.8, strokeStyle: 'dashed',
  }))
  if (markers.value.length) map.setFitView()
}

onMounted(async () => {
  if (!useSdk || !mapElement.value) return
  try {
    ;(window as any)._AMapSecurityConfig = { securityJsCode: import.meta.env.VITE_AMAP_SECURITY_JS_CODE || '' }
    if (!(window as any).AMap) {
      await new Promise<void>((resolve, reject) => {
        rejectLoad = reject
        script = document.createElement('script')
        script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(import.meta.env.VITE_AMAP_JS_KEY || '')}`
        script.onload = () => { clearTimeout(loadTimer); resolve() }
        script.onerror = () => reject(new Error('地图加载失败，已展示本地示意'))
        loadTimer = setTimeout(() => reject(new Error('地图加载超时，已展示本地示意')), 15000)
        document.head.appendChild(script)
      })
    }
    if (disposed) return
    map = new (window as any).AMap.Map(mapElement.value, { zoom: 5, center: [108.95, 34.27], viewMode: '2D' })
    renderMap()
  } catch (error) {
    if (!disposed) unavailable.value = error instanceof Error ? error.message : '地图不可用'
  } finally { clearTimeout(loadTimer) }
})
watch(() => [props.day, props.result], renderMap)
onUnmounted(() => {
  disposed = true
  clearTimeout(loadTimer)
  rejectLoad?.(new Error('地图已卸载'))
  script?.remove()
  map?.destroy()
})
</script>

<template>
  <section class="map-card">
    <div class="section-heading">
      <div><span class="eyebrow">MAP</span><h2>行程地图</h2></div>
      <label class="map-filter">查看范围
        <select aria-label="筛选行程日期" :value="day" @change="emit('update:day', Number(($event.target as HTMLSelectElement).value))">
          <option :value="0">全部行程</option>
          <option v-for="item in result.itinerary" :key="item.day" :value="item.day">第 {{ item.day }} 天 · {{ item.city }}</option>
        </select>
      </label>
    </div>
    <p class="map-caption">{{ viewCaption }}</p>
    <div v-if="!useSdk || unavailable" class="map-placeholder" data-testid="local-route">
      <strong>{{ result.data_mode === 'demo' ? '离线演示 · 路线示意' : unavailable || '未配置地图，展示路线示意' }}</strong>
      <svg role="img" aria-label="行程路线示意图" :viewBox="`0 0 ${Math.max(400, labels.length * 180)} 160`" class="route-diagram">
        <line v-if="labels.length > 1" x1="90" y1="65" :x2="(labels.length - 1) * 180 + 90" y2="65" stroke="#0f766e" stroke-width="3" stroke-dasharray="7 5" />
        <g v-for="(label, index) in labels" :key="index" :transform="`translate(${index * 180 + 90},65)`">
          <circle r="20" fill="#0f766e" /><text y="5" text-anchor="middle" fill="white">{{ index + 1 }}</text>
          <text y="48" text-anchor="middle" font-size="13">{{ label.length > 10 ? label.slice(0, 10) + '…' : label }}</text>
        </g>
      </svg>
      <small>连线只表示访问顺序，不是导航路线或实际距离。</small>
    </div>
    <div v-else ref="mapElement" class="amap-container"></div>
    <div class="map-footer">
      <div class="map-legend" aria-label="地图标记说明"><span><i class="legend-origin"></i>出发地</span><span><i class="legend-city"></i>旅游城市</span><span v-if="day !== 0"><i class="legend-place"></i>景点 / 住宿</span></div>
      <small v-if="day === 0">橙色虚线仅表示访问顺序，并非实际道路或导航路线。</small>
      <small v-else>切换日期，查看当天已核实的景点和住宿位置。</small>
    </div>
  </section>
</template>
