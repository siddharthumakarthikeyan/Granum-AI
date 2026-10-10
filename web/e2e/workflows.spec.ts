import { expect, test } from "@playwright/test";

test("images workspace loads and reports browser memory and filter latency", async ({ page }, info) => {
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  const start = Date.now();
  await page.goto("/#/p/qualification/images?dataset=synthetic");
  await expect(page.locator(".image-card").first()).toBeVisible();
  const loadMs = Date.now() - start;
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const { metrics } = await cdp.send("Performance.getMetrics");
  const heap = metrics.find((m: { name: string }) => m.name === "JSHeapUsedSize")?.value;
  if (heap === undefined) throw new Error("Chromium did not report JS heap usage");
  const filtering = Date.now();
  await page.getByRole("group", { name: "Status", exact: true }).getByRole("button", { name: /^Verified/ }).click();
  await expect(page.locator(".image-card")).toHaveCount(0);
  const filterMs = Date.now() - filtering;
  expect(failures).toEqual([]);
  await info.attach("browser-measurement", { body: JSON.stringify({ images: Number(process.env.GRANUM_BENCHMARK_IMAGES ?? 120), loadMs, filterMs, heapMiB: heap / 1024**2 }), contentType: "application/json" });
});

test("annotation editor recovers a class draft after reload, then commits it", async ({ page, request }) => {
  const overview = await (await request.get("/api/images?project=qualification&dataset=synthetic")).json();
  const image = overview.images[0].image;
  await page.goto(`/#/p/qualification/images?dataset=synthetic&edit=1&open=${encodeURIComponent(image)}`);
  const editor = page.getByRole("dialog", { name: /Edit sample-/ });
  await expect(editor).toBeVisible();
  await editor.getByRole("button", { name: "Class", exact: true }).first().click();
  await editor.getByPlaceholder("New class name").fill("recovered-class");
  await editor.getByRole("button", { name: "Add", exact: true }).click();
  await expect(editor.getByText(/Recovery copy saved/)).toBeVisible();
  page.on("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(page.getByRole("dialog", { name: "Recover unsaved annotations" })).toBeVisible();
  await page.getByRole("button", { name: "Recover edits", exact: true }).click();
  await expect(page.locator(".image-editor")).toContainText("recovered-class");
  await page.route("**/api/table/commit", (route) => route.fulfill({ status: 409, json: { detail: "Qualification: stale edit refused" } }));
  await page.keyboard.press("Control+s");
  await expect(page.getByText("Qualification: stale edit refused")).toBeVisible();
  await expect(page.getByText(/Recovery copy saved in this browser/)).toBeVisible();
  await page.unroute("**/api/table/commit");
  const committed = page.waitForResponse((response) => response.url().endsWith("/api/table/commit") && response.request().method() === "POST");
  await page.keyboard.press("Control+s");
  expect((await committed).status()).toBe(200);
  await expect(page.getByText(/Recovery copy saved/)).toHaveCount(0);
});

test("review editor recovers boxes and a comment, retaining both across a failed save", async ({ page }) => {
  await page.goto("/#/p/qualification/images?dataset=synthetic&review=1");
  await page.locator(".image-card-frame").first().click();
  const canvas = page.locator('.qa-inspector svg[viewBox="0 0 128 128"]');
  await expect(canvas).toBeVisible();
  const points = await canvas.evaluate((element) => {
    const matrix = (element as SVGSVGElement).getScreenCTM()!;
    const a = new DOMPoint(60, 70).matrixTransform(matrix);
    const b = new DOMPoint(90, 100).matrixTransform(matrix);
    return { ax: a.x, ay: a.y, bx: b.x, by: b.y };
  });
  await page.mouse.move(points.ax, points.ay);
  await page.mouse.down();
  await page.mouse.move(points.bx, points.by);
  await page.mouse.up();
  await expect(page.locator(".qa-side-title").filter({ hasText: "Boxes" })).toContainText("9");
  const comment = page.getByPlaceholder("Comment, or the reason for rework / isolate / delete");
  await comment.fill("Recovered review note");
  await expect(page.getByText(/Recovery copy saved in this browser/)).toBeVisible();
  page.on("dialog", (dialog) => dialog.accept());
  await page.reload();
  await page.locator(".image-card-frame").first().click();
  await page.getByRole("button", { name: "Recover edits", exact: true }).click();
  await expect(comment).toHaveValue("Recovered review note");
  await expect(page.locator(".qa-side-title").filter({ hasText: "Boxes" })).toContainText("9");
  await page.route("**/api/qa/comment", (route) => route.fulfill({ status: 503, json: { detail: "Qualification: save unavailable" } }));
  await page.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(page.getByText("Qualification: save unavailable")).toBeVisible();
  await expect(comment).toHaveValue("Recovered review note");
  await page.unroute("**/api/qa/comment");
  await page.getByRole("button", { name: "Comment", exact: true }).click();
  await expect(page.locator(".qa-thread").getByText("Recovered review note")).toBeVisible();
  await expect(comment).toHaveValue("");
  await comment.focus();
  await page.keyboard.press("Escape");
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/table/commit") && response.request().method() === "POST");
  await page.keyboard.press("Control+s");
  expect((await saved).status()).toBe(200);
  await expect(page.getByText(/Recovery copy saved in this browser/)).toHaveCount(0);
});

test("a dataset version is created with augmentations chosen and previewed in the dialog", async ({ page, request }) => {
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  const refused: string[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/augment/examples") && !response.ok()) refused.push(`${response.status()} ${response.url()}`);
  });
  const name = `augmented-${Date.now()}`;
  await page.goto("/#/p/qualification/images?dataset=synthetic");
  await page.getByRole("button", { name: "Create dataset" }).click();
  const dialog = page.getByRole("dialog", { name: "Create exploratory dataset version" });
  await dialog.getByLabel("Name", { exact: true }).fill(name);
  await dialog.getByRole("radiogroup", { name: "Augment the train set" }).getByRole("radio", { name: "Yes" }).click();
  await dialog.getByRole("radiogroup", { name: "Copies per train image" }).getByRole("radio", { name: "1×" }).click();

  // Every augmentation has a card, and each card shows the service's rendering of a train image.
  await expect(dialog.locator(".aug-card")).toHaveCount(17);
  await expect(dialog.locator(".aug-card image")).toHaveCount(17);
  const create = dialog.getByRole("button", { name: "Create dataset" });
  await expect(create).toBeDisabled();

  /** Opens one augmentation, waits for its previews, lets `change` edit it, and adds it. */
  const add = async (label: string, previews: number, change?: (editor: ReturnType<typeof page.getByRole>) => Promise<void>) => {
    await dialog.locator(".aug-card", { hasText: label }).first().click();
    const editor = page.getByRole("dialog", { name: label, exact: true });
    await expect(editor.locator(".aug-view image")).toHaveCount(previews + 1);
    await change?.(editor);
    await expect(editor.locator(".aug-view-media.loading")).toHaveCount(0);
    await expect(editor.locator(".form-error")).toHaveCount(0);
    await editor.getByRole("button", { name: "Add augmentation" }).click();
    await expect(editor).toHaveCount(0);
  };

  await add("Translation", 2, async (editor) => {
    await editor.getByRole("group", { name: "Horizontal" }).getByLabel(/^Maximum/).fill("25");
    await expect(editor.getByText("+25% h, +10% v")).toBeVisible();
    // A minimum above the maximum is caught before anything is sent.
    await editor.getByRole("group", { name: "Vertical" }).getByLabel(/^Minimum/).fill("40");
    await expect(editor.getByText("Vertical: minimum is above maximum.")).toBeVisible();
    await expect(editor.getByRole("button", { name: "Add augmentation" })).toBeDisabled();
    await editor.getByRole("group", { name: "Vertical" }).getByLabel(/^Minimum/).fill("-10");
  });
  await add("Zoom", 2);
  await add("Gamma", 2, async (editor) => {
    await editor.getByLabel(/^Maximum/).fill("1.5");
  });
  await add("Blur", 4, async (editor) => {
    await editor.getByRole("button", { name: /^Median/ }).click();
    await editor.getByRole("button", { name: /^Gaussian/ }).click();
    await editor.getByRole("button", { name: /^Median/ }).click();
    await expect(editor.getByText("Choose at least one kind.")).toBeVisible();
    await editor.getByRole("button", { name: /^Median/ }).click();
    await editor.getByRole("button", { name: /^Box/ }).click();
  });
  await add("Noise", 3, async (editor) => {
    await editor.getByRole("button", { name: /^ISO/ }).click();
  });
  await add("Grid mask", 2, async (editor) => {
    await editor.getByRole("group", { name: "Grid spacing" }).getByLabel(/^Minimum/).fill("8");
    await editor.getByRole("group", { name: "Grid spacing" }).getByLabel(/^Maximum/).fill("16");
  });

  await expect(dialog.locator(".aug-card.on")).toHaveCount(6);
  await expect(dialog.locator(".aug-card", { hasText: "Blur" })).toContainText("Up to 1.5 px · Median, Box");
  await expect(dialog.locator(".aug-card", { hasText: "Translation" })).toContainText("-10 to +25% h, -10 to +10% v");

  const sent = page.waitForRequest((r) => r.url().endsWith("/api/qa/release") && r.method() === "POST");
  await create.click();
  const expected = {
    copies: 1,
    translation: { horizontal_min: -10, horizontal_max: 25, vertical_min: -10, vertical_max: 10 },
    zoom: { min: 80, max: 120 },
    gamma: { min: 0.8, max: 1.5 },
    blur: { max: 1.5, median: true, box: true },
    noise: { max: 2, gaussian: true, iso: true },
    gridmask: { size_min: 8, size_max: 16, ratio_min: 0.3, ratio_max: 0.5 },
  };
  expect((await sent).postDataJSON().augmentation).toMatchObject(expected);
  await expect(dialog).toHaveCount(0, { timeout: 45000 });

  const { releases } = await (await request.get("/api/releases?project=qualification")).json();
  const release = releases.find((r: { name: string }) => r.name === name);
  expect(release.augmentation).toEqual(expected);
  const train = release.sets.train;
  expect(train.originals).toBeGreaterThan(0);
  expect(train.augmented).toBe(train.originals);
  expect(train.images).toBe(train.originals * 2);
  expect(refused).toEqual([]);
  expect(failures).toEqual([]);
});
