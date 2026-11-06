import {useId, type ReactNode, type Ref} from 'react';
import {createPortal} from 'react-dom';

export interface DrawerProps {
  open?: boolean;
  /** The original drawer heading's left column, including any metadata. */
  header?: ReactNode;
  title?: string;
  label?: string;
  onClose: () => void;
  children: ReactNode;
  panelRef?: Ref<HTMLDivElement>;
  container?: Element | DocumentFragment | null;
  overlayClassName?: string;
}

/** The original SkillDrawer shell, shared without an alternative dialog layout. */
export default function Drawer({open = true, header, title, label, onClose, children, panelRef, container,overlayClassName}: DrawerProps) {
  const headingId = useId();
  if (!open) return null;
  const content = (
    <div className={'drawer-overlay'+(overlayClassName?' '+overlayClassName:'')} onClick={onClose}>
      <div className="drawer" ref={panelRef} role="dialog" aria-modal="true"
        aria-label={label || title} aria-labelledby={label || title ? undefined : headingId}
        onClick={(event) => event.stopPropagation()}>
        <div className="drawer-header" id={headingId}>
          <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12}}>
            {header || <div><div className="skill-detail-title">{title}</div></div>}
            <button className="icon-btn" onClick={onClose} title="关闭" aria-label="关闭">×</button>
          </div>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
  return container ? createPortal(content, container) : content;
}
