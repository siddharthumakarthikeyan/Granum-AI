// Keep the input list/hash framing in sync with build_provenance.py; tested cross-language.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(web, "../src/granum/service/static");

function hashTree(root, paths, excluded = []) {
  const files = [];
  const walk = (path) => {
    if (!existsSync(path)) return;
    if (statSync(path).isDirectory()) {
      for (const name of readdirSync(path)) walk(join(path, name));
    } else {
      const name = relative(root, path).split("\\").join("/");
      if (!excluded.includes(name)) files.push([name, path]);
    }
  };
  for (const path of paths) walk(join(root, path));
  files.sort((a, b) => Buffer.compare(Buffer.from(a[0]), Buffer.from(b[0])));
  const hash = createHash("sha256");
  for (const [name, path] of files) hash.update(name).update("\0").update(readFileSync(path)).update("\0");
  return hash.digest("hex");
}

if (!existsSync(join(output, "index.html"))) throw new Error("No dashboard build to stamp");
const stamp = {
  version: 1,
  source_sha256: hashTree(web, ["src", "public", "scripts", "package.json", "package-lock.json", "tsconfig.json", "vite.config.ts"]),
  bundle_sha256: hashTree(output, ["."], ["build-stamp.json"]),
  node: process.version,
};
writeFileSync(join(output, "build-stamp.json"), JSON.stringify(stamp, null, 2) + "\n");