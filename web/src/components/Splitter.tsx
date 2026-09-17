import { useCallback, useEffect, useRef } from "react";

interface Props {
  direction: "vertical" | "horizontal";
  onResize: (delta: number) => void;
}

/** A draggable panel boundary. Vertical splitters move horizontally. */
export function Splitter({ direction, onResize }: Props) {
  const dragging = useRef(false);
  const last = useRef(0);

  const onDown = useCallback(
    (event: React.MouseEvent) => {
      dragging.current = true;
      last.current = direction === "vertical" ? event.clientX : event.clientY;
      event.preventDefault();
    },
    [direction],
  );

  useEffect(() => {
    const onMove = (event: MouseEvent) => {
      if (!dragging.current) return;
      const position = direction === "vertical" ? event.clientX : event.clientY;
      onResize(position - last.current);
      last.current = position;
    };
    const onUp = () => {
      dragging.current = false;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [direction, onResize]);

  return (
    <div
      className={direction === "vertical" ? "splitter-v" : "splitter-h"}
      onMouseDown={onDown}
      role="separator"
      aria-orientation={direction}
    />
  );
}
