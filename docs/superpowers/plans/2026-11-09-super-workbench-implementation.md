# 超级工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有工程中实现“登录 → 应用中心 → 小红书运营”的轻量应用框架，完整保留小红书功能。

**Architecture:** 在前端增加独立应用注册表、应用中心和应用入口解析页面。保留小红书原路由、页面及 AppShell；仅改登录落点和外壳返回入口，不改后端和认证实现。

**Tech Stack:** React 19、TypeScript、Vite、Ant Design 6、React Router 7；测试使用 Node 内置 node:test、现有 TypeScript、React DOM 和根工程已有 jsdom，不增加依赖。

## Global Constraints

以下要求引用已确认设计，各任务自动包含：

- 沿用现有技术栈、依赖和部署方式，不引入微前端、新后端服务或新框架。
- 复用现有认证与用户数据隔离，不另建登录系统，不新增角色、菜单权限或应用授权后台。
- 保留小红书所有现有功能。不得修改小红书业务页面、接口、数据库结构、数据范围、采集发布流程或定时任务。
- 变更只作用于统一入口、前端应用注册、外围路由组织、登录后的导航及工作区返回入口。
- 本次不实现其他业务应用，不以虚假应用卡片或原社交平台占位项充当已接入应用。
- 不执行真实平台采集、发布、账号绑定、外部模型调用或定时任务触发。
- 当前工作目录不是 Git 仓库；本文保存到本地，不自动初始化 Git 或创建提交。

设计依据：[设计文档](../specs/2026-11-09-super-workbench-design.md)，用户已于 2026-11-09 在对话中审阅通过。本计划仅待执行，不表示已完成实现或测试。

---

## 文件地图与依赖顺序

工作目录均为工程根目录 `E:/code/super_work`。命令从根目录执行，除非明确注明。

| 文件 | 动作与唯一职责 |
| --- | --- |
| `scripts/workbench-boundary.cjs` | 新增；记录/检查受保护源码哈希、菜单、缓存和原业务路由 |
| `frontend/src/apps/registry.ts` | 新增；应用元数据和按 ID 精确查找 |
| `frontend/src/pages/apps/app-center-page.tsx` | 新增；应用目录展示及选择 |
| `frontend/src/pages/apps/app-entry-page.tsx` | 新增；入口解析与不可用提示 |
| `frontend/tests/helpers/render.cjs` | 新增；只用于测试的 TS 加载、DOM 与依赖替身，不进入构建 |
| `frontend/tests/workbench.test.cjs` | 新增；注册表、页面、认证落点和路由集成测试 |
| `frontend/src/app/router.tsx:1-83` | 小幅修改；新增门户路由，保留所有业务绑定 |
| `frontend/src/components/ui/protected-route.tsx:57-59` | 修改；已登录访问登录页时跳转 `/apps` |
| `frontend/src/pages/login/login-page.tsx:23,51,81-84` | 修改；成功登录/注册固定跳转 `/apps`，移除不用的 location |
| `frontend/src/components/layout/app-shell.tsx:1-25,158-173` | 小幅修改；工作区身份和折叠/展开均可用的应用中心入口 |
| `docs/superpowers/verification/2026-11-09-super-workbench.md` | 新增；实际验证结果与未覆盖范围 |
| `.claude/launch.json` | 仅浏览器验收需要且不存在时新增；前端本地预览配置 |

不删除旧选择页、旧平台选择组件或旧平台配置。只使旧 `/platform-select` 路由变为兼容重定向。无需修改 package.json、锁文件、global.css、现有 API 层、use-auth 或 providers。

依赖顺序：任务 1 → 任务 2 → 任务 3 → 任务 4。这些是同一变更的连续步骤，不拆成互相独立的业务交付。

## 任务 1：建立保护基线和应用注册表

**Files:**
- Create: `scripts/workbench-boundary.cjs`
- Create: `frontend/src/apps/registry.ts`
- Create: `frontend/tests/helpers/render.cjs`
- Create: `frontend/tests/workbench.test.cjs`

**Interfaces:**
- Consumes: 原源码、现有 `frontend/node_modules`、根 `node_modules/jsdom`。
- Produces: `workbenchApps: readonly WorkbenchApp[]`；`findWorkbenchApp(id: string | undefined): WorkbenchApp | undefined`。
- Produces test helper: `load(relativePath: string, mocks?: Record<string, unknown>): any`；`render(element: ReactNode, pathname?: string): Promise<{container: HTMLElement; click(element: Element): Promise<void>; close(): Promise<void>}>`。

- [ ] **Step 1：确认依赖并使用锁文件安装。**

```bash
npm ci
```

```bash
npm --prefix frontend ci
```

