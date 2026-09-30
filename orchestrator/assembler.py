"""Stage 4 assembler: merge the Stage 3 slices into one page that builds.

1. Collect every file from every slice (deterministic, so nothing is silently dropped).
2. Resolve conflicts: same path, or same file name in different folders, go to the model per cluster.
3. Redirect imports of removed paths to the kept file.
4. Wire src/App.tsx in spec order.
5. Self-check: repair broken imports, prune files nothing imports, flag duplicate exports,
   and check spec requirements against the source.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from brain import Brain
from loop import code_section
from pagefiles import (ALLOWED_PACKAGES, CONFIG_FILES, HARNESS_OWNED, duplicate_exports, exports,
                       extract_files, import_problems, jsx_in_ts, normalize_tokens, reachable, render_files,
                       rewrite_imports)
from parallel import run_parallel
from roles import loop_prompt

APP = "src/App.tsx"
ASK_ATTEMPTS = 3


@dataclass
class Page:
    files: dict[str, str]
    sources: dict[str, list[str]]  # path -> roles that contributed it

    def inventory(self) -> str:
        return "\n".join(f"- {p}: {', '.join(exports(c)) or '(no exports)'}" for p, c in sorted(self.files.items()))

    def owners(self) -> str:
        return "\n".join(f"- {p}: {', '.join(self.sources.get(p) or ['unassigned'])}" for p in sorted(self.files))


@dataclass
class MergeReport:
    collected: dict[str, int] = field(default_factory=dict)
    ignored: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    rewrites: list[str] = field(default_factory=list)
    wiring: str = ""
    repaired: dict[str, list[str]] = field(default_factory=dict)
    unresolved: dict[str, list[str]] = field(default_factory=dict)
    pruned: list[str] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)
    requirements: list[dict] = field(default_factory=list)
    normalized: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    path: str
    role: str
    score: int
    content: str


class Assembler:
    def __init__(self, brain: Brain, spec: str, workers: int):
        self.brain = brain
        self.spec = spec
        self.workers = workers
        self.system = loop_prompt("assembler", packages=", ".join(sorted(ALLOWED_PACKAGES)))

    def run(self, slices_dir: Path, stage3_failures: str) -> tuple[Page, MergeReport]:
        report = MergeReport()
        candidates = self._collect(slices_dir, report)
        page = self._resolve(candidates, report)
        report.rewrites = rewrite_imports(page.files, self._moved)
        print(f"  assembled {len(page.files)} files from {len(report.collected)} slices "
              f"({len(report.conflicts)} conflicts resolved)")

        self._wire(page, stage3_failures, report)
        self._self_check(page, report)
        report.normalized = normalize_page(page)
        print(f"  normalized: {len(report.normalized)} deterministic fixes (JSX file names, color tokens)")
        return page, report

    # --- 1. collect ------------------------------------------------------

    def _collect(self, slices_dir: Path, report: MergeReport) -> list[Candidate]:
        candidates = []
        for path in sorted(slices_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            score = int(m.group(1)) if (m := re.search(r"Judge score: (\d+)", text)) else 0
            files = extract_files(code_section(text))
            report.collected[path.stem] = len(files)
            for file_path, content in files.items():
                if file_path in CONFIG_FILES or file_path in HARNESS_OWNED:
                    report.ignored.append(f"{file_path} ({path.stem}): harness-owned")
                elif file_path == APP:
                    report.ignored.append(f"{file_path} ({path.stem}): replaced by wiring step")
                else:
                    candidates.append(Candidate(file_path, path.stem, score, content))
        return candidates

    # --- 2. resolve conflicts --------------------------------------------

    def _resolve(self, candidates: list[Candidate], report: MergeReport) -> Page:
        clusters = _cluster(candidates)
        page = Page({}, {})
        self._moved: dict[str, str] = {}
        contested = {}
        for key, members in clusters.items():
            if len({c.content for c in members}) == 1 and len({c.path for c in members}) == 1:
                page.files[members[0].path] = members[0].content
                page.sources[members[0].path] = _ranked_roles(members)
            else:
                contested[key] = members

        inventory = "\n".join(f"- {c.path}: {', '.join(exports(c.content))}" for c in candidates)
        replies = run_parallel({key: (lambda m=members: self._ask(loop_prompt(
            "resolve", spec=self.spec, inventory=inventory, candidates=_render_candidates(m))))
            for key, members in contested.items()}, self.workers)

        for key, members in contested.items():
            kept = {p: c for p, c in extract_files(replies.get(key, "")).items() if p.startswith("src/")}
            if not kept:  # Model failed: keep the best-judged version.
                best = max(members, key=lambda c: c.score)
                kept = {best.path: best.content}
                notes = f"- fallback: kept {best.path} from {best.role} (highest judge score)"
            else:
                notes = _section(replies[key], "Notes") or "- (no notes)"
            roles = _ranked_roles(members)
            for path, content in kept.items():
                page.files[path] = content
                page.sources[path] = roles
            for path in {c.path for c in members} - set(kept):
                same = [k for k in kept if Path(k).stem.lower() == Path(path).stem.lower()]
                self._moved[path] = (same or list(kept))[0]
            listed = ", ".join(sorted({f"{c.path} ({c.role})" for c in members}))
            report.conflicts.append(f"**{key}**: {listed}\n  kept: {', '.join(sorted(kept))}\n{notes}")
        return page

    # --- 4. wire ---------------------------------------------------------

    def _wire(self, page: Page, stage3_failures: str, report: MergeReport) -> None:
        prompt = loop_prompt("wire", spec=self.spec, inventory=page.inventory(),
                             stage3_failures=stage3_failures or "(none)")
        for _ in range(ASK_ATTEMPTS):
            reply = self._ask(prompt)
            if app := extract_files(reply).get(APP):
                break
            print("  wiring reply had no src/App.tsx block; asking again")
        else:
            raise RuntimeError(f"wiring step returned no src/App.tsx after {ASK_ATTEMPTS} attempts")
        page.files[APP] = app
        page.sources[APP] = ["layout-page-structure"]
        report.wiring = _section(reply, "Notes") or "- (no notes)"
        print("  wired src/App.tsx")

    # --- 5. self-check ---------------------------------------------------

    def _self_check(self, page: Page, report: MergeReport) -> None:
        broken = import_problems(page.files)
        if broken:
            replies = run_parallel({path: (lambda p=path, found=found: self._ask(loop_prompt(
                "repair", path=p, broken="\n".join(f"- {s}" for s in found), content=page.files[p],
                inventory=page.inventory()))) for path, found in broken.items()}, self.workers)
            for path, reply in replies.items():
                if fixed := extract_files(reply).get(path):
                    page.files[path] = fixed
            report.repaired = broken
            report.unresolved = import_problems(page.files)
        print(f"  self-check: {len(broken)} files with broken imports/exports, {len(report.unresolved)} still broken")

        # Prune after repairs: repairs may redirect imports to files that were unreachable before.
        keep = reachable(page.files)
        report.pruned = sorted(p for p in page.files if p not in keep)
        for path in report.pruned:
            del page.files[path]
            page.sources.pop(path, None)
        report.unresolved = {p: f for p, f in report.unresolved.items() if p in page.files}
        report.duplicates = duplicate_exports(page.files)

        reply = self._ask(loop_prompt("selfcheck", spec=self.spec, source=render_files(page.files)))
        try:
            report.requirements = json.loads(re.search(r"\{.*\}", reply, re.DOTALL).group(0))["requirements"]
        except (AttributeError, ValueError, KeyError, TypeError):
            report.requirements = [{"requirement": "(self-check reply unparseable)", "present": False, "evidence": ""}]
        missing = sum(1 for r in report.requirements if not r.get("present"))
        print(f"  self-check: pruned {len(report.pruned)} dead files, {len(report.duplicates)} duplicate exports, "
              f"{missing} spec requirements missing")

    def _ask(self, prompt: str) -> str:
        """One assembler call. GPT-OSS sometimes returns reasoning with no text: ask again."""
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": prompt}]
        for _ in range(ASK_ATTEMPTS):
            reply = self.brain.chat(messages, max_tokens=self.brain.config.merge_max_tokens).content or ""
            if reply.strip():
                return reply
        return ""


def normalize_page(page: Page) -> list[str]:
    """Deterministic fixes the model keeps getting wrong: JSX inside .ts files (rename to .tsx)
    and color tokens in a form tailwind.config.ts cannot read. Returns a note per change."""
    notes = []
    for path in [p for p in page.files if jsx_in_ts(p, page.files[p])]:
        target = path + "x"
        if target in page.files:
            continue
        page.files[target] = page.files.pop(path)
        page.sources[target] = page.sources.pop(path, [])
        notes.append(f"renamed {path} -> {target} (contains JSX)")
    if "src/index.css" in page.files:
        page.files["src/index.css"], token_notes = normalize_tokens(page.files["src/index.css"])
        notes += [f"src/index.css: {n}" for n in token_notes]
    return notes


def _cluster(candidates: list[Candidate]) -> dict[str, list[Candidate]]:
    """Group candidates that are the same file (same path, case-insensitive) or the same
    concern (same file name in different folders, e.g. FAQ.tsx and faq/FAQ.tsx)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for c in candidates:
        stem = Path(c.path).stem.lower()
        keys = [f"path:{c.path.lower()}"] + ([] if stem == "index" else [f"name:{stem}{Path(c.path).suffix}"])
        for key in keys:
            parent[find(key)] = find(f"path:{c.path.lower()}")

    clusters: dict[str, list[Candidate]] = {}
    for c in candidates:
        clusters.setdefault(find(f"path:{c.path.lower()}").removeprefix("path:"), []).append(c)
    return clusters


