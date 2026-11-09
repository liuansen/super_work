import { ArrowRightOutlined, LogoutOutlined } from '@ant-design/icons';
import { Avatar, Button, Card, Col, Layout, Row, Space, Tag, Typography, theme } from 'antd';
import { useNavigate } from 'react-router-dom';
import { workbenchApps } from '../../apps/registry';
import { useAuth } from '../../hooks/use-auth';

const { Title, Text, Paragraph } = Typography;

export function AppCenterPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  return (
    <Layout style={{ minHeight: '100vh', padding: '40px 24px' }}>
      <main style={{ width: '100%', maxWidth: 1120, margin: '0 auto' }}>
        <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16, marginBottom: 40 }}>
          <div>
            <Text type="secondary">统一应用入口</Text>
            <Title level={1} style={{ margin: '8px 0' }}>超级工作台</Title>
            <Paragraph type="secondary" style={{ margin: 0 }}>选择一个应用，进入对应的工作台。</Paragraph>
          </div>
          <Space wrap>
            <Avatar>{(auth.user?.username ?? '用户')[0]}</Avatar>
            <Text>{auth.user?.username ?? '用户'}</Text>
            <Button icon={<LogoutOutlined />} onClick={() => void auth.logout()}>退出登录</Button>
          </Space>
        </header>
        <section aria-label="应用列表">
          <Row gutter={[24, 24]}>
            {workbenchApps.map(app => (
              <Col xs={24} sm={12} lg={8} key={app.id}>
                <Card data-app-id={app.id} style={{ height: '100%', borderColor: token.colorBorderSecondary }}>
                  <Space align="start" size={16} style={{ marginBottom: 20 }}>
                    <Avatar shape="square" size={48} src={app.icon} alt={app.name} />
                    <div>
                      <Title level={2} style={{ fontSize: 20, margin: '0 0 8px' }}>{app.name}</Title>
                      <Tag>{app.enabled ? '已开放' : '暂不可用'}</Tag>
                    </div>
                  </Space>
                  <Paragraph type="secondary" style={{ minHeight: 44 }}>{app.description}</Paragraph>
                  <Button type="primary" block disabled={!app.enabled} icon={<ArrowRightOutlined />}
                    onClick={() => navigate(`/apps/${encodeURIComponent(app.id)}`)}>
                    {app.enabled ? '进入工作台' : '暂不可用'}
                  </Button>
                </Card>
              </Col>
            ))}
          </Row>
        </section>
      </main>
    </Layout>
  );
}
