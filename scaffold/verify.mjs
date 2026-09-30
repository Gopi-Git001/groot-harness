// Harness-owned headless verification. Serves dist/ with `vite preview`, loads the page at each
// viewport width in Chromium, exercises every aria-expanded toggle, and prints one JSON report.
import { chromium } from "playwright";
import { preview } from "vite";

const WIDTHS = [360, 768, 1024, 1440];
const TOGGLE_WIDTHS = new Set([360, 1440]);
const clip = (s, n = 400) => String(s ?? "").slice(0, n);

const result = {
  url: "",
  console: [],
  pageErrors: [],
  rejections: [],
  failedRequests: [],
  viewports: {},
  landmarks: {},
  brokenAnchors: [],
  brokenImages: [],
  duplicateIds: [],
  toggles: [],
  outline: "",
};

// One entry per distinct message (first line), listing the widths it occurred at.
function record(list, entry) {
  const key = entry.text.split("\n")[0];
  const found = list.find((e) => e.text.split("\n")[0] === key);
  if (!found) list.push({ text: entry.text, widths: [entry.width], ...(entry.type ? { type: entry.type } : {}) });
  else if (!found.widths.includes(entry.width)) found.widths.push(entry.width);
}

const server = await preview({ preview: { port: 4317, strictPort: false, open: false }, logLevel: "silent" });
result.url = server.resolvedUrls.local[0];
const browser = await chromium.launch();

try {
  for (const width of WIDTHS) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    page.on("console", (m) => {
      if (m.type() === "error" || m.type() === "warning") record(result.console, { type: m.type(), text: clip(m.text()), width });
    });
    page.on("pageerror", (e) => record(result.pageErrors, { text: clip(`${e.message}\n${e.stack ?? ""}`, 800), width }));
    page.on("requestfailed", (r) => record(result.failedRequests, { text: `${r.failure()?.errorText ?? "failed"} ${r.url()}`, width }));
    page.on("response", (r) => {
      if (r.status() >= 400) record(result.failedRequests, { text: `HTTP ${r.status()} ${r.url()}`, width });
    });
    await page.addInitScript(() => {
      window.__rejections = [];
      window.addEventListener("unhandledrejection", (e) =>
        window.__rejections.push(String(e.reason?.stack ?? e.reason?.message ?? e.reason)));
    });

    await page.goto(result.url, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);

    result.viewports[width] = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      const describe = (el) =>
        `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${el.classList.length ? "." + [...el.classList].slice(0, 3).join(".") : ""}`;
      const offenders = sw > vw + 1
        ? [...document.querySelectorAll("body *")]
            .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1; })
            .slice(0, 8)
            .map((el) => `${describe(el)} (right edge ${Math.round(el.getBoundingClientRect().right)}px)`)
        : [];
      return { horizontalOverflow: sw > vw + 1, scrollWidth: sw, clientWidth: vw, offenders,
               rootTextLength: document.getElementById("root")?.innerText.trim().length ?? 0 };
    });

    if (TOGGLE_WIDTHS.has(width)) {
      const toggles = page.locator("[aria-expanded]");
      const count = await toggles.count();
      for (let i = 0; i < count; i++) {
        const toggle = toggles.nth(i);
        if (!(await toggle.isVisible())) continue;
        const label = clip((await toggle.innerText().catch(() => "")) || (await toggle.getAttribute("aria-label")) || "", 60);
        const before = await toggle.getAttribute("aria-expanded");
        await toggle.click({ timeout: 2000 }).catch(() => {});
        await page.waitForTimeout(150);
        const after = await toggle.getAttribute("aria-expanded").catch(() => before);
        result.toggles.push({ width, label, before, after, toggled: before !== after });
        await page.keyboard.press("Escape");
        if ((await toggle.getAttribute("aria-expanded").catch(() => before)) !== before) {
          await toggle.click({ timeout: 2000 }).catch(() => {});
        }
      }
    }

    if (width === 1440) {
      Object.assign(result, await page.evaluate(() => {
        const count = (sel) => document.querySelectorAll(sel).length;
        const landmarks = { header: count("header"), nav: count("nav"), main: count("main"), footer: count("footer"),
                            h1: count("h1"), section: count("section") };
        const brokenAnchors = [...document.querySelectorAll('a[href^="#"]')]
          .map((a) => a.getAttribute("href"))
          .filter((href) => href.length > 1 && !document.getElementById(decodeURIComponent(href.slice(1))));
        const outline = [...document.querySelectorAll("header,nav,main,section,footer,h1,h2,h3,button,a,[role=region]")]
          .map((el) => {
            const tag = el.tagName.toLowerCase();
            const text = (el.innerText || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ");
            const short = ["h1", "h2", "h3", "button", "a"].includes(tag) ? text.slice(0, 70) : "";
            return `${tag}${el.id ? "#" + el.id : ""}${short ? ` "${short}"` : ""}`;
          })
          .join("\n")
          .slice(0, 6000);
        // An <img> that finished loading with no pixels failed (missing file, or the SPA fallback served HTML).
        const brokenImages = [...document.images]
          .filter((img) => img.complete && img.naturalWidth === 0)
          .map((img) => `${img.getAttribute("src")} (alt: "${img.alt}")`);
        const ids = [...document.querySelectorAll("[id]")].map((el) => el.id);
        const duplicateIds = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))]
          .map((id) => `#${id} (${ids.filter((x) => x === id).length} elements)`);
        return { landmarks, brokenAnchors: [...new Set(brokenAnchors)], brokenImages, duplicateIds, outline };
      }));
    }

    for (const text of await page.evaluate(() => window.__rejections)) record(result.rejections, { text: text.slice(0, 800), width });
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}

console.log(JSON.stringify(result));
