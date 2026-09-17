/** Columns as flat typed arrays, cached per loaded row set.
 *
 * Reading a property off a million row objects is the slow part of every histogram and
 * chart; reading a Float64Array is not.
 */

import type { Row } from "../api/types";
import { ROW_INDEX } from "./types";

const vectorCache = new WeakMap<Row[], Map<string, Float64Array>>();

/** A column as a flat numeric vector. Missing or non-numeric cells become NaN. */
export function numericVector(rows: Row[], column: string): Float64Array {
  let byColumn = vectorCache.get(rows);
  if (!byColumn) {
    byColumn = new Map();
    vectorCache.set(rows, byColumn);
  }
  let vector = byColumn.get(column);
  if (!vector) {
    vector = new Float64Array(rows.length);
    if (column === ROW_INDEX) {
      for (let i = 0; i < rows.length; i += 1) vector[i] = i;
    } else {
      for (let i = 0; i < rows.length; i += 1) {
        const value = rows[i]![column];
        vector[i] =
          typeof value === "number" ? value : typeof value === "boolean" ? Number(value) : NaN;
      }
    }
    byColumn.set(column, vector);
  }
  return vector;
}

