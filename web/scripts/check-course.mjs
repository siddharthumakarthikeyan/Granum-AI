/** Browser qualification for the generated public course; no mocked media or responses. */
import { chromium, expect } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const website = path.resolve(repo, "../granum-website");
const output = path.join(repo, "build/course-recordings/docs-preview");
const origin = process.env.GRANUM_DOCS_URL ?? "http://127.0.0.1:18863";
const index = JSON.parse(await readFile(path.join(website, "public/docs/search.json"), "utf8"));
const lessons = index.filter(page => page.url.startsWith("/docs/course/"));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
let videos = 0;
try {
  for (const [name, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 375, height: 812 }]]) {
    const context = await browser.newContext({ viewport, reducedMotion: "reduce" });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    for (const lesson of lessons) {
      const response = await page.goto(origin + lesson.url);
      expect(response.status()).toBe(200);
      await expect(page.locator("main h1")).toHaveText(lesson.title);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: ${lesson.url} overflows`).toBeTruthy();
      for (const image of await page.locator("article img").all()) {
        await image.scrollIntoViewIfNeeded();
        await expect(image).toBeVisible();
        await image.evaluate(image => image.decode());
        expect(await image.evaluate(image => image.naturalWidth)).toBeGreaterThan(0);
      }
      if (name === "desktop") {
        for (const video of await page.locator("video").all()) {
          await video.scrollIntoViewIfNeeded();
          await video.evaluate(async video => { video.muted = true; video.load(); await video.play(); });
          await page.waitForFunction(video => video.currentTime > 0.1 && video.querySelector("track").readyState === 2, await video.elementHandle());
          const state = await video.evaluate(video => {
            video.pause();
            return { duration: video.duration, width: video.videoWidth, height: video.videoHeight,
              captions: video.textTracks[0].cues.length, error: video.error?.message };
          });
          expect(state.error).toBeUndefined();
          expect(state.duration).toBeGreaterThan(5);
          expect(state.width).toBe(1440);
          expect(state.height).toBe(960);
          expect(state.captions).toBeGreaterThan(0);
          const source = await video.locator("source").getAttribute("src");
          const metadata = JSON.parse(await readFile(path.join(website, "public", source.replace(/^\//, "").replace(/\.mp4$/, ".json")), "utf8"));
          expect(Math.abs(state.duration - metadata.duration)).toBeLessThan(0.06);
          expect(metadata.cues.at(-1).at).toBeLessThan(state.duration);
          videos++;
        }
      }
      if (lesson.url.endsWith("/start") || lesson.url.endsWith("/results")) {
        await page.evaluate(() => scrollTo(0, 0));
        await page.screenshot({ path: path.join(output, `${name}-${lesson.url.split("/").pop()}.png`), fullPage: false });
      }
    }
    await page.goto(origin + "/docs");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
    await page.getByRole("button", { name: "Search documentation", exact: true }).click();
    const search = page.getByRole("searchbox", { name: "Search documentation", exact: true });
    await search.fill("relocated references byte hashes");
    await expect(page.locator("[data-search-results] a[href='/docs/course/backup']")).toBeVisible();
    await search.fill("projects/<project>");
    await expect(page.locator("[data-search-results]")).toContainText("<project>");
    await expect(page.locator("[data-search-results] project")).toHaveCount(0);
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => Boolean(document.activeElement.closest("[data-search-panel]")))).toBeTruthy();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "Search documentation", exact: true })).toBeFocused();
    if (name === "mobile") {
      const menu = page.getByRole("button", { name: "Menu", exact: true });
      await expect(menu).toBeVisible();
      await menu.click();
      await expect(menu).toHaveAttribute("aria-expanded", "true");
      await page.locator("#doc-sidebar a[href='/docs/course/start']").click();
      await expect(page.locator("main h1")).toHaveText("Start the guided course");
    }
    expect(errors).toEqual([]);
    console.log(`${name}: ${lessons.length} lessons, images, layout, navigation and search passed.`);
    await context.close();
  }
  expect(videos).toBe(10);
  console.log(`${videos} actual MP4s decoded and played with loaded captions. Preview screenshots: ${output}`);
} finally {
  await browser.close();
}