import { useQuery, useQueryClient } from "@tanstack/react-query";

import { authenticatedHttp } from "../lib/api";
import { useAuth } from "./use-auth";

export type WorkbenchAppAccess = {
  app_key: string;
  name: string;
  description: string;
  enabled: boolean;
  sort_order: number;
  accessible: boolean;
};

export type AdminUserRow = {
  id: number;
  username: string;
  is_admin: boolean;
};

// key 必须含用户 id：全局 QueryClient 是模块级单例，
// 换账号登入若复用前任用户的缓存，守卫会按错误的应用列表放行（P1）
const myAppsKey = (userId: number | null) => ["apps", "me", userId ?? 0] as const;
const catalogKey = (["apps", "admin-catalog"] as const);
const usersKey = (["apps", "admin-users"] as const);
const userAppsKey = (id: number) => ["apps", "admin-user-apps", id] as const;

/** 当前账号可进入的应用（应用中心与路由守卫的唯一数据源）。 */
export function useMyApps() {
  const auth = useAuth();
  const query = useQuery({
    queryKey: myAppsKey(auth.user?.id ?? null),
    queryFn: async () => {
      const response = await authenticatedHttp.get<{ items: WorkbenchAppAccess[] }>("/apps");
      return response.data.items;
    },
    staleTime: 30_000,
    // 应用权限变更（管理员关闭/回收）需要尽快反映到前端守卫
    refetchOnWindowFocus: true,
  });

  const apps = query.data ?? [];
  const keys = new Set(apps.map((item) => item.app_key));
  return {
    apps,
    isLoading: query.isLoading,
    isError: query.isError,
    refresh: query.refetch,
    /** 是否可进入某应用；加载中按“可见”处理，避免路由守卫误踢。 */
    has: (appKey: string) => !query.isError && (query.isLoading || keys.has(appKey)),
  };
}

// ---------------------------------------------------------------------------
// 管理端（require_admin）
// ---------------------------------------------------------------------------

export function useAdminCatalog() {
  const query = useQuery({
    queryKey: catalogKey,
    queryFn: async () => {
      const response = await authenticatedHttp.get<{ items: WorkbenchAppAccess[] }>(
        "/apps/admin/catalog"
      );
      return response.data.items;
    },
  });
  return { catalog: query.data ?? [], isLoading: query.isLoading, refresh: query.refetch };
}

export async function toggleApp(appKey: string, enabled: boolean): Promise<void> {
  await authenticatedHttp.patch(`/apps/admin/catalog/${appKey}`, { enabled });
}

export function useAdminUsers() {
  const query = useQuery({
    queryKey: usersKey,
    queryFn: async () => {
      const response = await authenticatedHttp.get<{ items: AdminUserRow[] }>(
        "/apps/admin/users"
      );
      return response.data.items;
    },
  });
  return { users: query.data ?? [], isLoading: query.isLoading, refresh: query.refetch };
}

export function useUserApps(userId: number | null) {
  const query = useQuery({
    queryKey: userAppsKey(userId ?? 0),
    enabled: userId !== null,
    queryFn: async () => {
      const response = await authenticatedHttp.get<{ app_keys: string[] }>(
        `/apps/admin/users/${userId}/apps`
      );
      return response.data.app_keys;
    },
  });
  return { appKeys: query.data ?? [], isLoading: query.isLoading, refresh: query.refetch };
}

export async function setUserApps(userId: number, appKeys: string[]): Promise<void> {
  await authenticatedHttp.put(`/apps/admin/users/${userId}/apps`, { app_keys: appKeys });
}

export function useInvalidateApps() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["apps"] });
  };
}
