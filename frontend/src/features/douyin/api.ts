// 抖音应用 API：全部走统一认证实例 authenticatedHttp（复用 401 刷新）。
import { authenticatedHttp } from "../../lib/api";
import type {
  DouyinAccount,
  DouyinPublishTask,
  DouyinReference,
  MediaUploadResult,
} from "./types";

export async function fetchDouyinAccounts(): Promise<DouyinAccount[]> {
  const response = await authenticatedHttp.get<DouyinAccount[]>("/douyin/accounts");
  return response.data;
}

export async function addDouyinAccount(payload: {
  cookie: string;
  account_id?: number;
}): Promise<DouyinAccount> {
  const response = await authenticatedHttp.post<DouyinAccount>("/douyin/accounts", payload);
  return response.data;
}

export async function checkDouyinAccount(accountId: number): Promise<DouyinAccount> {
  const response = await authenticatedHttp.post<DouyinAccount>(`/douyin/accounts/${accountId}/check`);
  return response.data;
}

export async function deleteDouyinAccount(accountId: number): Promise<void> {
  await authenticatedHttp.delete(`/douyin/accounts/${accountId}`);
}

export async function uploadDouyinMedia(file: File): Promise<MediaUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await authenticatedHttp.post<MediaUploadResult>("/files/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

export async function collectDouyinReference(payload: {
  account_id: number;
  url: string;
}): Promise<{ reference: DouyinReference }> {
  const response = await authenticatedHttp.post<{ reference: DouyinReference }>(
    "/douyin/references/collect", payload,
  );
  return response.data;
}

export async function fetchDouyinReferences(params?: {
  keyword?: string;
  tag?: string;
}): Promise<DouyinReference[]> {
  const response = await authenticatedHttp.get<DouyinReference[]>("/douyin/references", { params });
  return response.data;
}

export async function updateDouyinReference(
  referenceId: number,
  payload: { tags?: string[]; note?: string },
): Promise<DouyinReference> {
  const response = await authenticatedHttp.patch<DouyinReference>(
    `/douyin/references/${referenceId}`, payload,
  );
  return response.data;
}

export async function fetchDouyinWorks(): Promise<DouyinReference[]> {
  const response = await authenticatedHttp.get<DouyinReference[]>("/douyin/works");
  return response.data;
}

export async function refreshDouyinWorkMetrics(
  referenceId: number,
  accountId?: number,
): Promise<unknown> {
  const response = await authenticatedHttp.post(
    `/douyin/works/${referenceId}/refresh`, { account_id: accountId ?? null },
  );
  return response.data;
}

export async function refreshDouyinAccountWorks(accountId: number): Promise<unknown> {
  const response = await authenticatedHttp.post(
    "/douyin/works/refresh-account", { account_id: accountId },
  );
  return response.data;
}

export async function fetchDouyinPublishTasks(): Promise<DouyinPublishTask[]> {
  const response = await authenticatedHttp.get<DouyinPublishTask[]>("/douyin/publish/tasks");
  return response.data;
}

export async function createDouyinPublishTask(payload: {
  account_id: number;
  kind: "video" | "images";
  media_names: string[];
  title: string;
  description: string;
  visibility: number;
  allow_download: boolean;
  scheduled_at?: string | null;
  idempotency_key: string;
}): Promise<{ task: DouyinPublishTask; created: boolean }> {
  const response = await authenticatedHttp.post<{ task: DouyinPublishTask; created: boolean }>(
    "/douyin/publish/tasks", payload,
  );
  return response.data;
}

export async function executeDouyinPublishTask(taskId: number): Promise<DouyinPublishTask> {
  const response = await authenticatedHttp.post<DouyinPublishTask>(
    `/douyin/publish/tasks/${taskId}/execute`,
  );
  return response.data;
}

export async function cancelDouyinPublishTask(taskId: number): Promise<DouyinPublishTask> {
  const response = await authenticatedHttp.post<DouyinPublishTask>(
    `/douyin/publish/tasks/${taskId}/cancel`,
  );
  return response.data;
}
