export interface OrientedBox { cx: number; cy: number; width: number; height: number; angle: number }

export function orientedBox(value: unknown): OrientedBox | null {
  if (!Array.isArray(value) || value.length !== 8 || !value.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
  const p = value as number[];
  return { cx: p.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b) / 4, cy: p.filter((_, i) => i % 2 === 1).reduce((a, b) => a + b) / 4,
    width: Math.hypot(p[2]! - p[0]!, p[3]! - p[1]!), height: Math.hypot(p[6]! - p[0]!, p[7]! - p[1]!), angle: Math.atan2(p[3]! - p[1]!, p[2]! - p[0]!) };
}

export function orientedCorners(box: OrientedBox): number[] {
  const { cx, cy, width, height, angle } = box;
  const c = Math.cos(angle), s = Math.sin(angle);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].flatMap(([x, y]) => [cx + x! * width / 2 * c - y! * height / 2 * s, cy + x! * width / 2 * s + y! * height / 2 * c]);
}

/** Keep all four corners in the image while retaining a rectangle and its angle. */
export function fitOriented(points: number[], imageWidth: number, imageHeight: number): number[] {
  const box = orientedBox(points);
  if (!box || imageWidth <= 0 || imageHeight <= 0) return points;
  const c = Math.abs(Math.cos(box.angle)), s = Math.abs(Math.sin(box.angle));
  const extentX = (box.width * c + box.height * s) / 2;
  const extentY = (box.width * s + box.height * c) / 2;
  const scale = Math.min(1, imageWidth / (2 * extentX), imageHeight / (2 * extentY));
  const rx = extentX * scale, ry = extentY * scale;
  return orientedCorners({ ...box, width: box.width * scale, height: box.height * scale,
    cx: Math.min(imageWidth - rx, Math.max(rx, box.cx)),
    cy: Math.min(imageHeight - ry, Math.max(ry, box.cy)) });
}

/** Keep the opposite corner fixed while resizing in the box's rotated coordinate frame. */
export function resizeOriented(points: number[], corner: number, point: [number, number]): number[] {
  const box = orientedBox(points);
  if (!box) return points;
  const other = ((corner + 2) % 4) * 2;
  const ax = points[other]!, ay = points[other + 1]!;
  const dx = point[0] - ax, dy = point[1] - ay;
  const c = Math.cos(box.angle), s = Math.sin(box.angle);
  return orientedCorners({ cx: (point[0] + ax) / 2, cy: (point[1] + ay) / 2,
    width: Math.max(1, Math.abs(dx * c + dy * s)), height: Math.max(1, Math.abs(-dx * s + dy * c)), angle: box.angle });
}
