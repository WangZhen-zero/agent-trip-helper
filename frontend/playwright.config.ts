import { defineConfig } from '@playwright/test'

const python = JSON.stringify(process.env.TRIP_TEST_PYTHON || 'python')

// 两个测试服务均固定为本地端口；前端仅代理到隔离的演示 API。
export default defineConfig({
  testDir: './e2e', timeout: 30_000, retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://127.0.0.1:15173', browserName: 'chromium' },
  webServer: [
    { command: `${python} -m uvicorn tests.demo_server:app --host 127.0.0.1 --port 18000`, cwd: '../backend', url: 'http://127.0.0.1:18000/api/v1/health', reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 15173', cwd: '.', url: 'http://127.0.0.1:15173', reuseExistingServer: false,
      env: { ...process.env, TRIP_BACKEND_URL: 'http://127.0.0.1:18000' } },
  ],
})