期望：两条命令退出码 0，锁文件不变。当前检查环境是 Node v24.18.0、npm 11.16.0、Python 3.12.1；前端依赖与根 jsdom 均未安装。安装失败时记录原因，不擅自升级或替换依赖。无需安装任何新测试包。

- [ ] **Step 2：创建源码保护脚本，在业务编辑之前捕获基线。**

`scripts/workbench-boundary.cjs` 完整内容：

```javascript
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const [mode, file] = process.argv.slice(2);
if (!['capture', 'check'].includes(mode) || !file) {
  throw new Error('Usage: node scripts/workbench-boundary.cjs capture|check <manifest>');
}
const protectedRoots = [
  'backend', 'apis', 'xhs_utils', 'spider', 'static', 'libs', 'sign', 'utils', 'config', 'tests/backend',
  'frontend/src/pages/platforms/xhs',
  'frontend/src/lib/api.ts', 'frontend/src/lib/platforms.ts',
  'frontend/src/hooks/use-auth.ts', 'frontend/src/types',
  'frontend/src/app/providers.tsx', 'frontend/src/global.css',
  'frontend/src/components/account', 'frontend/src/components/platforms',
  'frontend/src/components/layout/platform-selector.tsx',
  'frontend/src/pages/platform-select', 'frontend/src/pages/models',
  'frontend/src/pages/settings', 'frontend/src/pages/tasks',
  'package.json', 'package-lock.json',
  'frontend/package.json', 'frontend/package-lock.json',
  'requirements.txt', 'main.py', 'tests/backend'
];
function fingerprint() {
  const files = {};
  function visit(relative) {
    const full = path.join(root, relative);
    if (!fs.existsSync(full)) return;
    if (fs.statSync(full).isDirectory()) {
      for (const entry of fs.readdirSync(full).sort()) {
        if (['__pycache__', '.pytest_cache', 'node_modules'].includes(entry)) continue;
        visit(`${relative}/${entry}`);
      }
    } else if (!relative.endsWith('.pyc')) {
      files[relative] = crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');
    }
  }
  protectedRoots.forEach(visit);
  const shell = fs.readFileSync(path.join(root, 'frontend/src/components/layout/app-shell.tsx'), 'utf8');
  const router = fs.readFileSync(path.join(root, 'frontend/src/app/router.tsx'), 'utf8');
  const navigation = shell.match(/const mainNavItems[\s\S]*?const footerNavItems[\s\S]*?\n\];/);
  const cache = shell.match(/<KeepAliveRouteOutlet[^>]*\/>/);
  assert(navigation && cache, 'Cannot identify existing menu/cache; stop rather than weaken protection');
  const routes = [...router.matchAll(/<Route path="(\/platforms\/xhs\/[^\"]+|\/tasks|\/models|\/settings)" element=\{<([^ >]+)[^\n]*?\/>\} \/>/g)]
    .map(match => [match[1], match[2]]);
  assert.equal(routes.length, 17, 'Expected 14 XHS routes plus 3 shared routes');
  return { files, navigation: navigation[0], cache: cache[0], routes };
}
if (mode === 'capture') {
  assert(!fs.existsSync(file), 'Never overwrite an existing baseline');
  fs.mkdirSync(path.dirname(path.resolve(file)), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(fingerprint(), null, 2));
  console.log('Protected source baseline captured');
} else {
  assert.deepEqual(fingerprint(), JSON.parse(fs.readFileSync(file, 'utf8')));
  console.log('Protected files, menus, cache and all 17 business route bindings unchanged');
}
```

实际 SDK 若还存在其他目录，先用 Glob 查明并追加到 `protectedRoots`，再捕获；不得删除脚本列出的已存在目录。脚本是验证工具，不导入或运行后端。

```bash
node scripts/workbench-boundary.cjs capture .workbench-verification/baseline.json
```

期望：成功捕获、识别 17 个业务路由。基线只保存在本地验证目录，不能在修改后重新捕获以掩盖差异；最终保留供复核。

- [ ] **Step 3：创建最小测试加载器。**

`frontend/tests/helpers/render.cjs` 完整内容：

