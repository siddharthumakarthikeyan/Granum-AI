/** Boxes drawn over an image, in image pixel coordinates.
 *
 * The SVG shares the image's coordinate system through its viewBox, so the same markup
 * works on a 120px thumbnail and a full-size inspector, and zooming is a viewBox change.
 */

import type { DrawnBox, InstanceRef } from "./model";

interface Props {
  boxes: DrawnBox[];
  /** Image size in pixels. */
  width: number;
  height: number;
  annotate: "all" | "selected" | "none";
  focused?: InstanceRef | null;
  hovered?: InstanceRef | null;
  /** Stroke width in screen pixels. */
  stroke?: number;
  /** Label font size in image pixels. */
  fontSize?: number;
  onBoxClick?: (box: DrawnBox, event: React.MouseEvent) => void;
  onBoxHover?: (box: DrawnBox | null) => void;
}

const same = (a: InstanceRef | null | undefined, b: InstanceRef) =>
  Boolean(a && a.column === b.column && a.index === b.index);

export function BoxShapes({ boxes, annotate, focused, hovered, stroke = 1.5, fontSize = 12, onBoxClick, onBoxHover }: Omit<Props, "width" | "height">) {
  // Focused last, so it paints on top of anything it overlaps.
  const ordered = [...boxes].sort((a, b) => Number(same(focused, a)) - Number(same(focused, b)));
  return (
    <>
      {ordered.map((box) => {
        const isFocused = same(focused, box);
        const isHovered = same(hovered, box);
        const showText = annotate === "all" || (annotate === "selected" && (isFocused || isHovered));
        const color = isFocused ? "var(--accent)" : box.color;
        return (
          <g
            key={`${box.column}:${box.index}`}
            className={`box role-${box.role}${isFocused ? " focused" : ""}`}
            opacity={box.opacity}
            onClick={onBoxClick ? (e) => onBoxClick(box, e) : undefined}
            onMouseEnter={onBoxHover ? () => onBoxHover(box) : undefined}
            onMouseLeave={onBoxHover ? () => onBoxHover(null) : undefined}
          >
            <rect
              x={box.x0}
              y={box.y0}
              width={Math.max(0, box.x1 - box.x0)}
              height={Math.max(0, box.y1 - box.y0)}
              fill={isHovered || isFocused ? "rgba(240,138,36,.08)" : "transparent"}
              stroke={color}
              strokeWidth={isFocused || isHovered ? stroke * 1.8 : stroke}
              strokeDasharray={box.dash ?? undefined}
              vectorEffect="non-scaling-stroke"
            />
            {showText && (
              <text
                x={box.x0 + 1}
                y={Math.max(box.y0 - fontSize * 0.25, fontSize)}
                fontSize={fontSize}
                fill={color}
                className="box-text"
              >
                {box.text}
              </text>
            )}
          </g>
        );
      })}
    </>
  );
}

/** Thumbnail overlay: fits the image with `contain`, like the <img> beneath it. */
export function BoxOverlay(props: Props) {
  const { width, height } = props;
  if (!width || !height) return null;
  return (
    <svg
      className="box-overlay"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="xMidYMid meet"
      pointerEvents="none"
    >
      <BoxShapes {...props} fontSize={props.fontSize ?? Math.max(width, height) * 0.04} />
    </svg>
  );
}
