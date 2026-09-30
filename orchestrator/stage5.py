"""Stage 5: test, debug, and evaluate the Stage 4 page.

1. Testing role (GPT-OSS + real run_tests tool) writes a Playwright suite for this page and runs it.
2. Debugging role gets each failing test, the relevant source, and the spec section it maps to,
   and returns a minimal root-cause fix. A fix that breaks the build is reverted. Failing tests are
   re-run after each attempt; two failed attempts make a known limitation. A final full run
   catches regressions.
3. Evaluation role scores structure, fidelity, polish and checks spec compliance.
"""

import json
import re
from dataclasses import dataclass

from agent import run_tool_loop
from assembler import Page, normalize_page
from brain import Brain
from config import RESULTS_DIR, WORKSPACE_DIR
from loop import spec_sections
from pagefiles import ALLOWED_PACKAGES, HARNESS_OWNED, extract_files, render_files
from roles import Role, loop_prompt
from tools.browser import build_page, prepare_build_dir, run_test_file, verify_build, write_page
from tools.registry import ToolContext

MAX_ATTEMPTS = 2
STAGE4_PAGE = RESULTS_DIR / "stage-4-page.md"
PAGE_PATH = RESULTS_DIR / "stage-5-page.md"
SUITE_COPY = RESULTS_DIR / "stage-5-tests.mjs"
TESTS_PATH = RESULTS_DIR / "stage-5-test-results.md"
DEBUG_PATH = RESULTS_DIR / "stage-5-debug-log.md"
EVAL_PATH = RESULTS_DIR / "stage-5-evaluation.md"

TESTER = Role("stage5-tester", "tester", "")
DEBUGGER = Role("stage5-debugger", "debugger", "")
EVALUATOR = Role("stage5-evaluator", "evaluator", "")


@dataclass
class DebugEntry:
    test_id: str
    attempt: int
    error: str
    root_cause: str
    patched: list[str]
    outcome: str = "pending re-run"


def run_stage5(brain: Brain, spec: str) -> dict:
    # A rerun continues from the last Stage 5 page so earlier debug fixes are kept.
    source = PAGE_PATH if PAGE_PATH.exists() else STAGE4_PAGE
    if not source.exists():
        raise SystemExit("No Stage 4 page (results/stage-4-page.md). Run --stage 4 first.")
    print(f"Starting from results/{source.name}")
    page = Page(extract_files(source.read_text(encoding="utf-8")), {})

    print("Preparing build/ ...")
    prepare_build_dir()
    write_page(page.files)
    report = verify_build()
    if not report.get("build", {}).get("ok"):
        raise SystemExit("The Stage 4 page does not build; Stage 5 needs a working page.")

    print("\n== Testing role: writing the suite ==")
    suite = _write_suite(brain, spec, page, report.get("outline", ""))
    initial = _run(suite)
    results = {t["id"]: t for t in initial}
    print(f"  {_counts(initial)}")

    log: list[DebugEntry] = []
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            failing = [t for t in results.values() if t["status"] == "fail"]
            if not failing:
                break
            print(f"\n== Debugging role: attempt {attempt}, {len(failing)} failing tests ==")
            entries = [_debug_one(brain, spec, page, suite, test, attempt) for test in failing]
            rerun = {t["id"]: t for t in _run(suite, [t["id"] for t in failing])}
            for entry in entries:
                after = rerun.get(entry.test_id)
                results[entry.test_id] = after or results[entry.test_id]
                entry.outcome = "fixed" if after and after["status"] == "pass" else \
                    f"still failing: {(after or {}).get('error', 'not re-run')[:200]}"
                print(f"    {entry.test_id}: {entry.outcome}")
            log += entries

        print("\n== Final full run (regression check) ==")
        final = _run(suite)
        print(f"  {_counts(final)}")
    finally:
        PAGE_PATH.write_text(render_files(page.files), encoding="utf-8")
        DEBUG_PATH.write_text(render_debug_log(log), encoding="utf-8")

    TESTS_PATH.write_text(render_test_results(initial, final, log), encoding="utf-8")

    print("\n== Evaluation role ==")
    outline = verify_build().get("outline", "")
    evaluation = _evaluate(brain, spec, page, TESTS_PATH.read_text(encoding="utf-8"),
                           DEBUG_PATH.read_text(encoding="utf-8"), outline)
    EVAL_PATH.write_text(render_evaluation(evaluation), encoding="utf-8")
    scores = evaluation.get("scores", {})
    print(f"  scores: {scores}")
    print(f"\nStage 5 complete: {_counts(final)}")
    print(f"Results: results/{TESTS_PATH.name}, results/{DEBUG_PATH.name}, results/{EVAL_PATH.name}")
    return evaluation


