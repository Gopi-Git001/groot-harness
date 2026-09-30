"""Where the harness reads its own assets and where a run writes its state.

Harness assets (prompts, scaffold) always live next to this code. Run state depends on the mode:
- Project mode (GROOT_PROJECT_DIR set, as the `groot` CLI does): everything goes into the user's folder:
    <project>/groot/spec.md, <project>/groot/results/, <project>/groot/workspace/, <project>/site/
- Repo mode (no GROOT_PROJECT_DIR, as `python orchestrator/main.py` runs): the original repo layout.
"""

import os
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = HARNESS_DIR / "prompts"
SCAFFOLD_DIR = HARNESS_DIR / "scaffold"

_project = os.environ.get("GROOT_PROJECT_DIR", "").strip()
if _project:
    PROJECT_DIR = Path(_project).resolve()
    STATE_DIR = PROJECT_DIR / "groot"
    SPEC_PATH = STATE_DIR / "spec.md"
    RESULTS_DIR = STATE_DIR / "results"
    WORKSPACE_DIR = STATE_DIR / "workspace"
    BUILD_DIR = PROJECT_DIR / "site"
    ASSETS_DIR = PROJECT_DIR / "assets"
else:
    PROJECT_DIR = HARNESS_DIR
    STATE_DIR = HARNESS_DIR
    SPEC_PATH = HARNESS_DIR / "spec" / "page-spec.md"
    RESULTS_DIR = HARNESS_DIR / "results"
    WORKSPACE_DIR = HARNESS_DIR / "workspace"
    BUILD_DIR = HARNESS_DIR / "build"
    ASSETS_DIR = HARNESS_DIR / "assets"
