"""File tools. Reads are limited to the spec, results, workspaces, and page source; writes go to the role's own workspace.

Agents see a virtual layout, whatever the run mode:
  spec/page-spec.md   the page spec
  results/...         run results
  workspace/...       role workspaces
  src/...             page source (build/src/... is accepted too)
"""

import difflib
from pathlib import Path

from tools.paths import BUILD_DIR, RESULTS_DIR, SPEC_PATH, WORKSPACE_DIR

MAX_READ_CHARS = 20_000
_ROOTS = {"results/": RESULTS_DIR, "workspace/": WORKSPACE_DIR, "build/src/": BUILD_DIR / "src",
          "src/": BUILD_DIR / "src"}


def _readable(path: str) -> Path | str:
    """Resolve a virtual path, or return an error message."""
    path = path.strip().replace("\\", "/").lstrip("/")
    if path in ("spec/page-spec.md", "spec.md"):
        target = SPEC_PATH
    else:
        prefix = next((p for p in _ROOTS if path.startswith(p)), None)
        if prefix is None:
            return "Error: readable paths are spec/page-spec.md, results/..., workspace/... and src/..."
        base = _ROOTS[prefix].resolve()
        target = (base / path[len(prefix):]).resolve()
        if not target.is_relative_to(base):
            return "Error: path escapes its folder."
    if not target.is_file():
        return f"Error: {path} does not exist."
    return target


def read_file(ctx, path: str) -> str:
    target = _readable(path)
    if isinstance(target, str):
        return target
    text = target.read_text(encoding="utf-8")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + "\n...[truncated]"
    return text


def write_file(ctx, path: str, content: str) -> str:
    workspace = ctx.workspace.resolve()
    target = (workspace / path).resolve()
    if not target.is_relative_to(workspace):
        return "Error: writes must stay inside your workspace."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to workspace/{ctx.role_name}/{path}"


def diff(ctx, path_a: str, path_b: str) -> str:
    targets = [_readable(path_a), _readable(path_b)]
    errors = [t for t in targets if isinstance(t, str)]
    if errors:
        return "\n".join(errors)
    a, b = (t.read_text(encoding="utf-8").splitlines() for t in targets)
    text = "\n".join(difflib.unified_diff(a, b, path_a, path_b, lineterm=""))
    return (text or "Files are identical.")[:MAX_READ_CHARS]
