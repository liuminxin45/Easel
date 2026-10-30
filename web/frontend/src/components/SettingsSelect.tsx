import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './SettingsSelect.css';

export default function SettingsSelect({ value, options, disabled = false, label, title, className = '', onChange }: {
  value: string;
  options: { value: string; label: string }[];
  disabled?: boolean;
  label: string;
  title?: string;
  className?: string;
  onChange: (value: string) => void;
}) {
  const anchor = useRef<HTMLButtonElement | null>(null);
  const listId = useId();
  const [open, setOpen] = useState(false);
  const selected = options.find(option => option.value === value);
  const close = () => {
    setOpen(false);
    anchor.current?.focus();
  };

  return (
    <span className={`settings-select-wrap ${className}`}>
      <button type="button" className="proto-trigger settings-select" ref={anchor}
        title={title} aria-label={label} aria-haspopup="listbox" aria-controls={open && !disabled ? listId : undefined} aria-expanded={open && !disabled} disabled={disabled}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
          }
        }}>
        <span className="proto-label">{selected?.label || value}</span>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && !disabled && (
        <OptionsDropdown id={listId} label={label} anchor={anchor.current} items={options} current={value}
          focusOptions onPick={(next) => { onChange(next); close(); }} onClose={close} />
      )}
    </span>
  );
}

export function OptionsDropdown({ id, label, anchor, items, current, emptyHint, onPull, pulling, focusOptions = false, onPick, onClose }: {
  id?: string;
  label?: string;
  anchor: HTMLElement | null;
  items: { value: string; label: string }[];
  current: string;
  emptyHint?: string;
  onPull?: () => void;
  pulling?: boolean;
  focusOptions?: boolean;
  onPick: (value: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);
  const positioned = pos !== null;
  useLayoutEffect(() => {
    if (!anchor) return;
    const measure = () => {
      const menu = ref.current;
      if (!menu) return;
      const rect = anchor.getBoundingClientRect();
      const viewport = window.visualViewport;
      const edgeLeft = (viewport?.offsetLeft || 0) + 8;
      const edgeTop = (viewport?.offsetTop || 0) + 8;
      const edgeRight = edgeLeft + (viewport?.width || window.innerWidth) - 16;
      const edgeBottom = edgeTop + (viewport?.height || window.innerHeight) - 16;
      const width = Math.max(1, Math.min(Math.max(rect.width, 240), 380, edgeRight - edgeLeft));
      // Measure wrapped labels at their final width, including touch-sized rows.
      menu.style.width = `${width}px`;
      const desired = Math.min(menu.scrollHeight + 2, 320);
      const below = Math.max(0, edgeBottom - rect.bottom - 4);
      const above = Math.max(0, rect.top - edgeTop - 4);
      const openUp = below < desired && above > below;
      const maxHeight = Math.max(1, Math.min(320, openUp ? above : below, edgeBottom - edgeTop));
      const height = Math.min(desired, maxHeight);
      const next = {
        top: Math.max(edgeTop, Math.min(openUp ? rect.top - height - 4 : rect.bottom + 4, edgeBottom - height)),
        left: Math.max(edgeLeft, Math.min(rect.left, edgeRight - width)),
        width, maxHeight,
      };
      setPos(previous => previous && Object.keys(next).every(key => previous[key as keyof typeof next] === next[key as keyof typeof next]) ? previous : next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(anchor);
    observer.observe(ref.current!);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    window.visualViewport?.addEventListener('resize', measure);
    window.visualViewport?.addEventListener('scroll', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
      window.visualViewport?.removeEventListener('resize', measure);
      window.visualViewport?.removeEventListener('scroll', measure);
    };
  }, [anchor, items, emptyHint, pulling]);

  useEffect(() => {
    const onDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)
          && !(anchor && anchor.contains(event.target as Node))) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        anchor?.focus();
      } else if (event.key === 'Tab') {
        // Restore the trigger before the browser advances to its next tab stop.
        onClose();
        anchor?.focus();
      }
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [anchor, onClose]);

  useEffect(() => {
    if (!positioned || !focusOptions) return;
    const selected = ref.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    const first = ref.current?.querySelector<HTMLElement>('[role="option"]');
    (selected || first)?.focus();
  }, [positioned, focusOptions]);

  return createPortal(
    <div ref={ref} id={id} className="model-dd" role="listbox" aria-label={label || anchor?.getAttribute('aria-label') || '选择选项'} onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
        if (!keys.includes(event.key)) return;
        event.preventDefault();
        const options = Array.from(ref.current?.querySelectorAll<HTMLElement>('[role="option"]') || []);
        if (!options.length) return;
        const currentIndex = options.indexOf(document.activeElement as HTMLElement);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
          : (currentIndex + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
        options[next].focus();
        options[next].scrollIntoView({ block: 'nearest' });
      }}
      style={{ position: 'fixed', top: pos?.top ?? 0, left: pos?.left ?? 0, width: pos?.width, maxHeight: pos?.maxHeight, visibility: pos ? 'visible' : 'hidden' }}>
      {items.length === 0 && (
        <div className="dd-empty">
          <span>{emptyHint || '该端点没有返回模型'}</span>
          {onPull && (
            <button type="button" className="dd-pull" onClick={onPull} disabled={pulling}>
              {pulling ? <><span className="spin" />拉取中</> : '立即拉取'}
            </button>
          )}
        </div>
      )}
      {items.map((item) => (
        <div key={item.value} role="option" aria-selected={item.value === current} tabIndex={-1}
          className={`dd-item${item.value === current ? ' active' : ''}`}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onPick(item.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              onPick(item.value);
            }
          }}>
          <span>{item.label}</span>
          {item.value === current && <small>当前</small>}
        </div>
      ))}
    </div>,
    anchor?.closest('dialog[open]') || document.body,
  );
}
