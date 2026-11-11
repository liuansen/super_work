import { Card, Col, Row, Space, Spin, Switch, Table, Tag, Typography, message } from "antd";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "../../hooks/use-auth";
import {
  setUserApps,
  toggleApp,
  useAdminCatalog,
  useAdminUsers,
  useInvalidateApps,
  useUserApps,
  type AdminUserRow,
  type WorkbenchAppAccess,
} from "../../hooks/use-apps";

const { Title, Text, Paragraph } = Typography;

function AppToggleRow(props: { app: WorkbenchAppAccess; onChanged: () => void }) {
  const [saving, setSaving] = useState(false);
  return (
    <Row justify="space-between" align="middle" style={{ padding: "10px 0" }}>
      <Col>
        <Space size={8} align="center">
          <Text strong>{props.app.name}</Text>
          <Tag>{props.app.app_key}</Tag>
        </Space>
        <Paragraph type="secondary" style={{ margin: 0 }}>{props.app.description}</Paragraph>
      </Col>
      <Col>
        <Switch
          checked={props.app.enabled}
          loading={saving}
          checkedChildren="开放"
          unCheckedChildren="关闭"
          onChange={async (checked) => {
            setSaving(true);
            try {
              await toggleApp(props.app.app_key, checked);
              message.success(checked ? "应用已开放" : "应用已关闭");
              props.onChanged();
            } catch {
              message.error("保存失败，请重试");
            } finally {
              setSaving(false);
            }
          }}
        />
      </Col>
    </Row>
  );
}

/**
 * 单个账号的分配编辑行。
 *
 * 本地 Set 是勾选的唯一事实源：连续快速勾选基于最新本地状态计算，
 * 避免「两次 PUT 都基于同一份未刷新的 query 数据」丢失更新（P2）。
 * 服务端数据未就绪时渲染 Spin 禁点——空/旧 appKeys 会经 PUT 全量语义
 * 清空该用户其余授权（P1）。
 */
function UserAssignRow(props: {
  record: AdminUserRow;
  apps: WorkbenchAppAccess[];
  onSaved: () => void;
}) {
  const { appKeys, isLoading, refresh } = useUserApps(props.record.id);
  const [localKeys, setLocalKeys] = useState<Set<string> | null>(null);
  const [saving, setSaving] = useState(false);

  // 服务端数据到达后以它为初始值（换行展开时重置）
  useEffect(() => {
    if (!isLoading) setLocalKeys(new Set(appKeys));
  }, [isLoading, appKeys]);

  const effective = useMemo(() => localKeys ?? new Set(appKeys), [localKeys, appKeys]);
  const enabledApps = props.apps.filter((a) => a.enabled);
  const ready = !isLoading && localKeys !== null;

  async function toggle(appKey: string) {
    const next = new Set(effective);
    if (next.has(appKey)) next.delete(appKey);
    else next.add(appKey);
    setLocalKeys(next); // 乐观更新 + 唯一事实源，连续点击不丢失
    setSaving(true);
    try {
      await setUserApps(props.record.id, Array.from(next));
      message.success("分配已更新");
      await refresh();
      props.onSaved();
    } catch {
      message.error("保存失败，请重试");
      await refresh(); // 失败回弹：以服务端为准
    } finally {
      setSaving(false);
    }
  }

  if (!ready) {
    return <Spin size="small" />;
  }
  return (
    <Space direction="vertical" size={8}>
      <Text type="secondary">
        勾选「{props.record.username}」可以进入的应用（保存后立即生效；仅列出当前开放中的应用）。
      </Text>
      <Space wrap>
        {enabledApps.map((app) => (
          <Tag.CheckableTag
            key={app.app_key}
            checked={effective.has(app.app_key)}
            onChange={() => void toggle(app.app_key)}
          >
            {app.name}
          </Tag.CheckableTag>
        ))}
      </Space>
      {saving && <Text type="secondary">保存中…</Text>}
    </Space>
  );
}

export function AppManagePage() {
  const auth = useAuth();
  const { catalog, isLoading, refresh } = useAdminCatalog();
  const { users } = useAdminUsers();
  const invalidate = useInvalidateApps();
  const [expandedUserId, setExpandedUserId] = useState<number | null>(null);

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "32px 24px" }}>
      <Space direction="vertical" size={4} style={{ marginBottom: 24 }}>
        <Text type="secondary">后台管理</Text>
        <Title level={2} style={{ margin: 0 }}>应用管理</Title>
        <Paragraph type="secondary" style={{ margin: 0 }}>
          开放/关闭应用，或按账号分配可进入的应用。关闭的应用对所有人隐藏并拒绝接口访问。
        </Paragraph>
      </Space>

      <Card title="应用开关" style={{ marginBottom: 24 }}>
        <Row gutter={[24, 8]}>
          {catalog.map((app) => (
            <Col span={24} key={app.app_key}>
              <AppToggleRow app={app} onChanged={() => { void refresh(); invalidate(); }} />
            </Col>
          ))}
        </Row>
      </Card>

      <Card title="账号分配">
        <Table
          rowKey="id"
          loading={isLoading}
          dataSource={users}
          pagination={false}
          expandable={{
            expandedRowRender: (record) => (
              expandedUserId === record.id ? (
                <UserAssignRow
                  record={record}
                  apps={catalog}
                  onSaved={() => void refresh()}
                />
              ) : null
            ),
            onExpand: (expanded, record) => {
              setExpandedUserId(expanded ? record.id : null);
            },
          }}
          columns={[
            { title: "ID", dataIndex: "id", width: 80 },
            { title: "账号", dataIndex: "username" },
            {
              title: "角色",
              dataIndex: "is_admin",
              width: 120,
              render: (isAdmin: boolean) => (isAdmin ? <Tag color="gold">管理员</Tag> : <Tag>成员</Tag>),
            },
          ]}
        />
      </Card>

      <Text type="secondary">当前管理员：{auth.user?.username ?? "-"}</Text>
    </div>
  );
}