# --- 1. testing ------------------------------------------------------------

def _write_suite(brain: Brain, spec: str, page: Page, outline: str):
    ctx = ToolContext(TESTER.name, WORKSPACE_DIR / TESTER.name)
    messages = [
        {"role": "system", "content": "You are the Stage 5 testing sub-agent."},
        {"role": "user", "content": loop_prompt("tester", spec=spec, outline=outline or "(unavailable)",
                                                inventory=page.inventory())},
    ]
    tool_log: list[str] = []
    run_tool_loop(brain, TESTER, messages, ctx, tool_log, max_tokens=brain.config.merge_max_tokens)
    suite = (ctx.workspace / "tests.mjs").resolve()
    if not suite.is_file():
        raise RuntimeError("testing role never wrote tests.mjs")
    SUITE_COPY.write_text(suite.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  suite written ({len(tool_log)} tool calls); copy at results/{SUITE_COPY.name}")
    return suite


def _run(suite, ids: list[str] | None = None) -> list[dict]:
    result = run_test_file(suite, ids)
    if not result.get("build", {}).get("ok"):
        raise RuntimeError(f"page does not build: {result['build'].get('output', '')[:500]}")
    if result.get("loadError") or result.get("runnerCrashed"):
        raise RuntimeError(f"test suite could not run: {result.get('loadError') or result.get('runnerCrashed')}")
    return result["tests"]


# --- 2. debugging ----------------------------------------------------------

def _debug_one(brain: Brain, spec: str, page: Page, suite, test: dict, attempt: int) -> DebugEntry:
    sections = spec_sections(spec)
    section = sections.get(test.get("specSection", ""), spec)
    prompt = loop_prompt(
        "debugger", attempt=str(attempt), id=test["id"], test_name=test["name"], error=test["error"][:2500],
        test_code=_test_source(suite.read_text(encoding="utf-8"), test["id"]),
        spec_section=f"{test.get('specSection') or 'Full spec'}\n{section}",
        inventory=page.inventory(), packages=", ".join(sorted(ALLOWED_PACKAGES)),
    )
    ctx = ToolContext(DEBUGGER.name, WORKSPACE_DIR / DEBUGGER.name)
    messages = [{"role": "system", "content": "You are the Stage 5 debugging sub-agent."},
                {"role": "user", "content": prompt}]
    reply = run_tool_loop(brain, DEBUGGER, messages, ctx, [], max_tokens=brain.config.merge_max_tokens)

    root_cause = _section(reply, "Root cause") or "(not stated)"
    changed = {p: c for p, c in extract_files(_section(reply, "Fix") or reply).items()
               if p.startswith("src/") and p not in HARNESS_OWNED}
    entry = DebugEntry(test["id"], attempt, test["error"], root_cause, sorted(changed))
    if not changed:
        entry.outcome = "no fix proposed"
        print(f"  {test['id']}: no fix proposed")
        return entry

    backup = dict(page.files)
    page.files.update(changed)
    normalize_page(page)
    write_page(page.files)
    if not build_page()["ok"]:  # Never keep a fix that breaks the build.
        page.files.clear()
        page.files.update(backup)
        write_page(page.files)
        entry.patched = []
        entry.outcome = "fix broke the build; reverted"
    print(f"  {test['id']}: patched {', '.join(entry.patched) or 'nothing (reverted)'}")
    return entry


def _test_source(suite_text: str, test_id: str) -> str:
    """The lines of the suite around one test case."""
    lines = suite_text.splitlines()
    hit = next((i for i, line in enumerate(lines) if re.search(rf"""id:\s*['"]{re.escape(test_id)}['"]""", line)), None)
    if hit is None:
        return "(test source not found)"
    return "\n".join(lines[max(0, hit - 2):hit + 40])


# --- 3. evaluation ---------------------------------------------------------

def _evaluate(brain: Brain, spec: str, page: Page, tests: str, debug: str, outline: str) -> dict:
    prompt = loop_prompt("evaluator", spec=spec, tests=tests, debug=debug, outline=outline or "(unavailable)",
                         source=render_files(page.files))
    messages = [{"role": "system", "content": "You are the Stage 5 evaluation sub-agent. Reply with JSON only."},
                {"role": "user", "content": prompt}]
    for _ in range(3):
        reply = brain.chat(messages, max_tokens=brain.config.merge_max_tokens).content or ""
        try:
            data = json.loads(re.search(r"\{.*\}", reply, re.DOTALL).group(0))
            if isinstance(data.get("scores"), dict):
                return data
        except (AttributeError, ValueError):
            pass
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "Reply with only the evaluation JSON object described above."}]
    raise RuntimeError("evaluation role returned no valid JSON")


