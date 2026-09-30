"""Headless browser tooling: build the merged page and verify it with Playwright (Node).

The build dir (build/ in repo mode, <project>/site/ in CLI mode) is a copy of scaffold/
(harness-owned config + verify.mjs + run-tests.mjs) plus the merged page's src/ files and the
project's assets/ (served at /assets/...). node_modules and the Chromium download are kept across runs.
"""

import json
import shutil
import subprocess
from pathlib import Path

from tools.paths import ASSETS_DIR, BUILD_DIR, SCAFFOLD_DIR

RESULT_PATH = BUILD_DIR / "verify-result.json"
HARNESS_OWNED = {"src/main.tsx"}
TAILWIND_LAYERS = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"
BUILD_TIMEOUT = 300
OUTPUT_TAIL = 4000


def _run(*args: str, timeout: int = BUILD_TIMEOUT) -> subprocess.CompletedProcess:
    exe = shutil.which(args[0])
    if not exe:
        raise RuntimeError(f"'{args[0]}' not found on PATH")
    return subprocess.run([exe, *args[1:]], cwd=BUILD_DIR, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def prepare_build_dir() -> None:
    """Copy the scaffold into the build dir and install dependencies once."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for item in SCAFFOLD_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, BUILD_DIR / item.name)
    if not (BUILD_DIR / "node_modules").is_dir():
        print("  installing page dependencies (first run)...")
        for step in (("npm", "install", "--no-audit", "--no-fund"), ("npx", "playwright", "install", "chromium")):
            done = _run(*step, timeout=900)
            if done.returncode != 0:
                raise RuntimeError(f"{' '.join(step)} failed:\n{(done.stdout + done.stderr)[-OUTPUT_TAIL:]}")


def write_page(files: dict[str, str]) -> None:
    """Replace the build's src with the scaffold's src plus the merged page files, and publish assets."""
    src = BUILD_DIR / "src"
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(SCAFFOLD_DIR / "src", src)
    if ASSETS_DIR.is_dir():  # The user's own images/fonts, served at /assets/<name>.
        shutil.copytree(ASSETS_DIR, BUILD_DIR / "public" / "assets", dirs_exist_ok=True)
    for path, content in files.items():
        if path in HARNESS_OWNED or not path.startswith("src/"):
            continue
        if path == "src/index.css" and "@tailwind base" not in content:
            content = TAILWIND_LAYERS + content
        target = BUILD_DIR / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def verify_build() -> dict:
    """Build the page and run verify.mjs. Returns the raw report; also saved to build/verify-result.json."""
    build = build_page()
    if not build["ok"]:
        report = {"build": build}
    else:
        run = _run("node", "verify.mjs")
        lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
        if run.returncode != 0 or not lines:
            report = {"build": {"ok": True}, "verifyCrashed": (run.stdout + run.stderr)[-OUTPUT_TAIL:]}
        else:
            report = {"build": {"ok": True}, **json.loads(lines[-1])}
    RESULT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def playwright(ctx, **_args) -> str:
    """Tool: build the current merged page in build/ and return the headless verification report."""
    return json.dumps(verify_build(), indent=1)[:20_000]


def build_page() -> dict:
    """Build build/ once: {"ok": bool, "output": str}.

    Rollup only warns when an imported name is missing ("X is not exported by Y"), but the page then
    renders `undefined` and crashes, so those warnings count as build errors here."""
    build = _run("npm", "run", "build")
    output = build.stdout + build.stderr
    if build.returncode != 0:
        start = output.find("error during build")
        return {"ok": False, "output": output[start if start >= 0 else 0:][:OUTPUT_TAIL]}
    missing = [line.strip() for line in output.splitlines() if "is not exported by" in line]
    if missing:
        return {"ok": False, "output": "error during build: missing exports\n" + "\n".join(missing)[:OUTPUT_TAIL]}
    return {"ok": True}


def run_test_file(test_file: Path, ids: list[str] | None = None) -> dict:
    """Build the page and run a Stage 5 test suite (optionally only some ids) with run-tests.mjs."""
    build = build_page()
    if not build["ok"]:
        return {"build": build, "tests": []}
    run = _run("node", "run-tests.mjs", str(test_file), ",".join(ids or []))
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    if not lines:
        return {"build": build, "runnerCrashed": (run.stdout + run.stderr)[-OUTPUT_TAIL:], "tests": []}
    return {"build": build, **json.loads(lines[-1])}


def run_tests(ctx, ids: str = "") -> str:
    """Tool: build the page and run the tests.mjs suite in your workspace; ids narrows the run."""
    test_file = ctx.workspace / "tests.mjs"
    if not test_file.is_file():
        return "Error: write your suite to tests.mjs in your workspace first (write_file path 'tests.mjs')."
    selected = [i.strip() for i in ids.split(",") if i.strip()]
    return json.dumps(run_test_file(test_file.resolve(), selected), indent=1)[:20_000]
