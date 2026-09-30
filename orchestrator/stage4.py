"""Stage 4: assemble the Stage 3 slices into one page, verify it in headless Chromium, and fix.

Fix loop: each verifier error goes to its owning role, which patches the merged page files.
One fix pass per error per round; an error that survives two fix attempts is logged as a
known limitation. Re-verify after every round; at most MAX_FIX_ROUNDS rounds.
"""

import re
from dataclasses import dataclass, field

from agent import fix
from assembler import APP, Assembler, Page, normalize_page, render_merge_report
from brain import Brain
from config import RESULTS_DIR
from loop import LOG_PATH as STAGE3_LOG, STAGE3_DIR, code_section
from pagefiles import ALLOWED_PACKAGES, HARNESS_OWNED, extract_files, render_files
from parallel import run_parallel
from roles import Role
from tools.browser import prepare_build_dir, write_page
from verifier import Issue, Verification, verify

MAX_FIX_ROUNDS = 3
MAX_ATTEMPTS = 2
PAGE_PATH = RESULTS_DIR / "stage-4-page.md"
MERGE_REPORT_PATH = RESULTS_DIR / "stage-4-merge-report.md"
REPORT_PATH = RESULTS_DIR / "stage-4-report.md"


@dataclass
class FixRound:
    number: int
    sent: dict[str, list[Issue]]
    patched: dict[str, list[str]] = field(default_factory=dict)
    changes: dict[str, str] = field(default_factory=dict)


def run_stage4(brain: Brain, spec: str, roles: dict[str, Role], workers: int) -> Verification:
    slices_dir = STAGE3_DIR / "slices"
    if not any(slices_dir.glob("*.md")):
        raise SystemExit("No Stage 3 slices in results/stage-3/slices. Run --stage 3 first.")

    print("Preparing build/ ...")
    prepare_build_dir()

    print("\n== Assemble ==")
    page, merge_report = Assembler(brain, spec, workers).run(slices_dir, _stage3_failures())
    PAGE_PATH.write_text(render_files(page.files), encoding="utf-8")
    MERGE_REPORT_PATH.write_text(render_merge_report(merge_report, page), encoding="utf-8")

    verifier = roles["verifier-headless-run"]
    attempts: dict[str, int] = {}
    passes: list[Verification] = []
    rounds: list[FixRound] = []
    last_done: tuple[int, Page] | None = None  # Last page that met the done criteria, to fall back to.
    final_index, reverted = 0, False

    def check(label: str) -> None:
        nonlocal last_done
        print(f"\n== Verify ({label}) ==")
        passes.append(_verify(brain, spec, page, verifier))
        if passes[-1].done:
            last_done = (len(passes) - 1, Page(dict(page.files), {k: list(v) for k, v in page.sources.items()}))

    try:
        check("pass 0")
        for number in range(1, MAX_FIX_ROUNDS + 1):
            # Keep spending fix rounds on non-blocking errors (layout, elements) even after the
            # done criteria pass; stop only when nothing fixable is left.
            current = passes[-1]
            if not current.build_ok:
                errors = [e for e in current.errors if e.category == "build"]
            elif current.blank:  # A crash blanks the page; everything else is a symptom of it.
                errors = [e for e in current.errors if e.category in ("console", "runtime", "rejection")]
            else:
                errors = current.errors
            fixable = [e for e in errors if attempts.get(e.key, 0) < MAX_ATTEMPTS]
            if not fixable:
                print("  no errors left" if not errors
                      else "  no fixable errors left (all remaining are known limitations)")
                break

            print(f"\n== Fix round {number}/{MAX_FIX_ROUNDS}: {len(fixable)} errors ==")
            rounds.append(_fix_round(number, fixable, page, brain, spec, roles, workers))
            for error in fixable:
                attempts[error.key] = attempts.get(error.key, 0) + 1
            PAGE_PATH.write_text(render_files(page.files), encoding="utf-8")
            check(f"pass {number}")

        final_index = len(passes) - 1
        if not passes[-1].done and last_done:  # A later fix broke a passing page: roll back.
            final_index, snapshot = last_done
            page.files, page.sources = snapshot.files, snapshot.sources
            write_page(page.files)
            PAGE_PATH.write_text(render_files(page.files), encoding="utf-8")
            reverted = True
            print(f"  later fixes broke the done criteria; reverted to the page from pass {final_index}")
    finally:  # Keep the error and fix log even if a later call fails.
        if passes:
            final_index = final_index if reverted else len(passes) - 1
            limitations = [e for e in passes[final_index].errors if attempts.get(e.key, 0) >= MAX_ATTEMPTS]
            REPORT_PATH.write_text(render_report(passes, rounds, limitations, final_index, reverted),
                                   encoding="utf-8")

    final = passes[final_index]
    print(f"\nStage 4 {'DONE' if final.done else 'NOT DONE'}: {_summary(final)}")
    print(f"Report: results/{REPORT_PATH.name}  |  Page: results/{PAGE_PATH.name}  |  "
          f"Merge report: results/{MERGE_REPORT_PATH.name}")
    return final


def _verify(brain: Brain, spec: str, page: Page, verifier: Role) -> Verification:
    result = verify(brain, spec, page, verifier)
    print(f"  {_summary(result)}")
    for e in result.errors:
        message = " ".join(e.message.split())[:140]
        print(f"    [{e.category}] {message} -> {e.owner} ({e.file or 'file unknown'})")
    return result


