import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
import { viewStateModule } from './helpers/viewState.mjs';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function load(file, modules) {
  const source = readFileSync(new URL(`../../web/frontend/src/components/${file}`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } });
  const exports = {};
  runInNewContext(outputText, { exports, require: name => modules[name] });
  return exports.default;
}

// Initialize from the real cache/view-state ports, rather than private hook order.
function trendsFixture(sources, groups, initialSelected = sources.filter(source => source.default).map(source => source.id)) {
  let view = { selected: initialSelected, initialized: true };
  const react = { Component: class {},
    useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}],
    useEffect() {}, useCallback: fn => fn, useRef: value => ({ current: value }) };
  const modules = { react, 'react/jsx-runtime': jsx,
    '../lib/viewState': viewStateModule(react),
    '../lib/api': { peekApiData: path => path === '/api/trends/sources'
      ? { sources, warnings: [] } : { trends: groups, warnings: [], updated: 0 }, subscribeApiData: () => () => {} },
    './icons': {}, './TrendSourcesDialog': { __esModule: true, default: 'dialog' },
    './ContentPanel': { __esModule: true, default: 'panel' } };
  const Page = load('TrendsPage.tsx', modules);
  const root = Page({ onUseTopic() {}, viewState: { read: () => view, write: next => { view = next; } } });
  return { tree: root.props.children.type(root.props.children.props), selected: () => view.selected };
}

test('共享面板保留标题、内容和可键盘聚焦的命名滚动区域', () => {
  const panel = load('ContentPanel.tsx', { 'react/jsx-runtime': jsx });
  const tree = panel({ label: '微博热点列表', header: '标题', children: '内容', className: 'trend-col' });
  assert.equal(tree.type, 'section');
  assert.match(tree.props.className, /content-panel/);
  assert.equal(tree.props.children[0], '标题');
  const body = tree.props.children[1];
  assert.equal(body.props.role, 'region');
  assert.equal(body.props['aria-label'], '微博热点列表');
  assert.equal(body.props.tabIndex, 0);
  assert.equal(body.props.children, '内容');
});

test('长错误信息进入有界内容区域，来源名称和条目仍然保留', () => {
  const { tree: trends } = trendsFixture([{ id: 'x', label: '长来源', default: true }],
    [{ platform: 'x', label: '长来源', items: [], ok: false, error: { message: '很长的错误信息'.repeat(100) } }]);
  function nodes(node) { return Array.isArray(node) ? node.flatMap(nodes) : !node || typeof node !== 'object' ? [] : [node, ...nodes(node.props?.children)]; }
  const all = nodes(trends);
  const panel = all.find(node => node.type === 'panel');
  assert.equal(panel.props.label, '长来源热点列表');
  assert.equal(panel.props.header.props.children[0].props.title, '长来源');
  assert.ok(nodes(panel.props.children).some(node => node.props?.role === 'status'));
  assert.ok(nodes(panel.props.children).some(node => node.props?.className === 'trend-empty'));
  assert.equal(all.find(node => node.props?.['aria-label'] === '选择热点数据源').props.role, 'group');
});

test('数据源开关保留选中状态并能独立启用和停用', () => {
  const fixture = trendsFixture([{ id: 'one', label: '来源一' }, { id: 'two', label: '来源二' }], [], ['one']);
  const tree = fixture.tree;
  function nodes(node) { return Array.isArray(node) ? node.flatMap(nodes) : !node || typeof node !== 'object' ? [] : [node, ...nodes(node.props?.children)]; }
  const buttons = nodes(tree).filter(node => node.type === 'button' && 'aria-pressed' in node.props);
  assert.equal(buttons.length, 2);
  assert.equal(buttons[0].props['aria-pressed'], true);
  assert.equal(buttons[1].props['aria-pressed'], false);
  buttons[1].props.onClick();
  assert.equal(fixture.selected().join(','), 'one,two');
  buttons[0].props.onClick();
  assert.equal(fixture.selected().join(','), 'two');
});
