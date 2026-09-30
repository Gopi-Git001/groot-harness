"""Role templates (prompts/<group>/<role>.md) and harness prompts (prompts/_loop/<name>.md)."""

import re
from dataclasses import dataclass
from pathlib import Path

from config import PROMPTS_DIR

LOOP_PROMPTS_DIR = PROMPTS_DIR / "_loop"


@dataclass(frozen=True)
class Role:
    name: str
    group: str
    template: str

    def render(self, spec: str, prior_drafts: str = "") -> str:
        """Fill the template's Context placeholders."""
        return fill(self.template, spec=spec, prior_drafts=prior_drafts or "None yet.")

    @property
    def mission(self) -> str:
        match = re.search(r"^# Mission\n(.*?)(?=^# )", self.template, re.DOTALL | re.MULTILINE)
        return match.group(1).strip() if match else ""


def fill(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def load_roles(prompts_dir: Path = PROMPTS_DIR) -> dict[str, Role]:
    """Load every role template. Folders starting with '_' hold harness prompts, not roles."""
    return {
        path.stem: Role(path.stem, path.parent.name, path.read_text(encoding="utf-8"))
        for path in sorted(prompts_dir.glob("*/*.md"))
        if not path.parent.name.startswith("_")
    }


def loop_prompt(name: str, **values: str) -> str:
    """Load a harness prompt from prompts/_loop/ and fill its {{placeholders}}."""
    return fill((LOOP_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"), **values)
