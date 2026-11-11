import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios, { AxiosError, type AxiosRequestConfig } from "axios";

import {
  clearAuthTokens,
  getAccessToken,
  httpInstance,
  onAuthExpired,
  refreshAccessToken,
} from "./api";

type MockHandler = (config: AxiosRequestConfig) => {
  status: number;
  data?: unknown;
};

const originalAdapter = httpInstance.defaults.adapter;

/** 用受控 mock adapter 替换传输层；非 2xx 需手动 reject（内置 settle 不生效） */
function installAdapter(handler: MockHandler) {
  const calls: string[] = [];
  httpInstance.defaults.adapter = async (config: AxiosRequestConfig) => {
    const url = String(config.url ?? "");
    calls.push(`${String(config.method ?? "get").toUpperCase()} ${url}`);
    const result = handler(config);
    const response = {
      data: result.data ?? {},
      status: result.status,
      statusText: String(result.status),
      headers: {},
      config,
      request: {},
    };
    if (result.status >= 200 && result.status < 300) {
      return response as never;
    }
    throw new AxiosError(
      `Request failed with status code ${result.status}`,
      result.status === 401 ? axios.HttpStatusCode.Unauthorized.toString() : undefined,
      config as never,
      {},
      response as never,
    );
  };
  return calls;
}

beforeEach(() => {
  clearAuthTokens();
  window.localStorage.clear();
});

afterEach(() => {
  httpInstance.defaults.adapter = originalAdapter;
  vi.restoreAllMocks();
});

describe("api.ts 认证拦截器（FE-1/FE-5/FE-6）", () => {
  it("登录 401 不触发刷新（认证端点跳过刷新逻辑）", async () => {
    const calls = installAdapter((config) => {
      const url = String(config.url ?? "");
      if (url.includes("/auth/login")) return { status: 401, data: { detail: "Invalid username or password" } };
      return { status: 500 };
    });

    let loginFailed = false;
    await httpInstance.post("/auth/login", { username: "u", password: "p" }).catch(() => {
      loginFailed = true;
    });

    expect(loginFailed).toBe(true);
    // 只有 login 请求本身，没有任何 /auth/refresh 请求（P0-7 死循环根因）
    expect(calls.filter((c) => c.includes("/auth/refresh"))).toHaveLength(0);
  });

  it("refresh 自身 401 不再递归刷新", async () => {
    let refreshCalls = 0;
    installAdapter((config) => {
      if (String(config.url ?? "").includes("/auth/refresh")) {
        refreshCalls += 1;
        return { status: 401 };
      }
      return { status: 401 };
    });

    await refreshAccessToken().catch(() => undefined);

    expect(refreshCalls).toBe(1);
  });

  it("并发 401 共用同一次刷新（单飞）", async () => {
    let refreshCalls = 0;
    const calls = installAdapter((config) => {
      const url = String(config.url ?? "");
      if (url.includes("/auth/refresh")) {
        refreshCalls += 1;
        return { status: 200, data: { access_token: "new-token", token_type: "bearer" } };
      }
      if (url.startsWith("/notes")) {
        // 首次请求 401 → 刷新 → 重试成功
        const auth = (config.headers as Record<string, string> | undefined)?.Authorization;
        if (auth === "Bearer new-token") return { status: 200, data: { items: [], total: 0 } };
        return { status: 401 };
      }
      return { status: 404 };
    });

    const [a, b, c] = await Promise.all([
      httpInstance.get("/notes").catch(() => null),
      httpInstance.get("/notes").catch(() => null),
      httpInstance.get("/notes").catch(() => null),
    ]);

    expect(refreshCalls).toBe(1);
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(c).not.toBeNull();
    expect(getAccessToken()).toBe("new-token");
    void calls;
  });

  it("刷新失败时通知认证过期监听者（FE-5）", async () => {
    installAdapter((config) => {
      if (String(config.url ?? "").includes("/auth/refresh")) return { status: 401 };
      return { status: 401 };
    });

    const expired = vi.fn();
    const unsubscribe = onAuthExpired(expired);
    try {
      await httpInstance.get("/notes").catch(() => undefined);
      expect(expired).toHaveBeenCalledTimes(1);
    } finally {
      unsubscribe();
    }
  });

  it("refresh 请求不携带 body 的 refresh_token（FE-6 cookie 化）", async () => {
    let refreshBody: unknown = undefined;
    installAdapter((config) => {
      if (String(config.url ?? "").includes("/auth/refresh")) {
        refreshBody = config.data;
        return { status: 200, data: { access_token: "t", token_type: "bearer" } };
      }
      return { status: 404 };
    });

    await refreshAccessToken();
    // cookie 由 withCredentials 携带，请求体应为空
    expect(refreshBody == null || refreshBody === "null" || refreshBody === "").toBe(true);
  });
});