def _ranked_roles(members: list[Candidate]) -> list[str]:
    """Contributing roles, best judge score first: the first role is the file's primary owner."""
    return list(dict.fromkeys(c.role for c in sorted(members, key=lambda c: -c.score)))


def _render_candidates(members: list[Candidate]) -> str:
    return "\n\n".join(f"### {c.path} (from {c.role}, judge score {c.score})\n```\n// {c.path}\n{c.content}```"
                       for c in sorted(members, key=lambda c: -c.score))


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\s*\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def render_merge_report(report: MergeReport, page: Page) -> str:
    lines = ["# Stage 4 Merge Report", "",
             f"- Slices read: {len(report.collected)}, files collected: {sum(report.collected.values())}",
             f"- Final page files: {len(page.files)}", f"- Conflicts resolved: {len(report.conflicts)}",
             f"- Files pruned as dead code: {len(report.pruned)}", "",
             "## Files collected per slice", ""]
    lines += [f"- {role}: {n}" for role, n in sorted(report.collected.items())]
    lines += ["", "## Ignored (harness-owned or replaced)", ""] + ([f"- {i}" for i in report.ignored] or ["- (none)"])
    lines += ["", "## Conflicts and resolutions", ""] + (report.conflicts or ["- (none)"])
    lines += ["", "## Import redirects", ""] + ([f"- {r}" for r in report.rewrites] or ["- (none)"])
    lines += ["", "## Wiring (src/App.tsx)", "", report.wiring]
    lines += ["", "## Self-check", "", "### Broken imports found"]
    lines += [f"- {p}: {', '.join(s)}" for p, s in report.repaired.items()] or ["- (none)"]
    lines += ["", "### Broken imports still unresolved"]
    lines += [f"- {p}: {', '.join(s)}" for p, s in report.unresolved.items()] or ["- (none)"]
    lines += ["", "### Dead code pruned (not reachable from App.tsx or index.css)"]
    lines += [f"- {p}" for p in report.pruned] or ["- (none)"]
    lines += ["", "### Duplicate definitions (same export name in several files)"]
    lines += [f"- `{n}`: {', '.join(p)}" for n, p in report.duplicates.items()] or ["- (none)"]
    lines += ["", "### Deterministic normalization", ""]
    lines += [f"- {n}" for n in report.normalized] or ["- (none)"]
    lines += ["", "### Spec requirements (source check)", "", "| Requirement | Present | Evidence |", "|---|---|---|"]
    lines += [f"| {r.get('requirement', '')} | {'yes' if r.get('present') else 'NO'} | {r.get('evidence', '')} |"
              for r in report.requirements]
    return "\n".join(lines) + "\n"
