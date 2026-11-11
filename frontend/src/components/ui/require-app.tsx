import { Spin } from "antd";
import { type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../../hooks/use-auth";
import { useMyApps } from "../../hooks/use-apps";

/**
 * 应用级路由守卫：账号未被分配应用（或应用被后台关闭）时禁止进入。
 *
 * - 加载中：保持当前页 + Spin（默认按“可见”处理，避免误踢）；
 * - 管理员始终放行；
 * - 未授权：跳回应用中心，不带历史栈。
 */
export function RequireApp({ appKey, children }: { appKey: string; children: ReactNode }) {
  const auth = useAuth();
  const myApps = useMyApps();
  const location = useLocation();

  // bootstrap 探测期间不裁决（当前所有挂载点都在 ProtectedRoute 内，
  // 该分支属防御：防止守卫被复用到无 ProtectedRoute 的位置时误跳登录页）
  if (auth.isChecking) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "120px 0" }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (auth.user?.is_admin) {
    return <>{children}</>;
  }
  if (myApps.isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "120px 0" }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!myApps.has(appKey)) {
    return <Navigate to="/apps" replace />;
  }
  return <>{children}</>;
}

/** 管理页守卫：非管理员跳回应用中心。 */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const location = useLocation();

  if (auth.isChecking) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "120px 0" }}>
        <Spin size="large" />
      </div>
    );
  }
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (!auth.user?.is_admin) {
    return <Navigate to="/apps" replace />;
  }
  return <>{children}</>;
}
