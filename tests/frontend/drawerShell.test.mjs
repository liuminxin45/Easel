import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript'), react = require('react'), jsx = require('react/jsx-runtime');
const {renderToStaticMarkup} = require('react-dom/server');
const root = new URL('../../', import.meta.url);
function module(source, imports, globals = {}) {
  const {outputText} = ts.transpileModule(source, {compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }});
  const exports = {};
  runInNewContext(outputText, {exports, ...globals, require: id => {
    if (id === 'react/jsx-runtime') return jsx;
    if (id in imports) return imports[id];
    return assert.fail('Unexpected import: ' + id);
  }});
  return exports;
}
const source = name => readFileSync(new URL('web/frontend/src/' + name, root), 'utf8');
const children = node => Array.isArray(node.props.children) ? node.props.children : [node.props.children];
const normalizeSemantics = html => html.replace(/ (?:id|role|aria-label|aria-labelledby|aria-modal)="[^"]*"/g, '');

test('the shared shell renders the original official SkillDrawer DOM and heading layout', () => {
  const original = execFileSync('git', ['show', '0f43dc98277eac85fb48952878acad349731d3fc:web/frontend/src/components/SkillDrawer.tsx'], {
    cwd: root, encoding: 'utf8',
  });
  const hooks = {...react, useState: value => [value, () => {}], useEffect: () => {},
    useMemo: fn => fn(), useRef: value => ({current: value}), useId: () => 'heading'};
  const SkillDrawer = module(original, {
    react: hooks, './SettingsSelect': {default: () => null}, '../lib/api': {},
    '../lib/sanitize': {renderMarkdown: value => value}, '../lib/skillDisplayNames': {displayName: value => value},
  }).default;
  const official = SkillDrawer({skillName: 'ai-image-gen', persona: 'TEMP', onClose() {}, onConfigured() {}});
  const [heading, body] = children(official.props.children);
  const [left] = children(heading.props.children);
  const Drawer = module(source('components/Drawer.tsx'), {
    react: hooks, 'react-dom': {createPortal: content => content},
  }).default;
  const shared = Drawer({header: left, label: 'ai-image-gen', onClose() {}, children: body.props.children});
  assert.equal(normalizeSemantics(renderToStaticMarkup(shared)), normalizeSemantics(renderToStaticMarkup(official)));
  assert.equal(shared.props.children.props.role, 'dialog');
  assert.equal(shared.props.children.props['aria-modal'], 'true');
  assert.equal(shared.props.children.props['aria-label'], 'ai-image-gen');
});

test('a closed drawer has no overlay and an open drawer preserves original backdrop dismissal', () => {
  let closed = 0, stopped = 0;
  const Drawer = module(source('components/Drawer.tsx'), {
    react: {...react, useId: () => 'heading'}, 'react-dom': {createPortal: content => content},
  }).default;
  assert.equal(Drawer({open: false, title: 'TEMP', onClose() {}, children: 'body'}), null);
  const tree = Drawer({title: 'TEMP', onClose: () => closed++, children: 'body'});
  tree.props.children.props.onClick({stopPropagation: () => stopped++});
  assert.equal(stopped, 1);assert.equal(closed, 0);
  tree.props.onClick();assert.equal(closed, 1);
});

function hostFixture() {
  const effects = [], listeners = new Map();
  let released = 0, restored = 0, focused = 0, closed = 0, backed = 0, nativeDialog = null;
  class Element {isConnected = true;closest() {return null;}focus() {restored++;}}
  const previous = new Element(), ownOverlay = {getClientRects: () => [{}]}, nestedOverlay = {getClientRects: () => [{}]};
  let overlays = [ownOverlay], back;
  const mount = {}, panel = {parentElement: ownOverlay, querySelector: () => ({focus() {focused++;}})};
  const nav = {registerLayer: fn => {back = fn;return () => released++;}};
  const document = {activeElement: previous,
    querySelector: selector => selector === '.native-host' ? mount : selector === 'dialog[open]' ? nativeDialog : null,
    querySelectorAll: () => overlays,
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: name => listeners.delete(name),
  };
  const core = {}, hooks = {useWorkbench: () => ({navigation: nav})};
  const common = module(source('workbench/ui/common.tsx'), {
    react: {...react, useRef: value => ({current: value}), useEffect: effect => effects.push(effect)},
    '../../components/DownloadLink': () => null, '../../components/Drawer': 'EaselDrawer',
    '@workbench/core': core, './hooks': hooks, './lib/sanitize': {},
    '../../components/InteractionNotice': {}, './ExtensionDetails': {},
  }, {document, HTMLElement: Element, getComputedStyle: () => ({visibility: 'visible'}),
    requestAnimationFrame: fn => {fn();return 1;}, cancelAnimationFrame() {}, queueMicrotask: fn => fn()});
  const mounted = common.Drawer({open: true, title: '技能版本', onClose: () => closed++, onDismiss: () => {backed++;return false;}, children: 'retained body'});
  const tree = mounted.type(mounted.props);
  assert.equal(tree.type, 'EaselDrawer');assert.equal(tree.props.container, mount);
  tree.props.panelRef.current = panel;
  const cleanup = effects[0]();
  const escape = () => {
    const event = {key: 'Escape', defaultPrevented: false, preventDefault() {this.defaultPrevented = true;}, stopPropagation() {}};
    listeners.get('keydown')(event);return event;
  };
  return {tree, escape, back: () => back(), cleanup,
    nested: value => {overlays = value ? [ownOverlay, nestedOverlay] : [ownOverlay];},
    native: value => {nativeDialog = value ? {} : null;},
    state: () => ({released, restored, focused, closed, backed})};
}

test('the host keeps Back transactions and focus return while rendering the same official shell', () => {
  const host = hostFixture();assert.equal(host.state().focused, 1);
  assert.equal(host.back(), false);assert.equal(host.state().backed, 1);
  assert.equal(host.state().closed, 0);
  host.cleanup();assert.equal(host.state().released, 1);assert.equal(host.state().restored, 1);
});

test('Escape dismisses only the top host drawer and leaves native dialogs in control', () => {
  const host = hostFixture();host.nested(true);
  assert.equal(host.escape().defaultPrevented, false);assert.equal(host.state().closed, 0);
  host.nested(false);host.native(true);
  assert.equal(host.escape().defaultPrevented, false);assert.equal(host.state().closed, 0);
  host.native(false);assert.equal(host.escape().defaultPrevented, true);assert.equal(host.state().closed, 1);
  host.cleanup();
});
