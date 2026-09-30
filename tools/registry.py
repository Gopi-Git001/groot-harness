"""Tool registry: every tool a sub-agent can call, and which groups may call it.

No sub-agent gets tools outside its group. The orchestrator only offers a role
its group's tools and refuses any other call.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tools import browser, files, skills
from tools.stubs import make_stub


@dataclass(frozen=True)
class ToolContext:
    role_name: str
    workspace: Path


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _params(**props: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": desc} for name, desc in props.items()},
        "required": list(props),
    }


TOOLS = {
    tool.name: tool
    for tool in [
        Tool(
            "read_file",
            "Read a file: a page file (src/...), or a repo file under spec/, results/ or workspace/.",
            _params(path="e.g. src/App.tsx or spec/page-spec.md"),
            files.read_file,
        ),
        Tool(
            "write_file",
            "Write a file into your own workspace.",
            _params(
                path="Path inside your workspace, e.g. src/components/Hero.tsx",
                content="Full file contents",
            ),
            files.write_file,
        ),
        Tool(
            "component_library_skill",
            "Get the shadcn/ui + Tailwind conventions every component must follow.",
            _params(),
            skills.component_library_skill,
        ),
        Tool(
            "api_mock_generator",
            "Generate typed mock data for an API shape.",
            _params(description="The data shape and example use"),
            make_stub("api_mock_generator", "a later stage"),
        ),
        Tool(
            "linter",
            "Lint a TypeScript/TSX file with ESLint.",
            _params(path="Repo-relative file path"),
            make_stub("linter", "a later stage"),
        ),
        Tool(
            "test_runner",
            "Run unit or e2e tests.",
            _params(path="Repo-relative test file path"),
            make_stub("test_runner", "a later stage"),
        ),
        Tool(
            "a11y_checker",
            "Run an accessibility audit (axe) on a page or component.",
            _params(path="Repo-relative file path"),
            make_stub("a11y_checker", "a later stage"),
        ),
        Tool(
            "playwright",
            "Build the merged page in build/ and load it in headless Chromium at 360/768/1024/1440px. "
            "Returns JSON: build result, console errors, page errors, unhandled rejections, horizontal "
            "overflow per width, landmarks, broken #anchors, aria-expanded toggle results, DOM outline.",
            _params(),
            browser.playwright,
        ),
        Tool(
            "run_tests",
            "Build the page and run the Playwright test suite in your workspace file tests.mjs in headless "
            "Chromium. Returns JSON: build result, load errors, and per test id: status (pass/fail/skipped) and error.",
            {
                "type": "object",
                "properties": {"ids": {"type": "string", "description": "Comma-separated test ids; empty runs all"}},
                "required": [],
            },
            browser.run_tests,
        ),
        Tool(
            "diff",
            "Unified diff of two repo files under spec/, results/, workspace/ or build/.",
            _params(path_a="First repo-relative path", path_b="Second repo-relative path"),
            files.diff,
        ),
    ]
}

_BUILD = ["read_file", "write_file", "component_library_skill"]
_LOGIC = ["read_file", "write_file", "api_mock_generator"]
_QUALITY = ["linter", "test_runner", "a11y_checker"]
_REVIEW = ["read_file", "write_file", "playwright", "diff"]

GROUP_TOOLS = {
    "layout": _BUILD,
    "components": _BUILD,
    "styling": _BUILD,
    "state": _LOGIC,
    "data": _LOGIC,
    "quality": _QUALITY,
    "assembly": _REVIEW,
    "judge": _REVIEW,
    "verifier": _REVIEW,
    # Stage 5 harness roles.
    "tester": ["read_file", "write_file", "run_tests"],
    "debugger": ["read_file", "diff"],
    "evaluator": ["read_file"],
}


def schemas_for(group: str) -> list[dict]:
    return [TOOLS[name].schema() for name in GROUP_TOOLS[group]]


def execute(group: str, name: str, arguments: str, ctx: ToolContext) -> str:
    """Run one tool call for a role, enforcing its group allowlist. Errors come back as text."""
    if name not in GROUP_TOOLS[group]:
        return f"Error: tool '{name}' is not allowed for the {group} group."
    try:
        args = json.loads(arguments or "{}")
        return TOOLS[name].handler(ctx, **args)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Error: bad arguments for '{name}': {exc}"
