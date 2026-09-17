/** Mark selected images with a review decision, recorded at once and kept with the dataset. */

import { useMemo, useState } from "react";
import type { ReviewEvent } from "../api/types";
import { REVIEW_COLUMN, REVIEW_STATUSES, markReview, reviewProgress } from "../store/reviews";
import { useStore } from "../store/store";

export function ReviewBar({ onToast }: { onToast: (message: string) => void }) {
  const selection = useStore((s) => s.selection);
  const rows = useStore((s) => s.rows);
  const hasReview = useStore((s) => s.columns.some((c) => c.name === REVIEW_COLUMN));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const progress = useMemo(() => (hasReview ? reviewProgress(rows) : null), [rows, hasReview]);

  if (!hasReview || !progress) return null;
  const selected = [...selection.rows];

  const mark = async (status: ReviewEvent["status"], label: string) => {
    setBusy(true);
    const problem = await markReview(selected, status, reason);
    setBusy(false);
    if (problem) {
      onToast(problem);
      return;
    }
    setReason("");
    onToast(status === "unreviewed" ? `Cleared the review of ${selected.length} selected` : `Marked ${selected.length} as "${label}"`);
  };

  return (
    <div className={`review-strip${selected.length ? " active" : ""}`}>
      <span className="review-progress" title="Images with a review decision, out of the images loaded">
        <span className="review-meter">
          <span style={{ width: `${progress.total ? (progress.reviewed / progress.total) * 100 : 0}%` }} />
        </span>
        Reviewed {progress.reviewed.toLocaleString()} of {progress.total.toLocaleString()}
      </span>
      {selected.length === 0 ? (
        <span className="faint">Select rows to record a review decision.</span>
      ) : (
        <>
          <span className="muted">Mark {selected.length.toLocaleString()} selected as</span>
          {REVIEW_STATUSES.map((status) => (
            <button
              key={status.id}
              className={`review-button review-${status.id}`}
              disabled={busy}
              title={status.help}
              onClick={() => void mark(status.id, status.label)}
            >
              {status.label}
            </button>
          ))}
          <input
            type="text"
            className="review-reason"
            placeholder="Why? (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
            maxLength={2000}
          />
          <button
            className="review-clear"
            disabled={busy}
            onClick={() => void mark("unreviewed", "")}
            title="Remove the decision. Earlier decisions stay in the history."
          >
            Clear
          </button>
        </>
      )}
    </div>
  );
}
