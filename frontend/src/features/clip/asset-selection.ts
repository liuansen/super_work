import type { ClipAsset, ClipSelection } from "./types";

/** 列表项的稳定 key（kind + ref_id 在三类来源内唯一）。 */
export function assetKey(asset: ClipAsset): string {
  return `${asset.kind}:${asset.ref_id}`;
}

/** 前端选中项 → 后端会话创建请求体。 */
export function toSelections(assets: ClipAsset[]): ClipSelection[] {
  return assets.map((asset) =>
    asset.kind === "upload"
      ? { kind: "upload", file_name: asset.ref_id }
      : { kind: asset.kind, id: Number(asset.ref_id) },
  );
}
