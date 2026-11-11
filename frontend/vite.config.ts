import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    // antd 全量组件库单 chunk 约 1.4MB（gzip ~440KB），已单独作为
    // 长期缓存的 vendor chunk；这里放宽告警阈值避免构建噪音
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        // 把第三方大依赖拆成稳定的 vendor chunk：业务代码改动不再让
        // 1MB+ 的 antd chunk 缓存失效，首屏也可并行下载
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          antd: ["antd", "@ant-design/icons"],
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        // e2e 用 VITE_PROXY_TARGET 指向临时后端（默认仍是本地 8000）
        target: process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
    },
  },
});
