// 发布中心：创建发布意图 → 明确执行。创建不等于发送；每次发送都是显式操作。
import { InboxOutlined, SendOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  cancelDouyinPublishTask,
  createDouyinPublishTask,
  executeDouyinPublishTask,
  fetchDouyinAccounts,
  fetchDouyinPublishTasks,
  uploadDouyinMedia,
} from "../api";
import type { DouyinAccount, DouyinPublishTask, MediaUploadResult } from "../types";
import { readDouyinPreselect } from "../preselect";
import { DouyinPageHeader } from "../douyin-shell";

const { Paragraph, Text } = Typography;

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "blue", label: "待执行" },
  running: { color: "processing", label: "执行中" },
  succeeded: { color: "green", label: "已发布" },
  failed: { color: "red", label: "失败" },
  unknown: { color: "orange", label: "结果不明" },
  cancelled: { color: "default", label: "已取消" },
};

function statusTag(status: string) {
  const meta = STATUS_META[status] ?? { color: "default", label: status };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function newIdempotencyKey(): string {
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function DouyinPublishingPage() {
  const [tasks, setTasks] = useState<DouyinPublishTask[]>([]);
  const [accounts, setAccounts] = useState<DouyinAccount[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [kind, setKind] = useState<"video" | "images">("video");
  const [uploads, setUploads] = useState<MediaUploadResult[]>([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTasks(await fetchDouyinPublishTasks());
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
        if (active) form.setFieldValue("account_id", active.id);
      })
      .catch(() => {/* 失败提示已由统一拦截器处理 */});
  }, [load, form]);

  // 剪辑工坊「用于抖音发布」跳转预选：填入成片与标题并打开弹窗，
  // 随后清掉 URL 参数避免刷新重复触发
  useEffect(() => {
    const preselect = readDouyinPreselect(searchParams);
    if (!preselect.media) return;
    setKind("video");
    setUploads([
      {
        file_name: preselect.media,
        download_url: `/api/files/media/${preselect.media}`,
        asset_type: "video",
        size: 0,
      },
    ]);
    if (preselect.title) form.setFieldValue("title", preselect.title.slice(0, 20));
    setOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("media");
    next.delete("title");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, form]);

  const activeAccounts = accounts.filter((a) => a.status === "active");

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const result = await uploadDouyinMedia(file);
      setUploads((prev) => [...prev, result]);
      message.success(`已上传：${file.name}`);
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    const values = await form.validateFields();
    if (uploads.length === 0) {
      message.warning("请先上传媒体文件");
      return;
    }
    setSubmitting(true);
    try {
      // 设计规范：用户输入按北京时间解释。直接取选择器所见墙钟组装 +08:00，
      // 不经过浏览器本地时区换算（任何时区的用户所见即所提交）。
      const scheduledAt = values.scheduled_at
        ? `${values.scheduled_at.format("YYYY-MM-DDTHH:mm:ss")}+08:00`
        : null;
      const { created } = await createDouyinPublishTask({
        account_id: values.account_id,
        kind,
        media_names: uploads.map((u) => u.file_name),
        title: values.title || "",
        description: values.description || "",
        visibility: values.visibility,
        allow_download: values.allow_download,
        scheduled_at: scheduledAt,
        idempotency_key: newIdempotencyKey(),
      });
      message.success(
        created
          ? "发布意图已创建；确认无误后点击“执行发布”才会发送到平台"
          : "相同任务已存在（幂等返回），未重复创建",
      );
      setOpen(false);
      setUploads([]);
      form.resetFields();
      await load();
    } catch {
      /* 错误提示已由统一拦截器处理 */
    } finally {
      setSubmitting(false);
    }
  };

  const execute = (task: DouyinPublishTask) => {
    Modal.confirm({
      title: "确认发布到抖音？",
      width: 520,
      content: (
        <div>
          <Paragraph>
            将以账号「{accounts.find((a) => a.id === task.account_id)?.nickname ?? task.account_id}」
            发布{task.kind === "video" ? "视频" : "图集"}：
          </Paragraph>
          <Paragraph strong>{task.title || "(无标题)"}</Paragraph>
          {task.scheduled_at && (
            <Paragraph type="warning" style={{ marginBottom: 0 }}>
              定时发布：{task.scheduled_at}（北京时间，由平台侧定时）
            </Paragraph>
          )}
        </div>
      ),
      okText: "确认发布",
      onOk: async () => {
        const updated = await executeDouyinPublishTask(task.id);
        if (updated.status === "succeeded") message.success("发布成功");
        else if (updated.status === "unknown") message.warning("结果不明：网络中断，请勿盲目重发，稍后在平台核对");
        else message.error(updated.error_message || "发布失败");
        await load();
      },
    });
  };

  const cancel = (task: DouyinPublishTask) => {
    Modal.confirm({
      title: "取消该发布任务？",
      content: "只有未发送的任务可以取消。",
      okButtonProps: { danger: true },
      onOk: async () => {
        await cancelDouyinPublishTask(task.id);
        message.success("已取消");
        await load();
      },
    });
  };

  return (
    <div>
      <DouyinPageHeader
        eyebrow="抖音运营"
        title="发布中心"
        description="审核后发布：创建发布意图，核对信息后显式执行；失败与“结果不明”都会如实标注。"
        action={
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={() => setOpen(true)}
            disabled={activeAccounts.length === 0}
          >
            新建发布
          </Button>
        }
      />

      {activeAccounts.length === 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="还没有可用账号"
          description="请先在“账号”页绑定授权有效的抖音账号。"
        />
      )}

      <Card>
        <List
          loading={loading}
          locale={{ emptyText: <Empty description="暂无发布任务" /> }}
          dataSource={tasks}
          renderItem={(task) => (
            <List.Item
              actions={[
                task.status === "pending" && (
                  <Button key="exec" size="small" type="primary" onClick={() => execute(task)}>
                    执行发布
                  </Button>
                ),
                task.status === "pending" && (
                  <Button key="cancel" size="small" danger onClick={() => cancel(task)}>
                    取消
                  </Button>
                ),
              ].filter(Boolean)}
            >
              <List.Item.Meta
                title={
                  <Space size={8} wrap>
                    {statusTag(task.status)}
                    <Text strong>{task.title || "(无标题)"}</Text>
                    <Tag>{task.kind === "video" ? "视频" : "图集"}</Tag>
                    {task.scheduled_at && <Tag color="purple">定时 {task.scheduled_at}</Tag>}
                  </Space>
                }
                description={
                  <>
                    <Paragraph type="secondary" style={{ marginBottom: 4 }}>
                      账号 {accounts.find((a) => a.id === task.account_id)?.nickname || task.account_id} · 可见性{" "}
                      {task.visibility === 0 ? "公开" : task.visibility === 1 ? "仅自己" : "好友"} ·
                      {task.allow_download ? " 允许下载" : " 不允许下载"}
                    </Paragraph>
                    {task.provider_work_id && (
                      <Paragraph type="secondary" style={{ marginBottom: 4 }}>
                        平台作品 ID：{task.provider_work_id}
                      </Paragraph>
                    )}
                    {task.error_message && (
                      <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
                        {task.error_message}
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
        title="新建发布"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        confirmLoading={submitting}
        okText="创建发布意图"
        width={640}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="创建只是保存发布意图"
          description="只有在此列表点击“执行发布”后，才会真正发送到抖音平台。"
        />
        <Form form={form} layout="vertical" initialValues={{ visibility: 1, allow_download: true }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="account_id" label="发布账号" rules={[{ required: true, message: "选择账号" }]}>
                <Select
                  options={activeAccounts.map((a) => ({
                    value: a.id,
                    label: a.nickname || a.provider_account_id || `账号${a.id}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="作品类型">
                <Radio.Group
                  value={kind}
                  onChange={(event) => {
                    setKind(event.target.value);
                    setUploads([]);
                  }}
                >
                  <Radio.Button value="video">视频</Radio.Button>
                  <Radio.Button value="images">图集</Radio.Button>
                </Radio.Group>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="媒体文件（先上传）" required>
            <Upload.Dragger
              multiple={kind === "images"}
              accept={kind === "video" ? ".mp4,.mov,.avi,.mkv" : ".jpg,.jpeg,.png,.webp"}
              showUploadList={false}
              customRequest={({ file }) => void handleUpload(file as File)}
              disabled={uploading}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">
                {uploading ? "上传中…" : kind === "video" ? "点击或拖拽视频文件（≤100MB）" : "点击或拖拽图片，可多选"}
              </p>
            </Upload.Dragger>
            {uploads.length > 0 && (
              <div style={{ marginTop: 8 }}>
                {uploads.map((u) => (
                  <Tag
                    key={u.file_name}
                    closable
                    onClose={() => setUploads((prev) => prev.filter((x) => x.file_name !== u.file_name))}
                  >
                    {u.file_name.slice(0, 24)}…
                  </Tag>
                ))}
              </div>
            )}
          </Form.Item>
          <Form.Item name="title" label="标题（≤20字）" rules={[{ max: 20, message: "最多20字" }]}>
            <Input placeholder="作品标题" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="作品描述，可含 #话题" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="visibility" label="谁可以看">
                <Select
                  options={[
                    { value: 0, label: "公开" },
                    { value: 1, label: "仅自己" },
                    { value: 2, label: "好友可见" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="allow_download" label="允许下载" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="scheduled_at" label="定时发布（可选）">
                <DatePicker showTime style={{ width: "100%" }} placeholder="留空为立即" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
