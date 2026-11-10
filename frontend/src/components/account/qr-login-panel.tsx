import { Alert, Button, Card, Checkbox, Space, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import axios from "axios";
import { useEffect, useRef, useState } from "react";

import { createXhsCreatorQrLoginSession, createXhsPcQrLoginSession, pollXhsLoginSession } from "../../lib/api";
import type { PlatformAccount, XhsQrLoginSession } from "../../types";

const { Text, Link: AntLink } = Typography;
const blockedMessage = "小红书拒绝了本次登录请求，已停止自动重试。请先在小红书官方网页或 App 确认可正常登录，并完成平台提示的验证，再重新绑定。";

type QrLoginPanelProps = {
  accountType: "pc" | "creator";
  onConfirmed: (account: PlatformAccount) => void;
};

export function QrLoginPanel({ accountType, onConfirmed }: QrLoginPanelProps) {
  const [session, setSession] = useState<XhsQrLoginSession | null>(null);
  const [statusText, setStatusText] = useState("准备生成二维码");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncCreator, setSyncCreator] = useState(false);
  const confirmedRef = useRef(false);
  const onConfirmedRef = useRef(onConfirmed);

  useEffect(() => {
    onConfirmedRef.current = onConfirmed;
  }, [onConfirmed]);

  function errorMessage(error: unknown, fallback = "二维码生成失败，请稍后重试。"): string {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail;
      if (typeof detail === "string" && detail) {
        return detail;
      }
    }
    return fallback;
  }

  async function startSession() {
    setIsLoading(true);
    setError(null);
    setSession(null);
    confirmedRef.current = false;
    try {
      const nextSession =
        accountType === "pc"
          ? await createXhsPcQrLoginSession({ sync_creator: syncCreator })
          : await createXhsCreatorQrLoginSession();
      setSession(nextSession);
      setStatusText(accountType === "pc" ? "请使用小红书 App 扫描二维码" : "请使用小红书 App 扫描 Creator 二维码");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setIsLoading(false);
    }
  }

  // 记录已为哪组参数创建过会话：React StrictMode 会双调用 effect，
  // 不加守卫会在挂载瞬间连建两个上游会话（数据库里成对出现）
  const startedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    const key = `${accountType}:${syncCreator}`;
    if (startedKeyRef.current === key) {
      return;
    }
    // 切换账号类型或勾选“同步 Creator”会重建 session。
    // 已有二维码时给出明确提示，避免用户正扫的码被静默作废。
    if (startedKeyRef.current !== null) {
      setStatusText("参数已变更，正在重新生成二维码…");
    }
    startedKeyRef.current = key;
    void startSession();
    // startSession 依赖 accountType/syncCreator，二者变化即重建
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountType, syncCreator]);

  useEffect(() => {
    if (!session?.session_id || session.status === "confirmed" || session.status === "expired" || session.status === "blocked") {
      return;
    }

    let cancelled = false;
    let terminal = false;
    let timer: number | undefined;
    const sessionId = session.session_id;

    // 串行轮询（setTimeout 链）：单次上游请求可能超过 2s，
    // setInterval 会让请求重叠；后端虽已串行化，前端也不应堆积请求。
    const poll = async () => {
      if (cancelled) return;
      try {
        const polled = await pollXhsLoginSession(sessionId);
        if (cancelled) return;
        terminal = polled.status === "confirmed" || polled.status === "expired" || polled.status === "blocked";
        setError(null);
        setSession((current) => ({
          ...polled,
          qr_image_data_url: polled.qr_image_data_url ?? current?.qr_image_data_url
        }));
        if (polled.status === "scanned") {
          setStatusText("已扫码，请在手机端确认登录");
          setError(null);
        } else if (polled.status === "blocked") {
          setStatusText("登录请求被小红书拒绝，已停止自动重试");
        } else if (polled.status === "expired") {
          setStatusText("二维码已过期，请刷新");
        } else if (polled.status === "confirmed") {
          if (polled.account && !confirmedRef.current) {
            confirmedRef.current = true;
            setStatusText("账号绑定成功");
            onConfirmedRef.current(polled.account);
          } else if (!polled.account) {
            // 已确认但账号信息还在重试（后端幂等续跑）
            setStatusText("已确认登录，正在获取账号信息…");
          }
        }
      } catch (caught) {
        if (cancelled) return;
        // 展示后端返回的具体原因（如上游换取失败、会话失效），
        // 而不是笼统的“轮询失败”
        setError(errorMessage(caught, "轮询登录状态失败，正在等待下一次尝试。"));
      } finally {
        if (!cancelled && !terminal) {
          timer = window.setTimeout(() => void poll(), 2000);
        }
      }
    };

    timer = window.setTimeout(() => void poll(), 2000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [session?.session_id, session?.status]);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        styles={{
          body: {
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
            minHeight: 220,
            background: "#1f1f1f",
          },
        }}
        style={{ borderColor: "#303030" }}
      >
        {session?.qr_image_data_url ? (
          <img
            src={session.qr_image_data_url}
            alt="小红书登录二维码"
            style={{ width: 180, height: 180, borderRadius: 8, background: "#fff", padding: 8 }}
          />
        ) : (
          <div
            style={{
              width: 180,
              height: 180,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "#262626",
              borderRadius: 8,
              color: "rgba(255,255,255,0.3)",
              fontSize: 28,
              fontWeight: 700,
            }}
          >
            QR
          </div>
        )}
      </Card>

      <div style={{ textAlign: "center" }}>
        <Text strong style={{ display: "block", marginBottom: 4, color: "rgba(255,255,255,0.88)" }}>
          {statusText}
        </Text>
        {session?.qr_url ? (
          <AntLink href={session.qr_url} target="_blank" rel="noreferrer">
            打开二维码链接
          </AntLink>
        ) : null}
      </div>

      {accountType === "pc" ? (
        <Checkbox
          checked={syncCreator}
          onChange={(event) => setSyncCreator(event.target.checked)}
          style={{ color: "rgba(255,255,255,0.88)" }}
        >
          登录 PC 后同步 Creator 账号
        </Checkbox>
      ) : null}

      {session?.status === "blocked" ? (
        <Alert
          type="warning"
          message={session.message || blockedMessage}
          description={
            <AntLink href="https://www.xiaohongshu.com/" target="_blank" rel="noreferrer">
              打开小红书官方网页
            </AntLink>
          }
          showIcon
        />
      ) : null}

      {error ? <Alert type="error" message={error} showIcon /> : null}

      <Button
        block
        icon={<ReloadOutlined />}
        onClick={startSession}
        loading={isLoading}
      >
        {isLoading ? "生成中..." : "刷新二维码"}
      </Button>
    </Space>
  );
}
