<script setup lang="ts">
import type { DayPlan } from '../api'

defineProps<{ day: DayPlan; loading?: boolean; demo?: boolean }>()

function formatDistance(meters: number | null): string {
  if (meters === null) return ''
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${meters} m`
}
function placeLink(name: string, city: string): string {
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(name)}&city=${encodeURIComponent(city)}`
}
</script>

<template>
  <article class="day-card">
    <div class="day-number"><b>DAY</b><strong>{{ String(day.day).padStart(2, '0') }}</strong></div>
    <div class="day-main">
      <div class="day-title"><span>{{ day.date }} · {{ day.city }}</span><h3>{{ day.theme }}</h3>
        <small>{{ day.weather ? `${day.weather.summary} ${day.weather.temperature}` : '暂无该日期预报' }}</small></div>
      <div v-for="activity in day.activities" :key="activity.time" class="activity">
        <time>{{ activity.time }}</time>
        <div class="activity-media"><span aria-label="本地图片占位">{{ activity.poi_id ? '景' : '游' }}</span></div>
        <div class="activity-copy"><strong>{{ activity.title }}</strong><p>{{ activity.description }}</p>
          <small v-if="activity.poi_id" class="photo-credit">暂无获授权的实景照片 · <a :href="placeLink(activity.title, day.city)" target="_blank" rel="noopener noreferrer">在高德查看地点</a></small>
          <small v-else class="photo-credit">{{ demo ? '演示占位' : '自由活动' }}</small>
        </div>
        <b>{{ activity.estimated_cost === null ? '费用待定' : `约 ¥${activity.estimated_cost}` }}</b>
      </div>
      <section v-if="day.local_routes.length" class="day-connections" aria-label="当日景点间交通建议">
        <h4>景点间交通建议 <small>时间与线路均为查询时参考</small></h4>
        <article v-for="(route, index) in day.local_routes" :key="`${route.from_point}-${route.to_point}-${index}`" class="day-connection">
          <div class="connection-points"><strong>{{ route.from_point }}</strong><span>→</span><strong>{{ route.to_point }}</strong></div>
          <div class="connection-meta">
            <span>{{ route.mode === 'walking' ? '步行' : route.mode === 'driving' ? '驾车' : route.mode === 'bicycling' ? '骑行' : '公共交通' }}</span>
            <span v-if="route.line_names.length">{{ route.line_names.join('、') }}</span>
            <span v-if="route.distance_m !== null">{{ formatDistance(route.distance_m) }}</span>
            <span v-if="route.duration_seconds !== null">约 {{ Math.max(1, Math.round(route.duration_seconds / 60)) }} 分钟</span>
            <span v-if="route.cycling_minutes !== null && route.mode !== 'bicycling'">也可骑行约 {{ route.cycling_minutes }} 分钟</span>
            <span v-if="route.cost_cny !== null">参考费用 ¥{{ route.cost_cny }}</span>
            <span v-if="route.transfers">换乘 {{ route.transfers }} 次</span>
          </div>
        </article>
      </section>
      <p v-else-if="loading" class="route-load-state" role="status">正在查询当天景点间交通建议…</p>
      <p v-else-if="day.local_route_status === 'deferred'" class="route-load-state">打开这一天后将查询景点间交通建议。</p>
      <p v-else-if="day.local_route_status === 'unavailable'" class="route-load-state">当天接驳暂不可用，请通过官方地图核对。</p>
    </div>
  </article>
</template>
