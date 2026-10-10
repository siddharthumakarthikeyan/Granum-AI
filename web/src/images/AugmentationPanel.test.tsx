// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { AugmentRecipe } from "../api/types";
import { AugmentationPanel, NO_AUGMENTATION, augmentationProblem, recipeOf, recipeSummary, type AugmentationState } from "./AugmentationPanel";

const picture = { image: "data:image/jpeg;base64,", width: 40, height: 30, boxes: [] };
type Asked = Parameters<typeof api.augmentExamples>[0];
let asked: Asked[] = [];

beforeEach(() => {
  asked = [];
  vi.spyOn(api, "augmentExamples").mockImplementation(async (payload) => {
    asked.push(payload);
    return { set: "train", row: 0, source: "a.jpg", original: picture, bytes_per_image: 1000, items: Object.fromEntries(Object.keys(payload.items).map((k) => [k, picture])) };
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const on = (settings: AugmentationState["settings"]): AugmentationState => ({ enabled: true, copies: 2, settings });

function Harness({ start, seen }: { start: AugmentationState; seen: (s: AugmentationState) => void }) {
  const [state, setState] = useState(start);
  return (
    <AugmentationPanel project="p" dataset="d" state={state} trainImages={10} trainSet="train" labels={{}}
      onChange={(next) => { seen(next); setState(next); }} />
  );
}

/** The number box labelled `label` inside the group named `group` (or the whole editor). */
function box(editor: HTMLElement, label: string, group?: string): HTMLInputElement {
  const within_ = group ? within(within(editor).getByRole("group", { name: group })) : within(editor);
  // The label also holds the unit, so its text only starts with the name.
  return within_.getByLabelText(new RegExp(`^${label}`)) as HTMLInputElement;
}

it("builds the recipe the service takes for each new augmentation", () => {
  expect(recipeOf(NO_AUGMENTATION)).toBeNull();
  const state = on({
    translation: { horizontal_min: -10, horizontal_max: 10, vertical_min: -5, vertical_max: 5 },
    zoom: { min: 80, max: 120 },
    gamma: { min: 0.8, max: 1.2 },
    blur: { max: 1.5, gaussian: true, median: true, box: false },
    noise: { max: 2, iso: true },
    gridmask: { size_min: 32, size_max: 96, ratio_min: 0.3, ratio_max: 0.5 },
  });
  expect(augmentationProblem(state)).toBeNull();
  expect(recipeOf(state)).toEqual({ copies: 2, ...state.settings });
});

it("refuses settings the service would refuse", () => {
  const problem = (settings: AugmentationState["settings"]) => augmentationProblem(on(settings));
  expect(problem({})).toMatch(/at least one augmentation/);
  expect(problem({ translation: { horizontal_min: 10, horizontal_max: -10, vertical_min: 0, vertical_max: 0 } })).toBe("Translation: Horizontal: minimum is above maximum.");
  expect(problem({ translation: { horizontal_min: 0, horizontal_max: 0, vertical_min: -150, vertical_max: 0 } })).toBe("Translation: Vertical: use -100 to 100.");
  expect(problem({ zoom: { min: 5, max: 100 } })).toBe("Zoom: Use values from 10 to 400.");
  expect(problem({ gamma: { min: 2, max: 1 } })).toBe("Gamma: Minimum is above maximum.");
  expect(problem({ gridmask: { size_min: 32, size_max: 96, ratio_min: 0.3, ratio_max: 0.95 } })).toMatch(/^Grid mask: Hole.*use 0 to 0.9\.$/);
  expect(problem({ blur: { max: 2, gaussian: false, median: false } })).toBe("Blur: Choose at least one kind.");
  expect(problem({ noise: { max: 80, gaussian: true } })).toBe("Noise: Up to: use 0 to 50.");
  expect(recipeOf(on({ gamma: { min: 2, max: 1 } }))).toBeNull();
});

it("describes a saved recipe, with the kind an older one gets", () => {
  const recipe: AugmentRecipe = {
    copies: 3,
    translation: { horizontal_min: -10, horizontal_max: 10, vertical_min: 0, vertical_max: 5 },
    zoom: { min: 80, max: 120 },
    gamma: { min: 0.8, max: 1.2 },
    blur: { max: 1.5 },
    noise: { max: 2, salt_pepper: true, iso: true },
    gridmask: { size_min: 32, size_max: 96, ratio_min: 0.3, ratio_max: 0.5 },
  };
  const { names, detail } = recipeSummary(recipe);
  expect(names).toBe("Translation, Zoom, Gamma, Blur, Noise, Grid mask");
  expect(detail.split("\n")).toEqual([
    "3 copies per train image",
    "Translation: -10 to +10% h, 0 to +5% v",
    "Zoom: 80% to 120%",
    "Gamma: 0.8 to 1.2",
    "Blur: Up to 1.5 px · Gaussian",
    "Noise: Up to 2% · Salt & pepper, ISO",
    "Grid mask: 32 to 96 px, 0.3 to 0.5 holes",
  ]);
});

it("shows a card for every augmentation, each previewed on the train image", async () => {
  render(<Harness start={on({})} seen={() => undefined} />);
  for (const name of ["Flip", "90° Rotate", "Crop", "Rotation", "Shear", "Translation", "Zoom", "Grayscale", "Hue", "Saturation",
    "Brightness", "Exposure", "Gamma", "Blur", "Noise", "Cutout", "Grid mask"]) {
    expect(screen.getByRole("button", { name: new RegExp(`^${name}\\s*Add$`) })).toBeTruthy();
  }
  await waitFor(() => expect(asked.length).toBe(1));
  const items = asked[0]!.items;
  expect(Object.keys(items).sort()).toEqual(["blur", "brightness", "crop", "cutout", "exposure", "flip", "gamma", "grayscale", "gridmask",
    "hue", "noise", "rotate90", "rotation", "saturation", "shear", "translation", "zoom"]);
  expect(items.translation).toEqual({ recipe: { translation: { horizontal_min: -20, horizontal_max: 20, vertical_min: -15, vertical_max: 15 } }, at: "max" });
  expect(items.blur!.recipe).toEqual({ blur: { max: 4, gaussian: true } });
});

it("adds translation from its two ranges, previewing both ends", async () => {
  const seen = vi.fn();
  render(<Harness start={on({})} seen={seen} />);
  fireEvent.click(screen.getByRole("button", { name: /^Translation/ }));
  const editor = screen.getByRole("dialog", { name: "Translation" });
  expect(within(editor).getByText("Minimum", { selector: "figcaption span" })).toBeTruthy();
  expect(within(editor).getByText("-10% h, -10% v")).toBeTruthy();

  fireEvent.change(box(editor, "Maximum", "Horizontal"), { target: { value: "30" } });
  fireEvent.change(box(editor, "Minimum", "Vertical"), { target: { value: "0" } });
  expect(within(editor).getByText("+30% h, +10% v")).toBeTruthy();
  const value = { horizontal_min: -10, horizontal_max: 30, vertical_min: 0, vertical_max: 10 };
  await waitFor(() => expect(asked.at(-1)!.items).toEqual({
    min: { recipe: { translation: value }, at: "min" },
    max: { recipe: { translation: value }, at: "max" },
  }));

  // A minimum above its maximum cannot be added, and says which range is wrong.
  fireEvent.change(box(editor, "Minimum", "Horizontal"), { target: { value: "40" } });
  expect(within(editor).getByText("Horizontal: minimum is above maximum.")).toBeTruthy();
  const add = within(editor).getByRole("button", { name: "Add augmentation" }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  fireEvent.change(box(editor, "Minimum", "Horizontal"), { target: { value: "-10" } });
  expect(add.disabled).toBe(false);
  fireEvent.click(add);

  expect(seen).toHaveBeenLastCalledWith(on({ translation: value }));
  expect(screen.queryByRole("dialog", { name: "Translation" })).toBeNull();
  expect(screen.getByRole("button", { name: /^Translation/ }).textContent).toContain("-10 to +30% h, 0 to +10% v");
});

it("lets blur kinds be chosen, each previewed alone at the limit", async () => {
  const seen = vi.fn();
  render(<Harness start={on({})} seen={seen} />);
  fireEvent.click(screen.getByRole("button", { name: /^Blur/ }));
  const editor = screen.getByRole("dialog", { name: "Blur" });
  const kind = (name: string) => within(editor).getByRole("button", { name: new RegExp(`^${name}`) });
  expect(["Gaussian", "Median", "Average", "Box"].map((k) => kind(k).getAttribute("aria-pressed"))).toEqual(["true", "false", "false", "false"]);
  await waitFor(() => expect(asked.at(-1)!.items).toEqual({
    gaussian: { recipe: { blur: { max: 1.5, gaussian: true } }, at: "max" },
    median: { recipe: { blur: { max: 1.5, median: true } }, at: "max" },
    average: { recipe: { blur: { max: 1.5, average: true } }, at: "max" },
    box: { recipe: { blur: { max: 1.5, box: true } }, at: "max" },
  }));

  fireEvent.click(kind("Median"));
  fireEvent.click(kind("Gaussian"));
  fireEvent.change(box(editor, "Up to"), { target: { value: "3" } });
  await waitFor(() => expect(asked.at(-1)!.items.median!.recipe).toEqual({ blur: { max: 3, median: true } }));
  fireEvent.click(within(editor).getByRole("button", { name: "Add augmentation" }));
  expect(seen).toHaveBeenLastCalledWith(on({ blur: { max: 3, gaussian: false, median: true } }));
  expect(recipeOf(seen.mock.lastCall![0])).toEqual({ copies: 2, blur: { max: 3, gaussian: false, median: true } });
  expect(screen.getByRole("button", { name: /^Blur/ }).textContent).toContain("Up to 3 px · Median");
});

it("needs at least one noise kind, and opens an older setting with the kind it had", () => {
  const seen = vi.fn();
  render(<Harness start={on({ noise: { max: 4 } })} seen={seen} />);
  fireEvent.click(screen.getByRole("button", { name: /^Noise/ }));
  const editor = screen.getByRole("dialog", { name: "Noise" });
  const kind = (name: string) => within(editor).getByRole("button", { name: new RegExp(`^${name}`) });
  expect(["Gaussian", "Salt & pepper", "ISO"].map((k) => kind(k).getAttribute("aria-pressed"))).toEqual(["true", "false", "false"]);
  fireEvent.click(kind("Gaussian"));
  expect(within(editor).getByText("Choose at least one kind.")).toBeTruthy();
  const update = within(editor).getByRole("button", { name: "Update" }) as HTMLButtonElement;
  expect(update.disabled).toBe(true);
  fireEvent.click(kind("ISO"));
  fireEvent.click(kind("Salt & pepper"));
  fireEvent.click(update);
  expect(seen).toHaveBeenLastCalledWith(on({ noise: { max: 4, gaussian: false, iso: true, salt_pepper: true } }));
});

it("edits zoom, gamma and grid mask, and removes one again", () => {
  const seen = vi.fn();
  render(<Harness start={on({})} seen={seen} />);

  fireEvent.click(screen.getByRole("button", { name: /^Zoom/ }));
  let editor = screen.getByRole("dialog", { name: "Zoom" });
  expect(within(editor).getByText("80%")).toBeTruthy(); // no "+" on a zoom factor
  fireEvent.change(box(editor, "Maximum"), { target: { value: "150" } });
  fireEvent.click(within(editor).getByRole("button", { name: "Add augmentation" }));
  expect(seen).toHaveBeenLastCalledWith(on({ zoom: { min: 80, max: 150 } }));

  fireEvent.click(screen.getByRole("button", { name: /^Gamma/ }));
  editor = screen.getByRole("dialog", { name: "Gamma" });
  fireEvent.change(box(editor, "Minimum"), { target: { value: "0.5" } });
  fireEvent.click(within(editor).getByRole("button", { name: "Add augmentation" }));
  expect(seen.mock.lastCall![0].settings.gamma).toEqual({ min: 0.5, max: 1.2 });

  fireEvent.click(screen.getByRole("button", { name: /^Grid mask/ }));
  editor = screen.getByRole("dialog", { name: "Grid mask" });
  expect(within(editor).getByText("32px grid, 0.3 holes")).toBeTruthy();
  fireEvent.change(box(editor, "Maximum", "Grid spacing"), { target: { value: "64" } });
  fireEvent.click(within(editor).getByRole("button", { name: "Add augmentation" }));
  expect(seen.mock.lastCall![0].settings.gridmask).toEqual({ size_min: 32, size_max: 64, ratio_min: 0.3, ratio_max: 0.5 });
  expect(Object.keys(seen.mock.lastCall![0].settings)).toEqual(["zoom", "gamma", "gridmask"]);

  fireEvent.click(screen.getByRole("button", { name: /^Gamma/ }));
  fireEvent.click(within(screen.getByRole("dialog", { name: "Gamma" })).getByRole("button", { name: "Remove" }));
  expect(Object.keys(seen.mock.lastCall![0].settings)).toEqual(["zoom", "gridmask"]);
});
