const assert = require('node:assert/strict');
const test = require('node:test');
const { load, render, React } = require('./helpers/render.cjs');
const { act } = React;

function controlPollTimers() {
  const originalSetTimeout = window.setTimeout;
  const originalClearTimeout = window.clearTimeout;
  const scheduled = new Map();
  let nextId = 100000;
  window.setTimeout = (callback, delay, ...args) => {
    if (delay !== 2000) return originalSetTimeout.call(window, callback, delay, ...args);
    const id = nextId++;
    scheduled.set(id, () => callback(...args));
    return id;
  };
  window.clearTimeout = (id) => {
    if (scheduled.delete(id)) return;
    originalClearTimeout.call(window, id);
  };
  return {
    get size() { return scheduled.size; },
    async next() {
      const [id, callback] = scheduled.entries().next().value || [];
      assert.ok(callback, 'expected the next QR poll to be scheduled');
      scheduled.delete(id);
      await act(async () => callback());
    },
    restore() {
      window.setTimeout = originalSetTimeout;
      window.clearTimeout = originalClearTimeout;
    },
  };
}

function apiMock(poll) {
  let created = 0;
  return {
    get created() { return created; },
    createXhsPcQrLoginSession: async () => {
      created += 1;
      return { session_id: created, status: 'pending', qr_url: 'https://example.test/qr' };
    },
    createXhsCreatorQrLoginSession: async () => {
      throw new Error('unexpected creator login');
    },
    pollXhsLoginSession: poll,
  };
}

const confirmed = {
  session_id: 1, status: 'confirmed', qr_url: 'https://example.test/qr',
  account: { id: 5, platform: 'xhs', sub_type: 'pc', nickname: 'test-account', status: 'active' },
};

test('QR confirmation survives a parent render while polling and stops at completion', async () => {
  const timers = controlPollTimers();
  let finishPoll;
  let polled = 0;
  const api = apiMock(() => {
    polled += 1;
    return new Promise(resolve => { finishPoll = resolve; });
  });
  const { QrLoginPanel } = load('src/components/account/qr-login-panel.tsx', { 'src/lib/api.ts': api });
  const received = [];
  function Parent() {
    const [revision, setRevision] = React.useState(0);
    return React.createElement(React.Fragment, null,
      React.createElement('button', { id: 'rerender-parent', onClick: () => setRevision(n => n + 1) }, 'rerender'),
      React.createElement(QrLoginPanel, {
        accountType: 'pc', onConfirmed: account => received.push([revision, account.id]),
      }),
    );
  }
  let ui;
  try {
    ui = await render(React.createElement(React.StrictMode, null, React.createElement(Parent)));
    assert.equal(api.created, 1);
    await timers.next();
    assert.equal(polled, 1);
    assert.equal(timers.size, 0, 'do not overlap a slow poll');
    await ui.click(ui.container.querySelector('#rerender-parent'));
    await act(async () => finishPoll(confirmed));
    assert.deepEqual(received, [[1, 5]]);
    assert.ok(ui.container.textContent.includes('账号绑定成功'));
    assert.equal(timers.size, 0, 'stop scheduling after confirmed');
  } finally {
    if (ui) await ui.close();
    timers.restore();
  }
});

