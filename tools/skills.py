"""Skill tools: return curated guidance documents from tools/skills/."""

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def component_library_skill(ctx) -> str:
    return (SKILLS_DIR / "shadcn-tailwind.md").read_text(encoding="utf-8")
