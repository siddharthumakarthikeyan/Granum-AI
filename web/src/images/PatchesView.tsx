/** Patches: the gallery unrolled into one tile per labelled object.
 *
 * A mode of the Images tab rather than a page of its own, because it is the same set of
 * images under the same filters -- the ribbon's split, class and status still decide what
 * is in front of you, and the class filter narrows the objects as well as the images.
 *
 * Tiles are cut from the images the gallery has already fetched geometry for, and grow in
 * pages like the gallery itself rather than being virtualised: one page is a run a reader
 * can actually scan, and the page below it is a deliberate act rather than a scroll that
 * never ends. Clicking a tile opens its image full screen with that object picked out,
 * which is where a wrong label gets fixed.
 */

import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { ImageBoxes, ImageRow } from "../api/types";
import { Icon, formatNumber, plural } from "../components/ui";
import { fileName } from "../review/status";
import { labelColor } from "./labelColors";
import { patchPlacement, patchesFor } from "./patches";

const SIZES = { small: 96, medium: 132, large: 184 } as const;
type SizeKey = keyof typeof SIZES;

interface Props {
  project: string;
  dataset: string;
  /** The images the ribbon leaves, in the order it put them. */
  items: ImageRow[];
  /** Geometry for the images fetched so far, keyed by image. */
  boxes: Record<string, ImageBoxes>;
  /** The classes the ribbon is filtered to; empty means all of them. */
  classes: Set<number>;
  labels: Record<string, string>;
  /** How many objects to draw at once. */
  limit: number;
  /** Images of the list whose geometry has been asked for: the page the grid is cut from. */
  reach: number;
  /** Images beyond the ones fetched so far, which a further page would draw from. */
  more: boolean;
  onMore: () => void;
  /** Open the image this object belongs to, with the object picked out. */
  onOpen: (image: string, instance: number) => void;
}

export function PatchesView({ project, dataset, items, boxes, classes, labels, limit, reach, more, onMore, onOpen }: Props) {
  const [size, setSize] = useState<SizeKey>("medium");
  const page = useMemo(() => patchesFor(items, boxes, classes, limit), [items, boxes, classes, limit]);
  const tile = SIZES[size];
  const name = (label: number | null) => (label === null ? "Unlabelled" : labels[String(label)] ?? String(label));

  return (
    <div className="patches-view">
      <div className="ribbon patches-bar">
        <span className="strong">{formatNumber(page.patches.length)} objects</span>
        <span className="muted small">
          from {formatNumber(page.read)} of {plural(items.length, "image")}
          {page.read < reach ? " · reading the rest of this page" : ""}
          {classes.size > 0 ? " · only the classes the ribbon is filtered to" : ""}
        </span>
        <span className="spacer" />
        <div className="segmented" role="group" aria-label="Patch size">
          {(Object.keys(SIZES) as SizeKey[]).map((key) => (
            <button key={key} className={size === key ? "on" : ""} onClick={() => setSize(key)}>
              {key === "small" ? "Small" : key === "medium" ? "Medium" : "Large"}
            </button>
          ))}
        </div>
      </div>

      {page.patches.length === 0 ? (
        <p className="muted qa-empty">
          {page.read < reach
            ? "Reading the boxes of these images…"
            : classes.size > 0
              ? "No object of these classes in the images the filters leave."
              : "No labelled objects in the images the filters leave."}
        </p>
      ) : (
        <div className="patches-grid" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${tile}px, ${tile}px))` }}>
          {page.patches.map((patch) => {
            const place = patchPlacement(patch, tile);
            const colour = labelColor(patch.label);
            return (
              <button
                key={patch.id}
                className="patch-tile"
                style={{ width: tile }}
                title={`${name(patch.label)} · ${fileName(patch.item.image)} · ${Math.round(patch.x1 - patch.x0)} × ${Math.round(patch.y1 - patch.y0)} px in ${patch.width} × ${patch.height}`}
                onClick={() => onOpen(patch.item.image, patch.index)}
              >
                <span
                  className="patch-tile-image"
                  style={{
                    width: tile,
                    height: tile,
                    backgroundImage: `url("${api.mediaUrl(patch.item.image, 1280, project, dataset)}")`,
                    backgroundSize: place.backgroundSize,
                    backgroundPosition: place.backgroundPosition,
                  }}
                >
                  <svg width={tile} height={tile} aria-hidden="true">
                    <rect
                      x={place.box.x}
                      y={place.box.y}
                      width={place.box.width}
                      height={place.box.height}
                      fill="none"
                      stroke={colour}
                      strokeWidth={1.5}
                    />
                  </svg>
                </span>
                <span className="patch-tile-foot">
                  <span className="class-swatch" style={{ background: colour }} />
                  <span className="truncate small">{name(patch.label)}</span>
                  <Icon name="open" size={11} className="patch-tile-open" />
                </span>
              </button>
            );
          })}
        </div>
      )}

      {(page.capped || more) && (
        <div className="qa-more">
          <button className="button" onClick={onMore}>Show more objects</button>
          <span className="muted small">
            {formatNumber(page.patches.length)} objects from {formatNumber(page.read)} of {formatNumber(items.length)} images
          </span>
        </div>
      )}
    </div>
  );
}
