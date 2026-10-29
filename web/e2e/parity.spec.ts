import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { ExportResult, ImportResult, Job, PreflightReport } from "../src/api/types";

async function finished<T>(request: APIRequestContext, initial: Job<T>): Promise<Job<T> & { result: T }> {
  let job = initial;
  await expect.poll(async () => {
    job = await (await request.get(`/api/jobs/${initial.id}`)).json() as Job<T>;
    return job.status;
  }, { timeout: 20000 }).not.toBe("running");
  expect(job.error).toBeNull();
  expect(job.status).toBe("done");
  if (!job.result) throw new Error("Job finished without a result");
  return { ...job, result: job.result };
}

test("native semantic PNG datasets import and export through the browser without losing pixels", async ({ page, request }) => {
  await page.goto("/#/import");
  await page.getByLabel("Name", { exact: true }).fill("native-semantics");
  await page.getByText("Semantic segmentation", { exact: true }).click();
  await expect(page.getByRole("checkbox", { name: /^Semantic segmentation/ })).toBeChecked();
  await page.getByRole("button", { name: "Select folder", exact: true }).click();
  const picker = page.getByRole("dialog", { name: "Select data folder" });
  await picker.locator(".browser-entry").filter({ hasText: "granum-qualification-" }).click();
  await picker.getByRole("button", { name: "native-masks", exact: true }).click();
  await expect(picker.getByText("Semantic masks (PNG)", { exact: true })).toBeVisible();
  // Clicking the manifest itself must preserve the detected format, too.
  await picker.getByRole("button", { name: /semantic.json.*Use file/ }).click();
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Imported into native-semantics" })).toBeVisible();
  const { tables } = await (await request.get("/api/projects/native-semantics/tables")).json();
  const dataset = tables[0].dataset_name as string;
  const original = await (await request.get("/api/images", { params: { project: "native-semantics", dataset } })).json();
  const detail = await (await request.get("/api/qa/image", { params: {
    project: "native-semantics", dataset, table: tables[0].url, image: original.images[0].image,
  } })).json();
  const response = await request.post("/api/qa/release", { data: {
    project: "native-semantics", dataset, name: "mask-version", mode: "all",
  } });
  expect(response.status()).toBe(200);
  await page.goto("/#/p/native-semantics/datasets");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Export mask-version" });
  await dialog.getByRole("combobox", { name: /^Format/ }).selectOption("semantic");
  await dialog.getByRole("radio", { name: /^Copy them/ }).check();
  const exporting = page.waitForResponse(r => r.url().endsWith("/api/datasets/export") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: /Write 1 image/ }).click();
  const exported = await finished<ExportResult>(request, await (await exporting).json());
  await expect(page.getByRole("dialog", { name: "Written", exact: true })).toBeVisible();
  const checked = await finished<PreflightReport>(request, await (await request.post("/api/import/preflight", { data: {
    sources: [{ split: "train", format: "semantic", annotations: exported.result.sets[0]!.path }], media: "full",
  } })).json());
  const resolutions = Object.fromEntries(checked.result.findings.filter(f => f.default).map(f => [f.code, f.default]));
  await finished<ImportResult>(request, await (await request.post("/api/import/commit", { data: {
    preflight_job: checked.id, project_name: "native-roundtrip", tasks: ["semantic_segmentation"], resolutions,
  } })).json());
  const importedTables = await (await request.get("/api/projects/native-roundtrip/tables")).json();
  const importedDataset = importedTables.tables[0].dataset_name as string;
  const copied = await (await request.get("/api/images", { params: { project: "native-roundtrip", dataset: importedDataset } })).json();
  const after = await (await request.get("/api/qa/image", { params: {
    project: "native-roundtrip", dataset: importedDataset, table: importedTables.tables[0].url, image: copied.images[0].image,
  } })).json();
  const masks = (boxes: { label: number; segmentation: string }[]) => boxes.map(b => ({ label: b.label, mask: JSON.parse(b.segmentation) }));
  expect(masks(after.boxes)).toEqual(masks(detail.boxes));
  expect(detail.boxes.map((b: { area: number }) => b.area).sort((a: number, b: number) => a - b)).toEqual([4784, 10576]);
});