```javascript
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { JSDOM } = require('jsdom');
const frontend = path.resolve(__dirname, '../..');
const frontRequire = createRequire(path.join(frontend, 'package.json'));
const ts = frontRequire('typescript');
// DOM 必须先于 React DOM/Ant Design 导入建立，确保输入事件被正确识别。
const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/apps', pretendToBeVisual: true
});
const globals = {
  window: dom.window, document: dom.window.document,
  navigator: dom.window.navigator, HTMLElement: dom.window.HTMLElement,
  Element: dom.window.Element, SVGElement: dom.window.SVGElement,
  ShadowRoot: dom.window.ShadowRoot, Node: dom.window.Node,
  getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
  localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true
};
for (const [key, value] of Object.entries(globals)) {
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
dom.window.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } });
const React = frontRequire('react');
const { createRoot } = frontRequire('react-dom/client');
const { act } = React;

function load(relativePath, mocks = {}) {
  const cache = new Map();
  const normalized = Object.fromEntries(Object.entries(mocks).map(([key, value]) => [path.resolve(frontend, key), value]));
  function read(full) {
    if (Object.hasOwn(normalized, full)) return normalized[full];
    if (cache.has(full)) return cache.get(full).exports;
    const module = { exports: {} };
    cache.set(full, module);
    const source = fs.readFileSync(full, 'utf8');
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
        jsx: ts.JsxEmit.ReactJSX,
        esModuleInterop: true
      }, fileName: full
    });
    function requireLocal(specifier) {
      // 缓存行为由源码基线保护；DOM 导航测试不启动真实缓存容器。
      if (specifier === 'keepalive-for-react-router') return { __esModule: true, default: () => null };
      if (!specifier.startsWith('.')) return frontRequire(specifier);
      const base = path.resolve(path.dirname(full), specifier);
      const resolved = ['', '.ts', '.tsx', '.js'].map(ext => base + ext).find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
      if (!resolved) throw new Error(`Cannot resolve ${specifier} from ${full}`);
      return read(resolved);
    }
    new Function('require', 'module', 'exports', outputText)(requireLocal, module, module.exports);
    return module.exports;
  }
  return read(path.resolve(frontend, relativePath));
}

async function render(element, pathname = '/apps') {
  dom.window.history.replaceState(null, '', pathname);
  dom.window.localStorage.clear();
  const container = dom.window.document.createElement('div');
  dom.window.document.body.append(container);
  const root = createRoot(container);
  async function close() {
    await act(async () => root.unmount());
    container.remove();
  }
  try {
    await act(async () => root.render(element));
    return {
      container,
      async click(target) {
        await act(async () => target.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })));
      },
      close
    };
  } catch (error) {
    await close();
    throw error;
  }
}
module.exports = { load, render, React, frontRequire };
```

该加载器只处理本工程 TS/TSX，并允许测试替换认证及业务页面；不会改变 Node 全局模块加载规则。类型正确性仍由真实生产构建验证，不由 transpileModule 代替。测试不并发运行，避免 DOM 全局状态冲突。

- [ ] **Step 4：先写注册表失败测试。**

创建 `frontend/tests/workbench.test.cjs`，初始完整内容：

```javascript
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { load, render, React, frontRequire } = require('./helpers/render.cjs');
const { MemoryRouter, Routes, Route } = frontRequire('react-router-dom');
const h = React.createElement;

test('registry exposes only the real XHS app and never falls back for unknown IDs', () => {
  const { workbenchApps, findWorkbenchApp } = load('src/apps/registry.ts');
  assert.equal(workbenchApps.length, 1);
  assert.deepEqual(workbenchApps[0], {
    id: 'xhs', name: '小红书运营', description: '采集、内容管理、创作与发布的一站式运营工作台',
    icon: '/logo.jpg', entryPath: '/platforms/xhs/dashboard', enabled: true
  });
  assert.equal(findWorkbenchApp('xhs'), workbenchApps[0]);
  for (const id of [undefined, '', 'missing', '__proto__', 'constructor']) {
    assert.equal(findWorkbenchApp(id), undefined);
  }
});
```

```bash
node --test frontend/tests/workbench.test.cjs
```

期望：因 `registry.ts` 不存在而失败；不是依赖缺失。确认失败后再实现。

- [ ] **Step 5：实现注册表并验证转绿。**

`frontend/src/apps/registry.ts`：

```typescript
export type WorkbenchApp = Readonly<{
  id: string;
  name: string;
  description: string;
  icon: string;
  entryPath: string;
  enabled: boolean;
}>;

export const workbenchApps: readonly WorkbenchApp[] = [
  {
    id: 'xhs',
    name: '小红书运营',
    description: '采集、内容管理、创作与发布的一站式运营工作台',
    icon: '/logo.jpg',
    entryPath: '/platforms/xhs/dashboard',
    enabled: true
  }
];

export function findWorkbenchApp(id: string | undefined): WorkbenchApp | undefined {
  return workbenchApps.find(app => app.id === id);
}
```

```bash
node --test frontend/tests/workbench.test.cjs
```

期望：1 个测试通过。只接受注册项中的本地入口，不从查询参数或用户输入构造重定向目标。复核任务 1 的文件，不创建 Git 提交。

