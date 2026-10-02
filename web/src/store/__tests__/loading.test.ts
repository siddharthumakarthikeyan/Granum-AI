import { describe, expect, it } from "vitest";
import type { RowPage } from "../../api/types";
import { MAX_BROWSER_ROWS, PAGE_SIZE, fetchAllRows } from "../store";

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
  it("refuses oversized views before requesting more pages", async () => {
    const { calls, fetchPage } = source(MAX_BROWSER_ROWS + 1);
    await expect(fetchAllRows(fetchPage)).rejects.toThrow("browser budget");
    expect(calls).toEqual([0]);
  });

  it("does not silently accept incomplete pages or a changed total", async () => {
    const { fetchPage } = source(PAGE_SIZE + 1);
    await expect(fetchAllRows(async (offset, limit) => {
      const page = await fetchPage(offset, limit);
      return offset ? { ...page, total: page.total + 1 } : page;
    })).rejects.toThrow("changed");
    await expect(fetchAllRows(async (offset, limit) => ({ ...await fetchPage(offset, limit), rows: [] }))).rejects.toThrow("incomplete");
  });
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
