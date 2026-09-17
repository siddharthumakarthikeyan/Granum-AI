import { describe, expect, it } from "vitest";
import type { Row } from "../../api/types";
import { formatSelection } from "../clipboard";

const rows: Row[] = [
  { _row: 0, name: "a", loss: 0.5 },
  { _row: 1, name: 'has "quotes", and a comma', loss: 1.5 },
];

describe("formatSelection", () => {
  it("writes CSV with a header", () => {
    const csv = formatSelection(rows, [0], ["name", "loss"], "csv");
    expect(csv).toBe("name,loss\na,0.5");
  });

  it("escapes quotes and commas", () => {
    const csv = formatSelection(rows, [1], ["name"], "csv");
    expect(csv).toBe('name\n"has ""quotes"", and a comma"');
  });

  it("writes JSON of the chosen columns only", () => {
    const json = JSON.parse(formatSelection(rows, [0], ["loss"], "json"));
    expect(json).toEqual([{ loss: 0.5 }]);
  });

  it("writes tab-separated raw text", () => {
    expect(formatSelection(rows, [0], ["name", "loss"], "text")).toBe("a\t0.5");
  });

  it("ignores indices that are not present", () => {
    expect(formatSelection(rows, [99], ["name"], "csv")).toBe("name");
  });
});
