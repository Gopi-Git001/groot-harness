"""Spec writer: turn a user's free-form instructions (a prompt or a markdown file) into the page spec.

The model keeps every stated requirement and fills gaps. The Stack section is always the harness's
own, because the scaffold that builds the page is fixed.
"""

import re

from brain import Brain
from roles import loop_prompt

REQUIRED_HEADINGS = ("## Prompt", "## Constraints", "## Success Criteria")
ATTEMPTS = 3
STACK = """## Stack
- React 18 + TypeScript (strict), built with Vite.
- Tailwind CSS with shadcn/ui-style components (`cva`, `cn()`, Radix-style accessible primitives), `lucide-react` icons.
- Source lives under `src/`: `components/ui/` for primitives, `components/` for page sections, `lib/` for utilities, `data/` for content.
"""


def write_spec(brain: Brain, instructions: str, assets: list[str]) -> str:
    prompt = loop_prompt("spec-writer", instructions=instructions.strip(), assets=_asset_list(assets))
    return _ask_for_spec(brain, prompt)


def revise_spec(brain: Brain, spec: str, request: str, assets: list[str]) -> str:
    """Apply a user's change request to an existing spec, keeping everything else."""
    prompt = loop_prompt("spec-revise", spec=spec, request=request.strip(), assets=_asset_list(assets))
    return _ask_for_spec(brain, prompt)


def _asset_list(assets: list[str]) -> str:
    return "\n".join(f"- {name}" for name in assets) or "(none: use inline SVG or CSS for all images)"


def _ask_for_spec(brain: Brain, prompt: str) -> str:
    messages = [{"role": "system", "content": "You are the spec writer. Reply with the spec markdown only."},
                {"role": "user", "content": prompt}]
    for _ in range(ATTEMPTS):
        reply = (brain.chat(messages, max_tokens=brain.config.merge_max_tokens).content or "").strip()
        spec = _clean(reply)
        missing = [h for h in REQUIRED_HEADINGS if h not in spec]
        if not missing:
            return _with_stack(spec)
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": f"The spec is missing {', '.join(missing)}. "
                                                 "Reply with the complete spec in the exact structure."}]
    raise RuntimeError("spec writer did not produce a spec with the required sections")


def _clean(reply: str) -> str:
    """Drop a surrounding code fence and anything before the '# Page Spec' title."""
    reply = re.sub(r"^```\w*\n|\n```$", "", reply.strip())
    start = reply.find("# Page Spec")
    return reply[start:] if start >= 0 else reply


def _with_stack(spec: str) -> str:
    """Replace any Stack section with the harness's, placed before Success Criteria."""
    spec = re.sub(r"^## Stack\n.*?(?=^## |\Z)", "", spec, flags=re.DOTALL | re.MULTILINE)
    return spec.replace("## Success Criteria", STACK + "\n## Success Criteria", 1).strip() + "\n"
