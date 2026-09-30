"""Dispatch loop: run roles in parallel batches and write each slice to results/<role-name>.md.

Low-scoring slices are not retried here: Stage 3's judge and critique pass (loop.py) handles them.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agent import AgentResult, run_agent
from brain import Brain
from config import RESULTS_DIR
from roles import Role


def run_batches(roles: list[Role], brain: Brain, spec: str, batch_size: int) -> list[AgentResult]:
    results: list[AgentResult] = []
    for start in range(0, len(roles), batch_size):
        batch = roles[start:start + batch_size]
        print(f"\n== Batch {start // batch_size + 1}: {len(batch)} roles ==")
        results += _run_batch(batch, brain, spec)
    return results


def _run_batch(batch: list[Role], brain: Brain, spec: str) -> list[AgentResult]:
    results = []
    with ThreadPoolExecutor(max_workers=len(batch)) as pool:
        futures = {pool.submit(run_agent, role, brain, spec): role for role in batch}
        for future in as_completed(futures):
            role = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # One failed role must not sink the batch.
                print(f"  FAIL  {role.name}: {type(exc).__name__}: {exc}")
                continue
            path = write_result(result)
            revised = " (revised)" if result.revised else ""
            print(f"  {result.score:>3}   {role.name}{revised} -> {path.relative_to(RESULTS_DIR.parent)}")
            results.append(result)
    return results


def write_result(result: AgentResult) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{result.role}.md"
    tools = "\n".join(f"- {line}" for line in result.tool_log) or "- (none)"
    issues = "\n".join(f"- {i}" for i in result.review.issues) or "- (none)"
    path.write_text(
        f"# {result.role}\n\n"
        f"- Group: {result.group}\n"
        f"- Confidence score: {result.score}/100\n"
        f"- Revised: {'yes' if result.revised else 'no'}\n\n"
        f"{result.draft.strip()}\n\n"
        f"## Self-review\n\n{result.review.rationale}\n\n"
        f"### Open issues\n\n{issues}\n\n"
        f"## Tool calls\n\n{tools}\n",
        encoding="utf-8",
    )
    return path


def load_result(role: Role) -> tuple[str, int] | None:
    """Read back a slice written by write_result: (draft, confidence), or None if absent."""
    path = RESULTS_DIR / f"{role.name}.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Confidence score: (\d+)/100\n- Revised: \w+\n\n(.*?)\n## Self-review", text, re.DOTALL)
    if not match:
        return None
    return match.group(2).strip(), int(match.group(1))
