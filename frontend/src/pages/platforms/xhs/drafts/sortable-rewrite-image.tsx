import { DeleteOutlined, EditOutlined, EyeOutlined } from "@ant-design/icons";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button, Popconfirm } from "antd";
import type { CSSProperties } from "react";

import type { DraftAsset } from "../../../../lib/api";

export type SortableRewriteImageProps = {
  asset: DraftAsset;
  onEdit: () => void;
  onRemove: () => void;
  onView: () => void;
};

export function SortableRewriteImage({ asset, onEdit, onRemove, onView }: SortableRewriteImageProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: asset.id });
  const style: CSSProperties = {
    position: "relative",
    display: "inline-block",
    padding: 2,
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    cursor: "grab",
  };
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <img
        src={asset.url || asset.local_path}
        width={60}
        height={60}
        style={{ objectFit: "cover", borderRadius: 4, display: "block", pointerEvents: "none" }}
        referrerPolicy="no-referrer"
      />
      <Button
        type="text" size="small" icon={<EditOutlined />}
        onClick={(e) => { e.stopPropagation(); onEdit(); }}
        onPointerDown={(e) => e.stopPropagation()}
        style={{
          position: "absolute", top: -6, left: -6, fontSize: 10,
          width: 18, height: 18, minWidth: 18, padding: 0,
          background: "rgba(0,0,0,.6)", borderRadius: "50%", color: "#1668dc",
        }}
      />
      <Popconfirm title="移除此图片？" onConfirm={onRemove}>
        <Button
          type="text" danger size="small" icon={<DeleteOutlined />}
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          style={{
            position: "absolute", top: -6, right: -6, fontSize: 10,
            width: 18, height: 18, minWidth: 18, padding: 0,
            background: "rgba(0,0,0,.6)", borderRadius: "50%",
          }}
        />
      </Popconfirm>
      <Button
        type="text" size="small" icon={<EyeOutlined />}
        onClick={(e) => { e.stopPropagation(); onView(); }}
        onPointerDown={(e) => e.stopPropagation()}
        style={{
          position: "absolute", bottom: -6, left: -6, fontSize: 10,
          width: 18, height: 18, minWidth: 18, padding: 0,
          background: "rgba(0,0,0,.6)", borderRadius: "50%", color: "#fff",
        }}
      />
    </div>
  );
}