async function openEditor(page: Page, request: APIRequestContext, dataset: string) {
  const overview = await (await request.get(`/api/images?project=parity&dataset=${dataset}`)).json();
  const image = overview.images[0].image as string;
  await page.goto(`/#/p/parity/images?dataset=${dataset}&edit=1&open=${encodeURIComponent(image)}`);
  await expect(page.locator(".editor-canvas > svg")).toBeVisible();
  return image;
}

async function stroke(page: Page, start: [number, number], end = start) {
  const points = await page.locator(".editor-canvas > svg").evaluate((svg, { start, end }) => {
    const matrix = (svg as SVGSVGElement).getScreenCTM()!;
    const a = new DOMPoint(...start).matrixTransform(matrix), b = new DOMPoint(...end).matrixTransform(matrix);
    return [a.x, a.y, b.x, b.y];
  }, { start, end });
  await page.mouse.move(points[0]!, points[1]!);
  await page.mouse.down();
  await page.mouse.move(points[2]!, points[3]!, { steps: 4 });
  await page.mouse.up();
}

async function save(page: Page, request: APIRequestContext, dataset: string, image: string) {
  const response = page.waitForResponse(r => r.url().endsWith("/api/table/commit") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const committed = await response;
  expect(committed.status()).toBe(200);
  const { url } = await committed.json();
  await expect(page.getByText(/Recovery copy saved/)).toHaveCount(0);
  return (await request.get("/api/qa/image", { params: { project: "parity", dataset, table: url, image } })).json();
}

test("a pending SAM proposal restores prompts after reload and stays unapplied until reviewed", async ({ page, request }) => {
  let completed = false;
  const job = { id: "sam-recovery-fixture", kind: "segmentation", phase: "Segmenting", done: 0, total: 1, elapsed: 0, error: null, log: [] };
  const mask = { size: [128, 128], counts: [32 * 128 + 32, ...Array.from({ length: 31 }, () => [32, 96]).flat(), 32, 128 * 128 - 63 * 128 - 64] };
  await page.route("**/api/annotations/segment/models", route => route.fulfill({ json: { available: true, models: [{ id: "sam2.1_t.pt", name: "SAM 2.1 tiny" }] } }));
  await page.route("**/api/annotations/segment", route => route.fulfill({ json: { ...job, status: "running", result: null } }));
  await page.route("**/api/jobs/sam-recovery-fixture", route => route.fulfill({ json: { ...job, status: completed ? "done" : "running",
    result: completed ? { model: "sam2.1_t.pt", width: 128, height: 128, candidates: [{ mask, quality: .95 }] } : null } }));
  const image = await openEditor(page, request, "sam-recovery");
  await page.getByRole("button", { name: "Foreground point", exact: true }).click();
  await stroke(page, [48, 48]);
  await page.getByRole("button", { name: "Propose mask", exact: true }).click();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "Clear 1 points", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toBeVisible();
  completed = true;
  await expect(page.getByRole("button", { name: "Apply mask", exact: true })).toBeVisible();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(0);
  await page.getByRole("button", { name: "Apply mask", exact: true }).click();
  const detail = await save(page, request, "sam-recovery", image);
  expect(detail.boxes).toHaveLength(1);
  await page.reload();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Apply mask", exact: true })).toHaveCount(0);
});

test("semantic polygon creation removes competing class pixels and undo restores them", async ({ page, request }) => {
  const image = await openEditor(page, request, "semantic-polygons");
  await page.getByRole("combobox", { name: "Class for new shapes", exact: true }).selectOption("0");
  await page.getByRole("button", { name: /^Polygon P$/ }).click();
  for (const point of [[32, 32], [64, 32], [64, 64], [32, 64]] as [number, number][]) await stroke(page, point);
  await page.keyboard.press("Enter");
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  const detail = await save(page, request, "semantic-polygons", image);
  const other = detail.boxes.find((box: { label: number }) => box.label === 1);
  const rle = JSON.parse(other.segmentation) as { counts: number[] };
  const pixels = rle.counts.flatMap((count, index) => Array<number>(count).fill(index % 2));
  expect(pixels[48 * 128 + 48]).toBe(0);
  expect(pixels[24 * 128 + 24]).toBe(1);
  await page.reload();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(2);
});

test("bitmap painting and erasing survive undo, save and reload", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const image = await openEditor(page, request, "masks");
  await page.getByRole("button", { name: /^Paint M$/ }).click();
  await stroke(page, [40, 64], [88, 64]);
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(0);
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  // Undo can clear the selection. Select the restored object before erasing.
  await page.locator(".editor-objects .instance-row").click();
  await page.getByRole("button", { name: /^Erase E$/ }).click();
  const brush = page.getByRole("slider", { name: /^Brush diameter/ });
  await brush.focus();
  await page.keyboard.press("Home");
  for (let i = 1; i < 8; i++) await page.keyboard.press("ArrowRight");
  await stroke(page, [64, 64]);
  const detail = await save(page, request, "masks", image);
  const rle = JSON.parse(detail.boxes[0].segmentation) as { size: number[]; counts: number[] };
  expect(rle.size).toEqual([128, 128]);
  const pixels = rle.counts.flatMap((count, i) => Array<number>(count).fill(i % 2));
  expect(pixels[40 * 128 + 64]).toBe(1);
  expect(pixels[64 * 128 + 64]).toBe(0);
  await page.reload();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  await expect(page.locator('.editor-canvas image[href^="data:"]')).toBeVisible();
  expect(errors).toEqual([]);
});

