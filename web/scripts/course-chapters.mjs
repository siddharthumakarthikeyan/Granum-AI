/** Later course chapters. All actions target only the explicitly named tutorial project. */
import { expect } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import path from "node:path";

async function runs(env) {
  return (await env.json(`/api/projects/${env.project}/runs`)).runs.filter(run => run.status === "finished");
}

export async function review(env) {
  const { page, goto, cue, shot, json, project, dataset, imagesRoute } = env;
  const overview = await json(`/api/images?project=${project}&dataset=${dataset}`);
  const focus = overview.images.find(i => i.image.includes("0000099_00149"));
  const valid = overview.images.find(i => i.image.includes("0000103_01734"));
  if (!focus || !valid) throw new Error("The documented sample images are missing; rebuild the seeded aerial-mini pack.");
  const before = await json("/api/qa/image?" + new URLSearchParams({ project, dataset, table: focus.table, image: focus.image }));
  await goto(`${imagesRoute}&edit=1&open=${encodeURIComponent(focus.image)}`);
  const editor = page.locator(".image-editor");
  await editor.locator('.shape rect[data-role="shape"]').first().click();
  await cue("Inspect the full image: the one pedestrian already has a reasonable box. Do not manufacture a correction.");
  await shot("11-annotation-editor");
  await editor.getByLabel("Class of the selected object", { exact: true }).selectOption("9");
  await expect(page.getByText(/Recovery copy saved in this browser/)).toBeVisible();
  await cue("Practice only: temporarily relabel this object as people. Do not save this deliberate practice change.");
  await page.reload();
  await page.getByRole("dialog", { name: "Recover unsaved annotations" }).waitFor();
  await cue("Reload offers the draft from this browser profile. Recovery does not mean anything was committed to the dataset.");
  await shot("12-recover-annotations");
  await page.getByRole("button", { name: "Recover edits", exact: true }).click();
  await editor.getByLabel("Class of the selected object", { exact: true }).selectOption("8");
  await page.keyboard.press("Escape");
  await cue("Restore the original pedestrian class before saving. This teaches recovery and versioning, not a claimed label-quality improvement.");
  const saved = page.waitForResponse(r => r.url().endsWith("/api/table/commit") && r.request().method() === "POST");
  await page.keyboard.press("Control+s");
  expect((await saved).status()).toBe(200);
  await expect(page.getByText(/Recovery copy saved in this browser/)).toHaveCount(0);
  await shot("13-saved-annotation");
  const latest = (await json(`/api/images?project=${project}&dataset=${dataset}`)).images.find(i => i.image === focus.image);
  const after = await json("/api/qa/image?" + new URLSearchParams({ project, dataset, table: latest.table, image: latest.image }));
  expect(after.boxes).toEqual(before.boxes);
  for (const [item, comment] of [
    [focus, "Inspected full image: one visible pedestrian. Practice relabel restored; no source-label correction claimed."],
    [valid, "Inspected full image: three cars and one pedestrian. Retain the visible edge-truncated objects."],
  ]) {
    await goto(`${imagesRoute}&review=1`);
    await page.getByLabel("Reviewer", { exact: true }).fill("Course reviewer");
    await page.getByRole("button", { name: `Open ${path.basename(item.image)}`, exact: true }).click();
    const inspector = page.locator(".qa-inspector");
    await inspector.locator(".qa-canvas svg").waitFor();
    const note = page.getByPlaceholder("Comment, or the reason for rework / isolate / delete");
    await note.fill(comment);
    await page.getByRole("button", { name: "Comment", exact: true }).click();
    await expect(note).toHaveValue("");
    await cue("Record what you inspected, then Verify only this image. Saving annotations and verifying their correctness are separate actions.");
    const verified = page.waitForResponse(r => r.url().endsWith("/api/qa/status") && r.request().method() === "POST");
    await inspector.getByRole("button", { name: /^Verify/ }).click();
    expect((await verified).status()).toBe(200);
    await expect(inspector.locator(".qa-stage-name")).not.toHaveText(path.basename(item.image));
    await inspector.getByRole("button", { name: "Previous image", exact: true }).click();
    await expect(inspector.locator(".qa-side-head")).toContainText("Verified");
    if (item === focus) await shot("13a-review-verified");
    await inspector.getByRole("button", { name: "Close", exact: true }).click();
    await expect(page.locator(".qa-inspector")).toHaveCount(0);
  }
}

