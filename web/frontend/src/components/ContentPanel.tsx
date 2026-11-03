import type { HTMLAttributes, ReactNode } from 'react';

interface ContentPanelProps {
  className?: string;
  header: ReactNode;
  children: ReactNode;
  label: string;
  bodyProps?: HTMLAttributes<HTMLDivElement> & {'data-native-scroll-region'?: string};
}

/** Shared bounded, keyboard-scrollable content panel. */
export default function ContentPanel({ className = '', header, children, label, bodyProps }: ContentPanelProps) {
  const {className: bodyClassName, ...bodyAttributes}=bodyProps??{};
  return (
    <section className={`card content-panel ${className}`}>
      {header}
      <div className={`content-panel-body${bodyClassName?' '+bodyClassName:''}`} role="region" aria-label={label} tabIndex={0} {...bodyAttributes}>{children}</div>
    </section>
  );
}