test("oriented boxes preserve rotation and resize through saving", async ({ page, request }) => {
  const image = await openEditor(page, request, "rotated");
  await page.getByRole("button", { name: /^Oriented box O$/ }).click();
  await stroke(page, [32, 48], [96, 80]);
  const rotation = page.getByLabel("Rotation (degrees)");
  await rotation.fill("30");
  await expect(rotation).toHaveValue("30");
  await page.getByRole("button", { name: /^Select V$/ }).click();
  const handle = page.locator('[data-role="oriented-handle"]').first();
  const bounds = await handle.boundingBox();
  if (!bounds) throw new Error("No resize handle");
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 - 5, bounds.y + bounds.height / 2 - 10);
  await page.mouse.up();
  await expect(rotation).toHaveValue("30");
  const detail = await save(page, request, "rotated", image);
  const corners = JSON.parse(detail.boxes[0].coco_extra).obb as number[];
  expect(corners).toHaveLength(8);
  expect(Math.atan2(corners[3]! - corners[1]!, corners[2]! - corners[0]!) * 180 / Math.PI).toBeCloseTo(30, 1);
  await page.reload();
  await page.locator(".editor-objects .instance-row").click();
  await expect(rotation).toHaveValue("30");
});

test("SAM previews remain drafts and applying one assigns semantic pixels exclusively", async ({ page, request }) => {
  // Only model inference is substituted; the actual editor, undo and dataset commit run.
  const mask = { size: [128, 128], counts: [32 * 128 + 32, ...Array.from({ length: 31 }, () => [32, 96]).flat(), 32, 128 * 128 - 63 * 128 - 64] };
  const job = { id: "sam-fixture", kind: "segmentation", phase: "Proposed mask", done: 1, total: 1, elapsed: 0, error: null, log: [] };
  await page.route("**/api/annotations/segment/models", route => route.fulfill({ json: { available: true, models: [{ id: "sam2.1_t.pt", name: "SAM 2.1 tiny" }] } }));
  await page.route("**/api/annotations/segment", route => route.fulfill({ json: { ...job, status: "running", result: null } }));
  await page.route("**/api/jobs/sam-fixture", route => route.fulfill({ json: { ...job, status: "done", result: { model: "sam2.1_t.pt", width: 128, height: 128, candidates: [{ mask, quality: .95 }] } } }));
  const image = await openEditor(page, request, "semantic");
  await page.getByRole("button", { name: "Foreground point", exact: true }).click();
  await stroke(page, [48, 48]);
  const sent = page.waitForRequest(r => r.url().endsWith("/api/annotations/segment") && r.method() === "POST");
  await page.getByRole("button", { name: "Propose mask", exact: true }).click();
  const prompts = (await sent).postDataJSON();
  expect(prompts.labels).toEqual([1]);
  expect(prompts.points[0][0]).toBeCloseTo(48, 0);
  await expect(page.getByRole("button", { name: "Apply mask", exact: true })).toBeVisible();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Apply mask", exact: true }).click();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.locator(".editor-objects .instance-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  const detail = await save(page, request, "semantic", image);
  const pixels = detail.boxes.map((box: { segmentation: string }) => {
    const rle = JSON.parse(box.segmentation) as { counts: number[] };
    return rle.counts.flatMap((count, i) => Array<number>(count).fill(i % 2));
  }) as number[][];
  expect(pixels[0]!.some((v, i) => v && pixels[1]![i])).toBe(false);
  expect(pixels[1]!.reduce((a, b) => a + b)).toBe(32 * 32);
  expect(detail.boxes[1].source).toBe("model");
  expect(detail.boxes[1].model).toBe("sam2.1_t.pt");
});

