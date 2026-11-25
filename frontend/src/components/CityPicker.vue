<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref } from 'vue'
import catalog from '../../../shared/china_cities.json'
import { validateCity } from '../api'

interface CityRecord { city: string; province: string; featured: boolean }
const props = defineProps<{ selected: string[]; disabled?: boolean; max?: number; label?: string }>()
const emit = defineEmits<{ add: [city: string] }>()

const province = ref(''), query = ref(''), activeIndex = ref(-1), validating = ref(false), error = ref('')
const input = ref<HTMLInputElement | null>(null)
let pending: AbortController | null = null
const featured = new Set(catalog.featured)
const records: CityRecord[] = catalog.provinces.flatMap(group => group.cities.map(city => ({ city, province: group.name, featured: featured.has(city) })))
const provinces = catalog.provinces.map(group => group.name)
const canonical = (city: string) => city.replace(/市$/, '')
const visibleCities = computed(() => {
  const keyword = query.value.trim()
  return records.filter(record => (!province.value || record.province === province.value) &&
    // 空搜索只展示热门城市；完整目录只有在用户主动搜索时才出现。
    (Boolean(keyword) ? (record.city.includes(keyword) || record.province.includes(keyword)) : record.featured))
    .sort((a, b) => Number(b.featured) - Number(a.featured) || a.city.localeCompare(b.city, 'zh-CN'))
})

function isSelected(city: string) { return props.selected.some(item => canonical(item) === canonical(city)) }
function addKnown(city: string) {
  if (props.disabled || isSelected(city)) { if (isSelected(city)) error.value = '该城市已在行程中'; return }
  if (props.selected.length >= (props.max ?? 3)) { error.value = `最多可选择 ${props.max ?? 3} 个城市`; return }
  emit('add', city); query.value = ''; error.value = ''; activeIndex.value = -1
  nextTick(() => input.value?.focus())
}
function onKeydown(event: KeyboardEvent) {
  if (!visibleCities.value.length) return
  if (event.key === 'ArrowDown') { event.preventDefault(); activeIndex.value = Math.min(activeIndex.value + 1, visibleCities.value.length - 1) }
  if (event.key === 'ArrowUp') { event.preventDefault(); activeIndex.value = Math.max(activeIndex.value - 1, 0) }
  if (event.key === 'Enter' && activeIndex.value >= 0) { event.preventDefault(); addKnown(visibleCities.value[activeIndex.value].city) }
  if (event.key === 'Escape') activeIndex.value = -1
}
async function addManual() {
  const city = query.value.trim()
  if (!city || props.disabled || validating.value) { if (!city) error.value = '请输入城市名称'; return }
  if (props.selected.length >= (props.max ?? 3)) { error.value = `最多可选择 ${props.max ?? 3} 个城市`; return }
  pending?.abort(); pending = new AbortController(); validating.value = true; error.value = ''
  try {
    const result = await validateCity(city, pending.signal)
    if (!result.valid || !result.city) { error.value = result.message; return }
    addKnown(result.city)
  } catch (reason) {
    if (!pending.signal.aborted) error.value = reason instanceof Error ? reason.message : '城市校验失败，请重试'
  } finally { validating.value = false; pending = null }
}
function focus() { input.value?.focus() }
onUnmounted(() => pending?.abort())
defineExpose({ focus })
</script>

<template>
  <section class="city-picker" :aria-label="label || '选择旅行城市'">
    <div class="picker-controls">
      <label>所在省份
        <select v-model="province" :disabled="disabled" aria-label="按省份选择城市"><option value="">全部省份</option><option v-for="item in provinces" :key="item" :value="item">{{ item }}</option></select>
      </label>
      <label class="city-search-label">搜索或手工输入城市
        <input ref="input" v-model="query" :disabled="disabled" maxlength="40" autocomplete="off" aria-label="搜索或手工输入城市" placeholder="例如：杭州、大理、喀什" @keydown="onKeydown" @input="activeIndex = -1" />
      </label>
      <button type="button" class="manual-city-button" :disabled="disabled || validating" @click="addManual">{{ validating ? '正在验证…' : '验证并添加' }}</button>
    </div>
    <p class="picker-note">默认展示热门城市；搜索可查完整目录。手工输入需通过{{ catalog.scope }}校验后才会加入。</p>
    <div class="city-suggestions" role="listbox" aria-label="城市搜索结果">
      <button v-for="(record, index) in visibleCities" :key="record.province + record.city" type="button" class="city-option"
        :class="{ active: index === activeIndex, featured: record.featured }" :disabled="disabled || isSelected(record.city)" role="option"
        :aria-selected="index === activeIndex" @mousedown.prevent="addKnown(record.city)">
        <span>{{ record.city }}</span><small>{{ record.province }}{{ record.featured ? ' · 热门' : '' }}</small>
      </button>
      <p v-if="!visibleCities.length" class="empty-cities">没有目录匹配项；可点击“验证并添加”校验手工输入。</p>
    </div>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
  </section>
</template>
