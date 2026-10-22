import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Open dialogs, innermost last: Escape closes only the top one. */
const open: symbol[] = [];

interface Props {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  className?: string;
}

/** A dialog. Escape and a click outside close it; keys typed inside stay inside.
 * A dialog opened from another stacks on top of it. */
export function Modal({ title, onClose, children, footer, width = 460, className }: Props) {
  const id = useRef(Symbol(title));
  const dialog = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(document.activeElement as HTMLElement | null);
  useEffect(() => {
    const mine = id.current;
    const previousFocus = restoreFocus.current;
    open.push(mine);
    if (!dialog.current?.contains(document.activeElement)) {
      const first = dialog.current?.querySelector<HTMLElement>('.modal-body input:not(:disabled), .modal-body button:not(:disabled)')
        ?? dialog.current?.querySelector<HTMLElement>('.modal-head button');
      (first ?? dialog.current)?.focus();
    }
    return () => {
      open.splice(open.indexOf(mine), 1);
      if (previousFocus?.isConnected && !dialog.current?.contains(previousFocus)) previousFocus.focus();
    };
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (open[open.length - 1] !== id.current) return;
      if (event.key === "Escape" && open[open.length - 1] === id.current) {
        event.stopImmediatePropagation();
        onClose();
      }
      if (event.key === "Tab") {
        const focusable = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]') ?? [])
          .filter((element) => element.getClientRects().length > 0);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first) { event.preventDefault(); dialog.current?.focus(); }
        else if (event.shiftKey && (document.activeElement === first || !dialog.current?.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.current?.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialog} className={`modal${className ? ` ${className}` : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} style={{ width }}>
        <div className="modal-head">
          <span>{title}</span>
          <button onClick={onClose} title="Close (Esc)" aria-label="Close dialog">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