def _fix_round(number: int, fixable: list[Issue], page: Page, brain: Brain, spec: str,
               roles: dict[str, Role], workers: int) -> FixRound:
    by_owner: dict[str, list[Issue]] = {}
    for error in fixable:
        by_owner.setdefault(error.owner, []).append(error)
    fix_round = FixRound(number, by_owner)

    def task(owner: str, errors: list[Issue]):
        paths = [e.file for e in errors if e.file in page.files] or [APP]
        files = "\n\n".join(f"```\n// {p}\n{page.files[p]}```" for p in dict.fromkeys(paths))
        listed = "\n".join(f"{i}. [{e.category}] {e.message}" + (f" (file: {e.file})" if e.file else "")
                           for i, e in enumerate(errors, 1))
        return fix(roles[owner], brain, spec, listed, files, page.inventory(),
                   ", ".join(sorted(ALLOWED_PACKAGES)), number)

    replies = run_parallel({o: (lambda o=o, e=e: task(o, e)) for o, e in by_owner.items()}, workers)
    for owner, (reply, written) in replies.items():
        # Files returned in the reply win over files the role wrote to its workspace.
        changed = {p: c for p, c in {**written, **extract_files(code_section(reply))}.items()
                   if p.startswith("src/") and p not in HARNESS_OWNED}
        for path, content in changed.items():
            page.files[path] = content
            # The latest fixer becomes the primary owner of the file.
            page.sources[path] = [owner] + [r for r in page.sources.get(path, []) if r != owner]
        fix_round.patched[owner] = sorted(changed)
        fix_round.changes[owner] = _changes(reply) if reply.strip() else "(empty reply)"
        print(f"  {owner}: {len(by_owner[owner])} errors -> patched {', '.join(changed) or 'nothing'}"
              + ("" if reply.strip() else " (empty reply)"))
    for note in normalize_page(page):
        print(f"  normalized: {note}")
    return fix_round


def _stage3_failures() -> str:
    if not STAGE3_LOG.exists():
        return ""
    last = STAGE3_LOG.read_text(encoding="utf-8").rsplit("### Whole-page score", 1)[-1]
    return "\n".join(line for line in last.splitlines() if line.startswith("- ["))


def _changes(reply: str) -> str:
    match = re.search(r"^## Changes\s*\n(.*?)(?=^## |\Z)", reply, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else "(no Changes section)"


def _summary(v: Verification) -> str:
    audit = f"{sum(1 for a in v.spec_audit if a.get('pass'))}/{len(v.spec_audit)}"
    return (f"build {'ok' if v.build_ok else 'FAILED'}, {len(v.console_errors)} console errors, "
            f"{len(v.crashes)} crashes/rejections, spec audit {audit}, {len(v.errors)} errors")


def _mark(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def render_report(passes: list[Verification], rounds: list[FixRound], limitations: list[Issue],
                  final_index: int, reverted: bool) -> str:
    final = passes[final_index]
    audit_ok = sum(1 for a in final.spec_audit if a.get("pass"))
    lines = [
        "# Stage 4 Verification Report", "",
        f"**Outcome: {'DONE' if final.done else 'NOT DONE'}** after {len(rounds)} fix round(s), "
        f"{len(passes)} verification pass(es). Final page: verification pass {final_index}"
        + (" (later fixes broke the done criteria and were rolled back)." if reverted else "."), "",
        "## Done criteria", "", "| Criterion | Result |", "|---|---|",
        f"| Merged page builds and loads in headless Playwright | {_mark(final.build_ok)} |",
        f"| Zero console errors | {_mark(not final.console_errors)} ({len(final.console_errors)}) |",
        f"| Zero runtime crashes / unhandled rejections | {_mark(not final.crashes)} ({len(final.crashes)}) |",
        f"| Spec-compliance audit passes every requirement | {_mark(final.audit_passes)} ({audit_ok}/{len(final.spec_audit)}) |",
        "", "## Final checks", "", "| Check | Result | Details |", "|---|---|---|",
    ]
    lines += [f"| {c.get('name', '')} | {_mark(bool(c.get('pass')))} | {str(c.get('details', '')).replace('|', '/')} |"
              for c in final.checks]
    lines += ["", "## Spec-compliance audit", "", "| Requirement | Result | Evidence |", "|---|---|---|"]
    lines += [f"| {a.get('requirement', '')} | {_mark(bool(a.get('pass')))} | {str(a.get('evidence', '')).replace('|', '/')} |"
              for a in final.spec_audit]
    lines += ["", "### Extras (on the page but not in the spec)", ""]
    lines += [f"- {x}" for x in final.extras] or ["- (none)"]
    lines += ["", "## Known limitations (two failed fix attempts)", ""]
    lines += [f"- [{e.category}] {e.message} (owner: {e.owner})" for e in limitations] or ["- (none)"]
    lines += ["", "## Remaining errors", ""]
    lines += [f"- [{e.category}] {e.message} (file: {e.file or '?'}, owner: {e.owner})" for e in final.errors] or ["- (none)"]

    lines += ["", "## Error and fix log", ""]
    for i, v in enumerate(passes):
        lines += [f"### Verification pass {i}", "", f"- {_summary(v)}"]
        lines += [f"- [{e.category}] {e.message} (file: {e.file or '?'}, owner: {e.owner})" for e in v.errors]
        lines.append("")
        if i < len(rounds):
            r = rounds[i]
            lines += [f"### Fix round {r.number}", ""]
            for owner, errors in r.sent.items():
                lines += [f"**{owner}** ({len(errors)} errors) -> patched: {', '.join(r.patched.get(owner, [])) or 'nothing'}"]
                lines += [f"- sent: [{e.category}] {e.message}" for e in errors]
                lines += ["", r.changes.get(owner, "(fix call failed)"), ""]
    return "\n".join(lines) + "\n"
