// 抖音应用独立外壳：菜单、返回应用中心、主题切换；不触碰小红书外壳。
import {
  AppstoreOutlined,
  DatabaseOutlined,
  FundOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  ScissorOutlined,
  SendOutlined,
  SunOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Layout, Menu, Space, Typography } from "antd";
import type { MenuProps } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useThemeMode } from "../../app/providers";
import { useMyApps } from "../../hooks/use-apps";
import { useAuth } from "../../hooks/use-auth";

const { Sider, Header, Content } = Layout;
const { Text } = Typography;

function buildDouyinNav(douyinAllowed: boolean, clipAllowed: boolean): MenuProps["items"] {
  if (!douyinAllowed) return [];
  return [
    { key: "/platforms/douyin/accounts", icon: <SafetyCertificateOutlined />, label: "账号" },
    { key: "/platforms/douyin/references", icon: <DatabaseOutlined />, label: "参考库" },
    { key: "/platforms/douyin/works", icon: <FundOutlined />, label: "作品数据" },
    ...(clipAllowed ? [{ key: "/clip", icon: <ScissorOutlined />, label: "剪辑工坊" as const }] : []),
    { key: "/platforms/douyin/publish", icon: <SendOutlined />, label: "发布中心" },
  ];
}

export function DouyinShell() {
  const auth = useAuth();
  const myApps = useMyApps();
  const douyinAllowed = myApps.has("douyin");
  const clipAllowed = myApps.has("clip");
  const { mode: themeMode, toggle: toggleTheme } = useThemeMode();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const selectedKeys = [location.pathname];
  const siderWidth = collapsed ? 64 : 200;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        collapsed={collapsed}
        width={200}
        collapsedWidth={64}
        theme="dark"
        trigger={null}
        style={{
          height: "100vh",
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          borderRight: "1px solid var(--app-border)",
          overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <div
            style={{
              padding: collapsed ? "14px 0" : "14px 16px",
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "space-between",
              borderBottom: "1px solid var(--app-border)",
              flexShrink: 0,
              cursor: "pointer",
            }}
            onClick={() => navigate("/apps")}
          >
            <Space align="center" size={collapsed ? 0 : 8}>
              <img
                src="/logo.jpg"
                alt="Logo"
                style={{ width: 28, height: 28, borderRadius: 6, objectFit: "cover", flexShrink: 0 }}
              />
              {!collapsed && (
                <span style={{ fontWeight: 600, fontSize: 14, color: "rgba(255,255,255,.85)" }}>
                  抖音运营
                </span>
              )}
            </Space>
            {!collapsed && (
              <Button
                type="text"
                size="small"
                aria-label="收起侧栏"
                icon={<MenuFoldOutlined />}
                onClick={(e) => {
                  e.stopPropagation();
                  setCollapsed(true);
                }}
                style={{ color: "var(--app-text-disabled)" }}
              />
            )}
          </div>
          {collapsed && (
            <div style={{ textAlign: "center", padding: "6px 0", borderBottom: "1px solid var(--app-elevated)", flexShrink: 0 }}>
              <Button
                type="text"
                size="small"
                aria-label="展开侧栏"
                icon={<MenuUnfoldOutlined />}
                onClick={() => setCollapsed(false)}
                style={{ color: "var(--app-text-disabled)" }}
              />
            </div>
          )}

          <div style={{ padding: collapsed ? "8px 0" : "8px 12px", textAlign: "center", flexShrink: 0 }}>
            <Button
              type="text"
              icon={<AppstoreOutlined />}
              aria-label="应用中心"
              title="应用中心"
              onClick={() => navigate("/apps")}
              style={{ color: "var(--app-text-secondary)" }}
            >
              {!collapsed && "应用中心"}
            </Button>
          </div>

          <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
            <Menu
              theme="dark"
              mode="inline"
              selectedKeys={selectedKeys}
              onClick={({ key }) => navigate(key)}
              items={buildDouyinNav(douyinAllowed, clipAllowed)}
              style={{ borderRight: 0 }}
            />
          </div>

          <div style={{ flexShrink: 0, borderTop: "1px solid var(--app-border)" }}>
            <div
              style={{
                padding: collapsed ? "8px 0" : "8px 16px",
                display: "flex",
                alignItems: "center",
                gap: 8,
                justifyContent: collapsed ? "center" : "flex-start",
              }}
            >
              <Avatar size={22} icon={<UserOutlined />} style={{ background: "#1668dc", flexShrink: 0, fontSize: 11 }}>
                {(auth.user?.username ?? "U")[0].toUpperCase()}
              </Avatar>
              {!collapsed && (
                <>
                  <Text type="secondary" ellipsis style={{ fontSize: 12, flex: 1, lineHeight: "22px" }}>
                    {auth.user?.username ?? "用户"}
                  </Text>
                  <Button
                    type="text"
                    icon={<LogoutOutlined />}
                    onClick={() => void auth.logout()}
                    size="small"
                    style={{ color: "var(--app-text-disabled)", flexShrink: 0 }}
                  />
                </>
              )}
            </div>
          </div>
        </div>
      </Sider>

      <Layout style={{ marginLeft: siderWidth, transition: "margin-left 0.2s" }}>
        <Header
          style={{
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            borderBottom: "1px solid var(--app-border)",
            height: 48,
            lineHeight: "48px",
          }}
        >
          <Button
            type="text"
            icon={themeMode === "dark" ? <SunOutlined style={{ fontSize: 16 }} /> : <MoonOutlined style={{ fontSize: 16 }} />}
            onClick={toggleTheme}
            title={themeMode === "dark" ? "切换为浅色模式" : "切换为暗色模式"}
            style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
          />
        </Header>
        <Content style={{ padding: 24, minHeight: "calc(100vh - 48px)", overflow: "auto" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export function DouyinPageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24, gap: 16, flexWrap: "wrap" }}>
      <div>
        <Text type="secondary" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 1 }}>
          {eyebrow}
        </Text>
        <Typography.Title level={3} style={{ margin: "4px 0" }}>
          {title}
        </Typography.Title>
        <Text type="secondary">{description}</Text>
      </div>
      {action}
    </div>
  );
}
