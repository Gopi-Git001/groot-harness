"""Interactive groot session: describe a page in chat, refine the plan, build it, and open the preview.

Started by running `groot` with no arguments (or `groot build` with no target).
"""

import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from groot import cli

YES = {"y", "yes", "go", "build", "build it", "ok", "okay", "start", "do it", "yes build it"}
QUIT = {"q", "quit", "exit", "bye"}
# Build output lines worth showing in the chat; everything else goes to groot/build.log only.
PROGRESS = re.compile(r"^(== |Stage \d|  page score|  converged|\d+/\d+ roles|Average confidence|"
                      r"  (?:build ok|build FAILED)|Stage [45] |  \d+ passed|  scores:|  \[brain\]|  FAIL )")


def run() -> None:
    _say("groot — a GPT-OSS 120B team that builds your web page.")
    _say("Describe the page you want: what it is for, sections, text, colors, anything that matters.")
    _say("(Press Enter on an empty line to send. Type 'quit' to leave.)\n")

    description = _read_message()
    if not description or description.lower() in QUIT:
        return
    project = _choose_folder(description)

    cli._bootstrap(project)
    from brain import Brain
    from config import SPEC_PATH, load_config
    from specwriter import revise_spec, write_spec
    from tools.paths import ASSETS_DIR

    brain = Brain(load_config())
    assets = sorted(p.name for p in ASSETS_DIR.iterdir() if p.is_file()) if ASSETS_DIR.is_dir() else []
    (project / "INSTRUCTIONS.md").write_text(description + "\n", encoding="utf-8")

    _say("Planning your page...")
    spec = write_spec(brain, description, assets)
    _save_spec(SPEC_PATH, spec)
    _show_plan(spec)

    while True:
        _say("Want changes? Describe them. Or type 'yes' to build, 'show' for the full plan, 'quit' to stop.")
        reply = _read_message()
        answer = reply.strip().lower().rstrip("!.")
        if not answer:
            continue
        if answer in QUIT:
            _say(f"Stopped. Your plan is saved in {SPEC_PATH}; build it later with: groot build \"{project}\"")
            return
        if answer == "show":
            print("\n" + spec)
            continue
        if answer in YES:
            break
        _say("Updating the plan...")
        spec = revise_spec(brain, spec, reply, assets)
        _save_spec(SPEC_PATH, spec)
        with open(project / "INSTRUCTIONS.md", "a", encoding="utf-8") as notes:
            notes.write(f"\nChange: {reply.strip()}\n")
        _show_plan(spec)

    _build(brain, project)


def _build(brain, project: Path) -> None:
    _say(f"Building in {project}. This takes about 45-70 minutes; full detail goes to groot/build.log.")
    _say("You can leave this running. If it stops, resume with: groot build \"%s\" --from-stage 3\n" % project)
    terminal = sys.stdout
    sys.stdout = _Progress(terminal, project / "groot" / "build.log")
    try:
        page_works = cli._run_stages(brain, from_stage=2, rounds=5)
    except KeyboardInterrupt:
        sys.stdout = terminal
        _say(f"Interrupted. Resume with: groot build \"{project}\" --from-stage 3")
        return
    finally:
        sys.stdout.flush()
        sys.stdout = terminal

    cli._summary(project)
    if not page_works:
        _say("The page did not come out working. See groot/results/stage-4-report.md for what went wrong.")
        return
    _preview(project)