## 任务 2：实现应用中心和入口解析

**Files:**
- Create: `frontend/src/pages/apps/app-center-page.tsx`
- Create: `frontend/src/pages/apps/app-entry-page.tsx`
- Modify: `frontend/tests/workbench.test.cjs`（追加）

**Interfaces:**
- Consumes: `WorkbenchApp`、`workbenchApps`、`findWorkbenchApp`、现有 `useAuth()`；原 `useThemeMode` 和主题 token。
- Produces: `AppCenterPage(): JSX.Element`（TS 推断）、`AppEntryPage(): JSX.Element`（TS 推断）。
- Produces navigation: `/apps/:appId`；错误页返回 `/apps`。

- [ ] **Step 1：追加页面行为失败测试。**

```javascript
const authPath = 'src/hooks/use-auth.ts';
const registryPath = 'src/apps/registry.ts';
function authStub(overrides = {}) {
  return {
    user: { id: 1, username: '测试用户' }, status: 'authenticated',
    isAuthenticated: true, isChecking: false, error: null,
    logout: async () => {}, login: async () => {}, register: async () => {},
    ...overrides
  };
}

test('center shows the real app, username, logout, and navigates on selection', async () => {
  let logouts = 0;
  const auth = authStub({ logout: async () => { logouts += 1; } });
  const { AppCenterPage } = load('src/pages/apps/app-center-page.tsx', {
    [authPath]: { useAuth: () => auth }
  });
  const view = await render(h(MemoryRouter, { initialEntries: ['/apps'] },
    h(Routes, null,
      h(Route, { path: '/apps', element: h(AppCenterPage) }),
      h(Route, { path: '/apps/xhs', element: h('p', null, 'selected-xhs') })
    )));
  try {
    assert.match(view.container.textContent, /超级工作台/);
    assert.match(view.container.textContent, /测试用户/);
    assert.equal(view.container.querySelectorAll('[data-app-id]').length, 1);
    const logout = [...view.container.querySelectorAll('button')].find(x => x.textContent.includes('退出登录'));
    await view.click(logout);
    assert.equal(logouts, 1);
    await view.click(view.container.querySelector('[data-app-id="xhs"] button'));
    assert.match(view.container.textContent, /selected-xhs/);
  } finally { await view.close(); }
});

test('disabled apps cannot be selected and names remain text', async () => {
  const { AppCenterPage } = load('src/pages/apps/app-center-page.tsx', {
    [authPath]: { useAuth: () => authStub() },
    [registryPath]: { workbenchApps: [{ id: 'disabled', name: '<b>不可执行</b>', description: '未开放', icon: '/logo.jpg', entryPath: '/unused', enabled: false }] }
  });
  const view = await render(h(MemoryRouter, null, h(AppCenterPage)));
  try {
    assert.equal(view.container.querySelector('[data-app-id] button').disabled, true);
    assert.equal(view.container.querySelector('[data-app-id] b'), null);
    assert.match(view.container.textContent, /<b>不可执行<\/b>/);
  } finally { await view.close(); }
});

for (const scenario of ['enabled', 'unknown', 'disabled']) {
  test(`entry handles ${scenario} without silently falling back`, async () => {
    const registry = scenario === 'disabled'
      ? { findWorkbenchApp: () => ({ enabled: false }) }
      : {};
    const { AppEntryPage } = load('src/pages/apps/app-entry-page.tsx',
      scenario === 'disabled' ? { [registryPath]: registry } : {});
    const view = await render(h(MemoryRouter, { initialEntries: [`/apps/${scenario === 'unknown' ? 'missing' : 'xhs'}`] },
      h(Routes, null,
        h(Route, { path: '/apps/:appId', element: h(AppEntryPage) }),
        h(Route, { path: '/platforms/xhs/dashboard', element: h('p', null, 'xhs-dashboard') }),
        h(Route, { path: '/apps', element: h('p', null, 'app-center') })
      )));
    try {
      if (scenario === 'enabled') assert.match(view.container.textContent, /xhs-dashboard/);
      else {
        assert.doesNotMatch(view.container.textContent, /xhs-dashboard/);
        assert.match(view.container.textContent, scenario === 'unknown' ? /应用不存在/ : /应用暂不可用/);
        await view.click([...view.container.querySelectorAll('button')].find(x => x.textContent.includes('返回应用中心')));
        assert.match(view.container.textContent, /app-center/);
      }
    } finally { await view.close(); }
  });
}
```

```bash
node --test frontend/tests/workbench.test.cjs
```

期望：新增页面相关测试因文件不存在而失败，注册表测试继续通过。

- [ ] **Step 2：实现应用中心。**

