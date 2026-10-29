/** COCO masks use column-major pixels and alternating background/foreground runs. */
export interface RleMask { size: [number, number]; counts: number[] | string }
export const MAX_MASK_PIXELS = 25_000_000;

export function maskSize(width: number, height: number): number {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || width * height > MAX_MASK_PIXELS) {
    throw new Error("Mask editing supports images up to 25 million pixels.");
  }
  return width * height;
}

/** COCO's compressed counts are signed, differential, five-bit integers. */
export function rleCounts(value: unknown): { width: number; height: number; counts: number[] } {
  const rle = value as Partial<RleMask> | null;
  if (!rle || !Array.isArray(rle.size) || rle.size.length !== 2) throw new Error("Invalid mask dimensions.");
  const [height, width] = rle.size;
  const total = maskSize(width, height);
  let counts: number[];
  if (typeof rle.counts === "string") {
    counts = [];
    let at = 0;
    while (at < rle.counts.length) {
      let value = 0, bits = 0, part: number;
      do {
        part = rle.counts.charCodeAt(at++) - 48;
        if (!Number.isFinite(part) || part < 0 || part > 63 || bits > 30) throw new Error("Invalid compressed mask.");
        value += (part & 31) * 2 ** bits;
        bits += 5;
      } while (part & 32);
      if (part & 16) value -= 2 ** bits;
      if (counts.length > 2) value += counts[counts.length - 2]!;
      counts.push(value);
      if (counts.length > total + 1) throw new Error("Too many mask runs.");
    }
  } else if (Array.isArray(rle.counts)) counts = rle.counts;
  else throw new Error("Invalid mask counts.");
  let sum = 0;
  for (const n of counts) {
    if (!Number.isSafeInteger(n) || n < 0 || (sum += n) > total) throw new Error("Invalid mask run length.");
  }
  if (sum !== total) throw new Error("Mask runs do not cover the image.");
  return { width, height, counts };
}

export function decodeMask(value: unknown, width?: number, height?: number): Uint8Array {
  const rle = rleCounts(value);
  if ((width !== undefined && width !== rle.width) || (height !== undefined && height !== rle.height)) throw new Error("Mask and image dimensions differ.");
  const pixels = new Uint8Array(rle.width * rle.height);
  let at = 0;
  rle.counts.forEach((length, i) => { if (i % 2) pixels.fill(1, at, at + length); at += length; });
  return pixels;
}

export function encodeMask(pixels: Uint8Array, width: number, height: number): RleMask {
  if (pixels.length !== maskSize(width, height)) throw new Error("Mask and image dimensions differ.");
  const counts: number[] = [];
  let last = 0, length = 0;
  for (const v of pixels) {
    const bit = v ? 1 : 0;
    if (bit !== last) { counts.push(length); length = 0; last = bit; }
    length++;
  }
  counts.push(length);
  return { size: [height, width], counts };
}

export function maskBounds(pixels: Uint8Array, width: number, height: number): [number, number, number, number] {
  let x0 = width, y0 = height, x1 = 0, y1 = 0;
  for (let x = 0; x < width; x++) for (let y = 0; y < height; y++) if (pixels[x * height + y]) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x + 1); y0 = Math.min(y0, y); y1 = Math.max(y1, y + 1);
  }
  return x1 ? [x0, y0, x1, y1] : [0, 0, 0, 0];
}

/** Paint a continuous stroke, including the gaps between pointer events. Mutates pixels only. */
export function paintMask(pixels: Uint8Array, width: number, height: number, from: [number, number], to: [number, number], radius: number, value: 0 | 1): void {
  if (pixels.length !== maskSize(width, height) || !Number.isFinite(radius) || radius <= 0 || ![...from, ...to].every(Number.isFinite)) throw new Error("Invalid brush stroke.");
  const [dx, dy] = [to[0] - from[0], to[1] - from[1]];
  const length = dx * dx + dy * dy;
  for (let x = Math.max(0, Math.floor(Math.min(from[0], to[0]) - radius)); x < Math.min(width, Math.ceil(Math.max(from[0], to[0]) + radius)); x++) {
    for (let y = Math.max(0, Math.floor(Math.min(from[1], to[1]) - radius)); y < Math.min(height, Math.ceil(Math.max(from[1], to[1]) + radius)); y++) {
      const t = length ? Math.max(0, Math.min(1, ((x + 0.5 - from[0]) * dx + (y + 0.5 - from[1]) * dy) / length)) : 0;
      if ((x + 0.5 - from[0] - t * dx) ** 2 + (y + 0.5 - from[1] - t * dy) ** 2 <= radius * radius) pixels[x * height + y] = value;
    }
  }
}

export function polygonsToMask(polygons: number[][], width: number, height: number): Uint8Array {
  const pixels = new Uint8Array(maskSize(width, height));
  // Pixel-centre scan conversion avoids Canvas anti-aliasing and works in workers/tests.
  for (const p of polygons) {
    if (p.length < 6 || p.length % 2 || !p.every(Number.isFinite)) throw new Error("Invalid mask polygon.");
    const ys = p.filter((_, i) => i % 2 === 1);
    for (let y = Math.max(0, Math.floor(Math.min(...ys))); y < Math.min(height, Math.ceil(Math.max(...ys))); y++) {
      const intersections: number[] = [];
      for (let i = 0; i < p.length; i += 2) {
        const j = (i + 2) % p.length;
        if ((p[i + 1]! > y + 0.5) !== (p[j + 1]! > y + 0.5)) intersections.push(p[i]! + (y + 0.5 - p[i + 1]!) * (p[j]! - p[i]!) / (p[j + 1]! - p[i + 1]!));
      }
      intersections.sort((a, b) => a - b);
      for (let i = 0; i + 1 < intersections.length; i += 2) for (let x = Math.max(0, Math.ceil(intersections[i]! - 0.5)); x < Math.min(width, Math.ceil(intersections[i + 1]! - 0.5)); x++) pixels[x * height + y] = 1;
    }
  }
  return pixels;
}

export function translateMask(value: unknown, dx: number, dy: number): RleMask {
  const { width, height } = rleCounts(value);
  const source = decodeMask(value), target = new Uint8Array(source.length);
  dx = Math.round(dx); dy = Math.round(dy);
  for (let x = 0; x < width; x++) for (let y = 0; y < height; y++) {
    const tx = x + dx, ty = y + dy;
    if (source[x * height + y] && tx >= 0 && tx < width && ty >= 0 && ty < height) target[tx * height + ty] = 1;
  }
  return encodeMask(target, width, height);
}
