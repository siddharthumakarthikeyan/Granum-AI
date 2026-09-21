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
  useEffect(() => {
    const mine = id.current;
    open.push(mine);
    return () => {
      open.splice(open.indexOf(mine), 1);
    };
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && open[open.length - 1] === id.current) {
        event.stopImmediatePropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${className ? ` ${className}` : ""}`} role="dialog" aria-modal="true" aria-label={title} style={{ width }}>
        <div className="modal-head">
          <span>{title}</span>
          <button onClick={onClose} title="Close (Esc)">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
