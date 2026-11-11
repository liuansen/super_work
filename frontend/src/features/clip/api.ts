import { authenticatedHttp } from "../../lib/api";
import type {
  ClipAsset,
  ClipExport,
  ClipSelection,
  ClipSessionCreated,
} from "./types";

export async function fetchClipAssets(params: {
  q?: string;
  type?: string;
  source?: string;
} = {}): Promise<ClipAsset[]> {
  const response = await authenticatedHttp.get<{ items: ClipAsset[] }>("/clip/assets", { params });
  return response.data.items;
}

export async function createClipSession(payload: {
  title: string;
  assets: ClipSelection[];
}): Promise<ClipSessionCreated> {
  const response = await authenticatedHttp.post<ClipSessionCreated>("/clip/sessions", payload);
  return response.data;
}

export async function fetchClipExports(limit = 50): Promise<ClipExport[]> {
  const response = await authenticatedHttp.get<{ items: ClipExport[] }>("/clip/exports", {
    params: { limit },
  });
  return response.data.items;
}

export async function createClipDraft(exportId: number): Promise<{ draft_id: number; created: boolean }> {
  const response = await authenticatedHttp.post<{ draft_id: number; created: boolean }>(
    `/clip/exports/${exportId}/draft`,
  );
  return response.data;
}

export async function deleteClipExport(exportId: number): Promise<void> {
  await authenticatedHttp.delete(`/clip/exports/${exportId}`);
}
