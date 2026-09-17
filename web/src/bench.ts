/** Dev-only load test: `?bench=1000000` fills the dashboard with synthetic rows.
 *
 * Stage 5 is done when a million points render and lasso-select without dropping
 * frames. That needs a million rows in the store without a million-row object on
 * disk, so this bypasses the service and injects them directly.
 */

import type { ColumnInfo, Row } from "./api/types";
import { scatterSpec } from "./charts/spec";
import { isFilterable, makeFilter } from "./store/filtering";
import { useStore } from "./store/store";
import { emptySelection } from "./store/selection";
import type { Filter } from "./store/types";

function column(name: string, kind: ColumnInfo["kind"]): ColumnInfo {
  return { name, kind, writable: false, default_visible: true, number_role: null };
}

export function syntheticRows(count: number, seed = 1): Row[] {
  let state = seed;
  const random = () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
  const rows: Row[] = new Array(count);
  for (let i = 0; i < count; i += 1) {
    const label = Math.floor(random() * 10);
    const confidence = Math.min(1, Math.max(0.1, 0.55 + 0.45 * Math.sqrt(random()) * (random() < 0.9 ? 1 : -0.6)));
    const wrong = random() < 0.08;
    const loss = wrong ? -Math.log(Math.max(1e-6, 1 - confidence)) * (1 + random()) : -Math.log(confidence) * random() * 2;
    rows[i] = { _row: i, example_id: i, label, loss, confidence, epoch: i % 8 };
  }
  return rows;
}

export async function loadBench(count: number): Promise<void> {
  const started = performance.now();
  const rows = syntheticRows(count);
  const columns = [
    column("example_id", "example_id"), column("label", "int64"), column("loss", "float32"),
    column("confidence", "confidence"), column("epoch", "epoch"),
  ];
  const filters: Record<string, Filter> = {};
  for (const c of columns) {
    const filter = isFilterable(c) ? makeFilter(c, rows) : null;
    if (filter) filters[c.name] = filter;
  }
  useStore.setState({
    page: "data",
    project: "bench",
    sourceUrl: "bench://",
    sourceKind: "table",
    sourceName: `synthetic ${count.toLocaleString()}`,
    run: null,
    columns,
    rows,
    total: count,
    filters,
    sort: [],
    order: columns.map((c) => c.name),
    hidden: new Set(),
    selection: emptySelection(),
    charts: [scatterSpec("loss", "confidence", "label")],
    loading: false,
    error: null,
    serviceOk: true,
  });
  (window as unknown as { __granumBench: object }).__granumBench = {
    rows: count,
    loadMs: performance.now() - started,
  };
}
