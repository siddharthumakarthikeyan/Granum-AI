/** Declarative, reactive calculations over the complete loaded table. Never evaluates code. */
import type { ColumnInfo, Row } from "../api/types";

export const OPERATIONS = {
  add: "Add", subtract: "Subtract", multiply: "Multiply", divide: "Divide", power: "Power",
  abs: "Absolute value", negate: "Negate", sqrt: "Square root", log: "Natural logarithm",
  round: "Round", floor: "Floor", ceil: "Ceiling", sum: "Row sum", mean: "Row mean",
  min: "Row minimum", max: "Row maximum", length: "Vector length / text length",
  distance: "Euclidean distance", dot: "Dot product", equal: "Equal", greater: "Greater than",
  less: "Less than", rank: "Rank (ascending, average ties)", occurrence: "Occurrences",
  group_sum: "Group sum", group_mean: "Group mean", group_min: "Group minimum",
  group_max: "Group maximum", group_count: "Group count", group_std: "Group standard deviation",
  previous: "Previous observation", next: "Next observation", difference: "Change from previous",
  cumulative_sum: "Cumulative sum", standardize: "Standardize within group",
} as const;
export type Operation = keyof typeof OPERATIONS;
export interface VirtualColumn {
  name: string;
  operation: Operation;
  inputs: string[];
  groupBy: string[];
  orderBy?: string;
}
const binary = new Set<Operation>(["add", "subtract", "multiply", "divide", "power", "distance", "dot", "equal", "greater", "less"]);
const variadic = new Set<Operation>(["sum", "mean", "min", "max"]);
const temporal = new Set<Operation>(["previous", "next", "difference", "cumulative_sum"]);
const reserved = new Set(["__proto__", "prototype", "constructor", "_row", "_src", "#"]);
export const MAX_VIRTUAL_COLUMNS = 64;
const number = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
const finite = (value: number): number | null => Number.isFinite(value) ? value : null;
const vector = (value: unknown): number[] | null => Array.isArray(value) && value.every(v => number(v) !== null) ? value : null;

export function parseVirtualColumns(value: unknown): VirtualColumn[] {
  if (!Array.isArray(value) || value.length > MAX_VIRTUAL_COLUMNS) throw new Error("Invalid calculated-column list");
  return value.map(item => {
    if (!item || typeof item !== "object" || typeof item.name !== "string" || !item.name.trim()
      || item.name !== item.name.trim() || item.name.length > 120 || reserved.has(item.name)
      || !Object.prototype.hasOwnProperty.call(OPERATIONS, item.operation)) throw new Error("Invalid calculated-column definition");
    const strings = (input: unknown): input is string[] => Array.isArray(input) && input.length <= 16
      && input.every(s => typeof s === "string" && s.length > 0 && s.length <= 256);
    if (!strings(item.inputs) || !strings(item.groupBy ?? [])
      || (item.orderBy !== undefined && (typeof item.orderBy !== "string" || !item.orderBy))) {
      throw new Error(`Invalid inputs for ${item.name}`);
    }
    const operation = item.operation as Operation;
    if (binary.has(operation) ? item.inputs.length !== 2 : variadic.has(operation) ? !item.inputs.length : item.inputs.length !== 1) {
      throw new Error(`Wrong number of inputs for ${OPERATIONS[operation]}`);
    }
    if (temporal.has(operation) && !item.orderBy) throw new Error(`${OPERATIONS[operation]} needs an order column`);
    return { name: item.name, operation, inputs: [...item.inputs], groupBy: [...(item.groupBy ?? [])],
      ...(item.orderBy ? { orderBy: item.orderBy } : {}) };
  });
}

function groups(rows: Row[], keys: string[]): number[][] {
  const result = new Map<string, number[]>();
  rows.forEach((row, i) => {
    const key = JSON.stringify(keys.map(k => row[k] ?? null));
    const indices = result.get(key);
    if (indices) indices.push(i); else result.set(key, [i]);
  });
  return [...result.values()];
}

function moments(values: number[]): { mean: number; std: number; sum: number } {
  let mean = 0, m2 = 0, sum = 0;
  values.forEach((value, i) => {
    sum += value;
    const delta = value - mean;
    mean += delta / (i + 1);
    m2 += delta * (value - mean);
  });
  return { mean, std: Math.sqrt(Math.max(0, m2 / values.length)), sum };
}

function local(op: Operation, values: unknown[]): unknown {
  if (values.some(v => v === null || v === undefined)) return null;
  const [a, b] = values;
  if (op === "equal") return JSON.stringify(a) === JSON.stringify(b);
  if (op === "length") {
    if (typeof a === "string") return a.length;
    const v = vector(a);
    return v ? finite(Math.hypot(...v)) : null;
  }
  if (op === "distance" || op === "dot") {
    const x = vector(a), y = vector(b);
    if (!x || !y || x.length !== y.length) return null;
    return finite(op === "distance" ? Math.sqrt(x.reduce((s, v, i) => s + (v - y[i]!) ** 2, 0))
      : x.reduce((s, v, i) => s + v * y[i]!, 0));
  }
  const numbers = values.map(number);
  if (numbers.some(v => v === null)) return null;
  const x = numbers[0]!, y = numbers[1]!;
  switch (op) {
    case "add": return finite(x + y);
    case "subtract": return finite(x - y);
    case "multiply": return finite(x * y);
    case "divide": return y === 0 ? null : finite(x / y);
    case "power": return finite(x ** y);
    case "abs": return Math.abs(x);
    case "negate": return -x;
    case "sqrt": return finite(Math.sqrt(x));
    case "log": return finite(Math.log(x));
    case "round": return Math.round(x);
    case "floor": return Math.floor(x);
    case "ceil": return Math.ceil(x);
    case "sum": return finite((numbers as number[]).reduce((s, n) => s + n, 0));
    case "mean": return finite((numbers as number[]).reduce((s, n) => s + n, 0) / numbers.length);
    case "min": return Math.min(...numbers as number[]);
    case "max": return Math.max(...numbers as number[]);
    case "greater": return x > y;
    case "less": return x < y;
    default: return null;
  }
}

