const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('stub editor implements exchange, asset download and export upload', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', '..', 'tools', 'clip-editor-stub', 'index.html'), 'utf8');
  assert.match(html, /\/api\/clip\/sessions\/.*\/exchange/);
  assert.match(html, /\/api\/clip\/sessions\/.*\/assets\//);
  assert.match(html, /\/api\/clip\/exports/);
  assert.match(html, /history\.replaceState/);
  assert.match(html, /Authorization/);
});
