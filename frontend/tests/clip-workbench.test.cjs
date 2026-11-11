const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function read(relative) {
  return fs.readFileSync(path.join(__dirname, '..', relative), 'utf8');
}

test('clip page wires session creation and editor opening', () => {
  const page = read('src/features/clip/clip-page.tsx');
  assert.match(page, /剪辑工坊/);
  assert.match(page, /新建剪辑/);
  assert.match(page, /createClipSession/);
  assert.match(page, /buildEditorUrl/);
  assert.match(page, /window\.open/);
});

test('export list renders download, draft, douyin and delete actions', () => {
  const list = read('src/features/clip/components/export-list.tsx');
  assert.match(list, /下载/);
  assert.match(list, /送入小红书草稿/);
  assert.match(list, /用于抖音发布/);
  assert.match(list, /删除/);
  assert.match(list, /createClipDraft/);
  assert.match(list, /\/platforms\/douyin\/publish/);
});

test('clip app is registered and reachable from both shells', () => {
  const registry = read('src/apps/registry.ts');
  assert.match(registry, /id: 'clip'/);
  const router = read('src/app/router.tsx');
  assert.match(router, /path="\/clip"/);
  const xhsShell = read('src/components/layout/app-shell.tsx');
  assert.match(xhsShell, /剪辑工坊/);
  assert.match(xhsShell, /"\/clip"/);
  const douyinShell = read('src/features/douyin/douyin-shell.tsx');
  assert.match(douyinShell, /剪辑工坊/);
  assert.match(douyinShell, /"\/clip"/);
  const videoStudio = read('src/pages/platforms/xhs/video-studio-page.tsx');
  assert.match(videoStudio, /Navigate/);
  assert.match(videoStudio, /\/clip\?from=xhs/);
});

test('douyin publishing page consumes clip preselect params', () => {
  const page = read('src/features/douyin/pages/publishing-page.tsx');
  assert.match(page, /readDouyinPreselect/);
  assert.match(page, /setUploads/);
  assert.match(page, /setOpen\(true\)/);
});
