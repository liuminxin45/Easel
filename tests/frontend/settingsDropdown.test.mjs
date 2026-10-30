import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/SettingsSelect.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('SettingsSelect.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = parsed.statements.find(node =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'OptionsDropdown');
assert.ok(declaration);
const { outputText } = ts.transpileModule(declaration.getText(parsed).replace('export ', '') + '\nOptionsDropdown;', {
  compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
});

test('Escape is captured by the dropdown, not the surrounding settings dialog', () => {
  const listeners = [];
  const removed = [];
  const cleanups = [];
  let closed = 0;
  let focused = 0;
  const component = runInNewContext(outputText, {
    useRef: () => ({ current: null }),
    useState: () => [null, () => {}],
    useEffect: callback => {
      const cleanup = callback();
      if (cleanup) cleanups.push(cleanup);
    },
    useLayoutEffect: () => {},
    React: { createElement: (...args) => ({ args }) },
    createPortal: element => element,
    window: {
      innerHeight: 800, innerWidth: 1200,
      addEventListener: () => {}, removeEventListener: () => {},
    },
    document: {
      addEventListener: (...args) => listeners.push(args),
      removeEventListener: (...args) => removed.push(args),
    },
  });
  component({
    anchor: {
      getBoundingClientRect: () => ({ top: 100, bottom: 130, left: 20, width: 100 }),
      focus: () => { focused += 1; },
      getAttribute: () => null,
      closest: () => null,
    },
    items: [], current: '', onClose: () => { closed += 1; },
  });
  const registration = listeners.find(([name]) => name === 'keydown');
  assert.equal(registration[2], true);
  const event = {
    key: 'Escape', defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.stopped = true; },
  };
  registration[1](event);
  assert.equal(closed, 1);
  assert.equal(focused, 1);
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.stopped, true);
  registration[1]({ key: 'Enter' });
  assert.equal(closed, 1);
  for (const cleanup of cleanups) cleanup();
  assert.ok(removed.some(([name, callback, capture]) =>
    name === 'keydown' && callback === registration[1] && capture === true));
});

test('a dropdown in a native dialog stays inside its top layer', () => {
  const body = { name: 'body' };
  const dialog = { name: 'dialog' };
  const component = runInNewContext(outputText, {
    useRef: () => ({ current: null }),
    useState: () => [{ top: 100, left: 20, width: 240 }, () => {}],
    useEffect: () => {},
    useLayoutEffect: () => {},
    React: { createElement: (...args) => ({ args }) },
    createPortal: (element, parent) => ({ element, parent }),
    document: { body },
  });
  const props = { items: [], current: '', onPick: () => {}, onClose: () => {} };
  assert.equal(component({ ...props, anchor: { closest: () => dialog, getAttribute: () => null } }).parent, dialog);
  assert.equal(component({ ...props, anchor: { closest: () => null, getAttribute: () => null } }).parent, body);
});

function placement(rect, viewport, contentHeight) {
  let position = null;
  const menu = { style: {}, scrollHeight: contentHeight };
  const component = runInNewContext(outputText, {
    useRef: () => ({ current: menu }),
    useState: () => [null, update => { position = update(position); }],
    useLayoutEffect: effect => effect(), useEffect: () => {},
    ResizeObserver: class { observe() {} disconnect() {} },
    window: { innerWidth: viewport.width, innerHeight: viewport.height,
      visualViewport: { ...viewport, addEventListener() {}, removeEventListener() {} },
      addEventListener() {}, removeEventListener() {} },
    React: { createElement: (...args) => ({ args }) },
    createPortal: element => element,
    document: { body: {} },
  });
  component({ anchor: { getBoundingClientRect: () => rect, closest: () => null, getAttribute: () => null },
    items: [{ value: 'a', label: 'Long wrapped option' }], current: '', onPick() {}, onClose() {} });
  return position;
}

test('menu uses measured content and opens above a bottom-edge trigger without leaving the viewport', () => {
  const result = placement({ top: 550, bottom: 590, left: 300, width: 200 }, { width: 390, height: 640 }, 500);
  assert.equal(result.width, 240);
  assert.equal(result.left, 142);
  assert.equal(result.top, 226);
  assert.equal(result.maxHeight, 320);
});

test('small and zoomed visual viewports bound both menu width and scroll height', () => {
  const result = placement({ top: 120, bottom: 164, left: 80, width: 300 },
    { width: 220, height: 240, offsetLeft: 40, offsetTop: 100 }, 400);
  assert.equal(result.width, 204);
  assert.equal(result.left, 48);
  assert.equal(result.top, 168);
  assert.equal(result.maxHeight, 164);
});

test('short menus below the trigger size to actual wrapped content', () => {
  const result = placement({ top: 20, bottom: 54, left: 20, width: 260 }, { width: 1280, height: 900 }, 96);
  assert.equal(result.top, 58);
  assert.equal(result.width, 260);
  assert.equal(result.maxHeight, 320);
});
