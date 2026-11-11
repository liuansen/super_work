import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

type ThemeMode = "dark" | "light";

const ThemeContext = createContext<{ mode: ThemeMode; toggle: () => void }>({
  mode: "dark",
  toggle: () => {},
});

export function useThemeMode() {
  return useContext(ThemeContext);
}

const darkTokens = {
  colorPrimary: "#1668dc",
  colorBgBase: "#141414",
  colorBgContainer: "#1f1f1f",
  colorBgElevated: "#262626",
  colorBorder: "#303030",
  colorBorderSecondary: "#262626",
  borderRadius: 6,
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
};

const lightTokens = {
  colorPrimary: "#1668dc",
  colorBgBase: "#ffffff",
  colorBgContainer: "#ffffff",
  colorBgElevated: "#ffffff",
  colorBorder: "#e8e8e8",
  colorBorderSecondary: "#f0f0f0",
  borderRadius: 6,
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
};

const darkComponents = {
  Layout: { siderBg: "#141414", headerBg: "#141414", bodyBg: "#0a0a0a" },
  Menu: { darkItemBg: "#141414", darkSubMenuItemBg: "#141414", darkItemSelectedBg: "#1668dc20", darkItemSelectedColor: "#1668dc" },
  Card: { colorBgContainer: "#1a1a1a" },
  Table: { colorBgContainer: "#1a1a1a", headerBg: "#1f1f1f" },
};

const lightComponents = {
  Layout: { siderBg: "#ffffff", headerBg: "#ffffff", bodyBg: "#f5f5f5" },
  Menu: {},
  Card: {},
  Table: {},
};

// 服务端状态缓存：账号/通知等高频共享数据的 staleTime 内不重复请求。
// retry 保持 1 次（后端不可用时别放大轮询压力），窗口聚焦不自动重取，
// 避免长时间后台后切回来同时打出一串请求。
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

type AppProvidersProps = { children: ReactNode };

export function AppProviders({ children }: AppProvidersProps) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem("theme-mode");
    return saved === "light" ? "light" : "dark";
  });

  useEffect(() => {
    localStorage.setItem("theme-mode", mode);
    document.documentElement.dataset.theme = mode;
    document.body.style.background = mode === "dark" ? "#141414" : "#f5f5f5";
  }, [mode]);

  const toggle = () => setMode((m) => (m === "dark" ? "light" : "dark"));
  const isDark = mode === "dark";

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeContext.Provider value={{ mode, toggle }}>
        <ConfigProvider
          locale={zhCN}
          theme={{
            algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
            token: isDark ? darkTokens : lightTokens,
            components: isDark ? darkComponents : lightComponents,
          }}
        >
          <App>{children}</App>
        </ConfigProvider>
      </ThemeContext.Provider>
    </QueryClientProvider>
  );
}
