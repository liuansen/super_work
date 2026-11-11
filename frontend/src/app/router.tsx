import { Spin } from "antd";
import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/layout/app-shell";
import { ComingSoonPage } from "../components/platforms/coming-soon";
import { ProtectedRoute, PublicOnlyRoute } from "../components/ui/protected-route";
import { RequireAdmin, RequireApp } from "../components/ui/require-app";
import { AppCenterPage } from '../pages/apps/app-center-page';
import { AppEntryPage } from '../pages/apps/app-entry-page';
import { LoginPage } from "../pages/login/login-page";

const AppManagePage = lazy(
  () => import("../pages/apps/app-manage-page").then((m) => ({ default: m.AppManagePage }))
);
const ClipPage = lazy(
  () => import("../features/clip/clip-page").then((m) => ({ default: m.ClipPage }))
);

// review P2：此前 30+ 页面全部静态导入，antd + 全部业务代码打进单一 chunk。
// 首屏只需要登录/应用中心/工作区骨架，其余页面按路由懒加载。
const DouyinShell = lazy(
  () => import("../features/douyin/douyin-shell").then((m) => ({ default: m.DouyinShell }))
);
const DouyinAccountsPage = lazy(
  () => import("../features/douyin/pages/accounts-page").then((m) => ({ default: m.DouyinAccountsPage }))
);
const DouyinReferencesPage = lazy(
  () => import("../features/douyin/pages/references-page").then((m) => ({ default: m.DouyinReferencesPage }))
);
const DouyinWorksPage = lazy(
  () => import("../features/douyin/pages/works-page").then((m) => ({ default: m.DouyinWorksPage }))
);
const DouyinPublishingPage = lazy(
  () => import("../features/douyin/pages/publishing-page").then((m) => ({ default: m.DouyinPublishingPage }))
);
const ModelConfigPage = lazy(
  () => import("../pages/models/model-config-page").then((m) => ({ default: m.ModelConfigPage }))
);
const SettingsPage = lazy(
  () => import("../pages/settings/settings-page").then((m) => ({ default: m.SettingsPage }))
);
const TaskCenterPage = lazy(
  () => import("../pages/tasks/task-center-page").then((m) => ({ default: m.TaskCenterPage }))
);
const AutoOpsPage = lazy(
  () => import("../pages/platforms/xhs/auto-ops-page").then((m) => ({ default: m.AutoOpsPage }))
);
const XhsAccountsPage = lazy(
  () => import("../pages/platforms/xhs/accounts-page").then((m) => ({ default: m.XhsAccountsPage }))
);
const XhsAnalyticsPage = lazy(
  () => import("../pages/platforms/xhs/analytics-page").then((m) => ({ default: m.XhsAnalyticsPage }))
);
const XhsBenchmarksPage = lazy(
  () => import("../pages/platforms/xhs/benchmarks-page").then((m) => ({ default: m.XhsBenchmarksPage }))
);
const XhsDashboard = lazy(
  () => import("../pages/platforms/xhs/xhs-dashboard").then((m) => ({ default: m.XhsDashboard }))
);
const XhsCrawlerPage = lazy(
  () => import("../pages/platforms/xhs/crawler-page").then((m) => ({ default: m.XhsCrawlerPage }))
);
const XhsDiscoveryPage = lazy(
  () => import("../pages/platforms/xhs/discovery-page").then((m) => ({ default: m.XhsDiscoveryPage }))
);
const XhsDraftsPage = lazy(
  () => import("../pages/platforms/xhs/rewrite-page").then((m) => ({ default: m.XhsDraftsPage }))
);
const XhsKeywordsPage = lazy(
  () => import("../pages/platforms/xhs/keywords-page").then((m) => ({ default: m.XhsKeywordsPage }))
);
const XhsLibraryPage = lazy(
  () => import("../pages/platforms/xhs/library-page").then((m) => ({ default: m.XhsLibraryPage }))
);
const XhsMonitoringPage = lazy(
  () => import("../pages/platforms/xhs/monitoring-page").then((m) => ({ default: m.XhsMonitoringPage }))
);
const XhsImageStudioPage = lazy(
  () => import("../pages/platforms/xhs/image-studio-page").then((m) => ({ default: m.XhsImageStudioPage }))
);
const XhsPublishPage = lazy(
  () => import("../pages/platforms/xhs/publish-page").then((m) => ({ default: m.XhsPublishPage }))
);
const XhsVideoStudioPage = lazy(
  () => import("../pages/platforms/xhs/video-studio-page").then((m) => ({ default: m.XhsVideoStudioPage }))
);
const XhsSectionPage = lazy(
  () => import("../pages/platforms/xhs/xhs-section-page").then((m) => ({ default: m.XhsSectionPage }))
);

