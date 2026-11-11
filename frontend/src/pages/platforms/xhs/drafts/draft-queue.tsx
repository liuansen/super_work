import { DeleteOutlined, FileTextOutlined } from "@ant-design/icons";
import { Badge, Button, Card, Empty, List, Popconfirm, Space, Spin, Typography } from "antd";
import { Link } from "react-router-dom";

import { formatShanghaiTime } from "../../../../lib/time";
import type { Draft } from "../../../../types";

const { Text, Paragraph } = Typography;

export type DraftQueueProps = {
  drafts: Draft[];
  selectedDraftId: number | null;
  isLoading: boolean;
  onSelectDraft: (draft: Draft) => void;
  onDeleteDraft: (draftId: number) => void | Promise<void>;
};

function formatDraftTime(value: string): string {
  return formatShanghaiTime(value);
}

export function DraftQueue({ drafts, selectedDraftId, isLoading, onSelectDraft, onDeleteDraft }: DraftQueueProps) {
  return (
    <Card
      title={
        <Space>
          <Text strong>草稿队列</Text>
          <Badge count={drafts.length} style={{ backgroundColor: "#1668dc" }} />
        </Space>
      }
      styles={{ body: { padding: 0 } }}
    >
      {isLoading ? (
        <div style={{ textAlign: "center", padding: 32 }}>
          <Spin />
          <Paragraph type="secondary" style={{ marginTop: 12 }}>正在加载草稿...</Paragraph>
        </div>
      ) : drafts.length === 0 ? (
        <Empty
          image={<FileTextOutlined style={{ fontSize: 40, color: "var(--app-text-tertiary)" }} />}
          imageStyle={{ height: 56 }}
          description={
            <div>
              <Paragraph type="secondary">还没有可编辑草稿。</Paragraph>
              <Link to="/platforms/xhs/library">
                <Button size="small">去内容库选择笔记</Button>
              </Link>
            </div>
          }
          style={{ padding: 24 }}
        />
      ) : (
        <List
          dataSource={drafts}
          renderItem={(draft) => {
            const isActive = draft.id === selectedDraftId;
            return (
              <List.Item
                onClick={() => onSelectDraft(draft)}
                style={{
                  cursor: "pointer",
                  padding: "10px 16px",
                  background: isActive ? "#1668dc10" : "transparent",
                  borderLeft: isActive ? "2px solid #1668dc" : "2px solid transparent",
                  transition: "all 0.15s",
                  margin: 0,
                }}
              >
                <div style={{ minWidth: 0, width: "100%", display: "flex", alignItems: "center", gap: 4 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text
                      ellipsis
                      style={{
                        display: "block",
                        fontSize: 13,
                        fontWeight: isActive ? 600 : 400,
                      }}
                    >
                      {draft.title || "未命名草稿"}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {formatDraftTime(draft.created_at)}
                    </Text>
                  </div>
                  <Popconfirm title="删除此草稿？" onConfirm={(e) => { e?.stopPropagation(); void onDeleteDraft(draft.id); }} onCancel={(e) => e?.stopPropagation()}>
                    <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()} style={{ flexShrink: 0 }} />
                  </Popconfirm>
                </div>
              </List.Item>
            );
          }}
          style={{ maxHeight: "calc(100vh - 380px)", overflowY: "auto" }}
        />
      )}
    </Card>
  );
}
