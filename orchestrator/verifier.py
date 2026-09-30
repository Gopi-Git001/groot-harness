"""Stage 4 verifier: a GPT-OSS sub-agent that runs the page in headless Chromium via the playwright tool.

Pass/fail on build, console errors, and runtime crashes comes from the raw Playwright report,
never from the model's summary. The model attributes each error to a file and owning role,
and audits the rendered page against the spec.
"""

import json
import re
from dataclasses import dataclass

from agent import run_tool_loop
from assembler import Page
from brain import Brain
from config import WORKSPACE_DIR
from pagefiles import import_problems
from roles import Role, loop_prompt
from tools.browser import RESULT_PATH, write_page
from tools.registry import ToolContext

FALLBACK_OWNER = "layout-page-structure"
PARSE_ATTEMPTS = 2


@dataclass
class Issue:
    category: str
    message: str
    file: str = ""
    owner: str = ""

    @property
    def key(self) -> str:
        """Stable identity across verification passes, for counting fix attempts."""
        return f"{self.category}:{re.sub(r'[^a-z]+', ' ', self.message.lower()).strip()[:120]}"


@dataclass
class Verification:
    raw: dict
    checks: list[dict]
    spec_audit: list[dict]
    extras: list[str]
    errors: list[Issue]

    @property
    def build_ok(self) -> bool:
        return bool(self.raw.get("build", {}).get("ok")) and "verifyCrashed" not in self.raw

    @property
    def console_errors(self) -> list[dict]:
        return [e for e in self.raw.get("console", []) if e.get("type") == "error"]

    @property
    def crashes(self) -> list[dict]:
        return self.raw.get("pageErrors", []) + self.raw.get("rejections", [])

    @property
    def blank(self) -> bool:
        """The page crashed and rendered nothing at some width."""
        return any(v.get("rootTextLength", 1) == 0 for v in self.raw.get("viewports", {}).values())

    @property
    def audit_passes(self) -> bool:
        return bool(self.spec_audit) and all(item.get("pass") for item in self.spec_audit)

    @property
    def done(self) -> bool:
        return self.build_ok and not self.console_errors and not self.crashes and self.audit_passes


def verify(brain: Brain, spec: str, page: Page, verifier: Role) -> Verification:
    write_page(page.files)
    RESULT_PATH.unlink(missing_ok=True)
    ctx = ToolContext(verifier.name, WORKSPACE_DIR / verifier.name)
    tool_log: list[str] = []
    messages = [
        {"role": "system", "content": "You are the Stage 4 verifier sub-agent. You verify; you never edit code."},
        {"role": "user", "content": loop_prompt("verifier", spec=spec, owners=page.owners())},
    ]
    reply = run_tool_loop(brain, verifier, messages, ctx, tool_log)
    if not RESULT_PATH.exists():  # The model skipped the tool: insist once.
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "You must call the playwright tool before answering. Call it now."}]
        reply = run_tool_loop(brain, verifier, messages, ctx, tool_log)
    if not RESULT_PATH.exists():
        raise RuntimeError("verifier never called the playwright tool")

    raw = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    data = _parse(brain, messages, reply)
    owners = {role for roles in page.sources.values() for role in roles}
    model_errors = [_issue(e, page, owners) for e in data.get("errors", []) if isinstance(e, dict)]
    errors = _attribute(raw_issues(raw), model_errors, page, owners)
    if raw.get("build", {}).get("ok"):
        errors += [e for e in model_errors if e.category == "spec"]
    else:
        # Vite stops at the first error; list every import/export problem so one round can fix them all.
        # Spec findings are meaningless while the page cannot build, so they are not reported.
        for path, found in import_problems(page.files).items():
            errors += [Issue("build", f"{path} {problem}", path, page.sources.get(path, [FALLBACK_OWNER])[0])
                       for problem in found]
    return Verification(raw, data.get("checks", []), data.get("spec_audit", []), data.get("extras", []), errors)