export function evaluateColumn(rows: Row[], spec: VirtualColumn): unknown[] {
  const op = spec.operation;
  const input = spec.inputs[0]!;
  if (!op.startsWith("group_") && !temporal.has(op) && !["rank", "occurrence", "standardize"].includes(op)) {
    return rows.map(row => local(op, spec.inputs.map(key => row[key])));
  }
  const output: unknown[] = Array(rows.length).fill(null);
  for (const indices of groups(rows, spec.groupBy)) {
    if (temporal.has(op)) {
      const ordered = indices.filter(i => number(rows[i]![spec.orderBy!]) !== null)
        .sort((a, b) => Number(rows[a]![spec.orderBy!]) - Number(rows[b]![spec.orderBy!]) || a - b);
      let total = 0;
      ordered.forEach((index, pos) => {
        const value = rows[index]![input];
        if (op === "cumulative_sum") {
          const n = number(value);
          if (n !== null) { total += n; output[index] = finite(total); }
          return;
        }
        const neighbour = ordered[pos + (op === "next" ? 1 : -1)];
        if (neighbour === undefined) return;
        const other = rows[neighbour]![input];
        output[index] = op === "difference" ? local("subtract", [value, other]) : (other ?? null);
      });
      continue;
    }
    if (op === "occurrence") {
      const counts = new Map<string, number>();
      for (const i of indices) {
        const key = JSON.stringify(rows[i]![input] ?? null);
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
      for (const i of indices) if (rows[i]![input] != null) output[i] = counts.get(JSON.stringify(rows[i]![input]));
      continue;
    }
    const valid = indices.filter(i => number(rows[i]![input]) !== null);
    const values = valid.map(i => rows[i]![input] as number);
    if (op === "rank") {
      valid.sort((a, b) => Number(rows[a]![input]) - Number(rows[b]![input]));
      for (let start = 0; start < valid.length;) {
        let end = start + 1;
        while (end < valid.length && rows[valid[end]!]![input] === rows[valid[start]!]![input]) end++;
        for (let p = start; p < end; p++) output[valid[p]!] = (start + 1 + end) / 2;
        start = end;
      }
      continue;
    }
    const stats = moments(values);
    const aggregate = op === "group_count" ? indices.length : values.length === 0 ? null
      : op === "group_sum" ? stats.sum : op === "group_mean" ? stats.mean : op === "group_std" ? stats.std
        : op === "group_min" ? values.reduce((a, b) => Math.min(a, b), Infinity)
          : values.reduce((a, b) => Math.max(a, b), -Infinity);
    for (const i of indices) {
      const value = number(rows[i]![input]);
      output[i] = op === "standardize" ? value === null ? null : stats.std === 0 ? 0 : finite((value - stats.mean) / stats.std)
        : aggregate === null ? null : finite(aggregate);
    }
  }
  return output;
}

export function materializeColumns(rows: Row[], columns: ColumnInfo[], definitions: VirtualColumn[]): { rows: Row[]; columns: ColumnInfo[] } {
  const specs = parseVirtualColumns(definitions);
  const base = columns.filter(c => c.source !== "virtual");
  const known = new Map(base.map(c => [c.name, c]));
  const result = rows.map(row => {
    const copy = { ...row };
    for (const col of columns) if (col.source === "virtual") delete copy[col.name];
    return copy;
  });
  const added: ColumnInfo[] = [];
  for (const spec of specs) {
    if (known.has(spec.name)) throw new Error(`Column ${spec.name} already exists`);
    for (const name of [...spec.inputs, ...spec.groupBy, ...(spec.orderBy ? [spec.orderBy] : [])]) {
      if (name === "_src" || name === "_row") continue;
      const column = known.get(name);
      if (!column || column.source === "session") throw new Error(`Column ${spec.name} needs ${name}`);
    }
    const kind = ["previous", "next"].includes(spec.operation) ? known.get(spec.inputs[0]!)?.kind ?? "float32"
      : ["equal", "greater", "less"].includes(spec.operation) ? "bool" : "float32";
    const col: ColumnInfo = { name: spec.name, kind, source: "virtual", writable: false, default_visible: true, number_role: null };
    const values = evaluateColumn(result, spec);
    values.forEach((value, i) => { result[i]![spec.name] = value; });
    known.set(spec.name, col);
    added.push(col);
  }
  return { rows: result, columns: [...base, ...added] };
}
