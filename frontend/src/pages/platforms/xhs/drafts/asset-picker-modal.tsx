import { Button, Input, Modal, Space, Tabs, Typography } from "antd";

import type { GeneratedImageAsset, UserImageFile } from "../../../../types";

const { Text } = Typography;

export type AssetPickerModalProps = {
  open: boolean;
  userImages: UserImageFile[];
  aiAssets: GeneratedImageAsset[];
  urlInput: string;
  onCancel: () => void;
  onUrlInputChange: (value: string) => void;
  onPickImage: (url: string) => void;
  onAddUrl: () => void;
};

export function AssetPickerModal({
  open,
  userImages,
  aiAssets,
  urlInput,
  onCancel,
  onUrlInputChange,
  onPickImage,
  onAddUrl,
}: AssetPickerModalProps) {
  return (
    <Modal title="选择参考图" open={open} onCancel={onCancel} footer={null} width={560}>
      <Tabs size="small" items={[
        {
          key: "user",
          label: "普通图片资产",
          children: userImages.length === 0 ? <Text type="secondary">暂无</Text> : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
              {userImages.map((img) => (
                <div key={img.file_name} onClick={() => onPickImage(img.url)}
                  style={{ width: 60, height: 60, borderRadius: 4, overflow: "hidden", cursor: "pointer", border: "2px solid transparent" }}>
                  <img src={img.url} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                </div>
              ))}
            </div>
          ),
        },
        {
          key: "ai",
          label: "AI 图片资产",
          children: aiAssets.length === 0 ? <Text type="secondary">暂无</Text> : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
              {aiAssets.filter((a) => a.file_path.startsWith("http")).map((asset) => (
                <div key={asset.id} onClick={() => onPickImage(asset.file_path)}
                  style={{ width: 60, height: 60, borderRadius: 4, overflow: "hidden", cursor: "pointer", border: "2px solid transparent" }}>
                  <img src={asset.file_path} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                </div>
              ))}
            </div>
          ),
        },
        {
          key: "url",
          label: "URL",
          children: (
            <Space.Compact style={{ width: "100%" }}>
              <Input placeholder="粘贴图片 URL" value={urlInput} onChange={(e) => onUrlInputChange(e.target.value)} />
              <Button type="primary" onClick={onAddUrl}>添加</Button>
            </Space.Compact>
          ),
        },
      ]} />
    </Modal>
  );
}
