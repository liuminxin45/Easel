import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/workbench/platform/modal-focus.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS}}).outputText;

function fixture() {
  const listeners = new Map(), frames = new Map();let sequence = 0, observer, nativeDialog = null;
  let body, document;
  class Element {
    constructor(classes = '', tagName = 'DIV') {this.classes = new Set(classes.split(' ').filter(Boolean));this.tagName = tagName;this.children = [];this.parentElement = null;this.attributes = new Map();this.tabIndex = tagName === 'BUTTON' ? 0 : -1;}
    append(node) {if (node.parentElement) node.remove();this.children.push(node);node.parentElement = this;return node;}
    remove() {if (this.parentElement) {const siblings = this.parentElement.children;siblings.splice(siblings.indexOf(this), 1);this.parentElement = null;}}
    get isConnected() {return this === body || !!this.parentElement?.isConnected;}
    get className() {return [...this.classes].join(' ');}
    set inert(value) {if (value) this.setAttribute('inert', '');else this.removeAttribute('inert');}
    get inert() {return this.hasAttribute('inert');}
    getClientRects() {return this.isConnected ? [{}] : [];}
    hasAttribute(name) {return this.attributes.has(name);}
    getAttribute(name) {return this.attributes.get(name) ?? null;}
    setAttribute(name, value) {this.attributes.set(name, String(value));}
    removeAttribute(name) {this.attributes.delete(name);}
    contains(node) {return node === this || this.children.some(child => child.contains(node));}
    matches(selector) {
      if (selector === ':disabled') return this.hasAttribute('disabled');
      if (selector === '[inert]') return this.inert;
      if (selector === 'dialog[open]') return this.tagName === 'DIALOG' && this.hasAttribute('open');
      if (selector === '.native-host .settings-panel[aria-modal="true"],.native-host .sidebar-panel[aria-modal="true"]') return this.getAttribute('aria-modal') === 'true' && (this.classes.has('settings-panel') || this.classes.has('sidebar-panel'));
      if (selector === '.model-dd[role="listbox"],[popover]') return this.classes.has('model-dd') && this.getAttribute('role') === 'listbox' || this.hasAttribute('popover');
      return selector.split(',').some(part => {
        const name = part.trim().match(/^\.([\w-]+)$/)?.[1];
        return name ? this.classes.has(name) : false;
      });
    }
    closest(selector) {for (let node = this;node;node = node.parentElement) if (node.matches(selector)) return node;return null;}
    querySelector(selector) {
      if (selector === ':scope > .modal, :scope > .drawer') return this.children.find(child => child.classes.has('modal') || child.classes.has('drawer')) || null;
      return this.querySelectorAll(selector)[0] || null;
    }
    querySelectorAll(selector) {
      const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
      if (selector === '*') return descendants;
      if (selector === 'a[href],button,input,select,textarea,summary,[contenteditable="true"],[tabindex]') return descendants.filter(node => node.tagName === 'BUTTON' || node.hasAttribute('tabindex'));
      if (selector === '[aria-controls][aria-expanded="true"]') return descendants.filter(node => node.hasAttribute('aria-controls') && node.getAttribute('aria-expanded') === 'true');
      return descendants.filter(node => node.matches(selector));
    }
    focus() {
      if (!this.isConnected || this.closest('[inert]')) return;
      document.activeElement = this;
      for (const fn of listeners.get('focusin') || []) fn({target: this});
    }
  }
  body = new Element('', 'BODY');
  document = {body, activeElement: body,
    querySelector: selector => selector === 'dialog[open]' ? nativeDialog : body.querySelector(selector),
    querySelectorAll: selector => {
      if (selector === '.native-host .overlay, .native-host .drawer-overlay') return body.querySelectorAll('*').filter(node => node.closest('.native-host') && (node.classes.has('overlay') || node.classes.has('drawer-overlay')));
      if (selector === '.native-host .settings-panel[aria-modal="true"],.native-host .sidebar-panel[aria-modal="true"]') return body.querySelectorAll('*').filter(node => node.matches(selector));
      if (selector === 'dialog[open]') return nativeDialog ? [nativeDialog] : [];
      return body.querySelectorAll(selector);
    },
    getElementById: id => body.querySelectorAll('*').find(node => node.getAttribute('id') === id),
    addEventListener: (name, fn) => {const items = listeners.get(name) || [];items.push(fn);listeners.set(name, items);},
    removeEventListener: (name, fn) => {listeners.set(name, (listeners.get(name) || []).filter(item => item !== fn));},
  };
  const exports = {};
  runInNewContext(compiled, {exports, document, HTMLElement: Element, Element,
    window: {matchMedia: () => ({matches: false, addEventListener() {}, removeEventListener() {}})},
    MutationObserver: class {constructor(callback) {this.callback = callback;observer = this;}observe() {}disconnect() {}},
    requestAnimationFrame: fn => {const id = ++sequence;frames.set(id, fn);return id;},
    cancelAnimationFrame: id => frames.delete(id),
    getComputedStyle: () => ({visibility: 'visible', zIndex: '1000'}),
  });
  const host = body.append(new Element('native-host'));
  const app = host.append(new Element('app-layout'));
  const settingOverlay = app.append(new Element('settings-overlay'));
  const settingPanel = settingOverlay.append(new Element('settings-panel'));settingPanel.setAttribute('aria-modal', 'true');
  const trigger = settingPanel.append(new Element('', 'BUTTON'));
  const other = settingPanel.append(new Element('', 'BUTTON'));
  const flush = () => {for (let n = 0;frames.size && n < 12;n++) {const work = [...frames.values()];frames.clear();for (const fn of work) fn();}assert.equal(frames.size, 0);};
  const changed = node => {observer.callback([{type: 'childList', target: settingOverlay, addedNodes: node.isConnected ? [node] : [], removedNodes: node.isConnected ? [] : [node]}]);flush();};
  const key = (target, key = 'Tab', shiftKey = false) => {target.focus();const event = {key, shiftKey, defaultPrevented: false, preventDefault() {this.defaultPrevented = true;}};for (const fn of listeners.get('keydown') || []) fn(event);return event;};
  return {Element, body, host, app, settingOverlay, settingPanel, trigger, other, document, flush, changed, key,
    start: () => exports.bindNativeModalFocus(), native: value => {nativeDialog = value;}, listeners};
}

