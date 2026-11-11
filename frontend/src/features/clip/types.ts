export type ClipAssetKind = "note_asset" | "draft_asset" | "upload";
export type ClipAssetType = "image" | "video" | "audio";

export type ClipAsset = {
  id: string;
  kind: ClipAssetKind;
  ref_id: string;
  file_name: string;
  asset_type: ClipAssetType;
  source: "note" | "draft" | "upload";
  title: string;
  size_bytes: number;
  preview_url: string;
};

export type ClipSelection = {
  kind: ClipAssetKind;
  id?: number;
  file_name?: string;
};

export type ClipSessionCreated = {
  session_id: number;
  editor_url: string;
  handoff_token: string;
  handoff_expires_at: string;
};

export type ClipExport = {
  id: number;
  title: string;
  file_name: string;
  mime: string;
  size_bytes: number;
  duration_ms: number | null;
  status: "available" | "linked" | string;
  linked_draft_id: number | null;
  created_at: string;
  download_url: string;
};