`frontend/src/pages/apps/app-center-page.tsx` 完整内容：

```tsx
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
```

使用现有主题的 Layout 和 token，不写全局 CSS，不请求平台目录或外部图片。

- [ ] **Step 3：实现入口解析与明确错误提示。**

`frontend/src/pages/apps/app-entry-page.tsx`：

```tsx
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
```

- [ ] **Step 4：验证任务 2 与保护边界。**

```bash
node --test frontend/tests/workbench.test.cjs
```

期望：6 个测试通过（注册表 1、应用中心 2、入口 3），TAP 输出 6 tests / 0 fail。

```bash
node scripts/workbench-boundary.cjs check .workbench-verification/baseline.json
```

期望：受保护文件、菜单、缓存及 17 个业务绑定不变。任务级复核后继续，不提交。

## 任务 3：接入路由、登录落点与工作区返回入口

**Files:**
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/components/ui/protected-route.tsx`
- Modify: `frontend/src/pages/login/login-page.tsx`
- Modify: `frontend/src/components/layout/app-shell.tsx`
- Modify: `frontend/tests/workbench.test.cjs`（追加）

**Interfaces:**
- Consumes: `AppCenterPage`、`AppEntryPage`、原认证守卫与 `AppShell`。
- Produces: `/apps` 和 `/apps/:appId` 为受保护路由；`/`、`/platform-select`、成功认证后的落点统一 `/apps`；小红书深链接保留。

- [ ] **Step 1：先追加真实路由集成测试（业务页面使用替身，不访问外部接口）。**

```javascript
function routeMocks(auth) {
  const stubs = {
    [authPath]: { useAuth: () => auth },
    'src/components/layout/app-shell.tsx': { AppShell: frontRequire('react-router-dom').Outlet }
  };
  const pages = {
    'accounts-page': 'XhsAccountsPage', 'analytics-page': 'XhsAnalyticsPage',
    'auto-ops-page': 'AutoOpsPage', 'benchmarks-page': 'XhsBenchmarksPage',
    'xhs-dashboard': 'XhsDashboard', 'crawler-page': 'XhsCrawlerPage',
    'discovery-page': 'XhsDiscoveryPage', 'rewrite-page': 'XhsDraftsPage',
    'keywords-page': 'XhsKeywordsPage', 'library-page': 'XhsLibraryPage',
    'monitoring-page': 'XhsMonitoringPage', 'image-studio-page': 'XhsImageStudioPage',
    'publish-page': 'XhsPublishPage', 'video-studio-page': 'XhsVideoStudioPage',
    'xhs-section-page': 'XhsSectionPage'
  };
  for (const [file, exported] of Object.entries(pages)) {
    stubs[`src/pages/platforms/xhs/${file}.tsx`] = { [exported]: () => h('p', null, exported) };
  }
  for (const [file, exported] of [
    ['src/pages/models/model-config-page.tsx', 'ModelConfigPage'],
    ['src/pages/settings/settings-page.tsx', 'SettingsPage'],
    ['src/pages/tasks/task-center-page.tsx', 'TaskCenterPage'],
    ['src/components/platforms/coming-soon.tsx', 'ComingSoonPage']
  ]) stubs[file] = { [exported]: () => h('p', null, exported) };
  return stubs;
}

for (const pathname of ['/', '/apps', '/apps/xhs', '/platforms/xhs/library']) {
  test(`anonymous ${pathname} is guarded`, async () => {
    const auth = authStub({ isAuthenticated: false, status: 'anonymous', user: null });
    const { AppRouter } = load('src/app/router.tsx', routeMocks(auth));
    const view = await render(h(AppRouter), pathname);
    try {
      assert.equal(window.location.pathname, '/login');
      assert(view.container.querySelector('input[type="password"]'));
    } finally { await view.close(); }
  });
}

for (const pathname of ['/', '/platform-select', '/login']) {
  test(`authenticated ${pathname} lands on app center`, async () => {
    const { AppRouter } = load('src/app/router.tsx', routeMocks(authStub()));
    const view = await render(h(AppRouter), pathname);
    try {
      assert.equal(window.location.pathname, '/apps');
      assert.match(view.container.textContent, /超级工作台/);
    } finally { await view.close(); }
  });
}

test('app center selection reaches the unchanged dashboard route', async () => {
  const { AppRouter } = load('src/app/router.tsx', routeMocks(authStub()));
  const view = await render(h(AppRouter), '/apps');
  try {
    assert.equal(window.location.pathname, '/apps');
    await view.click(view.container.querySelector('[data-app-id="xhs"] button'));
    assert.equal(window.location.pathname, '/platforms/xhs/dashboard');
    assert.match(view.container.textContent, /XhsDashboard/);
  } finally { await view.close(); }
});

