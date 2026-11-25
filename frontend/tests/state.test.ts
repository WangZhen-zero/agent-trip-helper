import { describe, expect, it } from 'vitest'
import { consumeEvent, filterMarkers, initialState, moveCity, validateForm } from '../src/tripState'
import { form, result } from './fixtures'

describe('表单与阶段状态', () => {
  it('校验城市、日期、人数与预算边界', () => {
    expect(validateForm(form)).toBeNull()
    for (const change of [
      { cities: ['北京', '北京市'] }, { cities: ['北京', '西安', '上海'] }, { cities: ['北京', ' '] },
      { start_date: '2000-01-01' }, { end_date: '2099-05-15' }, { travelers: 0 }, { travelers: 1.5 },
      { budget_cny: 499 }, { budget_cny: 200001 }, { interests: [] },
    ]) expect(validateForm({ ...form, ...change })).not.toBeNull()
  })
  it('按用户要求移动城市并忽略越界操作', () => {
    const cities = ['北京', '西安', '上海']
    moveCity(cities, 0, 2)
    expect(cities).toEqual(['西安', '上海', '北京'])
    moveCity(cities, 3, 0)
    expect(cities).toHaveLength(3)
  })
  it('告警不覆盖阶段，完成时去重合并', () => {
    const state = initialState()
    consumeEvent(state, { type: 'planning', status: 'running', message: '正在规划' })
    consumeEvent(state, { type: 'warning', message: '暂无天气' })
    expect(state.current).toBe('planning')
    expect(state.message).toBe('正在规划')
    consumeEvent(state, { type: 'planning', status: 'done', message: '已完成规划' })
    consumeEvent(state, { type: 'complete', message: '完成', data: result() })
    expect(state.warnings).toEqual(['暂无天气'])
    expect(state.completed).toEqual(['planning'])
  })
  it('地图按天筛选，包含当天城市', () => {
    expect(filterMarkers(result(), 0)).toHaveLength(2)
    expect(filterMarkers(result(), 1)).toHaveLength(2)
    expect(filterMarkers(result(), 2).map(marker => marker.name)).toEqual(['西安'])
  })
})
