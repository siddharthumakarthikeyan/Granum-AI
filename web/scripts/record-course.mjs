/** Real application recordings, never mocked API responses. Run one chapter at a time.
 * Requires the isolated serve_walkthrough.py service and the real aerial-mini sample.
 * Generated media lives outside public/docs, which the documentation builder cleans.
 */
import { chromium, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { analysis, candidate, comparison, handoff, restored, review } from "./course-chapters.mjs";
import { publishTiming } from "./course-media.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const output = path.resolve(repo, "../granum-website/public/assets/course");
const raw = path.resolve(repo, "build/course-recordings");
const origin = process.env.GRANUM_COURSE_URL ?? "http://127.0.0.1:18861";
const project = process.env.GRANUM_COURSE_PROJECT ?? "aerial-walkthrough";
const dataset = "aerial-mini";
const chapter = process.argv[2];
await mkdir(output, { recursive: true });
await mkdir(raw, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1,
  recordVideo: { dir: raw, size: { width: 1440, height: 960 } }, colorScheme: "light", reducedMotion: "reduce" });
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.on("dialog", dialog => dialog.accept());
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const cues = [];
const shots = [];
const began = Date.now();
// This is recording pacing, not waiting for a background task or polling a terminal.
async function cue(text) {
  cues.push({ at: (Date.now() - began) / 1000, text });
  console.log(text);
  await page.waitForTimeout(Math.max(3000, Math.min(6500, text.split(/\s+/).length * 220)));
}
async function goto(route) {
  await page.goto(`${origin}/#${route}`);
  await page.locator("main").waitFor();
}
async function shot(name, locator = page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].filter(i => i.getBoundingClientRect().top < innerHeight).map(i => i.decode().catch(() => undefined)));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  const png = path.join(raw, `${name}.png`);
  await locator.screenshot({ path: png, animations: "disabled" });
  execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-i", png, "-c:v", "libwebp", "-quality", "88", path.join(output, `${name}.webp`)]);
  shots.push(name);
}
async function json(endpoint, options) {
  const response = await page.request.fetch(origin + endpoint, options);
  if (!response.ok()) throw new Error(`${endpoint}: ${response.status()} ${await response.text()}`);
  return response.json();
}
const imagesRoute = `/p/${project}/images?dataset=${dataset}`;

async function importing() {
  await goto("/import");
  await page.getByPlaceholder("e.g. aerial-people").fill(project);
  await page.getByText("Object detection", { exact: true }).click();
  await cue("Create a new object-detection project. This course uses aerial-walkthrough.");
  await page.getByRole("button", { name: "Select folder", exact: true }).click();
  const picker = page.getByRole("dialog", { name: "Select data folder" });
  await picker.locator(".browser-entry").first().click();
  await expect(picker.getByRole("button", { name: "Use 2 splits" })).toBeEnabled();
  await shot("01-source-folder");
  await cue("Choose the extracted aerial-mini folder. Keep both train and valid; there is no independent test set.");
  await picker.getByRole("button", { name: "Use 2 splits" }).click();
  await page.getByRole("radio", { name: /^All images/ }).check();
  await shot("02-import-setup");
  await page.locator(".create-submit").click();
  await page.getByRole("heading", { name: "Summary", exact: true }).waitFor();
  await cue("Preflight checks 96 training and 24 validation images before writing the project.");
  await shot("03-preflight-summary");
  const ignore = page.locator(".finding").filter({ hasText: "A category looks like an ignore marker, not an object" });
  if (await ignore.count()) {
    await ignore.scrollIntoViewIfNeeded();
    await cue("Read the ignore-region decision. Preserve regions as ignore/crowd; they are not ordinary target objects.");
    await shot("04-preflight-decision", ignore);
  }
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("heading", { name: `Imported into ${project}` }).waitFor();
  await cue("The import report records the applied decisions. The original source files are unchanged.");
  await shot("05-import-complete");
}

async function browsing() {
  await goto(`/p/${project}`);
  await expect(page.locator("main h1")).toContainText(project);
  await cue("The project overview connects working data, dataset versions and model runs.");
  await shot("06-overview");
  await goto(imagesRoute);
  await page.locator(".image-card").first().waitFor();
  await cue("Images is the working collection. Filtering changes the view, not membership in a dataset version.");
  await shot("07-images");
  await page.getByRole("button", { name: "Stats", exact: true }).click();
  await cue("Open Stats to inspect class imbalance and object sizes before choosing a training recipe.");
  await shot("08-image-statistics");
  await page.getByRole("button", { name: "Stats", exact: true }).click();
  await page.getByRole("button", { name: "Patches", exact: true }).click();
  await cue("Patches shows individual labelled objects. Use it to compare label consistency; inspect the full image before changing a label.");
  await shot("09-patches");
  await goto(`/p/${project}/health?dataset=${dataset}`);
  await page.getByRole("heading", { name: "Health", exact: true }).waitFor();
  await cue("Health flags measurable dataset risks. A clean report is not proof that every label is correct.");
  await shot("10-health");
}