test('a blocked QR login stops polling across parent renders and only restarts on explicit refresh', async () => {
  const timers = controlPollTimers();
  const message = '小红书拒绝了本次登录请求（HTTP 471），已停止自动重试。请先在小红书官方网页或 App 确认可正常登录，并完成平台提示的验证，再重新绑定。';
  const polled = [];
  let finishPoll;
  const api = apiMock(sessionId => {
    polled.push(sessionId);
    if (sessionId === 1) return new Promise(resolve => { finishPoll = resolve; });
    return Promise.resolve({ ...confirmed, session_id: sessionId });
  });
  const { QrLoginPanel } = load('src/components/account/qr-login-panel.tsx', { 'src/lib/api.ts': api });
  const received = [];
  function Parent() {
    const [revision, setRevision] = React.useState(0);
    return React.createElement(React.Fragment, null,
      React.createElement('button', { id: 'rerender-parent', onClick: () => setRevision(n => n + 1) }, 'rerender'),
      React.createElement(QrLoginPanel, {
        accountType: 'pc', onConfirmed: account => received.push([revision, account.id]),
      }),
    );
  }
  let ui;
  try {
    ui = await render(React.createElement(React.StrictMode, null, React.createElement(Parent)));
    assert.equal(api.created, 1);
    await timers.next();
    await ui.click(ui.container.querySelector('#rerender-parent'));
    await act(async () => finishPoll({
      session_id: 1, status: 'blocked', qr_url: 'https://example.test/qr',
      account: null, creator_account: null, message,
      error_code: 'xhs_login_blocked', upstream_status: 471, retryable: false,
    }));
    const warning = ui.container.querySelector('.ant-alert-warning');
    assert.ok(warning, 'show a warning for platform-blocked login');
    assert.ok(warning.textContent.includes(message), 'display the full backend explanation');
    const officialLink = warning.querySelector('a');
    assert.equal(officialLink.getAttribute('href'), 'https://www.xiaohongshu.com/');
    assert.equal(officialLink.getAttribute('target'), '_blank');
    assert.ok(officialLink.getAttribute('rel').includes('noreferrer'));
    assert.equal(window.location.pathname, '/apps', 'stay on the login panel');
    assert.equal(timers.size, 0, 'do not schedule another poll for a blocked session');
    for (let i = 0; i < 3; i += 1) {
      await ui.click(ui.container.querySelector('#rerender-parent'));
      assert.equal(timers.size, 0, 'parent renders must not restart blocked polling');
    }
    assert.deepEqual(polled, [1]);
    assert.equal(api.created, 1, 'do not automatically create a replacement session');
    assert.deepEqual(received, [], 'do not report a bound account for blocked login');
    assert.ok(!ui.container.textContent.includes('账号绑定成功'));
    assert.ok(!ui.container.textContent.includes('正在获取账号信息'));

    const refresh = [...ui.container.querySelectorAll('button')].find(button => button.textContent.includes('刷新二维码'));
    assert.ok(refresh);
    await ui.click(refresh);
    assert.equal(api.created, 2, 'explicit refresh creates a new session');
    assert.ok(!ui.container.querySelector('.ant-alert-warning'), 'clear the blocked warning for the new session');
    assert.equal(timers.size, 1, 'schedule polling for the new session');
    await timers.next();
    assert.deepEqual(polled, [1, 2], 'poll the replacement session, not the blocked one');
    assert.deepEqual(received, [[4, 5]]);
    assert.ok(ui.container.textContent.includes('账号绑定成功'));
    assert.equal(timers.size, 0);
  } finally {
    if (ui) await ui.close();
    timers.restore();
  }
});

test('a blocked QR login without a message still explains the required next steps', async () => {
  const timers = controlPollTimers();
  const api = apiMock(async () => ({
    session_id: 1, status: 'blocked', qr_url: 'https://example.test/qr',
    account: null, creator_account: null,
  }));
  const { QrLoginPanel } = load('src/components/account/qr-login-panel.tsx', { 'src/lib/api.ts': api });
  let ui;
  try {
    ui = await render(React.createElement(QrLoginPanel, {
      accountType: 'pc', onConfirmed: () => assert.fail('blocked login must not confirm an account'),
    }));
    await timers.next();
    const warning = ui.container.querySelector('.ant-alert-warning');
    assert.ok(warning.textContent.includes('已停止自动重试'));
    assert.ok(warning.textContent.includes('完成平台提示的验证，再重新绑定'));
    assert.equal(timers.size, 0);
  } finally {
    if (ui) await ui.close();
    timers.restore();
  }
});

test('a successful QR retry clears the previous error and reports the bound account', async () => {
  const timers = controlPollTimers();
  let attempts = 0;
  const api = apiMock(async () => {
    attempts += 1;
    if (attempts === 1) throw new Error('temporary upstream failure');
    return confirmed;
  });
  const { QrLoginPanel } = load('src/components/account/qr-login-panel.tsx', { 'src/lib/api.ts': api });
  const received = [];
  let ui;
  try {
    ui = await render(React.createElement(QrLoginPanel, { accountType: 'pc', onConfirmed: a => received.push(a.id) }));
    await timers.next();
    assert.ok(ui.container.textContent.includes('轮询登录状态失败'));
    await timers.next();
    assert.deepEqual(received, [5]);
    assert.ok(ui.container.textContent.includes('账号绑定成功'));
    assert.ok(!ui.container.textContent.includes('轮询登录状态失败'));
    assert.equal(timers.size, 0);
  } finally {
    if (ui) await ui.close();
    timers.restore();
  }
});
