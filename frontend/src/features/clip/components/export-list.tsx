import { DeleteOutlined, DownloadOutlined, SendOutlined } from "@ant-design/icons";
import { Button, Empty, List, Popconfirm, Space, Tag, Typography, message } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { formatShanghaiTime } from "../../../lib/time";
import { createClipDraft, deleteClipExport } from "../api";
import type { ClipExport } from "../types";

const { Text } = Typography;

export function ExportList(props: {
  items: ClipExport[];
  loading: boolean;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [busyId, setBusyId] = useState<number | null>(null);

  async function sendToDraft(item: ClipExport) {
    setBusyId(item.id);
    try {
      const result = await createClipDraft(item.id);
      message.success(result.created ? "已创建小红书草稿" : "该成片已关联草稿");
      navigate("/platforms/xhs/drafts");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(item: ClipExport) {
    setBusyId(item.id);
    try {
      await deleteClipExport(item.id);
      message.success("成片已删除");
      props.onRefresh();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <List
      loading={props.loading}
      dataSource={props.items}
      locale={{ emptyText: <Empty description="还没有成片，完成一次剪辑后会出现在这里" /> }}
      renderItem={(item) => (
        <List.Item
          actions={[
            <a key="download" href={item.download_url} target="_blank" rel="noreferrer">
              <DownloadOutlined /> 下载
            </a>,
            <Button
              key="draft"
              size="small"
              type="primary"
              loading={busyId === item.id}
              onClick={() => void sendToDraft(item)}
            >
              送入小红书草稿
            </Button>,
            <Button
              key="douyin"
              size="small"
              onClick={() => navigate(
                `/platforms/douyin/publish?media=${encodeURIComponent(item.file_name)}&title=${encodeURIComponent(item.title)}`,
              )}
            >
              <SendOutlined /> 用于抖音发布
            </Button>,
            <Popconfirm
              key="delete"
              title="删除这个成片？"
              description="已关联草稿的成片不能删除。"
              onConfirm={() => void remove(item)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} loading={busyId === item.id}>
                删除
              </Button>
            </Popconfirm>,
          ]}
        >
          <List.Item.Meta
            title={<Text strong>{item.title || "未命名成片"}</Text>}
            description={
              <Space size={8} wrap>
                <Tag color={item.linked_draft_id ? "green" : "default"}>
                  {item.linked_draft_id ? "已关联草稿" : "未关联"}
                </Tag>
                <Text type="secondary">{item.file_name}</Text>
                <Text type="secondary">
                  {item.size_bytes >= 1024 * 1024
                    ? `${Math.round(item.size_bytes / 1024 / 1024)} MB`
                    : `${Math.max(1, Math.round(item.size_bytes / 1024))} KB`}
                </Text>
                <Text type="secondary">{formatShanghaiTime(item.created_at)}</Text>
              </Space>
            }
          />
        </List.Item>
      )}
    />
  );
}