test('authenticated deep link is not forced through app selection', async () => {
  const { AppRouter } = load('src/app/router.tsx', routeMocks(authStub()));
  const view = await render(h(AppRouter), '/platforms/xhs/library');
  try {
    assert.equal(window.location.pathname, '/platforms/xhs/library');
    assert.match(view.container.textContent, /XhsLibraryPage/);
  } finally { await view.close(); }
});

for (const mode of ['login', 'register']) {
  test(`${mode} ignores a previous business destination and opens app center`, async () => {
    let calls = 0;
    const auth = authStub({ [mode]: async () => { calls += 1; } });
    const { LoginPage } = load('src/pages/login/login-page.tsx', { [authPath]: { useAuth: () => auth } });
    const view = await render(h(MemoryRouter, {
      initialEntries: [{ pathname: '/login', state: { from: { pathname: '/platforms/xhs/library' } } }]
    }, h(Routes, null,
      h(Route, { path: '/login', element: h(LoginPage) }),
      h(Route, { path: '/apps', element: h('p', null, 'new-session-app-center') }),
      h(Route, { path: '/platforms/xhs/library', element: h('p', null, 'wrong-business-destination') })
    )));
    try {
      if (mode === 'register') {
        const choice = [...view.container.querySelectorAll('.ant-segmented-item')].find(x => x.textContent.includes('注册'));
        assert(choice, 'Registration mode control must exist');
        await view.click(choice.querySelector('input') || choice);
      }
      const { act } = React;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      await act(async () => {
        const inputs = [...view.container.querySelectorAll('input')].filter(x => ['text', 'password'].includes(x.type));
        assert.equal(inputs.length, mode === 'register' ? 3 : 2);
        inputs.forEach((input, index) => {
          setter.call(input, index === 0 ? 'tester' : 'password123');
          input.dispatchEvent(new window.Event('input', { bubbles: true }));
        });
      });
      await act(async () => view.container.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })));
      assert.equal(calls, 1);
      assert.match(view.container.textContent, /new-session-app-center/);
    } finally { await view.close(); }
  });
}

test('shell exposes an app-center button in both expanded and collapsed states', async () => {
  const { AppShell } = load('src/components/layout/app-shell.tsx', {
    [authPath]: { useAuth: () => authStub() },
    'src/lib/api.ts': { fetchNotifications: async () => ({ items: [] }), markAllNotificationsRead: async () => {}, markNotificationRead: async () => {} },
    'src/app/providers.tsx': { useThemeMode: () => ({ mode: 'dark', toggle() {} }) }
  });
  for (const collapse of [false, true]) {
    const view = await render(h(MemoryRouter, { initialEntries: ['/platforms/xhs/dashboard'] },
      h(Routes, null,
        h(Route, { path: '/platforms/xhs/dashboard', element: h(AppShell) }),
        h(Route, { path: '/apps', element: h('p', null, 'returned-to-center') })
      )));
    try {
      if (collapse) await view.click(view.container.querySelector('button[aria-label="收起侧栏"]'));
      const back = view.container.querySelector('button[aria-label="应用中心"]');
      assert(back);
      await view.click(back);
      assert.match(view.container.textContent, /returned-to-center/);
    } finally { await view.close(); }
  }
});
```

测试加载器已对 KeepAlive 使用显式空替身；生产缓存配置由原始源码基线核对。DOM 测试不等于验证真实 KeepAlive 运行效果，不得调整生产缓存代码来适配测试。

```bash
node --test frontend/tests/workbench.test.cjs
```

期望：门户及注册表原测试通过；认证落点、登录提交和返回入口的新增测试失败。先确认失败指向待实现行为，不能因为测试 DOM 初始化或输入事件无效而判为有效红灯。

- [ ] **Step 2：路由中添加应用页面并保留业务路由原文。**

在 `router.tsx` 移除不再使用的 `PlatformSelectPage` import；新增：

```tsx
import { AppCenterPage } from '../pages/apps/app-center-page';
import { AppEntryPage } from '../pages/apps/app-entry-page';
```

根路由替换为：

```tsx
<Route path="/" element={<Navigate to="/apps" replace />} />
```

原 `/platform-select` 整个 Route 替换为下列三个同级 Route：

```tsx
<Route path="/platform-select" element={<Navigate to="/apps" replace />} />
<Route path="/apps" element={<ProtectedRoute><AppCenterPage /></ProtectedRoute>} />
<Route path="/apps/:appId" element={<ProtectedRoute><AppEntryPage /></ProtectedRoute>} />
```

不把 `/apps` 放进 AppShell；不更改 `/platforms/:platformId`；不更改现有 17 个业务 Route 及任何原 import 的组件对应关系。

- [ ] **Step 3：固定登录、注册和 PublicOnlyRoute 落点。**

`protected-route.tsx` 仅将已登录分支改为：

```tsx
if (auth.isAuthenticated) {
  return <Navigate to="/apps" replace />;
}
```

`login-page.tsx` 的路由 import 改为：

```tsx
import { useNavigate } from 'react-router-dom';
```

删除 `const location = useLocation();`。保留 auth.login/auth.register 调用原样，把原 `const from = ...` 至 navigate 的代码替换为：

```tsx
navigate('/apps', { replace: true });
```

不要改登录 UI、营销文案、输入校验或错误处理。此处测试会实际提交登录与注册表单，证明行为而非只检查字符串。

- [ ] **Step 4：外壳增加明确返回入口，保留菜单和缓存。**

在 `app-shell.tsx` 的图标 import 中增加 `AppstoreOutlined`。将 Logo 区的 `onClick={() => navigate("/platform-select")}` 改为 `onClick={() => navigate('/apps')}`，将 `Spider XHS` 展示文字改成 `小红书运营`，其他 Logo 样式不变。

原展开时收起按钮增加 `aria-label="收起侧栏"`，原折叠时展开按钮增加 `aria-label="展开侧栏"`，不改 click handler。

紧接现有 Logo 区及折叠控制之后、Main nav 之前插入：

```tsx
<div style={{ padding: collapsed ? '8px 0' : '8px 12px', textAlign: 'center', flexShrink: 0 }}>
  <Button type="text" icon={<AppstoreOutlined />} aria-label="应用中心" title="应用中心"
    onClick={() => navigate('/apps')} style={{ color: 'rgba(255,255,255,.65)' }}>
    {!collapsed && '应用中心'}
  </Button>