def raw_issues(raw: dict) -> list[Issue]:
    """Deterministic errors straight from the Playwright report."""
    build = raw.get("build", {})
    if not build.get("ok"):
        output = build.get("output", "")
        normalized = output.replace("\\", "/")
        m = re.search(r"/(src/[^\s:]+)", normalized) or re.search(r"^(src/\S+?\.\w+)", normalized, re.MULTILINE)
        file = m.group(1) if m else ""
        return [Issue("build", output.split("\n    at ")[0].strip()[:600], file)]
    if "verifyCrashed" in raw:
        return [Issue("runtime", "Headless verification crashed: " + raw["verifyCrashed"][:500])]

    diagnosis = raw.get("crashDiagnosis") or []
    if diagnosis:
        # Development React names the file and line: fix there, not in whatever the model guesses.
        hint = next((m.group(1) for d in diagnosis if (m := re.search(r"Check your code at ([\w.-]+\.\w+):", d))), "")
        detail = "\n".join(dict.fromkeys(re.sub(r"\n\s+at .*", "", d).strip() for d in diagnosis))
        crash = [Issue("runtime", "Page crashes on render and shows nothing. Development build says:\n" + detail, hint)]
        return crash  # Every other check is a symptom of the crash.

    issues = [Issue("console", e["text"].split("\n")[0]) for e in raw.get("console", []) if e.get("type") == "error"]
    issues += [Issue("runtime", e["text"].split("\n")[0]) for e in raw.get("pageErrors", [])]
    issues += [Issue("rejection", e["text"].split("\n")[0]) for e in raw.get("rejections", [])]
    for width, view in raw.get("viewports", {}).items():
        if view.get("horizontalOverflow"):
            issues.append(Issue("layout", f"Horizontal overflow at {width}px (scrollWidth {view['scrollWidth']}): "
                                          f"{'; '.join(view.get('offenders', []))}"))
        if view.get("rootTextLength", 1) == 0:
            issues.append(Issue("elements", f"Page renders no content at {width}px"))
    for toggle in raw.get("toggles", []):
        if not toggle.get("toggled"):
            issues.append(Issue("layout", f"aria-expanded toggle \"{toggle['label']}\" does not change state "
                                          f"when clicked at {toggle['width']}px"))
    for href in raw.get("brokenAnchors", []):
        issues.append(Issue("elements", f"Link {href} points at an id that does not exist"))
    for image in raw.get("brokenImages", []):
        issues.append(Issue("elements", f"Image fails to load: {image}. The page must be self-contained: "
                                        "use an inline SVG or CSS placeholder, not a missing file"))
    for entry in raw.get("duplicateIds", []):
        # Usually App.tsx wraps a section component in an element carrying the same id: fix it there.
        issues.append(Issue("elements", f"Duplicate element id {entry}: ids must be unique. If App.tsx wraps a "
                                        "section component that already renders this id, remove the id (or the "
                                        "wrapper element) in App.tsx", "src/App.tsx"))
    for request in raw.get("failedRequests", []):
        issues.append(Issue("elements", f"Network request failed: {request['text']}"))
    landmarks = raw.get("landmarks", {})
    # <nav> is not required here: not every page has one, and the spec audit checks it when the spec asks.
    for name in ("header", "main", "footer"):
        if landmarks and not landmarks.get(name):
            issues.append(Issue("elements", f"Missing <{name}> landmark"))
    if landmarks and landmarks.get("h1") != 1:
        issues.append(Issue("elements", f"Page has {landmarks.get('h1')} <h1> elements; exactly one required"))
    if landmarks and landmarks.get("main", 0) > 1:
        issues.append(Issue("elements", f"Page has {landmarks['main']} <main> elements; exactly one required"))
    return issues


def _parse(brain: Brain, messages: list[dict], reply: str) -> dict:
    for attempt in range(PARSE_ATTEMPTS + 1):
        try:
            return json.loads(re.search(r"\{.*\}", reply, re.DOTALL).group(0))
        except (AttributeError, ValueError):
            if attempt == PARSE_ATTEMPTS:
                return {}
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": "Reply with only the verification JSON object described above."}]
            reply = brain.chat(messages).content or ""
    return {}


def _issue(entry: dict, page: Page, owners: set[str]) -> Issue:
    file = str(entry.get("file") or "").strip().removeprefix("build/")
    owner = str(entry.get("owner") or "").strip()
    if owner not in owners:
        owner = (page.sources.get(file) or [FALLBACK_OWNER])[0]
    return Issue(str(entry.get("category", "")).strip(), str(entry.get("message", "")).strip(), file, owner)


def _attribute(raw: list[Issue], model: list[Issue], page: Page, owners: set[str]) -> list[Issue]:
    """Give each raw issue the file and owner of the model error that best matches it."""
    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9#]{4,}", text.lower())}

    for issue in raw:
        if issue.file and issue.file not in page.files:  # A bare file name from a stack trace: find its path.
            issue.file = next((p for p in page.files if p.rsplit("/", 1)[-1] == issue.file), issue.file)
        if issue.file in page.sources:  # The report names the file: its owner is known for certain.
            issue.owner = page.sources[issue.file][0]
            continue
        scored = [(len(words(issue.message) & words(m.message)), m) for m in model if m.category != "spec"]
        best = max(scored, key=lambda s: s[0], default=(0, None))
        if best[1] and best[0] > 0:
            issue.file = best[1].file
            issue.owner = best[1].owner
        if issue.owner not in owners:
            issue.owner = (page.sources.get(issue.file) or [FALLBACK_OWNER])[0]
    return raw
