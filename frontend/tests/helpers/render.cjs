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
