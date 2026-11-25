import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import CityPicker from '../src/components/CityPicker.vue'
import { validateCity } from '../src/api'

vi.mock('../src/api', async importOriginal => ({ ...await importOriginal<object>(), validateCity: vi.fn() }))
afterEach(() => vi.clearAllMocks())

it('按省筛选、搜索和键盘操作都添加目录中的规范城市', async () => {
  const wrapper = mount(CityPicker, { props: { selected: [] } })
  await wrapper.get('[aria-label="按省份选择城市"]').setValue('浙江')
  expect(wrapper.findAll('.city-option').every(option => option.text().includes('浙江'))).toBe(true)
  await wrapper.get('[aria-label="搜索或手工输入城市"]').setValue('杭州')
  await wrapper.get('[aria-label="搜索或手工输入城市"]').trigger('keydown', { key: 'ArrowDown' })
  await wrapper.get('[aria-label="搜索或手工输入城市"]').trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('add')?.[0]).toEqual(['杭州'])
})
it('手工城市必须经后端验证；失败不加入，成功使用规范名称', async () => {
  const wrapper = mount(CityPicker, { props: { selected: [] } })
  vi.mocked(validateCity).mockResolvedValueOnce({ valid: false, city: null, province: null, message: '未找到该城市' })
  const input = wrapper.get('[aria-label="搜索或手工输入城市"]')
  await input.setValue('不存在之城'); await wrapper.get('.manual-city-button').trigger('click'); await flushPromises()
  expect(wrapper.emitted('add')).toBeUndefined(); expect(wrapper.text()).toContain('未找到该城市')
  vi.mocked(validateCity).mockResolvedValueOnce({ valid: true, city: '北京', province: '北京', message: '已验证' })
  await input.setValue('北京市'); await wrapper.get('.manual-city-button').trigger('click'); await flushPromises()
  expect(validateCity).toHaveBeenLastCalledWith('北京市', expect.any(AbortSignal)); expect(wrapper.emitted('add')?.[0]).toEqual(['北京'])
})
