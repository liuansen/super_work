import { FileImageOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { Empty, Input, List, Modal, Segmented, Space, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { fetchClipAssets } from "../api";
import { assetKey } from "../asset-selection";
import type { ClipAsset } from "../types";

const { Text } = Typography;

type SourceFilter = "all" | "note" | "draft" | "upload";

const SOURCE_LABELS: Record<SourceFilter, string> = {
  all: "全部",
  note: "内容库",
  draft: "草稿",
  upload: "本地上传",
};

export function AssetPicker(props: {
  open: boolean;
  onCancel: () => void;
  onConfirm: (assets: ClipAsset[]) => void;
}) {
  const [source, setSource] = useState<SourceFilter>("all");
  const [keyword, setKeyword] = useState("");
  const [items, setItems] = useState<ClipAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Record<string, ClipAsset>>({});

  useEffect(() => {
    if (!props.open) return;
    let cancelled = false;
    setLoading(true);
    fetchClipAssets({ q: keyword, source: source === "all" ? undefined : source })
      .then((list) => { if (!cancelled) setItems(list); })
      .catch(() => { /* 失败提示由统一拦截器处理 */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [props.open, keyword, source]);

  useEffect(() => {
    if (!props.open) {
      setSelected({});
      setKeyword("");
      setSource("all");
    }
  }, [props.open]);

  const selectedAssets = useMemo(() => Object.values(selected), [selected]);

  return (
    <Modal
      open={props.open}
      title="选择素材"
      width={720}
      okText={`加入剪辑（${selectedAssets.length}）`}
      okButtonProps={{ disabled: selectedAssets.length === 0 }}
      onCancel={props.onCancel}
      onOk={() => props.onConfirm(selectedAssets)}
      destroyOnClose
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Segmented
          value={source}
          onChange={(value) => setSource(value as SourceFilter)}
          options={(Object.keys(SOURCE_LABELS) as SourceFilter[]).map((value) => ({
            value,
            label: SOURCE_LABELS[value],
          }))}
        />
        <Input.Search placeholder="按标题或文件名搜索" allowClear onSearch={setKeyword} />
        <List
          loading={loading}
          rowKey={assetKey}
          style={{ maxHeight: 420, overflowY: "auto" }}
          dataSource={items}
          locale={{ emptyText: <Empty description="没有可用素材，请先到内容库下载或上传文件" /> }}
          renderItem={(asset) => {
            const key = assetKey(asset);
            const checked = Boolean(selected[key]);
            return (
              <List.Item
                actions={[
                  <a key="toggle" onClick={() => setSelected((prev) => {
                    const next = { ...prev };
                    if (next[key]) delete next[key]; else next[key] = asset;
                    return next;
                  })}>
                    {checked ? "已选择" : "选择"}
                  </a>,
                ]}
              >
                <List.Item.Meta
                  avatar={asset.asset_type === "image"
                    ? <FileImageOutlined style={{ fontSize: 24 }} />
                    : <VideoCameraOutlined style={{ fontSize: 24 }} />}
                  title={<Text strong>{asset.title}</Text>}
                  description={
                    <Space size={8} wrap>
                      <Tag color={checked ? "blue" : undefined}>{SOURCE_LABELS[asset.source]}</Tag>
                      <Tag>{asset.asset_type}</Tag>
                      <Text type="secondary">{asset.file_name}</Text>
                    </Space>
                  }
                />
              </List.Item>
            );
          }}
        />
      </Space>
    </Modal>
  );
}
