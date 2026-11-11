// 抖音账号页：Cookie 绑定、状态检查、删除。
import { InboxOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  List,
  Modal,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  addDouyinAccount,
  checkDouyinAccount,
  deleteDouyinAccount,
  fetchDouyinAccounts,
} from "../api";
import type { DouyinAccount } from "../types";
import { DouyinPageHeader } from "../douyin-shell";

const { Paragraph, Text } = Typography;

function statusTag(status: string) {
  if (status === "active") return <Tag color="green">已授权</Tag>;
  if (status === "invalid") return <Tag color="red">已失效</Tag>;
  return <Tag>未知</Tag>;
}

export function DouyinAccountsPage() {
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [cookieOpen, setCookieOpen] = useState(false);
  const [cookie, setCookie] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setAccounts(await fetchDouyinAccounts());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load().catch(() => {/* 失败提示已由统一拦截器处理 */});
  }, [load]);

  const submitCookie = async () => {
    if (cookie.trim().length < 10) {
      message.warning("请粘贴完整的抖音 Cookie");
      return;
    }
    setSubmitting(true);
    try {
      const saved = await addDouyinAccount({ cookie: cookie.trim() });
      message.success(
        saved.status === "active"
          ? `账号已绑定：${saved.nickname || saved.provider_account_id}`
          : `凭证确认失败：${saved.status_message || "请检查 Cookie"}`,
      );
      setCookieOpen(false);
      setCookie("");
      await load();
    } catch {
      /* 错误提示已由统一拦截器处理 */
    } finally {
      setSubmitting(false);
    }
  };

  const recheck = async (account: DouyinAccount) => {
    try {
      const updated = await checkDouyinAccount(account.id);
      message.info(updated.status === "active" ? "授权有效" : `状态：${updated.status} ${updated.status_message}`);
      await load();
    } catch {
      /* 错误提示已由统一拦截器处理 */
    }
  };

  const remove = (account: DouyinAccount) => {
    Modal.confirm({
      title: "删除该抖音账号？",
      content: "解除绑定并删除本地加密凭证；参考作品保留。存在未完成的发布任务时需先取消才能删除。",
      okButtonProps: { danger: true },
      onOk: async () => {
        await deleteDouyinAccount(account.id);
        message.success("已删除");
        await load();
      },
    });
  };

  return (
    <div>
      <DouyinPageHeader
        eyebrow="抖音运营"
        title="账号"
        description="绑定用于采集与发布的抖音账号；凭证仅保存在服务端并加密存储。"
        action={<Button type="primary" onClick={() => setCookieOpen(true)}>绑定账号</Button>}
      />

      {accounts.some((a) => a.status === "invalid") && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="有账号凭证已失效"
          description="失效账号无法采集与发布，请删除后重新绑定。"
        />
      )}

      <Card>
        <List
          loading={loading}
          locale={{ emptyText: <Empty description="还没有绑定抖音账号" /> }}
          dataSource={accounts}
          renderItem={(account) => (
            <List.Item
              actions={[
                <Button key="check" size="small" onClick={() => void recheck(account)}>
                  检查授权
                </Button>,
                <Button key="delete" size="small" danger onClick={() => remove(account)}>
                  删除
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8}>
                    <Text strong>{account.nickname || "未命名账号"}</Text>
                    {statusTag(account.status)}
                  </Space>
                }
                description={
                  <>
                    <Paragraph type="secondary" style={{ marginBottom: 4 }}>
                      平台 ID：{account.provider_account_id ?? "未确认（凭证未通过校验）"}
                    </Paragraph>
                    {account.status_message && (
                      <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                        {account.status_message}
                      </Paragraph>
                    )}
                  </>
                }
              />
            </List.Item>
          )}
        />
      </Card>

      <Modal
        title="绑定抖音账号"
        open={cookieOpen}
        onCancel={() => setCookieOpen(false)}
        onOk={() => void submitCookie()}
        confirmLoading={submitting}
        okText="确认绑定"
        width={560}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="请从已登录的浏览器复制完整 Cookie"
          description="绑定时会立即校验身份；发布与采集能力依赖该 Cookie 的有效性。"
        />
        <Input.TextArea
          rows={6}
          value={cookie}
          onChange={(event) => setCookie(event.target.value)}
          placeholder="粘贴抖音网页版完整 Cookie…"
        />
      </Modal>
    </div>
  );
}
