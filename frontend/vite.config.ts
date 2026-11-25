import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  // 与后端共用根目录 .env；只有 VITE_ 前缀会进入浏览器构建。
  envDir: fileURLToPath(new URL('..', import.meta.url)),
  envPrefix: 'VITE_',
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': process.env.TRIP_BACKEND_URL || 'http://127.0.0.1:8000' },
  },
})