</div>
```

保留原有 mainNavItems、footerNavItems、主题、通知和 KeepAliveRouteOutlet 配置逐字不变；不抽取或重写外壳。

- [ ] **Step 5：运行集成测试和保护检查，记录实际输出。**

```bash
node --test frontend/tests/workbench.test.cjs
```

期望：所有测试通过，0 fail。若测试 harness 在当前 React/Ant Design 下有警告，区分警告与失败并记录；只能修正测试环境兼容性，不更改业务代码来消除无关警告。

```bash
node scripts/workbench-boundary.cjs check .workbench-verification/baseline.json
```

期望：受保护文件、全部业务菜单、缓存和 17 个路由绑定不变。任务级复核四个生产修改文件，无 Git 提交。

## 任务 4：构建、回归及本地浏览器验收

**Files:**
- Create: `docs/superpowers/verification/2026-11-09-super-workbench.md`
- Create only if absent: `.claude/launch.json`
- Read only: 全部受保护源码与已有后端测试

**Interfaces:**
- Consumes: 已实现的门户与原系统；任务 1 捕获的原始基线。
- Produces: 明确的实际命令结果、兼容性证据与未覆盖范围。不得把本计划的“期望”复制成实际通过结果。

- [ ] **Step 1：执行完整前端测试及生产构建。**

```bash
node --test frontend/tests/workbench.test.cjs
```

```bash
npm --prefix frontend run build
```

期望：测试 0 fail，`tsc && vite build` 退出码 0。构建覆盖真实 TypeScript 检查；不得仅以测试加载器的转译成功代替类型检查。大于约两分钟的命令后台运行并等待完成通知，不轮询。

- [ ] **Step 2：在隔离环境运行已有后端测试，不启动服务器或调度器。**

已核实 `get_settings()` 以 YAML 值作为显式构造参数，可能覆盖同名环境变量，因此不能仅设置 SCHEDULER_ENABLED。执行前再检查已有后端测试中的数据库覆盖/网络 monkeypatch，确认不使用真实账号、模型配置或业务库，不运行 uvicorn/main.py，不进入真实应用启动 lifespan。

先创建本地测试覆盖配置（不修改 config/default.yaml）：

```bash
python -I -c "from pathlib import Path; p=Path('.workbench-verification/test-config.yaml'); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('scheduler:\n  enabled: false\n',encoding='utf-8')"
```

```bash
CONFIG_FILE=.workbench-verification/test-config.yaml SCHEDULER_ENABLED=false DATABASE_URL=sqlite:// python -m pytest tests/backend -q
```

期望：已有测试通过，报告真实计数；覆盖配置明确关闭调度器；`database_url` 不在 YAML 字段映射内，DATABASE_URL 可直接使用进程内存数据库 `sqlite://`，测试原有 tmp_path 数据库保持原隔离方式。不安装/改写已有后端实现来掩盖失败。如发现测试直接调用外部网络，先不执行该测试，记录具体测试与原因；不能声称全部后端测试通过。

