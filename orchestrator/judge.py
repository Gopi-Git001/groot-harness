"""Stage 3 judge: scores slices and whole pages on structure, fidelity, and polish."""

import json
import re
from dataclasses import dataclass

from brain import Brain
from roles import Role, loop_prompt

AXES = ("structure", "fidelity", "polish")
BLOCKER_BELOW = 60
PASS_AT = 80
CONVERGED_AT = 85
ATTEMPTS = 3

SYSTEM_PROMPT = "You are a strict senior front-end judge. Reply with JSON only."


@dataclass(frozen=True)
class Failure:
    axis: str
    reason: str
    spec_section: str = ""
    owner: str = ""


@dataclass(frozen=True)
class Verdict:
    scores: dict[str, int]
    failures: list[Failure]

    @property
    def score(self) -> int:
        return round(sum(self.scores.values()) / len(self.scores))

    @property
    def status(self) -> str:
        if self.score < BLOCKER_BELOW:
            return "blocker"
        return "rework" if self.score < PASS_AT else "pass"


class JudgeError(RuntimeError):
    pass


def judge_slice(brain: Brain, spec: str, sections: list[str], role: Role, slice_text: str, confidence: int) -> Verdict:
    prompt = loop_prompt(
        "judge-slice",
        sections=", ".join(sections),
        spec=spec,
        role=role.name,
        mission=role.mission,
        confidence=str(confidence),
        slice=slice_text,
    )
    return _ask(brain, prompt, owners=[], reasons_below=PASS_AT)


def judge_page(brain: Brain, spec: str, sections: list[str], page: str, owners: list[str]) -> Verdict:
    prompt = loop_prompt(
        "judge-page",
        sections=", ".join(sections),
        roles="\n".join(f"  - {name}" for name in owners),
        spec=spec,
        page=page,
    )
    return _ask(brain, prompt, owners=owners, reasons_below=CONVERGED_AT)


def _ask(brain: Brain, prompt: str, owners: list[str], reasons_below: int) -> Verdict:
    """Call the judge, re-asking when the reply is not a valid, specific verdict."""
    error = None
    for _ in range(ATTEMPTS):
        try:
            return parse_verdict(brain.complete(SYSTEM_PROMPT, prompt), owners, reasons_below)
        except ValueError as exc:
            error = exc
    raise JudgeError(f"no valid verdict after {ATTEMPTS} attempts: {error}")


def parse_verdict(reply: str, owners: list[str], reasons_below: int) -> Verdict:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        raise ValueError("reply contains no JSON object")
    data = json.loads(match.group(0))

    scores: dict[str, int] = {}
    failures: list[Failure] = []
    for axis in AXES:
        entry = data.get(axis)
        if not isinstance(entry, dict) or not isinstance(entry.get("score"), (int, float)):
            raise ValueError(f"missing or malformed '{axis}' axis")
        scores[axis] = max(0, min(100, int(entry["score"])))
        axis_failures = [
            Failure(
                axis,
                str(item["reason"]).strip(),
                str(item.get("spec_section", "")).strip(),
                owner if (owner := str(item.get("owner", "")).strip()) in owners else "",
            )
            for item in entry.get("failures") or []
            if isinstance(item, dict) and str(item.get("reason", "")).strip()
        ]
        if scores[axis] < reasons_below and not axis_failures:
            raise ValueError(f"'{axis}' scored {scores[axis]} without failure reasons")
        failures += axis_failures
    return Verdict(scores, failures)
