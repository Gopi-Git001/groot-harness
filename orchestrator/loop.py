"""Stage 3: judge, critique, and rewrite loop until the merged page converges on the spec.

Each round:
1. Judge every slice (round 1) on structure, fidelity, polish.
2. Critique: each failing slice, plus each role the last page verdict blamed, goes back to
   its owning role with the judge's failures, the spec sections they cite, and peer slices.
   One revision per slice per round; revised slices are re-judged.
3. Rewrite: the assembly-merge role merges the slices (per group, then into one page).
4. The judge scores the merged page as a whole.
Stops when the page scores CONVERGED_AT or more, or after max_rounds.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from agent import revise
from brain import Brain
from config import RESULTS_DIR
from judge import CONVERGED_AT, PASS_AT, Failure, Verdict, judge_page, judge_slice
from parallel import run_parallel
from roles import Role, loop_prompt

BUILDER_GROUPS = ("layout", "components", "styling", "state", "data")
MAX_ROUNDS = 5
PEER_COUNT = 5
PEER_CHARS = 6_000

STAGE3_DIR = RESULTS_DIR / "stage-3"
LOG_PATH = RESULTS_DIR / "stage-3-log.md"
PAGE_PATH = RESULTS_DIR / "stage-3-page.md"

T = TypeVar("T")


@dataclass
class Slice:
    role: Role
    text: str
    confidence: int
    verdict: Verdict | None = None
    revisions: int = 0


@dataclass
class Round:
    number: int
    critiqued: dict[str, list[Failure]]
    slice_verdicts: dict[str, Verdict]
    page: str
    page_verdict: Verdict


@dataclass
class Stage3:
    brain: Brain
    spec: str
    merger: Role
    workers: int
    max_rounds: int = MAX_ROUNDS
    sections: dict[str, str] = field(init=False)

    def __post_init__(self):
        self.sections = spec_sections(self.spec)

    def run(self, slices: list[Slice]) -> Round | None:
        STAGE3_DIR.mkdir(parents=True, exist_ok=True)
        history: list[Round] = []
        page_failures: list[Failure] = []

        for number in range(1, self.max_rounds + 1):
            print(f"\n== Stage 3 round {number}/{self.max_rounds} ==")
            if number == 1:
                self._judge_slices(slices)
            critiqued = self._critique(slices, page_failures, number)
            page = self._merge(slices)
            page_verdict = judge_page(self.brain, self.spec, list(self.sections), page,
                                      [s.role.name for s in slices])
            print(f"  page score {page_verdict.score} {page_verdict.scores}")

            history.append(Round(number, critiqued, {s.role.name: s.verdict for s in slices if s.verdict},
                                 page, page_verdict))
            self._write_round(history)
            for s in slices:
                self._write_slice(s)
            if page_verdict.score >= CONVERGED_AT:
                print(f"  converged at round {number}")
                break
            page_failures = page_verdict.failures

        return max(history, key=lambda r: r.page_verdict.score, default=None)

    # --- judge -----------------------------------------------------------

    def _judge_slices(self, slices: list[Slice]) -> None:
        verdicts = self._parallel({
            s.role.name: (lambda s=s: judge_slice(self.brain, self.spec, list(self.sections),
                                                  s.role, s.text, s.confidence))
            for s in slices
        })
        for s in slices:
            if s.role.name in verdicts:
                s.verdict = verdicts[s.role.name]
                print(f"  judged  {s.verdict.score:>3} {s.verdict.status:<7} {s.role.name}")

    # --- critique --------------------------------------------------------

    def _critique(self, slices: list[Slice], page_failures: list[Failure], number: int) -> dict[str, list[Failure]]:
        todo: dict[str, list[Failure]] = {}
        for s in slices:
            failures = list(s.verdict.failures) if s.verdict and s.verdict.score < PASS_AT else []
            failures += [f for f in page_failures if f.owner == s.role.name]
            if failures:
                todo[s.role.name] = failures
        if not todo:
            print("  critique: no failing slices")
            return {}

        by_name = {s.role.name: s for s in slices}
        drafts = self._parallel({
            name: (lambda s=by_name[name], f=failures: revise(
                s.role, self.brain, self._sections_for(f), s.text,
                format_failures(f), self._peers(s, slices), number))
            for name, failures in todo.items()
        })
        revised = []
        for name, (draft, _tools) in drafts.items():
            if draft.strip():
                by_name[name].text = draft
                by_name[name].revisions += 1
                revised.append(by_name[name])
        print(f"  critique: revised {len(revised)}/{len(todo)} slices")

        self._judge_slices(revised)
        return todo

    def _sections_for(self, failures: list[Failure]) -> str:
        cited = [name for name in self.sections if any(f.spec_section.lower() == name.lower() for f in failures)]
        if not cited:
            return self.spec
        return "\n\n".join(f"## {name}\n{self.sections[name]}" for name in cited)

    def _peers(self, target: Slice, slices: list[Slice]) -> str:
        peers = [s for s in slices if s.role.group == target.role.group and s is not target][:PEER_COUNT]
        return "\n\n".join(f"### Peer slice: {s.role.name}\n{code_section(s.text)[:PEER_CHARS]}" for s in peers)

    # --- merge -----------------------------------------------------------

    def _merge(self, slices: list[Slice]) -> str:
        groups = [g for g in BUILDER_GROUPS if any(s.role.group == g for s in slices)]
        group_pages = self._parallel({
            g: (lambda g=g: self._merge_group(g, [s for s in slices if s.role.group == g]))
            for g in groups
        })
        missing = [g for g in groups if g not in group_pages]
        if missing:
            raise RuntimeError(f"group merge failed for: {', '.join(missing)}")
        print(f"  merged {len(groups)} groups")
        drafts = "\n\n".join(f"### {g} layer\n{group_pages[g]}" for g in groups)
        return self._merge_call(drafts, "final page", "one complete page file tree with `src/App.tsx` as the entry")

    def _merge_group(self, group: str, members: list[Slice]) -> str:
        if len(members) == 1:
            return code_section(members[0].text)
        drafts = "\n\n".join(f"### {s.role.name}\n{code_section(s.text)}" for s in members)
        return self._merge_call(drafts, f"{group} group", f"one coherent {group} layer")

    def _merge_call(self, drafts: str, scope: str, target: str) -> str:
        prompt = self.merger.render(self.spec, drafts) + loop_prompt("merge", scope=scope, target=target)
        reply = self.brain.chat(
            [
                {"role": "system", "content": "You are the assembly sub-agent merging slices into one page."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.brain.config.merge_max_tokens,
        ).content or ""
        if not reply.strip():
            raise RuntimeError(f"merge of {scope} returned an empty reply")
        return reply

    # --- output ----------------------------------------------------------

    def _write_slice(self, s: Slice) -> None:
        path = STAGE3_DIR / "slices" / f"{s.role.name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        v = s.verdict
        header = (f"- Judge score: {v.score}/100 ({v.status}) {v.scores}\n" if v else "- Judge score: n/a\n")
        path.write_text(f"# {s.role.name}\n\n- Group: {s.role.group}\n{header}- Revisions: {s.revisions}\n\n"
                        f"{s.text.strip()}\n", encoding="utf-8")

    def _write_round(self, history: list[Round]) -> None:
        latest = history[-1]
        (STAGE3_DIR / f"round-{latest.number}-page.md").write_text(latest.page, encoding="utf-8")
        best = max(history, key=lambda r: r.page_verdict.score)
        PAGE_PATH.write_text(
            f"# Stage 3 best page\n\n- Round: {best.number}\n- Page score: {best.page_verdict.score}/100 "
            f"{best.page_verdict.scores}\n\n{best.page}\n",
            encoding="utf-8",
        )
        LOG_PATH.write_text(render_log(history, self.max_rounds), encoding="utf-8")

    def _parallel(self, tasks: dict[str, Callable[[], T]]) -> dict[str, T]:
        return run_parallel(tasks, self.workers)


def spec_sections(spec: str) -> dict[str, str]:
    """Split the page spec into its '## ' sections, keyed by heading."""
    parts = re.split(r"^## (.+)$", spec, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def code_section(text: str) -> str:
    """The '## Code' part of a slice, or the whole slice if it has none."""
    match = re.search(r"^## Code\s*\n(.*?)(?=^## (?:Rationale|Changes|Plan)\b|\Z)", text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else text


def format_failures(failures: list[Failure]) -> str:
    return "\n".join(
        f"{i}. [{f.axis}] {f.reason}" + (f" (spec: {f.spec_section})" if f.spec_section else "")
        for i, f in enumerate(failures, 1)
    )


def render_log(history: list[Round], max_rounds: int) -> str:
    best = max(history, key=lambda r: r.page_verdict.score)
    last = history[-1]
    if last.page_verdict.score >= CONVERGED_AT:
        outcome = f"Converged at round {last.number} (page score {last.page_verdict.score} >= {CONVERGED_AT})."
    elif last.number >= max_rounds:
        outcome = f"Round cap reached ({max_rounds}) without converging."
    else:
        outcome = f"In progress: {last.number}/{max_rounds} rounds done."

    lines = [
        "# Stage 3 Log", "",
        f"- Outcome: {outcome}",
        f"- Best page: round {best.number}, score {best.page_verdict.score}/100 -> results/stage-3-page.md",
        f"- Page scores by round: {', '.join(str(r.page_verdict.score) for r in history)}", "",
    ]
    for r in history:
        lines += [f"## Round {r.number}", "", "### Critique pass", ""]
        if r.critiqued:
            for name, failures in r.critiqued.items():
                lines += [f"**{name}** ({len(failures)} failures sent)", format_failures(failures), ""]
        else:
            lines += ["No slices sent back.", ""]
        lines += ["### Slice scores after critique", "",
                  "| Role | Structure | Fidelity | Polish | Score | Status |", "|---|---|---|---|---|---|"]
        for name, v in sorted(r.slice_verdicts.items(), key=lambda kv: kv[1].score):
            s = v.scores
            lines.append(f"| {name} | {s['structure']} | {s['fidelity']} | {s['polish']} | {v.score} | {v.status} |")
        pv = r.page_verdict
        lines += ["", f"### Whole-page score: {pv.score}/100 {pv.scores}", ""]
        lines += [f"- [{f.axis}] {f.reason}" + (f" (spec: {f.spec_section})" if f.spec_section else "")
                  + f" -> owner: {f.owner or 'unassigned'}" for f in pv.failures] or ["- (no failures)"]
        lines.append("")
    return "\n".join(lines)
