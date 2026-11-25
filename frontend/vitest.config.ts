import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// 单元测试不加载根目录密钥；浏览器服务与 E2E 测试各自独立启动。
export default defineConfig({
  plugins: [vue()], envDir: false,
  test: { environment: 'jsdom', include: ['tests/**/*.test.ts'], restoreMocks: true },
})
