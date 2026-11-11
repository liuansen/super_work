import { AppstoreOutlined, PlusOutlined, ScissorOutlined } from "@ant-design/icons";
import { Button, Card, Input, Layout, Space, Tabs, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../../hooks/use-auth";
import { useLatestRequest } from "../../hooks/use-latest-request";
import { createClipSession, fetchClipExports } from "./api";
import { toSelections } from "./asset-selection";
import { AssetPicker } from "./components/asset-picker";
import { ExportList } from "./components/export-list";
import { buildEditorUrl } from "./session-url";
import type { ClipAsset, ClipExport } from "./types";

const { Content } = Layout;
const { Title, Paragraph, Text } = Typography;

export function ClipPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const from = searchParams.get("from");
  const [exports, setExports] = useState<ClipExport[]>([]);
  const [loading, setLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedAssets, setSelectedAssets] = useState<ClipAsset[]>([]);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const request = useLatestRequest();

  const backPath = from === "douyin"
    ? "/platforms/douyin/accounts"
    : from === "xhs"
      ? "/platforms/xhs/dashboard"
      : "/apps";
  const backLabel = from === "douyin" ? "返回抖音运营" : from === "xhs" ? "返回小红书运营" : "返回应用中心";

  const load = useCallback(async () => {
    const seq = request.begin();
    setLoading(true);
    try {
      const items = await fetchClipExports();
      // 快速切换 tab/刷新时旧响应不得覆盖新数据
      if (!request.isLatest(seq)) return;
      setExports(items);
    } finally {
      if (request.isLatest(seq)) setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    void load().catch(() => {/* 统一错误提示由请求层处理 */});
  }, [load]);

  const selectedSummary = useMemo(
    () => selectedAssets.map((asset) => asset.title || asset.file_name).join("、"),
    [selectedAssets],
  );

  async function startEditing() {
    if (!title.trim()) {
      message.warning("请先填写成片标题");
      return;
    }
    if (selectedAssets.length === 0) {
      message.warning("请至少选择一个素材");
      return;
    }
    setCreating(true);
    try {
      const session = await createClipSession({
        title: title.trim(),
        assets: toSelections(selectedAssets),
      });
      const url = buildEditorUrl(session.editor_url, session.handoff_token, session.session_id);
      // 异步请求后调用 open 可能被浏览器拦截（用户激活窗口已过期）：
      // 返回 null 时保留用户已填内容，提示放行弹窗后重试
      const opened = window.open(url, "_blank", "noopener,noreferrer");
      if (!opened) {
        message.warning("浏览器拦截了剪辑器窗口，请允许弹窗后重试");
        return;
      }
      message.success("已打开剪辑器；导出后成片会回到这里");
      setTitle("");
      setSelectedAssets([]);
    } finally {
      setCreating(false);
    }
  }

  const editorTab = (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card title="新建剪辑">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Input
            placeholder="成片标题，例如：新品开箱 30 秒"
            value={title}
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
          />
          <Space wrap>
            <Button icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
              选择素材
            </Button>
            <Button type="primary" icon={<ScissorOutlined />} loading={creating} onClick={() => void startEditing()}>
              新建剪辑
            </Button>
            <Button onClick={() => navigate(backPath)}>{backLabel}</Button>
          </Space>
          {selectedSummary && <Text type="secondary">已选：{selectedSummary}</Text>}
        </Space>
      </Card>
      <Card title="最近成片" extra={<Button size="small" onClick={() => void load()}>刷新</Button>}>
        <ExportList items={exports.slice(0, 5)} loading={loading} onRefresh={() => void load()} />
      </Card>
    </Space>
  );

  const exportsTab = (
    <Card title="成片库" extra={<Button size="small" onClick={() => void load()}>刷新</Button>}>
      <ExportList items={exports} loading={loading} onRefresh={() => void load()} />
    </Card>
  );

  return (
    <Layout style={{ minHeight: "100vh", background: "var(--app-bg)" }}>
      <Content style={{ width: "100%", maxWidth: 1080, margin: "0 auto", padding: "32px 24px" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <div>
            <Text type="secondary">独立应用</Text>
            <Title level={1} style={{ margin: "8px 0" }}>剪辑工坊</Title>
            <Paragraph type="secondary" style={{ margin: 0 }}>
              从内容库、草稿或本地上传中选择素材，拼接成片后送入小红书或抖音发布。
            </Paragraph>
          </div>
          <Space>
            <Tag>{auth.user?.username ?? "用户"}</Tag>
            <Button icon={<AppstoreOutlined />} onClick={() => navigate("/apps")}>应用中心</Button>
          </Space>
        </Space>
        <Tabs
          style={{ marginTop: 24 }}
          items={[
            { key: "editor", label: "剪辑台", children: editorTab },
            { key: "exports", label: "成片库", children: exportsTab },
          ]}
        />
      </Content>
      <AssetPicker
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        onConfirm={(assets) => {
          setSelectedAssets(assets);
          setPickerOpen(false);
          if (!title.trim() && assets[0]) setTitle((assets[0].title || "新成片").slice(0, 120));
        }}
      />
    </Layout>
  );
}