# --- reports ---------------------------------------------------------------

def _counts(tests: list[dict]) -> str:
    by = {s: sum(1 for t in tests if t["status"] == s) for s in ("pass", "fail", "skipped")}
    return f"{by['pass']} passed, {by['fail']} failed, {by['skipped']} skipped of {len(tests)} tests"


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\s*\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")[:220]


def render_test_results(initial: list[dict], final: list[dict], log: list[DebugEntry]) -> str:
    before = {t["id"]: t["status"] for t in initial}
    debugged = {e.test_id for e in log}
    lines = ["# Stage 5 Test Results", "",
             f"- Initial run: {_counts(initial)}", f"- Final run: {_counts(final)}", "",
             "| Test | Category | Width | Initial | Final | Error (final) |", "|---|---|---|---|---|---|"]
    for t in final:
        mark = t["status"].upper() if t["status"] != "skipped" else "SKIPPED"
        regression = " (regression)" if before.get(t["id"]) == "pass" and t["status"] == "fail" else ""
        lines.append(f"| `{t['id']}` {_cell(t['name'])} | {t['category']} | {t['width']} | "
                     f"{before.get(t['id'], '-')} | {mark}{regression} | {_cell(t['error'])} |")
    limitations = [t for t in final if t["status"] == "fail" and t["id"] in debugged]
    lines += ["", "## Known limitations (two failed fix attempts)", ""]
    lines += [f"- `{t['id']}` {t['name']}: {_cell(t['error'])}" for t in limitations] or ["- (none)"]
    return "\n".join(lines) + "\n"


def render_debug_log(log: list[DebugEntry]) -> str:
    lines = ["# Stage 5 Debug Log", ""]
    if not log:
        return "\n".join(lines + ["No failing tests: nothing to debug."]) + "\n"
    for e in log:
        lines += [f"## `{e.test_id}` attempt {e.attempt}", "",
                  f"- Error: {_cell(e.error)}", f"- Root cause: {_cell(e.root_cause)}",
                  f"- Patched: {', '.join(e.patched) or '(nothing)'}", f"- Outcome: {e.outcome}", ""]
    still = sorted({e.test_id for e in log if e.attempt == MAX_ATTEMPTS and not e.outcome.startswith("fixed")})
    lines += ["## Known limitations", ""] + ([f"- `{t}`" for t in still] or ["- (none)"])
    return "\n".join(lines) + "\n"


def render_evaluation(data: dict) -> str:
    scores = data.get("scores", {})
    overall = round(sum(scores.values()) / len(scores)) if scores else 0
    lines = ["# Stage 5 Evaluation", "",
             f"**Overall: {overall}/100** (structure {scores.get('structure')}, fidelity {scores.get('fidelity')}, "
             f"polish {scores.get('polish')})", "", data.get("summary", ""), "",
             "## Spec compliance", "", "| Requirement | Met | Evidence |", "|---|---|---|"]
    lines += [f"| {_cell(c.get('requirement', ''))} | {'yes' if c.get('met') else 'NO'} | {_cell(c.get('evidence', ''))} |"
              for c in data.get("compliance", [])]
    lines += ["", "## Extras (not in the spec)", ""] + ([f"- {x}" for x in data.get("extras", [])] or ["- (none)"])
    lines += ["", "## Remaining gaps", ""] + ([f"- {g}" for g in data.get("gaps", [])] or ["- (none)"])
    return "\n".join(lines) + "\n"
