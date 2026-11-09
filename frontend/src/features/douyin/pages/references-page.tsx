// 参考库：链接采集、列表、标签与备注。
import { SearchOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Empty,
  Input,
  List,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  collectDouyinReference,
  fetchDouyinAccounts,
  fetchDouyinReferences,
  updateDouyinReference,
} from "../api";
import type { DouyinAccount, DouyinReference } from "../types";
import { DouyinPageHeader } from "../douyin-shell";

const { Paragraph, Text } = Typography;

function formatDuration(ms: number | null): string {
  if (!ms) return "-";
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
}

export function DouyinReferencesPage() {
  const [rows, setRows] = useState<DouyinReference[]>([]);
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [url, setUrl] = useState("");
  const [accountId, setAccountId] = useState<number | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [keyword, setKeyword] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchDouyinReferences());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void fetchDouyinAccounts().then((list) => {
      setAccounts(list);
      const active = list.find((a) => a.status === "active");
      if (active) setAccountId(active.id);
    });
  }, [load]);

  const collect = async () => {
    if (!accountId) {
      message.warning("请先在“账号”页绑定并授权账号");
      return;
    }
    if (!url.trim()) {
      message.warning("请输入作品链接");
      return;
    }
    setCollecting(true);
    try {
      const { reference } = await collectDouyinReference({ account_id: accountId, url: url.trim() });
      message.success(`已采集：${reference.title || reference.provider_work_id}`);
      setUrl("");
      await load();
    } catch {
      /* 错误提示已由统一拦截器处理 */
    } finally {
      setCollecting(false);
    }
  };

  const editMeta = (row: DouyinReference) => {
    let tags = [...row.tags];
    let note = row.note;
    Modal.confirm({
      title: "编辑标签与备注",
      width: 520,
      content: (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}>
          <Select
            mode="tags"
            placeholder="输入标签后回车"
            defaultValue={row.tags}
            onChange={(value) => {
              tags = value;
            }}
          />
          <Input.TextArea
            rows={3}
            defaultValue={row.note}
            placeholder="创作备注…"
            onChange={(event) => {
              note = event.target.value;
            }}
          />
        </div>
      ),
      onOk: async () => {
        await updateDouyinReference(row.id, { tags, note });
        message.success("已保存");
        await load();
      },
    });
  };

  const filtered = keyword
    ? rows.filter((r) => (r.title || "").toLowerCase().includes(keyword.toLowerCase()))
    : rows;

  return (
    <div>
      <DouyinPageHeader
        eyebrow="抖音运营"
        title="参考库"
        description="采集对标作品到本工作台；重复采集自动去重并保留你的标签与备注。"
      />

      <Card style={{ marginBottom: 16 }}>
        <Space.Compact style={{ width: "100%" }} size="large">
          <Select
            style={{ width: 220 }}
            placeholder="使用账号"
            value={accountId}
            onChange={setAccountId}
            options={accounts
              .filter((a) => a.status === "active")
              .map((a) => ({ value: a.id, label: a.nickname || a.provider_account_id || `账号${a.id}` }))}
          />
          <Input
            placeholder="粘贴抖音作品链接 https://www.douyin.com/video/…"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onPressEnter={() => void collect()}
          />
          <Button type="primary" loading={collecting} onClick={() => void collect()}>
            采集
          </Button>
        </Space.Compact>
      </Card>

      <Card
        title={`作品 ${filtered.length}`}
        extra={
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="按标题过滤"
            style={{ width: 200 }}
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        }
      >
        <List
          loading={loading}
          locale={{ emptyText: <Empty description="暂无采集记录" /> }}
          dataSource={filtered}
          renderItem={(row) => (
            <List.Item
              actions={[
                <Button key="meta" size="small" onClick={() => editMeta(row)}>
                  标签/备注
                </Button>,
                <Button key="open" size="small" type="link" href={row.work_url} target="_blank">
                  查看原作品
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8} wrap>
                    <Text strong>{row.title || row.provider_work_id}</Text>
                    {row.tags.map((tag) => (
                      <Tag key={tag}>{tag}</Tag>
                    ))}
                  </Space>
                }
                description={
                  <>
                    <Paragraph type="secondary" style={{ marginBottom: 4 }}>
                      作者：{row.author_nickname || "-"} · 时长：{formatDuration(row.duration_ms)} ·
                      点赞 {row.stats.digg_count ?? "-"} · 评论 {row.stats.comment_count ?? "-"} ·
                      分享 {row.stats.share_count ?? "-"} · 收藏 {row.stats.collect_count ?? "-"}
                    </Paragraph>
                    {row.note && (
                      <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                        备注：{row.note}
                      </Paragraph>
                    )}
                  </>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
}
