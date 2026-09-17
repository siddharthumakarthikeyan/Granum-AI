/** Ship a dataset: record the exact version of each set, once every image is reviewed. */

import { useState } from "react";
import { api } from "../api/client";
import type { QaSet, QaState } from "../api/types";
import { Modal } from "../components/Modal";
import { formatNumber, plural } from "../components/ui";
import { countStatuses } from "./ReviewPage";

export function ShipDialog({ project, dataset, sets, statuses, author, upToDate, onClose, onShipped }: {
  project: string;
  dataset: string;
  sets: QaSet[];
  statuses: Record<string, QaState>;
  author: string;
  upToDate: boolean;
  onClose: () => void;
  onShipped: (message: string) => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rows = sets.map((s) => ({ set: s, counts: countStatuses(s, statuses) }));
  const waiting = rows.reduce((n, r) => n + r.counts.unreviewed + r.counts.rework, 0);
  const images = rows.reduce((n, r) => n + r.set.images.length, 0);

  const ship = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.ship({ project, dataset, author, note });
      onShipped(`${dataset} shipped: ${plural(images, "image")} now available for training`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Ship ${dataset}`}
      onClose={onClose}
      width={560}
      footer={
        <>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || waiting > 0 || images === 0 || upToDate} onClick={() => void ship()}>
            {busy ? "Shipping" : "Ship dataset"}
          </button>
        </>
      }
    >
      <table className="data-table ship-table">
        <thead>
          <tr><th>Set</th><th>Version</th><th className="num">Images</th><th className="num">Reviewed</th><th className="num">Rework</th><th className="num">Unreviewed</th></tr>
        </thead>
        <tbody>
          {rows.map(({ set, counts }) => (
            <tr key={set.set}>
              <td className="strong">{set.set}</td>
              <td className="cell-mono small">{set.name}</td>
              <td className="num">{formatNumber(set.images.length)}</td>
              <td className="num">{formatNumber(counts.reviewed)}</td>
              <td className={`num${counts.rework ? " delta-down" : " faint"}`}>{formatNumber(counts.rework)}</td>
              <td className={`num${counts.unreviewed ? " warn-text" : " faint"}`}>{formatNumber(counts.unreviewed)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {upToDate ? (
        <p className="muted small ship-message">These versions are already shipped. Changes to the data create new versions that can be shipped again.</p>
      ) : waiting > 0 ? (
        <p className="form-error">{plural(waiting, "image")} still unreviewed or in rework. Every image must be reviewed before shipping.</p>
      ) : (
        <>
          <p className="muted small ship-message">Training will be able to use exactly these versions. Later changes need a new shipment.</p>
          <label className="field">
            <span>Note</span>
            <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional, e.g. batch 3 QA complete" maxLength={4000} />
          </label>
        </>
      )}
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
