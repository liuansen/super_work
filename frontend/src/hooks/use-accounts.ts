import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchAccounts } from "../lib/api";
import { useAuth } from "./use-auth";
import type { PlatformAccount } from "../types";

// key 含用户 id：全局 QueryClient 是单例，换账号登入不得复用前任用户的账号列表
export const accountsQueryKey = (platform: string, userId?: number) =>
  ["accounts", userId ?? 0, platform] as const;

/**
 * 账号列表（共享缓存）。
 *
 * 此前 5 个页面各自调 fetchAccounts（每次还要 100/页翻页聚合全量），
 * 来回切页面就重复请求。这里走 TanStack Query：
 * - staleTime 30s 内复用缓存；
 * - 同一时刻多个组件订阅只发一次请求；
 * - 账号增删改后 invalidate 即可全局刷新。
 */
export function useAccounts(platform = "xhs") {
  const auth = useAuth();
  const query = useQuery({
    queryKey: accountsQueryKey(platform, auth.user?.id),
    queryFn: () => fetchAccounts(platform),
    staleTime: 30_000,
  });

  return {
    accounts: (query.data ?? []) as PlatformAccount[],
    isLoading: query.isLoading,
    error: query.error,
    refresh: query.refetch,
  };
}

/** 账号数据变更后调用（绑定/删除账号等）。 */
export function useInvalidateAccounts(platform = "xhs") {
  const queryClient = useQueryClient();
  const auth = useAuth();
  return () =>
    queryClient.invalidateQueries({
      queryKey: accountsQueryKey(platform, auth.user?.id),
    });
}

export { useMutation, useQueryClient };
