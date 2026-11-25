<script setup lang="ts">
import type { TripResult } from '../api'

defineProps<{ leg: TripResult['intercity_legs'][number] }>()
</script>

<template>
  <article class="leg-card">
    <div class="leg-points"><strong>{{ leg.from }}</strong><i>→</i><strong>{{ leg.to }}</strong>
      <span>{{ leg.distance_km === null ? '距离暂无数据' : `驾车距离约 ${leg.distance_km} km` }}</span></div>
    <p class="leg-advice">{{ leg.advice }}</p>
    <div v-for="option in leg.transport?.options || []" :key="option.id" class="route-option-card"
      :class="{ recommended: option.id === leg.transport?.recommended_id }">
      <div class="option-heading"><strong>{{ option.id === leg.transport?.recommended_id ? '建议方案' : '其他参考' }}</strong>
        <small v-if="option.source === 'RailGo'"><a href="https://www.railgo.dev/" target="_blank" rel="noopener noreferrer">数据来源：RailGo</a></small>
        <small v-else>{{ option.source }}</small></div>
      <p>{{ option.summary }}</p>
      <div class="route-meta">
        <span>{{ option.mode === 'rail' ? '铁路' : option.mode === 'air' ? '航空' : option.mode === 'coach' ? '大巴' : '公共交通' }}</span>
        <span v-if="option.duration_minutes !== null">约 {{ option.duration_minutes }} 分钟</span>
        <span v-if="option.line_names.length">{{ option.line_names.join('、') }}</span>
        <span v-if="option.arrival_day_offset">次日到达</span>
        <b v-if="option.group_cost_cny !== null">同行参考 ¥{{ option.group_cost_cny }}</b>
        <span v-else>票价待查询</span>
      </div>
      <small v-if="option.date_verified && option.checked_at">按所选日期查询 · {{ option.checked_at }} 获取；以官方售票渠道为准</small>
      <small v-else>交通方式与时间仅供参考，未核实当日具体班次</small>
    </div>
    <small v-if="leg.transport">{{ leg.transport.notice }}</small>
    <div class="route-meta"><a href="https://www.12306.cn/" target="_blank" rel="noopener noreferrer">到 12306 核对车次与余票</a>
      <a v-if="(leg.distance_km || 0) >= 600" href="https://www.caac.gov.cn/te/" target="_blank" rel="noopener noreferrer">到民航局查询国内航班</a></div>
  </article>
</template>
