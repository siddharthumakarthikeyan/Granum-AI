/** Ship sets for training: choose which sets, and which version of each, to approve.
 *
 * A version can ship once every one of its images is reviewed. Shipping one set does not
 * require the others, and every version ever shipped stays available for training.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { QaSet, QaState, QaStatus, QaVersionCounts } from "../api/types";
import { Modal } from "../components/Modal";
import { formatNumber, formatWhen, plural } from "../components/ui";
import { countStatuses } from "./ReviewPage";

interface Row {
  set: QaSet;
  url: string;
  counts: Record<QaStatus, number> | null;
  images: number | null;
  shipped: boolean;
}

export function ShipDialog({ project, dataset, sets, statuses, author, onClose, onShipped }: {
  project: string;
  dataset: string;
  sets: QaSet[];
  statuses: Record<string, QaState>;
  author: string;
  onClose: () => void;
  onShipped: (message: string) => void;
}) {
  // Start each set on the version most likely wanted: the newest if it can ship, else the
  // newest earlier version that can, else the newest.
  const [chosenVersion, setChosenVersion] = useState<Record<string, string>>(() => Object.fromEntries(sets.map((s) => {
    const newestReady = s.images.length > 0 && countStatuses(s, statuses).reviewed === s.images.length && !s.shipped;
    const earlier = (s.versions ?? []).slice(1).find((v) => v.ready && !v.shipped);
    return [s.set, newestReady || !earlier ? s.url : earlier.url];
  })));
  const [remote, setRemote] = useState<Record<string, QaVersionCounts>>({});
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Counts for earlier versions come from the service; the newest version is counted here,
  // so decisions made a moment ago on this page are reflected.
  useEffect(() => {
    for (const s of sets) {
      const url = chosenVersion[s.set];
      if (!url || url === s.url || remote[url]) continue;
      api.qaVersion(project, dataset, url)
        .then((counts) => setRemote((was) => ({ ...was, [url]: counts })))
        .catch((e: Error) => setError(e.message));
    }
  }, [chosenVersion, sets, project, dataset, remote]);

  const rows: Row[] = useMemo(() => sets.map((s) => {
    const url = chosenVersion[s.set] ?? s.url;
    if (url === s.url) {
      return { set: s, url, counts: countStatuses(s, statuses), images: s.images.length, shipped: Boolean(s.shipped) };
    }
    const known = remote[url];
    const version = s.versions?.find((v) => v.url === url);
    return { set: s, url, counts: known?.counts ?? null, images: known?.images ?? null, shipped: Boolean(version?.shipped) };
  }), [sets, chosenVersion, remote, statuses]);

  const isReady = (row: Row) => row.counts !== null && row.images !== null && row.images > 0 && row.counts.reviewed === row.images;
  const canShip = (row: Row) => isReady(row) && !row.shipped;
  const isIncluded = (row: Row) => (included[row.set.set] ?? true) && canShip(row);
  const selected = rows.filter(isIncluded);
  const images = selected.reduce((n, r) => n + (r.images ?? 0), 0);

  const ship = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.ship({ project, dataset, author, note, sets: Object.fromEntries(selected.map((r) => [r.set.set, r.url])) });
      const names = selected.map((r) => r.set.set).join(", ");
      onShipped(`Shipped ${names}: ${plural(images, "image")} available for training`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Ship ${dataset}`}
      onClose={onClose}
      width={860}
      footer={
        <>
          <span className="muted small">{selected.length ? `${plural(selected.length, "set")}, ${plural(images, "image")}` : "Nothing selected"}</span>
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || selected.length === 0} onClick={() => void ship()}>
            {busy ? "Shipping" : selected.length > 1 ? `Ship ${selected.length} sets` : "Ship"}
          </button>
        </>
      }
    >
      <table className="data-table ship-table">
        <thead>
          <tr>
            <th style={{ width: 28 }} />
            <th>Set</th>
            <th>Version</th>
            <th className="num">Images</th>
            <th className="num">Reviewed</th>
            <th className="num">Rework</th>
            <th className="num">Unreviewed</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const versions = row.set.versions ?? [];
            const status = row.counts === null ? "Counting"
              : row.shipped ? "Shipped"
                : isReady(row) ? "Ready"
                  : "Not reviewed";
            return (
              <tr key={row.set.set} className={canShip(row) ? "" : "ship-row-blocked"}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Ship ${row.set.set}`}
                    checked={isIncluded(row)}
                    disabled={!canShip(row)}
                    onChange={(e) => setIncluded((was) => ({ ...was, [row.set.set]: e.target.checked }))}
                  />
                </td>
                <td className="strong">{row.set.set}</td>
                <td>
                  <div className="select-wrap ship-version">
                    <select
                      aria-label={`Version of ${row.set.set}`}
                      value={row.url}
                      onChange={(e) => setChosenVersion((was) => ({ ...was, [row.set.set]: e.target.value }))}
                    >
                      {versions.map((v, i) => (
                        <option key={v.url} value={v.url}>
                          {v.name}{i === 0 ? " (newest)" : ""} · {v.shipped ? "shipped" : v.ready ? "ready" : `${formatNumber(v.reviewed)}/${formatNumber(v.images)} reviewed`} · {formatWhen(v.created)}
                        </option>
                      ))}
                    </select>
                  </div>
                </td>
                <td className="num">{row.images === null ? "—" : formatNumber(row.images)}</td>
                <td className="num">{row.counts ? formatNumber(row.counts.reviewed) : "—"}</td>
                <td className={`num${row.counts?.rework ? " delta-down" : " faint"}`}>{row.counts ? formatNumber(row.counts.rework) : "—"}</td>
                <td className={`num${row.counts?.unreviewed ? " warn-text" : " faint"}`}>{row.counts ? formatNumber(row.counts.unreviewed) : "—"}</td>
                <td><span className={`ship-status ${status.toLowerCase().replace(" ", "-")}`}>{status}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="muted small ship-message">
        Each set ships on its own, as the version you choose. A version can ship once every image in it is reviewed.
        Every shipped version stays available for training.
      </p>
      {selected.length > 0 && (
        <label className="field">
          <span>Note</span>
          <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional, e.g. batch 3 QA complete" maxLength={4000} />
        </label>
      )}
      {error && <p className="form-error">{error}</p>}
    </Modal>
  );
}