/** 懒加载页面的统一占位（避免切路由时白屏闪烁） */
function RouteFallback() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "80px 0" }}>
      <Spin size="large" />
    </div>
  );
}

/**
 * 复核 P3：每个路由自带 Suspense，懒加载 fallback 只占内容区。
 * 此前唯一的顶层 Suspense 包在 Routes 外，任何 lazy 页面首载都会把
 * fallback 渲染成整页（含已挂载的 AppShell 侧栏/顶栏一起消失再回来）。
 */
function lazyPage(node: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{node}</Suspense>;
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Navigate to="/apps" replace />} />
          <Route
            path="/login"
            element={
              <PublicOnlyRoute>
                <LoginPage />
              </PublicOnlyRoute>
            }
          />
          <Route path="/platform-select" element={<Navigate to="/apps" replace />} />
          <Route path="/apps" element={<ProtectedRoute><AppCenterPage /></ProtectedRoute>} />
          <Route path="/apps/:appId" element={<ProtectedRoute><AppEntryPage /></ProtectedRoute>} />
          <Route
            path="/apps/manage"
            element={
              <ProtectedRoute>
                <RequireAdmin>{lazyPage(<AppManagePage />)}</RequireAdmin>
              </ProtectedRoute>
            }
          />
          {/* 剪辑工坊是独立应用：不进 AppShell，无小红书侧栏 */}
          <Route
            path="/clip"
            element={
              <ProtectedRoute>
                <RequireApp appKey="clip">{lazyPage(<ClipPage />)}</RequireApp>
              </ProtectedRoute>
            }
          />
          {/* 已上线平台不带 section 时回到默认页，而不是落到“即将开放”占位页 */}
          <Route path="/platforms/xhs" element={<Navigate to="/platforms/xhs/dashboard" replace />} />
          <Route
            path="/platforms/douyin"
            element={
              <ProtectedRoute>
                <RequireApp appKey="douyin">
                  {lazyPage(<DouyinShell />)}
                </RequireApp>
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/platforms/douyin/accounts" replace />} />
            <Route path="accounts" element={lazyPage(<DouyinAccountsPage />)} />
            <Route path="references" element={lazyPage(<DouyinReferencesPage />)} />
            <Route path="works" element={lazyPage(<DouyinWorksPage />)} />
            <Route path="publish" element={lazyPage(<DouyinPublishingPage />)} />
          </Route>
          <Route
            element={
              <ProtectedRoute>
                <RequireApp appKey="xhs">
                  <AppShell />
                </RequireApp>
              </ProtectedRoute>
            }
          >
            <Route path="/platforms/xhs/dashboard" element={lazyPage(<XhsDashboard />)} />
            <Route path="/platforms/xhs/accounts" element={lazyPage(<XhsAccountsPage />)} />
            <Route path="/platforms/xhs/analytics" element={lazyPage(<XhsAnalyticsPage />)} />
            <Route path="/platforms/xhs/discovery" element={lazyPage(<XhsDiscoveryPage />)} />
            <Route path="/platforms/xhs/crawler" element={lazyPage(<XhsCrawlerPage />)} />
            <Route path="/platforms/xhs/keywords" element={lazyPage(<XhsKeywordsPage />)} />
            <Route path="/platforms/xhs/library" element={lazyPage(<XhsLibraryPage />)} />
            <Route path="/platforms/xhs/drafts" element={lazyPage(<XhsDraftsPage />)} />
            {/* FE-12：监测页此前被 ：section 通配成占位页，监控无法从 UI 创建 */}
            <Route path="/platforms/xhs/monitoring" element={lazyPage(<XhsMonitoringPage />)} />
            <Route path="/platforms/xhs/benchmarks" element={lazyPage(<XhsBenchmarksPage />)} />
            <Route path="/platforms/xhs/image-studio" element={lazyPage(<XhsImageStudioPage />)} />
            <Route path="/platforms/xhs/video-studio" element={lazyPage(<XhsVideoStudioPage />)} />
            <Route path="/platforms/xhs/publish" element={lazyPage(<XhsPublishPage />)} />
            <Route path="/platforms/xhs/auto-ops" element={lazyPage(<AutoOpsPage />)} />
            <Route path="/platforms/xhs/:section" element={lazyPage(<XhsSectionPage />)} />
            <Route path="/tasks" element={lazyPage(<TaskCenterPage />)} />
            <Route path="/models" element={lazyPage(<ModelConfigPage />)} />
            <Route path="/settings" element={lazyPage(<SettingsPage />)} />
          </Route>
          <Route
            path="/platforms/:platformId"
            element={
              <ProtectedRoute>
                <ComingSoonPage />
              </ProtectedRoute>
            }
          />
          {/* review P2：未定义的路径此前渲染空白内容区，补 404 兜底 */}
          <Route path="*" element={<Navigate to="/apps" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
