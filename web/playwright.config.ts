import { defineConfig } from "@playwright/test";

const images = Number(process.env.GRANUM_BENCHMARK_IMAGES ?? "120");
if (!Number.isInteger(images) || images < 1 || images > 25000) throw new Error("Use 1–25000 benchmark images");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  use: { baseURL: "http://127.0.0.1:18860", headless: true, trace: "retain-on-failure" },
  webServer: {
    command: `python3 ../tools/benchmark_workflows.py --serve --images ${images} --epochs 2 --port 18860`,
    url: "http://127.0.0.1:18860/api/health",
    timeout: 120000,
    reuseExistingServer: false,
  },
});