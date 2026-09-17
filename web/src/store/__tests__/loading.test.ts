import { describe, expect, it } from "vitest";
import type { RowPage } from "../../api/types";
import { PAGE_SIZE, fetchAllRows } from "../store";

function source(total: number) {
  const calls: number[] = [];
  const fetchPage = async (offset: number, limit: number): Promise<RowPage> => {
    calls.push(offset);
    const stop = Math.min(offset + limit, total);
    const rows = Array.from({ length: stop - offset }, (_, i) => ({ _row: offset + i }));
    return { url: "u", total, offset, limit, rows };
  };
  return { calls, fetchPage };
}

describe("fetchAllRows", () => {
  it("loads every row in order when the object spans many pages", async () => {
    const total = PAGE_SIZE * 16 + 7;
    const { calls, fetchPage } = source(total);
    const page = await fetchAllRows(fetchPage);
    expect(page.rows).toHaveLength(total);
    expect(page.rows.every((row, i) => row._row === i)).toBe(true);
    expect(calls).toHaveLength(17);
  });

  it("makes one request when everything fits in the first page", async () => {
    const { calls, fetchPage } = source(3);
    expect((await fetchAllRows(fetchPage)).rows).toHaveLength(3);
    expect(calls).toEqual([0]);
  });
});
