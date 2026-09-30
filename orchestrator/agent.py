"""One sub-agent's thinking loop.

1. Read spec and context      } draft call: role template + loop instructions,
2. Plan the slice (3-5 bullets)}  with the role's group tools available
3. Write code                  }
5. Run allowed tools           }
4. Self-review against mission  -> review call returns a 0-100 score
6. Revise once if score below 80
7. Emit slice + rationale + score
"""

import json
import re
from dataclasses import dataclass, field

from brain import Brain
from config import WORKSPACE_DIR
from roles import Role, loop_prompt
from tools.registry import ToolContext, execute, schemas_for

REVISE_BELOW = 80
EMPTY_RETRIES = 2
EMPTY_NUDGE = ("Your last turn contained no reply. Now give your complete answer in the exact format the task "
               "asks for, including every file you change in full.")

SYSTEM_PROMPT = (
    "You are one specialist sub-agent on a 50-agent front-end team. Your role template "
    "defines your identity, mission, context, tools, and output. Produce only your slice, "
    "and make it the best possible version of that slice."
)

DRAFT_INSTRUCTIONS = """
---
Work through these steps:
1. Read the spec and context above.
2. Plan your slice in 3-5 bullet points before writing any code.
3. Write the code.
4. Use your allowed tools where they help (e.g. write your files to your workspace).

Then reply in exactly this format:

## Plan
- 3-5 bullets

## Code
One fenced block per file. The first line of each block is a comment with the file path.

## Rationale
Why this slice meets your mission and the spec's success criteria.

Do not include a confidence score: it is assigned in a separate self-review step.
"""

REVIEW_PROMPT = """You are reviewing a draft slice against its role's mission and the page spec.

# Role template
{role}

# Draft
{draft}

Score how well the draft fulfils the mission and the spec's success criteria (0-100).
Reply with only a JSON object:
{{"score": <int 0-100>, "rationale": "<2-4 sentences>", "issues": ["<specific, fixable issue>", ...]}}
"""

REVISE_PROMPT = """Your self-review scored this draft {score}/100 (revise threshold {threshold}).
Issues found:
{issues}

Revise the slice to fix every issue. Reply in the same Plan / Code / Rationale format."""


@dataclass
class Review:
    score: int
    rationale: str
    issues: list[str]


@dataclass
class AgentResult:
    role: str
    group: str
    draft: str
    review: Review
    revised: bool
    tool_log: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return self.review.score


def run_agent(role: Role, brain: Brain, spec: str, prior_drafts: str = "") -> AgentResult:
    ctx = ToolContext(role.name, WORKSPACE_DIR / role.name)
    tool_log: list[str] = []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": role.render(spec, prior_drafts) + DRAFT_INSTRUCTIONS},
    ]

    draft = run_tool_loop(brain, role, messages, ctx, tool_log)
    review = _review(brain, role, spec, draft)
    revised = False

    if review.score < REVISE_BELOW:
        messages += [
            {"role": "assistant", "content": draft},
            {"role": "user", "content": REVISE_PROMPT.format(
                score=review.score,
                threshold=REVISE_BELOW,
                issues="\n".join(f"- {i}" for i in review.issues) or "- (none listed)",
            )},
        ]
        draft = run_tool_loop(brain, role, messages, ctx, tool_log)
        review = _review(brain, role, spec, draft)
        revised = True

    return AgentResult(role.name, role.group, draft, review, revised, tool_log)


def revise(role: Role, brain: Brain, spec_sections: str, slice_text: str,
           failures: str, peers: str, round_no: int) -> tuple[str, list[str]]:
    """Stage 3 critique pass: the owning role fixes the judge's listed failures in its slice."""
    ctx = ToolContext(role.name, WORKSPACE_DIR / role.name)
    tool_log: list[str] = []
    critique = loop_prompt("critique", round=str(round_no), failures=failures, slice=slice_text)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": role.render(spec_sections, peers) + critique},
    ]
    return run_tool_loop(brain, role, messages, ctx, tool_log), tool_log


def fix(role: Role, brain: Brain, spec: str, errors: str, files: str, inventory: str,
        packages: str, round_no: int) -> tuple[str, dict[str, str]]:
    """Stage 4 fix pass: the owning role fixes verifier errors in the merged page files.
    Returns the reply and any src/ files the role wrote with write_file instead of replying with them."""
    ctx = ToolContext(role.name, WORKSPACE_DIR / role.name)
    task = loop_prompt("fix", round=str(round_no), errors=errors, files=files,
                       inventory=inventory, packages=packages)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": role.render(spec) + task},
    ]
    tool_log: list[str] = []
    reply = run_tool_loop(brain, role, messages, ctx, tool_log, max_tokens=brain.config.merge_max_tokens)
    return reply, written_files(ctx, tool_log)


def written_files(ctx: ToolContext, tool_log: list[str]) -> dict[str, str]:
    """src/ files a role wrote to its workspace during a tool loop."""
    prefix = f"workspace/{ctx.role_name}/"
    written = {}
    for line in tool_log:
        if match := re.search(rf"Wrote \d+ chars to {re.escape(prefix)}(src/\S+)", line):
            path = ctx.workspace / match.group(1)
            if path.is_file():
                written[match.group(1)] = path.read_text(encoding="utf-8")
    return written


def run_tool_loop(brain: Brain, role: Role, messages: list[dict], ctx: ToolContext, tool_log: list[str],
                  max_tokens: int | None = None) -> str:
    """Run the model with the role's tools until it answers without calling any."""
    tools = schemas_for(role.group)
    empty_replies = 0
    for _ in range(brain.config.max_tool_steps):
        message = brain.chat(messages, tools if empty_replies < EMPTY_RETRIES else None, max_tokens)
        if not message.tool_calls:
            if (message.content or "").strip() or empty_replies > EMPTY_RETRIES:
                return message.content or ""
            # GPT-OSS sometimes ends a turn after a tool result with reasoning only and no text.
            # Nudge it to answer; the final retry withdraws tools so it must reply in text.
            empty_replies += 1
            messages.append({"role": "user", "content": EMPTY_NUDGE})
            continue

        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in message.tool_calls
            ],
        })
        for call in message.tool_calls:
            output = execute(role.group, call.function.name, call.function.arguments, ctx)
            tool_log.append(f"{call.function.name}: {output.splitlines()[0][:240] if output else ''}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

    # Tool budget spent: ask for the final answer with tools withdrawn.
    messages.append({"role": "user", "content": "Tool budget used up. Give your final answer now."})
    return brain.chat(messages, max_tokens=max_tokens).content or ""


def _review(brain: Brain, role: Role, spec: str, draft: str) -> Review:
    reply = brain.complete(
        "You are a strict senior front-end reviewer. Reply with JSON only.",
        REVIEW_PROMPT.format(role=role.render(spec), draft=draft or "(empty draft)"),
    )
    return _parse_review(reply)


def _parse_review(reply: str) -> Review:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    score = data.get("score")
    if not isinstance(score, (int, float)):
        found = re.search(r'"?score"?\s*[:=]\s*(\d{1,3})', reply)
        score = int(found.group(1)) if found else 0
    return Review(
        score=max(0, min(100, int(score))),
        rationale=str(data.get("rationale") or reply.strip()[:500]),
        issues=[str(i) for i in data.get("issues") or []],
    )
