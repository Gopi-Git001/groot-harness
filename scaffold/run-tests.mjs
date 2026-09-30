// Harness-owned Stage 5 test runner. Usage: node run-tests.mjs <tests.mjs> [id,id,...]
// tests.mjs must `export default` an array of test cases:
//   { id, name, category, specSection, width?, skip?, run: async ({ page, assert, errors, url }) => {} }
// Each case gets a fresh page at its width; `errors` collects console errors and page errors.
import { chromium } from "playwright";
import { preview } from "vite";
import { pathToFileURL } from "node:url";

const [file, only = ""] = process.argv.slice(2);
const ids = only ? new Set(only.split(",").map((s) => s.trim()).filter(Boolean)) : null;
const TEST_TIMEOUT = 20000;

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

let tests;
try {
  tests = (await import(`${pathToFileURL(file).href}?t=${Date.now()}`)).default;
  if (!Array.isArray(tests)) throw new Error("tests.mjs must `export default` an array of test cases");
} catch (e) {
  console.log(JSON.stringify({ loadError: String(e?.stack ?? e).slice(0, 1500), tests: [] }));
  process.exit(0);
}

const server = await preview({ preview: { port: 4319, strictPort: false, open: false }, logLevel: "silent" });
const url = server.resolvedUrls.local[0];
const browser = await chromium.launch();
const results = [];

try {
  for (const t of tests) {
    if (ids && !ids.has(t.id)) continue;
    const base = { id: t.id, name: t.name, category: t.category ?? "", specSection: t.specSection ?? "", width: t.width ?? 1280 };
    if (t.skip) {
      results.push({ ...base, status: "skipped", error: String(t.skip), ms: 0 });
      continue;
    }
    const page = await browser.newPage({ viewport: { width: base.width, height: t.height ?? 900 } });
    page.setDefaultTimeout(5000);
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
    page.on("pageerror", (e) => errors.push(String(e.message).slice(0, 300)));
    const started = Date.now();
    let status = "pass";
    let error = "";
    try {
      await page.goto(url, { waitUntil: "networkidle" });
      let timer;
      await Promise.race([
        t.run({ page, assert, errors, url }),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`timed out after ${TEST_TIMEOUT}ms`)), TEST_TIMEOUT); }),
      ]).finally(() => clearTimeout(timer));
    } catch (e) {
      status = "fail";
      // Keep Playwright's call log: lines like "<div ...> intercepts pointer events" name the root cause.
      error = String(e?.message ?? e).replace(/\x1b\[[0-9;]*m/g, "").slice(0, 2500);
    }
    results.push({ ...base, status, error, ms: Date.now() - started });
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}

console.log(JSON.stringify({ tests: results }));
