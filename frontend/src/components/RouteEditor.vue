<script setup lang="ts">
import { nextTick, ref } from 'vue'
import CityPicker from './CityPicker.vue'

const props = defineProps<{ origin: string; cities: string[]; disabled?: boolean; error?: string }>()
const emit = defineEmits<{
  origin: [city: string]
  add: [city: string]
  remove: [index: number]
  move: [from: number, to: number]
}>()
const picker = ref<InstanceType<typeof CityPicker> | null>(null)
const target = ref<'origin' | 'destination'>('origin')
const pickerOpen = ref(true)
const draggedCity = ref<number | null>(null)

async function chooseTarget(next: 'origin' | 'destination') {
  if (props.disabled || (next === 'destination' && !props.origin)) return
  target.value = next
  pickerOpen.value = true
  await nextTick()
  picker.value?.focus()
}
function selectCity(city: string) {
  if (target.value === 'origin') {
    emit('origin', city)
    target.value = 'destination'
    pickerOpen.value = true
    nextTick(() => picker.value?.focus())
  } else {
    emit('add', city)
    pickerOpen.value = false
  }
}
function dropCity(index: number) {
  if (!props.disabled && draggedCity.value !== null) emit('move', draggedCity.value, index)
  draggedCity.value = null
}
async function focus() { await chooseTarget(props.origin ? 'destination' : 'origin') }
defineExpose({ focus })
</script>

<template>
  <section class="route-editor" aria-label="出行路线编辑器">
    <div class="route-editor-heading">
      <div><span class="eyebrow">YOUR ROUTE</span><h2>规划你的出行路线</h2></div>
      <span class="counter">{{ cities.length }}/3 座旅游城市</span>
    </div>
    <p class="field-hint">从一座城市出发，依次走过 1–3 座目的地。出发地只用于交通规划。</p>
    <div class="route-flow">
      <div class="route-stop route-origin">
        <span class="route-node start-node" aria-hidden="true">起</span>
        <div class="route-stop-body route-stop-summary">
          <div><small>出发地 · 不安排游玩日程</small><strong>{{ origin || '尚未选择出发城市' }}</strong></div>
          <button type="button" :disabled="disabled" @click="chooseTarget('origin')">{{ origin ? '更换' : '选择' }}</button>
        </div>
      </div>
      <div class="route-stop route-destinations">
        <span class="route-node" aria-hidden="true">站</span>
        <div class="route-stop-body">
          <div class="route-stop-summary"><div><small>旅游城市 · 按访问顺序</small><strong>{{ cities.length ? `${cities.length} 座已加入路线` : '尚未添加旅游城市' }}</strong></div>
            <button type="button" :disabled="disabled || !origin || cities.length >= 3" @click="chooseTarget('destination')">＋ 添加下一站</button></div>
          <div v-if="cities.length" class="cities selected-cities" aria-label="已选城市与访问顺序">
            <div v-for="(city, index) in cities" :key="city" class="city-chip" :draggable="!disabled"
              @dragstart="draggedCity = index" @dragend="draggedCity = null" @dragover.prevent @drop.prevent="dropCity(index)">
              <span class="city-index">0{{ index + 1 }}</span><strong>{{ city }}</strong>
              <div class="chip-actions">
                <button type="button" :aria-label="`上移${city}`" :disabled="disabled || index === 0" @click="emit('move', index, index - 1)">↑</button>
                <button type="button" :aria-label="`下移${city}`" :disabled="disabled || index === cities.length - 1" @click="emit('move', index, index + 1)">↓</button>
                <button type="button" :aria-label="`删除${city}`" :disabled="disabled" @click="emit('remove', index)">×</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="pickerOpen" class="route-search-panel">
      <div class="route-search-heading"><strong>{{ target === 'origin' ? '选择出发城市' : '添加旅游城市' }}</strong>
        <button v-if="origin" type="button" :disabled="disabled" @click="pickerOpen = false">收起搜索</button></div>
      <CityPicker ref="picker" :key="target" :selected="target === 'origin' ? cities : [origin, ...cities]"
        :max="4" :label="target === 'origin' ? '选择出发城市' : '选择旅游城市'"
        :disabled="disabled" @add="selectCity" />
    </div>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </section>
</template>
