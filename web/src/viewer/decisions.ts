/** Keep or remove, per image: saved as review decisions the moment they are made.
 *
 * "Remove" is a decision first and a change to the data second. Marking an image records
 * it (so nothing is lost if the page closes); taking the marked images out of a set is a
 * separate, confirmed step that writes a new version of the set and moves the images to
 * the dataset's removed set.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

export type Decision = "keep" | "remove" | "removed";

export interface Decisions {
  /** Image reference -> decision. Images without a decision are absent. */
  byImage: Map<string, Decision>;
  reasons: Map<string, string>;
  loading: boolean;
  error: string | null;
  decide: (images: string[], decision: "keep" | "remove" | "clear", reason?: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export const REMOVE_REASONS = [
  "Wrong or missing labels",
  "Blurry or unusable",
  "Duplicate of another image",
  "Not relevant",
];

export function useDecisions(project: string, dataset: string | null): Decisions {
  const [byImage, setByImage] = useState<Map<string, Decision>>(new Map());
  const [reasons, setReasons] = useState<Map<string, string>>(new Map());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!dataset) return;
    setLoading(true);
    try {
      const [reviews, removed] = await Promise.all([api.reviews(project, dataset), api.removedImages(project, dataset)]);
      const next = new Map<string, Decision>();
      const why = new Map<string, string>();
      for (const [image, event] of Object.entries(reviews.statuses)) {
        if (event.status === "correct") next.set(image, "keep");
        else if (event.status === "excluded") next.set(image, "remove");
        if (event.reason) why.set(image, event.reason);
      }
      for (const item of removed.images) {
        next.set(item.image, "removed");
        if (item.removed_reason) why.set(item.image, item.removed_reason);
      }
      setByImage(next);
      setReasons(why);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [project, dataset]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const decide = useCallback(async (images: string[], decision: "keep" | "remove" | "clear", reason = "") => {
    if (!dataset || images.length === 0) return;
    // Shown at once; the service call follows, and a failure puts things back.
    const before = byImage;
    setByImage((current) => {
      const next = new Map(current);
      for (const image of images) {
        if (current.get(image) === "removed") continue;
        if (decision === "clear") next.delete(image);
        else next.set(image, decision);
      }
      return next;
    });
    if (reason) setReasons((current) => new Map([...current, ...images.map((i) => [i, reason] as [string, string])]));
    try {
      await api.recordReview({
        project, dataset, samples: images,
        status: decision === "keep" ? "correct" : decision === "remove" ? "excluded" : "unreviewed",
        reason: decision === "keep" ? "Kept" : reason,
      });
    } catch (e) {
      setByImage(before);
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [project, dataset, byImage]);

  return { byImage, reasons, loading, error, decide, refresh };
}
