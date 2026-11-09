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
  'author',
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
