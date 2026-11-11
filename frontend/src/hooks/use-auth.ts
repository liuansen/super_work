import axios from "axios";
import { useEffect, useSyncExternalStore } from "react";

import * as api from "../lib/api";
import type { PlatformUser } from "../types";

type AuthStatus = "checking" | "authenticated" | "anonymous";

type AuthSnapshot = {
  status: AuthStatus;
  user: PlatformUser | null;
  error: string | null;
};

let snapshot: AuthSnapshot = {
  // FE-6：refresh token 在 HttpOnly Cookie 中，客户端不可读——
  // 初始一律进入 checking，由 /auth/refresh 探测结果决定最终状态
  status: "checking",
  user: null,
  error: null
};

let bootstrapped = false;
const listeners = new Set<() => void>();

// FE-5：api 层刷新失败（登录过期）时同步 store 到匿名态，
// 受保护页面会立即跳转登录页，不再滞留在"看似已登录"的状态
api.onAuthExpired(() => {
  emit({ status: "anonymous", user: null, error: "登录已过期，请重新登录。" });
});

function emit(next: AuthSnapshot): void {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): AuthSnapshot {
  return snapshot;
}

function authErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError(error)) {
    return fallback;
  }

  const detail = error.response?.data?.detail;
  if (detail === "Invalid username or password") {
    return "账号不存在或密码错误，请检查后重试。";
  }
  if (detail === "Username already exists") {
    return "该平台账号已存在，请直接登录或换一个账号。";
  }
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  return fallback;
}

async function bootstrap(): Promise<void> {
  if (bootstrapped) {
    return;
  }
  bootstrapped = true;

  emit({ ...snapshot, status: "checking", error: null });
  try {
    const user = await api.bootstrapAuth();
    emit(user ? { status: "authenticated", user, error: null } : { status: "anonymous", user: null, error: null });
  } catch {
    // FE-5：网络/5xx 不销毁 token（api 层已保留），UI 回到匿名态并提示重试；
    // 只有 api 层在明确 401/refresh 失效时才会清理凭证
    // review P3：失败后复位 bootstrapped，否则后续任何挂载都不会再探测，
    // 用户会一直停在“网络异常”的匿名态直到手动刷新页面
    bootstrapped = false;
    emit({ status: "anonymous", user: null, error: "网络异常，暂时无法验证登录状态，请稍后重试。" });
  }
}

async function login(credentials: api.AuthCredentials): Promise<void> {
  emit({ ...snapshot, error: null });
  try {
    const payload = await api.login(credentials);
    emit({ status: "authenticated", user: payload.user, error: null });
  } catch (error) {
    const message = authErrorMessage(error, "账号不存在或密码错误，请检查后重试。");
    emit({ status: "anonymous", user: null, error: message });
    throw new Error(message);
  }
}

async function register(credentials: api.AuthCredentials): Promise<void> {
  emit({ ...snapshot, error: null });
  try {
    const payload = await api.register(credentials);
    emit({ status: "authenticated", user: payload.user, error: null });
  } catch (error) {
    const message = authErrorMessage(error, "注册失败，该平台账号可能已存在。");
    emit({ status: "anonymous", user: null, error: message });
    throw new Error(message);
  }
}

async function logout(): Promise<void> {
  try {
    await api.logout();
  } finally {
    // 即使登出请求网络失败，本地也必须回到未登录态，
    // 否则 UI 停在“已登录”且后续请求全部 401
    emit({ status: "anonymous", user: null, error: null });
  }
}

export function useAuth() {
  const current = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    void bootstrap();
  }, []);

  return {
    ...current,
    isAuthenticated: current.status === "authenticated",
    isChecking: current.status === "checking",
    login,
    register,
    logout
  };
}
