import { EditOutlined, FileImageOutlined, PictureOutlined, PlayCircleOutlined, PlusOutlined } from "@ant-design/icons";
import { closestCenter, DndContext, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { horizontalListSortingStrategy, SortableContext } from "@dnd-kit/sortable";
import { Button, Card, Space, Tag, Typography } from "antd";

import type { DraftAsset } from "../../../../lib/api";
import { SortableRewriteImage } from "./sortable-rewrite-image";

const { Text } = Typography;

export type AssetSortableGridProps = {
  imageAssets: DraftAsset[];
  videoAssets: DraftAsset[];
  hasVideoAssets: boolean;
  hasImageAssets: boolean;
  videoFallbackUrl?: string | null;
  onDragEnd: (event: DragEndEvent) => void;
  onEditAsset: (assetId: number) => void;
  onRemoveAsset: (assetId: number) => void;
  onViewAsset: (url: string) => void;
  onOpenUpload: () => void;
};

export function AssetSortableGrid({
  imageAssets,
  videoAssets,
  hasVideoAssets,
  hasImageAssets,
  videoFallbackUrl,
  onDragEnd,
  onEditAsset,
  onRemoveAsset,
  onViewAsset,
  onOpenUpload,
}: AssetSortableGridProps) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  return (
    <Card
      title="素材"
      size="small"
      style={{ marginBottom: 16 }}
      extra={
        <Button
          type="dashed"
          size="small"
          icon={<PlusOutlined />}
          onClick={onOpenUpload}
        >
          添加素材
        </Button>
      }
    >
      <div style={{ marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <FileImageOutlined /> 图片素材 ({imageAssets.length}) — 拖拽调整顺序
          </Text>
        </div>
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={imageAssets.map((a) => a.id)} strategy={horizontalListSortingStrategy}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              {imageAssets.map((asset) => (
                <SortableRewriteImage
                  key={asset.id}
                  asset={asset}
                  onEdit={() => onEditAsset(asset.id)}
                  onRemove={() => onRemoveAsset(asset.id)}
                  onView={() => onViewAsset(asset.url || asset.local_path)}
                />
              ))}
              {/* 上传入口始终显示，不依赖已有素材 */}
              <div
                onClick={onOpenUpload}
                style={{
                  width: 60, height: 60, borderRadius: 4, border: "1px dashed var(--app-scrollbar)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: "pointer", background: "var(--app-fill-weak)",
                }}
              >
                <PlusOutlined style={{ fontSize: 20, color: "var(--app-text-tertiary)" }} />
              </div>
            </div>
          </SortableContext>
        </DndContext>
      </div>

      {hasVideoAssets && (
        <div style={{ marginBottom: 8 }}>
          {videoAssets.map((asset) => (
            <div key={asset.id} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <Button
                type="link" size="small" icon={<PlayCircleOutlined />}
                href={asset.url || videoFallbackUrl || "#"} target="_blank" rel="noopener noreferrer"
              >
                查看视频
              </Button>
              <Button type="text" size="small" icon={<EditOutlined />}
                onClick={() => onEditAsset(asset.id)}
                style={{ color: "#1668dc" }}
              />
            </div>
          ))}
        </div>
      )}

      <Space size={4}>
        <Tag color={hasVideoAssets ? "purple" : "blue"}>
          {hasVideoAssets ? "视频" : "图文"}
        </Tag>
        {hasImageAssets && (
          <>
            <PictureOutlined style={{ color: "var(--app-text-tertiary)", fontSize: 12 }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {imageAssets.length} 张图片
            </Text>
          </>
        )}
      </Space>
    </Card>
  );
}
