import { useMemo } from "react";
import { decodeMask, rleCounts } from "./masks";

/** A transparent bitmap inside the editor's SVG coordinate system. */
export function MaskOverlay({ value, color, selected, at }: { value: unknown; color: string; selected: boolean; at: number }) {
  const result = useMemo(() => {
    try {
      const { width, height } = rleCounts(value), pixels = decodeMask(value);
      const canvas = document.createElement("canvas");
      canvas.width = width; canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Bitmap preview is unavailable.");
      context.fillStyle = color; context.fillRect(0, 0, 1, 1);
      const rgb = context.getImageData(0, 0, 1, 1).data;
      const data = context.createImageData(width, height);
      for (let x = 0; x < width; x++) for (let y = 0; y < height; y++) if (pixels[x * height + y]) {
        const offset = (y * width + x) * 4;
        data.data[offset] = rgb[0]!; data.data[offset + 1] = rgb[1]!; data.data[offset + 2] = rgb[2]!; data.data[offset + 3] = 255;
      }
      context.putImageData(data, 0, 0);
      return { url: canvas.toDataURL(), width, height };
    } catch (e) { return { error: e instanceof Error ? e.message : String(e) }; }
  }, [value, color]);
  if (result.error) return <text x={4} y={20} fill="#f88">{result.error}</text>;
  return <image data-role="shape" data-shape={at} href={result.url} width={result.width} height={result.height} opacity={selected ? 0.4 : 0.25} style={{ imageRendering: "pixelated" }} />;
}
