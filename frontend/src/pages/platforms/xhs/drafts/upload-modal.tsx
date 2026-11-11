import { InboxOutlined, LinkOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Divider, Input, Modal, Space, Tabs, Typography, Upload } from "antd";

import type { GeneratedImageAsset, UserImageFile } from "../../../../types";

const { Text } = Typography;

export type UploadModalProps = {
  open: boolean;
  assetUrl: string;
  userImages: UserImageFile[];
  aiAssets: GeneratedImageAsset[];
  selectedAssetUrls: string[];
  isAddingAssets: boolean;
  onCancel: () => void;
  onAssetUrlChange: (value: string) => void;
  onUrlAdd: () => void;
  onToggleAssetUrl: (url: string) => void;
  onAddSelectedAssets: () => void;
  onFileUpload: (file: File) => false;
};

export function UploadModal({
  open,
  assetUrl,
  userImages,
  aiAssets,
  selectedAssetUrls,
  isAddingAssets,
  onCancel,
  onAssetUrlChange,
  onUrlAdd,
  onToggleAssetUrl,
  onAddSelectedAssets,
  onFileUpload,
}: UploadModalProps) {
  return (
    <Modal title="上传素材" open={open} onCancel={onCancel} footer={null} width={480}>
      <Upload.Dragger
        accept=".jpg,.jpeg,.png,.gif,.webp,.mp4,.mov,.avi,.mkv"
        multiple
        showUploadList={false}
        beforeUpload={(file) => onFileUpload(file as File)}
        style={{ marginBottom: 12 }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text" style={{ fontSize: 13 }}>
          点击或拖拽文件上传
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          支持 JPG / PNG / GIF / WEBP / MP4 / MOV
        </p>
      </Upload.Dragger>
      <div style={{ marginTop: 12 }}>
        <Text type="secondary" style={{ fontSize: 12, marginBottom: 4, display: "block" }}>或粘贴链接</Text>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            placeholder="粘贴图片或视频链接"
            prefix={<LinkOutlined />}
            value={assetUrl}
            onChange={(e) => onAssetUrlChange(e.target.value)}
            onPressEnter={onUrlAdd}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={onUrlAdd}
          >
            添加
          </Button>
        </Space.Compact>
      </div>

      <Divider style={{ margin: "12px 0" }}>或从图片资产选择</Divider>

      <Tabs size="small" items={[
        {
          key: "user",
          label: "普通图片资产",
          children: userImages.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无普通图片资产，请先在图片工坊上传</Text>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
              {userImages.map((img) => (
                <div key={img.file_name} onClick={() => onToggleAssetUrl(img.url)}
                  style={{
                    width: 60, height: 60, borderRadius: 4, overflow: "hidden", cursor: "pointer",
                    border: selectedAssetUrls.includes(img.url) ? "2px solid #1668dc" : "2px solid transparent",
                  }}>
                  <img src={img.url} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                </div>
              ))}
            </div>
          ),
        },
        {
          key: "ai",
          label: "AI 图片资产",
          children: aiAssets.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无 AI 图片资产，请先在图片工坊生成</Text>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, maxHeight: 200, overflowY: "auto" }}>
              {aiAssets.filter(a => a.file_path.startsWith("http")).map((asset) => (
                <div key={asset.id} onClick={() => onToggleAssetUrl(asset.file_path)}
                  style={{
                    width: 60, height: 60, borderRadius: 4, overflow: "hidden", cursor: "pointer",
                    border: selectedAssetUrls.includes(asset.file_path) ? "2px solid #1668dc" : "2px solid transparent",
                  }}>
                  <img src={asset.file_path} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                </div>
              ))}
            </div>
          ),
        },
      ]} />

      {selectedAssetUrls.length > 0 && (
        <Button type="primary" block style={{ marginTop: 12 }} onClick={onAddSelectedAssets} loading={isAddingAssets}>
          添加选中的 {selectedAssetUrls.length} 个图片
        </Button>
      )}
    </Modal>
  );
}
