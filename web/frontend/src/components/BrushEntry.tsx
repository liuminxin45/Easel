import { useEffect, useMemo, useRef, useState } from 'react';
import { CAPABILITY_MENU } from '../lib/capabilityMenu';
import type { CapabilityItem } from '../lib/capabilityMenu';

const DOT: Record<string, string> = { done: 's-done', ready: 's-ready', need: 's-need', incoming: 's-incoming' };

/** 笔入口：点开「能做的都在这」→ 选一项自动填进输入框。纯前端，选中即预填，不自动发送。 */
export interface BrushChoice {id:string;label:string;description?:string;disabled?:boolean;group?:string}
export default function BrushEntry({ onPick, items, onSelect, registerLayer, disabled=false }: { onPick: (text: string) => void;
  items?:BrushChoice[];onSelect?:(id:string)=>void;registerLayer?:(close:()=>void)=>(()=>void)|undefined;disabled?:boolean }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState(0);
  const [q, setQ] = useState('');
  const wrapRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const menu = useMemo(()=>items ? {tabs:[{id:'available',label:'技能与能力',groups:Array.from(new Set(items.map(item=>item.group||'已接入能力'))).map(label=>({label,items:items.filter(item=>(item.group||'已接入能力')===label).map(item=>({id:item.id,label:item.label,desc:item.description,skill:item.id,status:item.disabled?'need':'ready'}))}))}]} : CAPABILITY_MENU,[items]);

  useEffect(()=>{if(!open)return;const close=()=>{setOpen(false);wrapRef.current?.querySelector<HTMLButtonElement>('.brush-btn')?.focus()};const release=registerLayer?.(close);const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();close()}};document.addEventListener('keydown',key);return()=>{release?.();document.removeEventListener('keydown',key)}},[open,registerLayer]);
  useEffect(()=>{if(disabled)setOpen(false)},[disabled]);

  useEffect(() => { if (open) searchRef.current?.focus(); }, [open]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const all = useMemo(
    () => menu.tabs.flatMap((t) => t.groups.flatMap((g) => g.items)),
    [menu],
  );
  const pipeline = useMemo(() => all.find((x) => x.status === 'incoming'), [all]);

  const ql = q.trim().toLowerCase();
  const hit = (it: CapabilityItem) => !ql || `${it.label}${it.desc || ''}${it.skill || ''}`.toLowerCase().includes(ql);

  const pick = (it: CapabilityItem, pipe?: boolean) => {
    if(items){if(disabled||items.find(item=>item.id===it.id)?.disabled)return;onSelect?.(it.id!);setOpen(false);return;}
    onPick(pipe ? '用「视频产线」做一支整片：' : `帮我做「${it.label}」`);
    setOpen(false);
  };

  return (
    <div className={`brush-entry${open ? ' open' : ''}`} ref={wrapRef}>
      <button type="button" className="brush-btn" onClick={() => setOpen((v) => !v)}
        disabled={disabled} aria-expanded={open} aria-label="看看能做什么" title="看看能做什么">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <defs>
            <linearGradient id="brushHandleGrad" x1="12" y1="1.6" x2="12" y2="11.6" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#8adfce" /><stop offset="1" stopColor="#45b0b4" />
            </linearGradient>
            <linearGradient id="brushTipGrad" x1="12" y1="13.2" x2="12" y2="22.6" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="#2f6fae" /><stop offset="1" stopColor="#222e83" />
            </linearGradient>
          </defs>
          <g transform="rotate(45 12 12)">
            <rect x="11.15" y="1.6" width="1.7" height="10" rx=".85" fill="url(#brushHandleGrad)" />
            <rect x="10.6" y="11.5" width="2.8" height="1.75" rx=".6" fill="#b9e3d9" stroke="#7fb3aa" strokeWidth=".3" />
            <path d="M10.7 13.2 C9.95 16.6 10.2 19.9 11.95 22.6 C13.7 19.9 13.95 16.6 13.2 13.2 Z" fill="url(#brushTipGrad)" />
            <path d="M11.95 13.6 L11.95 21.2" stroke="#1d2c6f" strokeWidth=".4" strokeLinecap="round" opacity=".38" />
          </g>
        </svg>
        <span className="brush-mark" aria-hidden="true" />
        <span className="brush-tip">看看能做什么</span>
      </button>

      {open && (
        <div className="brush-panel" role="dialog" aria-label="能做的都在这">
          <div className="brush-panel-head">
            <div className="brush-panel-headline">
              <div className="brush-panel-title">能做的都在这</div>
              <div className="brush-panel-sub">{items?'选一个 → 带入输入框，发送后执行':'选一个 → 自动填进输入框；「管线」件走整片产线'}</div>
            </div>
            <input ref={searchRef} className="brush-search" placeholder="搜索…" value={q}
              onChange={(e) => setQ(e.target.value)} />
            <button type="button" className="brush-close" onClick={() => setOpen(false)} aria-label="关闭">×</button>
          </div>
          <div className="brush-tabs">
            {menu.tabs.map((t, i) => (
              <button type="button" key={t.id} className={`brush-tab${i === tab ? ' on' : ''}`}
                onClick={() => setTab(i)}>{t.label}</button>
            ))}
          </div>
          <div className="brush-body">
            {pipeline && hit(pipeline) && (
              <div className="brush-grp">
                <div className="brush-grp-name">整片级 · 走独立管线</div>
                <button type="button" className="brush-item brush-item-pipe" onClick={() => pick(pipeline, true)}>
                  <span className={`brush-dot ${DOT[pipeline.status || 'ready'] || 's-ready'}`} />
                  <span className="brush-il">{pipeline.label}</span>
                  <span className="brush-chip-pipe">管线</span>
                  <span className="brush-idesc">{pipeline.desc}</span>
                  <span className="brush-iadd">＋</span>
                </button>
              </div>
            )}
            {(menu.tabs[tab]||menu.tabs[0])?.groups.map((g) => {
              const groupItems = g.items.filter((it) => it.status !== 'incoming' && hit(it));
              if (!groupItems.length) return null;
              return (
                <div key={g.label} className="brush-grp">
                  <div className="brush-grp-name">{g.label} · {groupItems.length}</div>
                  {groupItems.map((it) => (
                    <button type="button" key={it.skill || it.label} className="brush-item" disabled={disabled||!!items?.find(item=>item.id===it.id)?.disabled} onClick={() => pick(it)}>
                      <span className={`brush-dot ${DOT[it.status || 'ready'] || 's-ready'}`} />
                      <span className="brush-il">{it.label}</span>
                      <span className="brush-idesc">{it.desc}</span>
                      <span className="brush-iadd">＋</span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