export async function analysis(env) {
  const { page, goto, cue, shot, json, project, raw } = env;
  const baseline = (await runs(env)).find(r => r.parameters?.epochs === 3);
  if (!baseline) throw new Error("Finish the three-epoch baseline before recording its results.");
  await writeFile(path.join(raw, "baseline-run.json"), JSON.stringify(baseline, null, 2));
  const query = encodeURIComponent(baseline.url);
  await goto(`/p/${project}/runs`);
  await expect(page.locator("main")).toContainText(baseline.name);
  await cue("Read the finished run, its recipe and exact input versions. Our three-epoch exercise produced poor scores; that is the observed result.");
  await shot("19-finished-baseline");
  await goto(`/p/${project}/run?url=${query}`);
  await expect(page.locator("main h1")).toContainText(baseline.name);
  await cue("The run workspace joins per-image measurements back to the input images. Historical rows describe the recorded input version.");
  await shot("20-run-workspace");
  await goto(`/p/${project}/learning?url=${query}`);
  await page.locator(".learning-page .tabs").waitFor();
  await cue("Sample dynamics reads F1 across epochs. Not learned after three epochs does not mean this image should be deleted.");
  await shot("21-sample-dynamics");
  await goto(`/p/${project}/evaluation?url=${query}`);
  await page.locator(".eval-headline").waitFor();
  await cue("Evaluation separates missed labels, invented predictions and class confusion. Read the chosen split and confidence threshold first.");
  await shot("22-evaluation-matrix");
  await page.getByRole("heading", { name: "Every object, one tile each" }).scrollIntoViewIfNeeded();
  await cue("Open the underlying objects, not just a score. Solid boxes are labels; dashed boxes are model predictions.");
  await shot("23-evaluation-objects");
  await goto(`/p/${project}/findings?url=${query}`);
  await page.locator(".findings-bar").waitFor();
  await cue("Findings requires useful model evidence. A weak run or an empty queue is not proof that the labels are correct.");
  await shot("24-findings-evidence");
  await writeFile(path.join(raw, "baseline-findings.json"), JSON.stringify(await json(`/api/run/findings?url=${query}`), null, 2));
}

