const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { load, render, React, frontRequire } = require('./helpers/render.cjs');
const { MemoryRouter, Routes, Route } = frontRequire('react-router-dom');
const h = React.createElement;
// jsdom 未实现 ResizeObserver；antd 6 的 Avatar 在挂载后会测量文本子元素。
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
// Node 提供 MessageChannel，@rc-component/overflow 会为每次测量新建且从不关闭它，
// 导致 antd Menu 测试结束后进程无法退出；移除后该模块回退到 rAF/setTimeout。
delete globalThis.MessageChannel;

test('registry exposes the real XHS and douyin apps and never falls back for unknown IDs', () => {
  const { workbenchApps, findWorkbenchApp } = load('src/apps/registry.ts');
  assert.equal(workbenchApps.length, 2);
  assert.deepEqual(workbenchApps[0], {
    id: 'xhs', name: '小红书运营', description: '采集、内容管理、创作与发布的一站式运营工作台',
    icon: '/logo.jpg', entryPath: '/platforms/xhs/dashboard', enabled: true
  });
  assert.deepEqual(workbenchApps[1], {
    id: 'douyin', name: '抖音运营', description: '多账号采集参考、审核发布与真实数据复盘',
    icon: '/logo.jpg', entryPath: '/platforms/douyin/accounts', enabled: true
  });
  assert.equal(findWorkbenchApp('xhs'), workbenchApps[0]);
  assert.equal(findWorkbenchApp('douyin'), workbenchApps[1]);
  for (const id of [undefined, '', 'missing', '__proto__', 'constructor']) {
    assert.equal(findWorkbenchApp(id), undefined);
  }
});

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
      h(Route, { path: '/apps/xhs', element: h('p', null, 'selected-xhs') }),
      h(Route, { path: '/apps/douyin', element: h('p', null, 'selected-douyin') })
    )));
  try {
    assert.match(view.container.textContent, /超级工作台/);
    assert.match(view.container.textContent, /测试用户/);
    assert.equal(view.container.querySelectorAll('[data-app-id]').length, 2);
    const logout = [...view.container.querySelectorAll('button')].find(x => x.textContent.includes('退出登录'));
    await view.click(logout);
    assert.equal(logouts, 1);
    await view.click(view.container.querySelector('[data-app-id="xhs"] button'));
    assert.match(view.container.textContent, /selected-xhs/);
    await view.close();
    // 抖音入口同样可选，且进入其真实入口路径
    const view2 = await render(h(MemoryRouter, { initialEntries: ['/apps'] },
      h(Routes, null,
        h(Route, { path: '/apps', element: h(AppCenterPage) }),
        h(Route, { path: '/apps/douyin', element: h('p', null, 'selected-douyin') })
      )));
    try {
      await view2.click(view2.container.querySelector('[data-app-id="douyin"] button'));
      assert.match(view2.container.textContent, /selected-douyin/);
    } finally { await view2.close(); }
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