test("pose creation uses named slots and deletion retains keypoint indices", async ({ page, request }) => {
  const image = await openEditor(page, request, "pose");
  await page.getByRole("button", { name: /^Keypoint K$/ }).click();
  await stroke(page, [40, 40]);
  await expect(page.locator(".editor-keypoints li")).toHaveCount(2);
  await stroke(page, [80, 80]);
  await stroke(page, [90, 90]);
  await expect(page.locator(".editor-keypoints li")).toHaveCount(2);
  await page.getByRole("button", { name: "Delete point 1", exact: true }).click();
  const detail = await save(page, request, "pose", image);
  const extra = JSON.parse(detail.boxes[0].coco_extra);
  expect(extra.keypoints).toEqual([0, 0, 0, 80, 80, 2]);
  expect(extra.num_keypoints).toBe(1);
  await page.reload();
  await page.locator(".editor-objects .instance-row").click();
  await expect(page.getByRole("button", { name: "head", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "tail", exact: true })).toBeVisible();
});

async function analysis(page: Page, request: APIRequestContext) {
  const { tables } = await (await request.get("/api/projects/parity/tables")).json();
  const source = tables.find((t: { dataset_name: string; name: string }) => t.dataset_name === "analysis" && t.name === "initial");
  await page.goto(`/#/p/parity/table?url=${encodeURIComponent(source.url)}`);
  await expect(page.getByRole("button", { name: "Calculate", exact: true })).toBeVisible();
  return source;
}

