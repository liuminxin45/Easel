(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('neo-review-config').textContent);
  const localKey = `neo-review:${config.article_id}:${config.version}:${config.content_hash}`;
  const online = location.protocol === 'http:' || location.protocol === 'https:';
  const roots = {title: document.querySelector('[data-review-scope="title"]'), article: document.getElementById('article')};
  const button = (text, handler, className = '') => {
    const item = document.createElement('button'); item.type = 'button'; item.textContent = text;
    item.className = className; item.addEventListener('click', handler); return item;
  };
  const panel = document.createElement('aside'); panel.id = 'neo-review-panel'; panel.hidden = true; panel.setAttribute('aria-label', '文章批注');
  const header = document.createElement('div'); header.className = 'neo-review-header';
  const heading = document.createElement('strong'); heading.textContent = '文章批注'; header.append(heading);
  header.append(button('关闭', () => setOpen(false)));
  const status = document.createElement('div'); status.id = 'neo-review-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const list = document.createElement('div'); list.id = 'neo-review-list'; panel.append(header, status, list);
  const toggle = button('批注 · 0', () => setOpen(panel.hidden)); toggle.id = 'neo-review-toggle';
  const selectionAction = button('批注选中文字', addNote); selectionAction.id = 'neo-review-selection'; selectionAction.disabled = true;
  selectionAction.title = '先选中标题或正文，再点这里添加批注';
  const bubble = button('添加批注', addNote); bubble.id = 'neo-review-bubble'; bubble.hidden = true;
  for (const control of [bubble, selectionAction]) {
    control.addEventListener('pointerdown', event => event.preventDefault());
    control.addEventListener('mousedown', event => event.preventDefault());
  }
  document.body.append(toggle, selectionAction, panel, bubble);
  let state = null, notes = [], selected = null, active = null, dirty = false, saving = false, blocked = false, ready = false, conflictSaved = false, timer;
  const message = value => { status.textContent = value; };
  const signature = value => JSON.stringify(value);
  function setOpen(value) { panel.hidden = !value; document.body.classList.toggle('neo-review-open', value); }
  function mirror() {
    if (conflictSaved) return;
    try { localStorage.setItem(localKey, JSON.stringify({notes, dirty, base_seq: state?.edit_seq, generation: state?.generation})); }
    catch { message('浏览器暂存不可用，请保持页面打开，等待项目自动保存完成。'); }
  }
  function readMirror() { try { return JSON.parse(localStorage.getItem(localKey) || 'null'); } catch { return null; } }
  function getRange(anchor) {
    const root = roots[anchor.scope]; if (!root) return null;
    const text = root.textContent;
    let {start, end, quote} = anchor;
    if (text.slice(start, end) !== quote) {
      const at = text.indexOf(quote);
      if (at < 0 || text.indexOf(quote, at + 1) >= 0) return null;
      start = at; end = at + quote.length;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); let node, offset = 0, begin = null, finish = null;
    while ((node = walker.nextNode())) {
      const length = node.nodeValue.length;
      if (!begin && start < offset + length) begin = [node, start - offset];
      if (end <= offset + length && end > offset) { finish = [node, end - offset]; break; }
      offset += length;
    }
    if (!begin || !finish) return null;
    const range = document.createRange(); range.setStart(...begin); range.setEnd(...finish); return range;
  }
  function highlights() {
    if (!window.Highlight || !window.CSS?.highlights) return;
    const ranges = notes.map(note => getRange(note.anchor)).filter(Boolean);
    CSS.highlights.set('neo-review-notes', new Highlight(...ranges));
    const range = notes.find(note => note.id === active);
    const selectedRange = range && getRange(range.anchor);
    CSS.highlights.set('neo-review-active', new Highlight(...(selectedRange ? [selectedRange] : [])));
  }
  function locate(note) {
    active = note.id; setOpen(true); highlights();
    const range = getRange(note.anchor);
    if (!range) { message('这条批注的原文位置已变化，请核对引用内容。'); return; }
    const rect = range.getBoundingClientRect();
    window.scrollTo({top: Math.max(0, scrollY + rect.top - 90), behavior: 'smooth'});
    for (const card of list.children) card.classList.toggle('active', card.dataset.noteId === active);
  }
  function render(focusId) {
    list.replaceChildren(); toggle.textContent = `批注 · ${notes.length}`;
    if (!notes.length) { const empty = document.createElement('p'); empty.className = 'neo-review-empty'; empty.textContent = '选中标题或正文，点浮动的“添加批注”，或右下角“批注选中文字”。新增、编辑和删除都会自动保存。'; list.append(empty); }
    for (const note of notes) {
      const card = document.createElement('section'); card.className = 'neo-review-note'; card.dataset.noteId = note.id;
      const quote = document.createElement('blockquote'); quote.className = 'neo-review-quote'; quote.textContent = note.anchor.quote;
      const label = document.createElement('label'); label.textContent = '你的修改意见'; label.htmlFor = 'note-' + note.id;
      const input = document.createElement('textarea'); input.id = label.htmlFor; input.value = note.comment; input.placeholder = '写下你的意见，自动保存'; input.disabled = blocked;
      input.addEventListener('input', () => { note.comment = input.value; note.updated_at = new Date().toISOString(); change(); });
      input.addEventListener('focus', () => { active = note.id; highlights(); });
      const actions = document.createElement('div'); actions.className = 'neo-review-actions';
      const remove = button('删除', () => { if (blocked) return; notes = notes.filter(value => value.id !== note.id); if (active === note.id) active = null; change(); render(); }, 'neo-review-delete'); remove.disabled = blocked;
      actions.append(button('定位原文', () => locate(note)), remove); card.append(quote, label, input, actions); list.append(card);
    }
    highlights(); if (focusId) document.getElementById('note-' + focusId)?.focus();
  }
  function captureSelection() {
    if (!ready || blocked) { bubble.hidden = true; selectionAction.disabled = true; return; }
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) { bubble.hidden = true; selectionAction.disabled = true; selected = null; return; }
    const range = selection.getRangeAt(0);
    const scope = Object.keys(roots).find(name => roots[name]?.contains(range.startContainer) && roots[name]?.contains(range.endContainer));
    if (!scope || !range.toString().trim()) { bubble.hidden = true; selectionAction.disabled = true; selected = null; return; }
    const prefixRange = document.createRange(); prefixRange.selectNodeContents(roots[scope]); prefixRange.setEnd(range.startContainer, range.startOffset);
    const start = prefixRange.toString().length, quote = range.toString(), text = roots[scope].textContent;
    selected = {scope, start, end: start + quote.length, quote, prefix: text.slice(Math.max(0, start - 32), start), suffix: text.slice(start + quote.length, start + quote.length + 32)};
    selectionAction.disabled = false;
    selectionAction.title = `批注：${quote.slice(0, 80)}`;
    const rect = range.getBoundingClientRect(); bubble.hidden = false;
    bubble.style.left = `${Math.max(8, Math.min(innerWidth - 112, rect.left))}px`;
    bubble.style.top = `${Math.max(8, Math.min(innerHeight - 44, rect.bottom + 7))}px`;
  }
  function addNote() {
    if (!selected || blocked) return;
    const note = {id: crypto.randomUUID ? crypto.randomUUID() : `n${Date.now()}-${Math.random().toString(16).slice(2)}`, anchor: selected, comment: '', created_at: new Date().toISOString(), updated_at: new Date().toISOString()};
    notes.push(note); active = note.id; selected = null; bubble.hidden = true; selectionAction.disabled = true;
    window.getSelection()?.removeAllRanges(); setOpen(true); change(); render(note.id);
  }
  function change() {
    dirty = true; mirror();
    if (!online) { message('已自动暂存在当前浏览器；要同步项目，请使用本地审阅链接。'); return; }
    message('正在自动保存…'); clearTimeout(timer); timer = setTimeout(save, 350);
  }
  function payload() { return {generation: state.generation, version: state.version, content_hash: state.content_hash, edit_seq: state.edit_seq, annotations: JSON.parse(JSON.stringify(notes))}; }
  async function save() {
    if (!online || !state || !dirty || saving || blocked) return;
    saving = true; const request = payload(), sent = signature(request.annotations);
    try {
      const result = await fetch('/api/annotations', {method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Neo-Review': '1'}, body: JSON.stringify(request), keepalive: true});
      if (result.status === 409) {
        const conflict = await result.json(); blocked = true;
        if (conflict.preserved) { conflictSaved = true; try { localStorage.removeItem(localKey); } catch {} }
        message(conflictSaved ? '批注或文章已在其他页面更新。本页修改已留档到项目的未合并意见，请重新打开审阅页核对。' : '批注版本冲突，当前输入仍有浏览器暂存，请保持页面打开。');
        render(); return;
      }
      if (!result.ok) throw new Error('save');
      state = await result.json(); dirty = signature(notes) !== sent; mirror();
      message(dirty ? '正在自动保存…' : '已自动保存到项目');
    } catch { message('尚未保存到项目，意见已暂存；连接恢复后自动重试。'); }
    finally { saving = false; if (dirty && !blocked) timer = setTimeout(save, 1500); }
  }
  async function start() {
    const cached = readMirror();
    if (!online) { notes = Array.isArray(cached?.notes) ? cached.notes : []; ready = true; render(); message('文件预览：批注会自动暂存在当前浏览器；项目同步请使用本地审阅链接。'); return; }
    try {
      const result = await fetch('/api/annotations', {cache: 'no-store'}); if (!result.ok) throw new Error('load');
      state = await result.json();
      if (state.version !== config.version || state.content_hash !== config.content_hash) { blocked = true; ready = true; render(); message('这份文章已不是当前审阅版，请重新打开审阅链接。'); return; }
      notes = state.annotations;
      if (cached?.dirty && cached.generation === state.generation && signature(cached.notes) !== signature(notes)) {
        if (cached.base_seq === state.edit_seq) { notes = cached.notes; dirty = true; }
        else { notes = cached.notes; dirty = true; blocked = true; }
      }
      ready = true; render();
      message(blocked ? '检测到另一页面的更新；本页暂存尚未同步，请重新打开审阅页核对。' : '已自动保存到项目');
      if (notes.length || blocked) setOpen(true); if (dirty && !blocked) save();
    } catch { message('审阅服务暂未连接，请重新打开本地审阅链接。'); }
  }
  let selectionFrame;
  function scheduleSelection() { cancelAnimationFrame(selectionFrame); selectionFrame = requestAnimationFrame(captureSelection); }
  document.addEventListener('mouseup', scheduleSelection);
  document.addEventListener('pointerup', scheduleSelection);
  document.addEventListener('touchend', scheduleSelection, {passive:true});
  document.addEventListener('keyup', event => { if (event.key === 'Escape') bubble.hidden = true; else captureSelection(); });
  document.addEventListener('selectionchange', scheduleSelection);
  window.addEventListener('pagehide', () => { mirror(); if (dirty && state && !saving && !blocked && online) { fetch('/api/annotations', {method:'PUT', headers:{'Content-Type':'application/json','X-Neo-Review':'1'}, body:JSON.stringify(payload()), keepalive:true}).catch(() => {}); } });
  window.addEventListener('online', save);
  setInterval(async () => {
    if (!online || !state || dirty || saving || blocked) return;
    try {
      const result = await fetch('/api/annotations', {cache:'no-store'}); if (!result.ok) return;
      const latest = await result.json();
      if (latest.generation !== state.generation || (latest.interface_revision || 0) !== (state.interface_revision || 0)) { location.reload(); return; }
      if (latest.edit_seq > state.edit_seq && !panel.contains(document.activeElement)) {
        state = latest; notes = latest.annotations; mirror(); render(); message('已同步项目中的最新批注');
      }
    } catch {}
  }, 4000);
  start();
})();
