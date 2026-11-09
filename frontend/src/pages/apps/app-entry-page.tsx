import { Button, Layout, Result } from 'antd';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { findWorkbenchApp } from '../../apps/registry';

export function AppEntryPage() {
  const { appId } = useParams<{ appId: string }>();
  const navigate = useNavigate();
  const app = findWorkbenchApp(appId);
  if (app?.enabled) return <Navigate to={app.entryPath} replace />;
  return (
    <Layout style={{ minHeight: '100vh', justifyContent: 'center', padding: 24 }}>
      <Result status="warning" title={app ? '应用暂不可用' : '应用不存在'}
        subTitle="请返回应用中心选择已开放的应用。"
        extra={<Button type="primary" onClick={() => navigate('/apps', { replace: true })}>返回应用中心</Button>} />
    </Layout>
  );
}