test("a calculated column can be exported, imported and applied after reload", async ({ page, request }) => {
  await analysis(page, request);
  await page.getByRole("button", { name: "Calculate", exact: true }).click();
  const calculated = page.getByRole("dialog", { name: "Calculated columns" });
  await calculated.getByLabel("Column name").fill("ratio");
  await calculated.getByLabel("Input 1").selectOption("loss");
  await calculated.getByLabel("Input 2").selectOption("count");
  await calculated.getByRole("button", { name: "Add calculation" }).click();
  await calculated.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: /^ratio/ })).toBeVisible();
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  const workflows = page.getByRole("dialog", { name: "Analysis workflows" });
  await workflows.getByLabel("Name this setup").fill("loss ratio");
  await workflows.getByRole("button", { name: "Save current setup" }).click();
  const download = page.waitForEvent("download");
  await workflows.getByRole("button", { name: "Export", exact: true }).click();
  const downloaded = await download;
  const file = await downloaded.path();
  if (!file) throw new Error("Workflow was not downloaded");
  await workflows.getByRole("button", { name: "Remove", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Workflows", exact: true }).click();
  await workflows.locator('input[type="file"]').setInputFiles(file);
  await workflows.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByRole("columnheader", { name: /^ratio/ })).toBeVisible();
  const table = page.locator("table.grid");
  const headers = await table.locator("th").allTextContents();
  const index = headers.findIndex(value => value.startsWith("ratio"));
  await expect(table.locator("tbody tr").filter({ has: page.locator("td") }).first().locator("td").nth(index)).toHaveText("1");
});

