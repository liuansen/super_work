const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { load, render, React, frontRequire } = require('./helpers/render.cjs');
const { MemoryRouter } = frontRequire('react-router-dom');
const h = React.createElement;
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
delete globalThis.MessageChannel;

const authPath = 'src/hooks/use-auth.ts';
const appsPath = 'src/hooks/use-apps.ts';

function read(relative) {
  return fs.readFileSync(path.join(__dirname, '..', relative), 'utf8');
}

test('app center hides apps the account has not been assigned', async () => {
  const auth = { user: { id: 2, username: '受限用户', is_admin: false }, status: 'authenticated', isAuthenticated: true, isChecking: false, error: null, logout: async () => {} };
  const { AppCenterPage } = load('src/pages/apps/app-center-page.tsx', {
    [authPath]: { useAuth: () => auth },
    [appsPath]: {
      // 仅 xhs 分配给该账号：douyin/clip 必须从应用中心消失
      useMyApps: () => ({
        apps: [], isLoading: false, isError: false,
        has: (key) => key === 'xhs', refresh: async () => {}
      })
    }
  });
  const view = await render(h(MemoryRouter, null, h(AppCenterPage)));
  try {
    const cards = [...view.container.querySelectorAll('[data-app-id]')].map(x => x.getAttribute('data-app-id'));
    assert.deepEqual(cards, ['xhs']);
    assert.equal(view.container.textContent.includes('抖音运营'), false);
    assert.equal(view.container.textContent.includes('剪辑工坊'), false);
  } finally { await view.close(); }
});

test('app manage page wires toggles and user assignment', () => {
  const page = read('src/pages/apps/app-manage-page.tsx');
  assert.match(page, /应用管理/);
  assert.match(page, /toggleApp/);
  assert.match(page, /setUserApps/);
  assert.match(page, /useAdminCatalog/);
  assert.match(page, /useAdminUsers/);
  assert.match(page, /应用开关/);
  assert.match(page, /账号分配/);
});

test('require-app guard redirects unassigned accounts to app center', () => {
  const guard = read('src/components/ui/require-app.tsx');
  assert.match(guard, /RequireApp/);
  assert.match(guard, /useMyApps/);
  assert.match(guard, /Navigate to="\/apps" replace/);
  assert.match(guard, /is_admin/);
});

test('router gates xhs, douyin and clip routes by app permission', () => {
  const router = read('src/app/router.tsx');
  assert.match(router, /RequireApp appKey="xhs"/);
  assert.match(router, /RequireApp appKey="douyin"/);
  assert.match(router, /RequireApp appKey="clip"/);
  assert.match(router, /RequireAdmin/);
  assert.match(router, /path="\/apps\/manage"/);
});

test('backend catalog api enforces admin on management endpoints', () => {
  const api = fs.readFileSync(path.join(__dirname, '..', '..', 'backend', 'app', 'api', 'apps.py'), 'utf8');
  assert.match(api, /Depends\(require_admin\)/);
  assert.match(api, /app_access_required|require_admin/, 'management endpoints must be gated');
  const deps = fs.readFileSync(path.join(__dirname, '..', '..', 'backend', 'app', 'core', 'deps.py'), 'utf8');
  assert.match(deps, /def require_admin/);
  assert.match(deps, /def app_access_required/);
});
