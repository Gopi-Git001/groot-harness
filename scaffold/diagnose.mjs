// Harness-owned crash diagnosis. Production React reports crashes as "Minified React error #N" with no
// component name. This builds the page with development React into dist-dev/, loads it once, and prints
// the full error messages (e.g. "Check the render method of `PreOrderForm`") as JSON.
process.env.NODE_ENV = "development";
const { build, preview } = await import("vite");
const { chromium } = await import("playwright");

await build({ mode: "development", logLevel: "silent", build: { outDir: "dist-dev", minify: false } });
const server = await preview({ build: { outDir: "dist-dev" }, preview: { port: 4322, strictPort: false }, logLevel: "silent" });
const browser = await chromium.launch();
const errors = [];
try {
  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    // Keep the message and React's component stack, which name the file at fault.
    const text = m.text().split(String.fromCharCode(10)).slice(0, 12).join("\n").slice(0, 1500);
    if (!errors.includes(text)) errors.push(text);
  });
  page.on("pageerror", (e) => { const t = String(e.message).slice(0, 800); if (!errors.includes(t)) errors.push(t); });
  await page.goto(server.resolvedUrls.local[0], { waitUntil: "networkidle" });
} finally {
  await browser.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}
console.log(JSON.stringify({ errors: errors.slice(0, 5) }));
