// 作品数据：真实互动指标与复盘刷新。无数据展示空状态，不用模拟数。
import {
  BarChartOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Empty,
  List,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  fetchDouyinAccounts,
  fetchDouyinWorks,
  refreshDouyinAccountWorks,
  refreshDouyinWorkMetrics,
} from "../api";
import type { DouyinAccount, DouyinReference } from "../types";
import { DouyinPageHeader } from "../douyin-shell";

const { Text } = Typography;

function fmt(value: number | null | undefined): string {
  // 真实 0 显示 0；平台未返回显示 "-"，绝不伪造 0。
  return value === null || value === undefined ? "-" : String(value);
}

function collectedText(snapshot: DouyinReference["latest_metrics"]): string {
  if (!snapshot?.collected_at) return "未采集";
  return new Date(snapshot.collected_at).toLocaleString("zh-CN");
}

export function DouyinWorksPage() {
  const [rows, setRows] = useState<DouyinReference[]>([]);
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchDouyinWorks());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load().catch(() => {/* 失败提示已由统一拦截器处理 */});
    void fetchDouyinAccounts()
      .then((list) => {
        setAccounts(list);
        const active = list.find((a) => a.status === "active");
        if (active) setAccountId(active.id);
      })
      .catch(() => {/* 失败提示已由统一拦截器处理 */});
  }, [load]);

  const refreshOne = async (row: DouyinReference) => {
    try {
      await refreshDouyinWorkMetrics(row.id, accountId ?? undefined);
      message.success(`已刷新：${row.title || row.provider_work_id}`);
      await load();
    } catch {
      /* 错误提示已由统一拦截器处理 */
    }
  };

  const refreshAccount = async () => {
    if (!accountId) {
      message.warning("请选择要刷新的账号");
      return;
    }
    setRefreshingAll(true);
    try {
      await refreshDouyinAccountWorks(accountId);
      message.success("账号作品数据已刷新");
      await load();
    } catch {
      /* 错误提示已由统一拦截器处理 */
    } finally {
      setRefreshingAll(false);
    }
  };

  return (
    <div>
      <DouyinPageHeader
        eyebrow="抖音运营"
        title="作品数据"
        description="仅展示从平台真实回收的互动指标；未采集/平台未返回的字段显示为“-”。"
        action={
          <Space>
            <Select
              style={{ width: 200 }}
              placeholder="选择账号"
              value={accountId}
              onChange={setAccountId}
              options={accounts
                .filter((a) => a.status === "active")
                .map((a) => ({ value: a.id, label: a.nickname || a.provider_account_id || `账号${a.id}` }))}
            />
            <Button icon={<ReloadOutlined />} loading={refreshingAll} onClick={() => void refreshAccount()}>
              刷新账号作品
            </Button>
          </Space>
        }
      />

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          locale={{ emptyText: <Empty description="暂无作品数据；可先采集作品或在账号作品刷新后查看" /> }}
          dataSource={rows}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          columns={[
            {
              title: "作品",
              dataIndex: "title",
              render: (_, row) => (
                <Space size={8}>
                  {row.cover_url && (
                    <img
                      src={row.cover_url}
                      alt=""
                      style={{ width: 40, height: 40, borderRadius: 6, objectFit: "cover" }}
                    />
                  )}
                  <div>
                    <Text strong>{row.title || row.provider_work_id}</Text>
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {row.author_nickname || "-"}
                      </Text>
                    </div>
                  </div>
                </Space>
              ),
            },
            { title: "点赞", dataIndex: ["latest_metrics", "digg_count"], width: 90, align: "center", render: (v) => fmt(v) },
            { title: "评论", dataIndex: ["latest_metrics", "comment_count"], width: 90, align: "center", render: (v) => fmt(v) },
            { title: "分享", dataIndex: ["latest_metrics", "share_count"], width: 90, align: "center", render: (v) => fmt(v) },
            { title: "收藏", dataIndex: ["latest_metrics", "collect_count"], width: 90, align: "center", render: (v) => fmt(v) },
            {
              title: "采集时间",
              dataIndex: "latest_metrics",
              width: 180,
              render: (snapshot) => collectedText(snapshot),
            },
            {
              title: <span><BarChartOutlined /> 操作</span>,
              width: 110,
              render: (_, row) => (
                <Button size="small" icon={<ReloadOutlined />} onClick={() => void refreshOne(row)}>
                  刷新
                </Button>
              ),
            },
          ]}
        />
        {rows.some((r) => r.latest_metrics?.availability && r.latest_metrics.availability !== "available") && (
          <div style={{ marginTop: 12 }}>
            <Tag>部分指标平台未返回，显示为“-”</Tag>
          </div>
        )}
      </Card>
    </div>
  );
}
