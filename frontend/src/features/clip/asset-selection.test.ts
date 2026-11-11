import { describe, expect, it } from "vitest";

import { assetKey, toSelections } from "./asset-selection";
import type { ClipAsset } from "./types";

const noteAsset: ClipAsset = {
  id: "note_asset:7", kind: "note_asset", ref_id: "7", file_name: "xhs-asset-u1-a.mp4",
  asset_type: "video", source: "note", title: "参考笔记", size_bytes: 10,
  preview_url: "/api/files/media/xhs-asset-u1-a.mp4",
};
const uploadAsset: ClipAsset = {
  ...noteAsset, id: "upload:xhs-upload-u1-b.mp4", kind: "upload",
  ref_id: "xhs-upload-u1-b.mp4", file_name: "xhs-upload-u1-b.mp4", source: "upload",
};

describe("asset selection", () => {
  it("为每项生成稳定 key", () => {
    expect(assetKey(noteAsset)).toBe("note_asset:7");
    expect(assetKey(uploadAsset)).toBe("upload:xhs-upload-u1-b.mp4");
  });

  it("转换为后端选择结构", () => {
    expect(toSelections([noteAsset, uploadAsset])).toEqual([
      { kind: "note_asset", id: 7 },
      { kind: "upload", file_name: "xhs-upload-u1-b.mp4" },
    ]);
  });
});
