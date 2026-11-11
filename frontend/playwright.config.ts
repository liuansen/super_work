import { defineConfig, devices } from "@playwright/test";

/**
 * 端到端冒烟：真实后端 + 真实前端。
 *
 * 覆盖的是「三轮 review 都发现不了」的跨层问题：前后端字段漂移、
 * 认证 cookie/header 契约、路由与权限、关键页面的整页渲染。
 *
 * 运行：npm run test:e2e（首次需 npx playwright install chromium）
 */
const BACKEND_PORT = 8787;
const FRONTEND_PORT = 5174;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // 独立临时库 + 关闭调度器：不触碰开发数据，也不发真实发布
      command: "python main.py --host 127.0.0.1 --port " + BACKEND_PORT,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      cwd: "..",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        ENVIRONMENT: "development",
        DATABASE_URL: "sqlite:///./data/e2e-playwright.db",
        SCHEDULER_ENABLED: "false",
        REGISTRATION_ENABLED: "true",
        SECRET_KEY: "e2e-only-secret-key-not-for-production",
        BACKEND_CORS_ORIGINS: `http://127.0.0.1:${FRONTEND_PORT}`,
      },
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        // vite.config.ts 的 proxy 目标固定 127.0.0.1:8000；
        // e2e 用 8787，直接改环境变量让代理指向 e2e 后端
        VITE_PROXY_TARGET: `http://127.0.0.1:${BACKEND_PORT}`,
      },
    },
  ],
});