def _preview(project: Path) -> None:
    npx = shutil.which("npx")
    site = project / "site"
    if not npx or not (site / "dist" / "index.html").exists():
        _say(f"Preview with: groot preview \"{project}\"")
        return
    url = f"http://localhost:{cli.PREVIEW_PORT}"
    server = subprocess.Popen([npx, "vite", "preview", "--port", str(cli.PREVIEW_PORT), "--strictPort"],
                              cwd=site, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    webbrowser.open(url)
    _say(f"Your page is open at {url}. Press Enter here to stop the preview and exit.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        server.terminate()


# --- helpers -----------------------------------------------------------------

FILLER = {"a", "an", "the", "for", "my", "our", "page", "landing", "website", "web", "site", "one", "single",
           "with", "and", "of", "to", "in", "on", "that", "is", "it", "i", "want", "need", "build", "create", "make",
           "please", "small", "simple", "nice", "new"}


def _choose_folder(description: str) -> Path:
    words = [w for w in re.findall(r"[a-z0-9]+", description.lower()) if w not in FILLER]
    slug = "-".join(words[:3]) or "my-site"
    default = Path.home() / "Documents" / slug
    answer = input(f"\ngroot › Where should I put it? [{default}]\nyou › ").strip().strip('"')
    project = Path(answer).expanduser().resolve() if answer else default
    project.mkdir(parents=True, exist_ok=True)
    return project


def _read_message() -> str:
    lines = []
    try:
        while True:
            line = input("you › " if not lines else "      ")
            if not line.strip():
                if lines:
                    break
                continue
            lines.append(line)
            if len(lines) == 1 and line.strip().lower() in QUIT | YES | {"show"}:
                break  # One-word commands send immediately.
    except (EOFError, KeyboardInterrupt):
        return "quit"
    return "\n".join(lines).strip()


def _save_spec(path: Path, spec: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(spec, encoding="utf-8")


def _show_plan(spec: str) -> None:
    """A short summary of the spec: the opening paragraph, the numbered sections, and the palette."""
    prompt = re.search(r"## Prompt\s*\n(.*?)(?=^## )", spec, re.DOTALL | re.MULTILINE)
    body = prompt.group(1) if prompt else spec
    intro = body.strip().split("\n\n")[0]
    sections = re.findall(r"^\s*\d+\.\s+(.+)$", body, re.MULTILINE)
    lines = spec.split("## Constraints", 1)[-1].split("\n## ", 1)[0].splitlines()
    at = next((i for pattern in (r"(?i)palette", r"(?i)colou?rs?\b(?!\s+contrast)")
               for i, line in enumerate(lines) if re.search(pattern, line)), None)
    palette = ""
    if at is not None:
        palette = lines[at]
        if palette.rstrip().endswith(":"):  # Details follow as a nested list or a CSS block.
            items = []
            indent = len(palette) - len(palette.lstrip())
            for line in lines[at + 1:at + 10]:
                depth = len(line) - len(line.lstrip())
                if line.strip() and depth <= indent and not line.strip().startswith("`"):
                    break  # Next item at the heading's level: the palette details are over.
                if re.match(r"\s*[-*]\s", line):
                    items.append(line.strip(" -*"))
                elif hexes := re.search(r"(#[0-9a-fA-F]{3,6})\b.*?(?:/\*\s*(.*?)\s*\*/)?\s*$", line):
                    items.append(f"{hexes.group(2)} {hexes.group(1)}" if hexes.group(2) else hexes.group(1))
            palette = palette.rstrip() + " " + ", ".join(items[:6])
    print()
    _say("Here's the plan:")
    print(f"   {_short(intro, 400)}")
    for i, section in enumerate(sections, 1):
        print(f"   {i}. {_short(section, 110)}")
    if palette:
        style = re.sub(r"^[-\s]*", "", palette)
        print(f"   Style: {_short(style, 140)}")
    print()


def _plain(text: str) -> str:
    return re.sub(r"[*`]", "", " ".join(text.split()))


def _short(text: str, limit: int) -> str:
    """Plain text cut at a word boundary."""
    text = _plain(text)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _say(text: str) -> None:
    print(f"groot › {text}")


class _Progress:
    """During a build: every line to groot/build.log, only milestone lines to the chat."""

    def __init__(self, terminal, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.terminal = terminal
        self.log = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        self.pending = ""

    def write(self, text: str) -> int:
        self.log.write(text)
        self.pending += text
        *lines, self.pending = self.pending.split("\n")
        for line in lines:
            if PROGRESS.match(line):
                self.terminal.write(f"   {line.strip()}\n")
                self.terminal.flush()
        return len(text)

    def flush(self) -> None:
        self.log.flush()
        self.terminal.flush()

    def __getattr__(self, name):
        return getattr(self.terminal, name)