async function versions() {
  await goto(imagesRoute);
  await page.locator(".image-card").first().waitFor();
  await page.getByRole("button", { name: "Create dataset", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Create exploratory dataset version" });
  await dialog.getByLabel("Name", { exact: true }).fill("aerial-baseline");
  await dialog.getByLabel("Description", { exact: true }).fill("Course baseline: 96 train / 24 valid. Unreviewed source labels; exploratory only. No test or augmentation.");
  await cue("Freeze aerial-baseline with the entire dataset and no added augmentation. Frozen does not mean approved.");
  await shot("14-create-baseline");
  await dialog.getByRole("button", { name: "Create dataset", exact: true }).click();
  await goto(`/p/${project}/datasets`);
  await expect(page.locator(".release-panel")).toContainText("aerial-baseline");
  await cue("The version appears as Exploratory. Training records the exact versions used, not whatever is edited later.");
  await shot("15-exploratory-version");
  await page.getByRole("button", { name: "Approve…", exact: true }).first().click();
  await page.getByRole("button", { name: "Check and approve", exact: true }).click();
  await expect(page.getByRole("dialog").locator(".form-error")).toBeVisible();
  await cue("Approval correctly refuses unreviewed contents. Do not mark images verified just to make this warning disappear.");
  await shot("16-approval-refused");
}

async function training() {
  await goto(`/p/${project}/datasets`);
  await page.locator(".release-panel").filter({ hasText: "aerial-baseline" }).getByRole("button", { name: "Train", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Train model", exact: true });
  await dialog.getByLabel("Epochs", { exact: true }).fill("3");
  await dialog.getByLabel(/I understand this is exploratory training/).check();
  await expect(dialog.getByRole("button", { name: "Start training", exact: true })).toBeEnabled({ timeout: 120000 });
  await cue("Use YOLO nano, 640 pixels and 3 epochs for this small workflow exercise. Keep Test on None and record per-sample history.");
  await shot("17-training-recipe");
  // Preserve the actual UI submission and generated run name; no request is replaced.
  const submitted = page.waitForResponse(response => response.url().endsWith("/api/training") && response.request().method() === "POST");
  await dialog.getByRole("button", { name: "Start training", exact: true }).click();
  const response = await submitted;
  if (!response.ok()) throw new Error(await response.text());
  const job = await response.json();
  await writeFile(path.join(raw, "baseline-job.json"), JSON.stringify(job, null, 2));
  await cue("Training runs in a separate process. The run card reports progress and exposes the log; do not treat a running job as a finished result.");
  await shot("18-training-started");
}

const env = { page, goto, cue, shot, json, project, dataset, imagesRoute, raw, output };
const chapters = { "01-import": importing, "02-browse": browsing, "03-review": () => review(env),
  "04-versions": versions, "05-train": training, "06-results": () => analysis(env),
  "07-experiment": () => candidate(env), "08-compare": () => comparison(env),
  "09-handoff": () => handoff(env), "10-restore": () => restored(env) };
let success = false;
try {
  if (!(chapter in chapters)) throw new Error(`Choose a chapter: ${Object.keys(chapters).join(", ")}`);
  await chapters[chapter]();
  await page.waitForTimeout(1700);
  if (errors.length) throw new Error(errors.join("\n"));
  success = true;
} catch (error) {
  await page.screenshot({ path: path.join(raw, "capture-error.png") });
  console.error((await page.locator("body").innerText()).slice(-6000));
  throw error;
} finally {
  const video = page.video();
  const duration = (Date.now() - began) / 1000;
  await context.close();
  await browser.close();
  if (success) {
    const sourceVideo = await video.path();
    execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-i", sourceVideo,
      "-c:v", "libx264", "-preset", "medium", "-crf", "25", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", path.join(output, `${chapter}.mp4`)]);
    const metadata = await publishTiming(output, { chapter, recorded: new Date().toISOString(),
      source: "Actual Granum dashboard with aerial-mini; no mocked metrics or API responses.",
      viewport: { width: 1440, height: 960 }, duration, shots, cues });
    console.log(`Recorded ${chapter}: ${shots.length} screenshots, ${metadata.duration.toFixed(1)}s video and captions.`);
  }
}