若 Python 缺失测试依赖，记录缺失项并按原 requirements 安装流程处理；依赖安装/测试结果与前端结果分别报告。不得打开真实业务库。

- [ ] **Step 3：用 Browser 工具启动前端预览，只做无真实业务操作的视觉检查。**

执行此步骤前调用 `run` 技能；它若要求 UI 设计验收，遵循既有设计，不扩大为重设计。先检查 `.claude/launch.json` 是否已存在；存在则读取并保留原配置，仅必要时追加。不存在时创建：

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "super-workbench-frontend",
      "runtimeExecutable": "npm",
      "runtimeArgs": ["--prefix", "frontend", "run", "dev", "--", "--host", "127.0.0.1"],
      "port": 5173
    }
  ]
}
```

通过 `preview_start` 启动，不用 Bash 启动服务器。不启动后端、不输入真实账号；匿名访问 `/apps`、`/apps/xhs`、`/platform-select`，核对进入原登录页，无跳转循环。检查浏览器控制台与网络失败，将未启动后端导致的预期请求失败和真正运行错误区分。

应用中心的已认证行为、未知/禁用入口、登录注册与折叠返回已由 DOM 集成测试验证。为了在真实浏览器验证应用中心布局，可使用 Vite SSR 的本地离线预览页面，或已有允许网络 mock 的浏览器测试工具；不允许通过修改生产认证、伪造持久登录状态或在 DOM 中拼一个假页面冒充应用中心。若工具不支持安全的网络 mock，本轮明确记录“已认证页面浏览器视觉验收未执行”，不得声称已完整浏览器验收。

在可安全渲染真实应用中心的测试环境下，验收：375px 手机宽度、桌面宽度、深浅主题；按钮可键盘访问，无横向溢出；使用 inspect 核对主题 token 的实际样式，不靠截图推测颜色。结束后恢复 desktop viewport。该视觉检查不替代 DOM 导航测试。

- [ ] **Step 4：最终保护复核并写验证报告。**

```bash
node scripts/workbench-boundary.cjs check .workbench-verification/baseline.json
```

期望：全部保护检查通过。核对新增/修改的文件只在文件地图范围内；验证目录为本地产物，不能混入业务功能。若实际 SDK 保护范围扩大，在报告中注明捕获时的完整目录清单。

创建 `docs/superpowers/verification/2026-11-09-super-workbench.md`，逐项写入真实证据：

- 实施日期及环境版本。
- 原始保护基线位置、保护范围、最终 check 输出。
- 生产源码实际新增与修改文件列表。
- 注册表及页面/路由测试实际计数、失败或警告。
- 前端构建命令、退出码、产物结果。
- 后端测试命令、实际计数或无法执行的具体原因。
- 浏览器已执行的路径与视口；已认证视觉检查若未执行则明确记为未验证。
- 未执行真实采集、发布、绑定、模型调用或调度任务。
- 无 Git 提交；不声称已实测所有外部小红书功能。

不能预先填入“全部通过”。报告书写不需要新框架或格式依赖。

- [ ] **Step 5：最终审查并交付。**

使用 verification-before-completion 规则，逐项比对设计文档与本次证据，再报告实际完成范围。若任务 4 有环境阻断，明确区分“功能代码已写”“测试通过”和“未验证”。不执行提交、推送、初始化 Git 或创建 PR。

## 实施前的计划自查

- 设计覆盖：注册与入口在任务 1/2；主题与响应式在任务 2/4；登录、旧入口及深链接在任务 3；小红书保护和全部原路由在任务 1/3/4；现有后端回归与不执行外部操作在任务 4。
- 类型一致：`WorkbenchApp`、`workbenchApps`、`findWorkbenchApp`、`AppCenterPage`、`AppEntryPage` 为本计划全部新增生产接口，均有定义。
- 依赖限制：不新增 npm/pip 包声明，不改 package 或锁文件；只安装锁文件中已有依赖。
- 未扩范围：不新增其他真实应用，不做 RBAC、租户或跨应用任务聚合。
- 保护策略：原始哈希基线先于生产代码修改；测试不执行小红书功能。

## 执行方式

计划批准后有两种执行方式：

1. **子代理逐任务执行（推荐）**：使用 subagent-driven-development；各任务依次执行，在任务间做规格与代码审查，同一时间不让两个写入者改同一文件。
2. **当前会话分批执行**：使用 executing-plans；按任务顺序实现，在测试和保护检查节点暂停复核。

两种方式均遵守同一设计与保护基线。本轮只交付计划，不开始上述步骤。