test("landmark analysis filters numeric pose scores and excludes unlabelled landmarks", async ({ page, request }) => {
  const { runs } = await (await request.get("/api/projects/parity/runs")).json();
  const run = runs.find((r: { name: string }) => r.name === "pose-analysis");
  expect(run).toBeDefined();
  await page.goto(`/#/p/parity/run?url=${encodeURIComponent(run.url)}`);
  await page.getByRole("button", { name: "Landmarks", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Landmark analysis" });
  const first = dialog.getByRole("row").filter({ hasText: "Keypoint 0" });
  await expect(first.locator("td").first()).toHaveText("head (Keypoint 0)");
  await expect(first.locator("td").nth(1)).toHaveText("2");
  await expect(first.locator("td").nth(2)).toHaveText("1");
  await dialog.getByRole("button", { name: "Show keypoint 0 OKS below threshold", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".rows-count > b")).toHaveText("1");
  await page.getByRole("button", { name: "Landmarks", exact: true }).click();
  await dialog.getByRole("combobox", { name: "Summarize", exact: true }).selectOption("filtered");
  await expect(first.locator("td").nth(1)).toHaveText("1");
  await expect(first.locator("td").nth(2)).toHaveText("0");
  await expect(first.locator("td").nth(3)).toHaveText("0.000");
});

test("classification comparison uses accuracy and exports every matched image", async ({ page, request }) => {
  const { runs } = await (await request.get("/api/projects/parity/runs")).json();
  const baseline = runs.find((r: { name: string }) => r.name === "classification-before");
  const candidate = runs.find((r: { name: string }) => r.name === "classification-after");
  await page.goto(`/#/p/parity/compare?baseline=${encodeURIComponent(baseline.url)}&candidate=${encodeURIComponent(candidate.url)}`);
  const scores = page.getByRole("table", { name: "Comparison scores" });
  await expect(scores).toContainText("Accuracy");
  await expect(scores).toContainText("0.6667");
  await expect(scores).toContainText("1.0000");
  await expect(page.getByRole("table", { name: "Per-image changes" }).locator("tbody tr")).toHaveCount(3);
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download report", exact: true }).click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toBe("granum-comparison.json");
  expect(await file.failure()).toBeNull();
  await page.goto(`/#/p/parity/learning?url=${encodeURIComponent(candidate.url)}`);
  await expect(page.getByLabel("Accuracy threshold")).toBeVisible();
  await expect(page.locator(".sample-card")).toHaveCount(3);
  await page.locator(".sample-card").first().click();
  const sample = page.getByRole("dialog", { name: "Sample across epochs" });
  await expect(sample).toContainText("Label: cat");
  await expect(sample).toContainText("Prediction: cat");
  await sample.getByRole("combobox", { name: "Epoch", exact: true }).selectOption("0");
  await expect(sample).toContainText("Accuracy: 1.000");
});

test("semantic samples show original polygons and predicted bitmaps across epochs", async ({ page, request }) => {
  const { runs } = await (await request.get("/api/projects/parity/runs")).json();
  const run = runs.find((r: { name: string }) => r.name === "semantic-learning");
  await page.goto(`/#/p/parity/learning?url=${encodeURIComponent(run.url)}`);
  await expect(page.getByLabel("Image mean IoU threshold")).toBeVisible();
  await page.locator(".sample-card").first().click();
  const sample = page.getByRole("dialog", { name: "Sample across epochs" });
  await expect(sample).toContainText("Image mean IoU: 0.750");
  await expect(sample.locator("svg polygon")).toHaveCount(1);
  await expect(sample.locator('svg image[data-role="shape"]')).toHaveCount(1);
  await sample.getByRole("combobox", { name: "Epoch", exact: true }).selectOption("0");
  await expect(sample).toContainText("Image mean IoU: 0.250");
});

test("PCA creates an immutable three-dimensional projection that renders in a browser", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const source = await analysis(page, request);
  await page.getByRole("button", { name: "Embeddings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Project embeddings" });
  await dialog.getByRole("combobox", { name: "Dimensions", exact: true }).selectOption("3");
  await dialog.getByText("Save this coordinate system for reuse", { exact: true }).click();
  await dialog.getByRole("textbox", { name: "Saved projection name", exact: true }).fill("Browser reference");
  await dialog.getByRole("button", { name: "Create projection" }).click();
  await dialog.getByRole("button", { name: "Open projection" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("3D scatter: projection_x, projection_y, projection_z").locator("canvas")).toBeVisible();
  await page.getByRole("combobox", { name: "Trajectory sample", exact: true }).selectOption("count");
  await page.getByRole("combobox", { name: "Trajectory order", exact: true }).selectOption("loss");
  await page.getByRole("combobox", { name: "Radius by", exact: true }).selectOption("count");
  const chart = page.getByLabel("3D scatter: projection_x, projection_y, projection_z");
  await expect(chart.getByRole("status")).toContainText("9 trajectory segments");
  await page.getByRole("button", { name: "rect selection", exact: true }).click();
  const area = await page.getByLabel("3D selection area").boundingBox();
  if (!area) throw new Error("Selection area is not visible");
  const selectAll = async () => {
    await page.mouse.move(area.x + 1, area.y + 1);
    await page.mouse.down();
    await page.mouse.move(area.x + area.width - 1, area.y + area.height - 1, { steps: 5 });
    await page.mouse.up();
  };
  await selectAll();
  await expect(chart.getByRole("status")).toContainText("12 selected");
  await page.keyboard.down("Shift");
  await selectAll();
  await page.keyboard.up("Shift");
  await expect(chart.getByRole("status")).toContainText("0 selected");
  expect(new URLSearchParams(new URL(page.url()).hash.split("?")[1]).get("url")).not.toBe(source.url);
  const original = await (await request.get("/api/table", { params: { url: source.url } })).json();
  expect(original.columns.some((c: { name: string }) => c.name === "projection_x")).toBe(false);
  await page.reload();
  await page.getByRole("button", { name: "Embeddings", exact: true }).click();
  const saved = await request.get("/api/analysis/reducers", { params: { url: source.url, kind: "table" } });
  const records = await saved.json();
  const reference = records.find((r: { name: string }) => r.name === "Browser reference");
  expect(reference).toBeDefined();
  await dialog.getByRole("combobox", { name: "Coordinate system", exact: true }).selectOption(reference.id);
  await expect(dialog.getByText(/saved 3D coordinate system/)).toBeVisible();
  await dialog.getByRole("textbox", { name: "Output column prefix", exact: true }).fill("aligned");
  await dialog.getByRole("button", { name: "Create projection" }).click();
  await dialog.getByRole("button", { name: "Open projection" }).click();
  await expect(page.getByLabel("3D scatter: aligned_x, aligned_y, aligned_z").locator("canvas")).toBeVisible();
  expect(errors).toEqual([]);
});