test('a nested official drawer isolates the parent settings and restores its exact trigger', () => {
  const f = fixture(), stop = f.start();f.trigger.focus();f.flush();
  const overlay = f.settingOverlay.append(new f.Element('drawer-overlay'));
  const panel = overlay.append(new f.Element('drawer'));
  const first = panel.append(new f.Element('', 'BUTTON')), last = panel.append(new f.Element('', 'BUTTON'));
  f.changed(overlay);
  assert.equal(f.settingPanel.inert, true);assert.equal(f.document.activeElement, first);
  f.other.focus();assert.equal(f.document.activeElement, first);
  assert.equal(f.key(first, 'Tab', true).defaultPrevented, true);assert.equal(f.document.activeElement, last);
  assert.equal(f.key(last).defaultPrevented, true);assert.equal(f.document.activeElement, first);
  overlay.remove();f.changed(overlay);
  assert.equal(f.settingPanel.inert, false);assert.equal(f.document.activeElement, f.trigger);
  assert.equal(f.listeners.has('wheel'), false);assert.equal(f.listeners.has('touchmove'), false);
  stop();
});

test('a dropdown owned by the nested drawer retains its focus and keyboard ownership', () => {
  const f = fixture(), stop = f.start();f.trigger.focus();
  const overlay = f.settingOverlay.append(new f.Element('drawer-overlay')), panel = overlay.append(new f.Element('drawer'));
  const trigger = panel.append(new f.Element('', 'BUTTON'));trigger.setAttribute('aria-controls', 'choice');trigger.setAttribute('aria-expanded', 'true');
  const popup = f.body.append(new f.Element('model-dd'));popup.setAttribute('role', 'listbox');popup.setAttribute('id', 'choice');
  const option = popup.append(new f.Element('', 'BUTTON'));
  f.changed(overlay);f.changed(popup);option.focus();
  assert.equal(f.document.activeElement, option);assert.equal(f.key(option).defaultPrevented, false);
  assert.equal(f.settingPanel.inert, true);
  popup.remove();overlay.remove();f.changed(overlay);stop();
});

test('native dialog top-layer focus is left to the browser', () => {
  const f = fixture(), stop = f.start();f.trigger.focus();
  const dialog = f.settingOverlay.append(new f.Element('', 'DIALOG'));dialog.setAttribute('open', '');f.native(dialog);
  const inside = dialog.append(new f.Element('', 'BUTTON'));inside.focus();
  assert.equal(f.key(inside).defaultPrevented, false);assert.equal(f.document.activeElement, inside);
  stop();
});