export async function candidate(env) {
  const { page, goto, cue, shot, project, raw } = env;
  const baseline = (await runs(env)).find(r => r.parameters?.epochs === 3);
  if (!baseline) throw new Error("The baseline must finish before the next experiment.");
  await goto(`/p/${project}/datasets`);
  await page.locator(".release-panel").filter({ hasText: "aerial-baseline" }).getByRole("button", { name: "Train", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Train model", exact: true });
  await dialog.getByLabel("Epochs", { exact: true }).fill("12");
  await dialog.getByLabel(/Compare with/).selectOption(baseline.name);
  await dialog.getByLabel(/I understand this is exploratory training/).check();
  await expect(dialog.getByRole("button", { name: "Start training", exact: true })).toBeEnabled({ timeout: 120000 });
  await cue("Change one planned variable: 12 epochs instead of 3, on the same frozen dataset. This is a schedule experiment, not evidence that label edits helped.");
  await shot("25-candidate-recipe");
  const submitted = page.waitForResponse(r => r.url().endsWith("/api/training") && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Start training", exact: true }).click();
  const response = await submitted;
  if (!response.ok()) throw new Error(await response.text());
  await writeFile(path.join(raw, "candidate-job.json"), JSON.stringify(await response.json(), null, 2));
  await cue("The earlier model will be rescored on the same validation labels. Comparing numbers from different label versions would confound the result.");
}

export async function comparison(env) {
  const { page, goto, cue, shot, json, project, output } = env;
  const completed = await runs(env);
  const baseline = completed.find(run => run.parameters?.epochs === 3);
  const candidate = completed.find(run => run.parameters?.epochs === 12);
  if (!baseline || !candidate) throw new Error("Both real training jobs must finish before the comparison is recorded.");
  const params = new URLSearchParams({ baseline: baseline.url, candidate: candidate.url, split: "valid" });
  await goto(`/p/${project}/compare?${params}`);
  await page.locator(".compare-verdict").waitFor();
  await cue("Check compatibility before reading the delta: same validation images, labels, class mapping and scoring policy.");
  const checks = page.getByRole("button", { name: /checks? passed$/ });
  if (await checks.count()) await checks.click();
  await shot("26-comparison-checks");
  await page.locator(".compare-pooled").scrollIntoViewIfNeeded();
  await cue("Read improved, regressed and unchanged images, not just the average. More epochs is the planned change; no label-improvement claim follows.");
  await shot("27-comparison-outcomes");
  const report = await json(`/api/runs/compare?${params}`);
  const evaluations = {};
  for (const [label, run] of [["baseline", baseline], ["candidate", candidate]]) {
    const evaluation = await json(`/api/run/evaluation?${new URLSearchParams({ url: run.url, split: "valid", confidence: "0.25" })}`);
    evaluations[label] = { headline: evaluation.headline, images: evaluation.images,
      classes: evaluation.classes, split: evaluation.split, set: evaluation.set };
  }
  const retain = run => ({ name: run.name, status: run.status, created: run.created,
    parameters: Object.fromEntries(Object.entries(run.parameters).filter(([key]) =>
      !["weights", "train_table", "valid_table", "test_table", "release_id"].includes(key))),
    last_metrics: run.last_metrics, history: run.history });
  await writeFile(path.join(output, "evidence.json"), JSON.stringify({
    recorded: new Date().toISOString(), project, sample: "aerial-mini", actual_training: true,
    limits: "One local GPU, one seed, 96 training and 24 validation images; no independent test, no model-quality or significance claim.",
    experiment: "Same frozen input versions and nominal recipe, changing epochs from 3 to 12. Practice annotation changes were restored and were NOT training inputs.",
    sample_sha256: "2641dcdfbd88fea0bea27b59689f68b3b9a1d1fbd4b3d8c4da1a2c62789efa5d",
    runs: { baseline: retain(baseline), candidate: retain(candidate) }, evaluations,
    comparison: { headline: report.headline, interpretation: report.interpretation,
      checks: report.checks, policy: report.policy, counts: report.samples?.counts,
      shared: report.samples?.shared },
  }, null, 2) + "\n");
  await cue("The downloadable evidence records the actual numbers, including poor results. Approval of data is separate from accepting a model.");
}

export async function handoff(env) {
  const { page, goto, cue, shot, project, imagesRoute } = env;
  await goto(imagesRoute);
  await page.locator(".image-card").first().waitFor();
  await page.getByRole("button", { name: "Create dataset", exact: true }).click();
  const create = page.getByRole("dialog", { name: "Create exploratory dataset version" });
  await create.getByLabel("Name", { exact: true }).fill("aerial-reviewed-excerpt");
  await create.getByLabel("Description", { exact: true }).fill("Two inspected images only: one train / one valid. Approval/export demonstration, NOT a sufficient training or evaluation dataset.");
  await create.getByText("Use only verified", { exact: true }).click();
  await cue("Create a verified-only excerpt: just the two images actually inspected. This is not approval of the other 118 images.");
  await shot("28-verified-excerpt");
  await create.getByRole("button", { name: "Create dataset", exact: true }).click();
  await goto(`/p/${project}/datasets`);
  const release = page.locator(".release-panel").filter({ hasText: "aerial-reviewed-excerpt" });
  await release.getByRole("button", { name: "Approve…", exact: true }).click();
  await page.getByRole("button", { name: "Check and approve", exact: true }).click();
  await expect(release.getByText("Approved", { exact: true })).toBeVisible();
  await cue("Approval pins those exact annotations and media. It records a review decision; it does not certify model quality or dataset size.");
  await shot("29-approved-excerpt");
  await release.getByRole("button", { name: "Export", exact: true }).click();
  const exportDialog = page.getByRole("dialog", { name: "Export aerial-reviewed-excerpt", exact: true });
  await exportDialog.getByText("Copy them", { exact: true }).click();
  await cue("Export COCO with Copy them for a portable handoff. Linked images break when the original files are unavailable.");
  await shot("30-export-options");
  await exportDialog.getByRole("button", { name: "Write 2 images" }).click();
  await page.getByRole("dialog", { name: "Written", exact: true }).waitFor();
  await cue("Confirm the output folder and the one-image train and valid splits. An export is not a backup of reviews, runs or approval history.");
  await shot("31-export-complete");
}

export async function restored(env) {
  const { page, goto, cue, shot, project, imagesRoute } = env;
  if (project !== "aerial-restored") throw new Error("Point the recording at the separate, actually restored rehearsal project.");
  await goto(`/p/${project}`);
  await expect(page.locator("main h1")).toContainText(project);
  await cue("The offline backup and restore commands finished before this recording. This is the separate restored project, not the original.");
  await shot("32-restored-project");
  await goto(imagesRoute);
  await page.locator(".image-card").first().waitFor();
  await cue("Open the restored media. All 120 image hashes were checked; the references now point inside the rehearsal workspace.");
  await shot("33-restored-images");
  await goto(`/p/${project}/datasets`);
  const release = page.locator(".release-panel").filter({ hasText: "aerial-reviewed-excerpt" });
  await expect(release.getByText("Approved", { exact: true })).toBeVisible();
  await cue("Check the exploratory baseline and the approved two-image excerpt. A verified restore is stronger evidence than merely creating a ZIP.");
  await shot("34-restored-approval");
}