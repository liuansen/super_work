import { DeleteOutlined, EyeOutlined, HighlightOutlined, PlayCircleOutlined, PlusOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { Button, Col, Image, Input, Modal, Row, Space, Typography } from "antd";

import type { DraftAsset } from "../../../../lib/api";

const { Text } = Typography;

export type ImageOptimizeModalProps = {
  open: boolean;
  asset: DraftAsset | null;
  isOptimizing: boolean;
  prompt: string;
  refImages: string[];
  result: string | null;
  onCancel: () => void;
  onPromptChange: (value: string) => void;
  onRemoveRefImage: (index: number) => void;
  onOpenRefPicker: () => void;
  onGenerate: () => void;
  onReplace: () => void;
};

export function ImageOptimizeModal({
  open,
  asset,
  isOptimizing,
  prompt,
  refImages,
  result,
  onCancel,
  onPromptChange,
  onRemoveRefImage,
  onOpenRefPicker,
  onGenerate,
  onReplace,
}: ImageOptimizeModalProps) {
  const isImage = asset?.asset_type === "image";
  return (
    <Modal
      title="素材优化"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={600}
    >
      {!asset ? (
        <Text type="secondary">素材不存在</Text>
      ) : (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}>
              <div style={{ padding: 8, background: "var(--app-fill-weak)", borderRadius: 8, textAlign: "center" }}>
                <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>当前素材</Text>
                {isImage ? (
                  <Image
                    src={asset.url || asset.local_path}
                    width={180}
                    height={180}
                    style={{ objectFit: "contain", borderRadius: 6 }}
                    referrerPolicy="no-referrer"
                    preview={{ mask: <EyeOutlined style={{ fontSize: 16 }} /> }}
                  />
                ) : (
                  <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Space direction="vertical" align="center"><PlayCircleOutlined style={{ fontSize: 32, color: "#1668dc" }} /><Text style={{ fontSize: 12 }}>视频</Text></Space>
                  </div>
                )}
              </div>
            </Col>
            <Col span={12}>
              <div style={{ padding: 8, background: "var(--app-fill-weak)", borderRadius: 8, textAlign: "center" }}>
                <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>优化后预览</Text>
                {result ? (
                  <Image
                    src={result}
                    width={180}
                    height={180}
                    style={{ objectFit: "contain", borderRadius: 6 }}
                    referrerPolicy="no-referrer"
                    preview={{ mask: <EyeOutlined style={{ fontSize: 16 }} /> }}
                  />
                ) : (
                  <div style={{ width: 180, height: 180, margin: "0 auto", border: "1px dashed var(--app-scrollbar)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>{isOptimizing ? "生成中..." : "等待生成"}</Text>
                  </div>
                )}
              </div>
            </Col>
          </Row>

          {isImage ? (
            <div>
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 4 }}>额外参考图（可选）</Text>
                <Space size={8} wrap>
                  {refImages.map((url, idx) => (
                    <div key={idx} style={{ position: "relative", width: 40, height: 40, borderRadius: 4, overflow: "hidden", border: "1px solid #333" }}>
                      <img src={url} style={{ width: "100%", height: "100%", objectFit: "cover" }} referrerPolicy="no-referrer" />
                      <Button type="text" danger size="small" icon={<DeleteOutlined />}
                        onClick={() => onRemoveRefImage(idx)}
                        style={{ position: "absolute", top: -4, right: -4, fontSize: 8, width: 14, height: 14, minWidth: 14, padding: 0, background: "rgba(0,0,0,.6)", borderRadius: "50%" }}
                      />
                    </div>
                  ))}
                  <div
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={onOpenRefPicker}
                    style={{ width: 40, height: 40, borderRadius: 4, border: "1px dashed var(--app-scrollbar)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", background: "var(--app-fill-weak)" }}
                  >
                    <PlusOutlined style={{ fontSize: 14, color: "var(--app-text-tertiary)" }} />
                  </div>
                </Space>
              </div>
              <Input.TextArea
                value={prompt}
                onChange={(e) => onPromptChange(e.target.value)}
                placeholder="描述你想要的润色效果，如：提升画面清晰度和色彩饱和度，增加小红书风格滤镜..."
                rows={3}
                style={{ marginBottom: 12 }}
                disabled={isOptimizing}
              />
              <Space direction="vertical" style={{ width: "100%" }} size={8}>
                <Button
                  block
                  type="primary"
                  icon={<HighlightOutlined />}
                  loading={isOptimizing}
                  onClick={onGenerate}
                >
                  图片润色
                </Button>
                {result && (
                  <Button
                    block
                    onClick={onReplace}
                  >
                    替换当前素材
                  </Button>
                )}
              </Space>
            </div>
          ) : (
            <Button block icon={<VideoCameraOutlined />} disabled>
              视频润色（即将上线）
            </Button>
          )}
        </div>
      )}
    </Modal>
  );
}
