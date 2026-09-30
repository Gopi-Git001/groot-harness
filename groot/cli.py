"""groot CLI: build a web page from a prompt or from a folder of instructions.

    groot                                       interactive chat: describe, refine the plan, build, preview
    groot init                                  set up the model endpoint and API key
    groot build "a landing page for ..." --out ./my-site
    groot build ./my-folder                     reads INSTRUCTIONS.md (or the folder's only .md file)
    groot build ./my-folder --review            stop after writing the spec so you can edit it
    groot build ./my-folder --from-stage 4      resume from a stage
    groot preview ./my-folder                   serve the built page at http://localhost:4173
    groot test ./my-folder                      re-run Stage 5 (tests, debugging, evaluation)
    groot status ./my-folder                    show what has been produced

Project folder layout:
    INSTRUCTIONS.md   your instructions (never modified; written from --prompt text in prompt mode)
    assets/           optional images and files the page may use, served at /assets/<name>
    groot/            harness state: spec.md, build.log (live progress), results/ (reports, scores), workspace/
    site/             the finished React + Vite project
"""

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent
USER_ENV = Path.home() / ".groot" / ".env"
INSTRUCTION_NAMES = ("INSTRUCTIONS.md", "instructions.md", "Instructions.md")
PREVIEW_PORT = 4173


class _Tee:
    """Write output to the terminal and to the project's groot/build.log as it happens."""

    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.log.write(text)
        return len(text)

    def flush(self) -> None:
        self.stream.flush()
        self.log.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _log_to(project: Path) -> None:
    """Mirror stdout/stderr into <project>/groot/build.log, line by line."""
    log_path = project / "groot" / "build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 (lives for the whole run)
    log.write(f"\n===== groot {' '.join(sys.argv[1:])} =====\n")
    sys.stdout, sys.stderr = _Tee(sys.stdout, log), _Tee(sys.stderr, log)


def main(argv: list[str] | None = None) -> None:
    # Flush every line, so progress shows live even when output is redirected to a file.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv == ["build"]:  # `groot` alone opens the chat.
        from groot import chat
        chat.run()
        return
    parser = argparse.ArgumentParser(prog="groot", description="Build a web page with a GPT-OSS 120B agent team. "
                                     "Run `groot` with no arguments for an interactive chat.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="configure the model endpoint and API key (~/.groot/.env)")

    build = sub.add_parser("build", help="build a page from a prompt or a folder of instructions")
    build.add_argument("target", help="a prompt in quotes, or a folder containing INSTRUCTIONS.md")
    build.add_argument("--out", help="project folder for prompt mode (default: ./<slug of the prompt>)")
    build.add_argument("--instructions", help="instructions file inside the folder (default: INSTRUCTIONS.md)")
    build.add_argument("--review", action="store_true", help="stop after writing the spec")
    build.add_argument("--respec", action="store_true", help="rewrite the spec even if groot/spec.md exists")
    build.add_argument("--from-stage", type=int, choices=[2, 3, 4, 5], default=2, help="resume from this stage")
    build.add_argument("--rounds", type=int, default=5, help="Stage 3 round cap")

    for name, text in (("preview", "serve the built page"), ("test", "re-run Stage 5 on the built page"),
                       ("status", "show what has been produced")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("folder", nargs="?", default=".", help="project folder (default: current folder)")
        if name == "preview":
            cmd.add_argument("--port", type=int, default=PREVIEW_PORT)

    args = parser.parse_args(argv)
    {"init": cmd_init, "build": cmd_build, "preview": cmd_preview,
     "test": cmd_test, "status": cmd_status}[args.command](args)


# --- init --------------------------------------------------------------------

def cmd_init(args) -> None:
    print("groot setup: the brain is GPT-OSS 120B behind any OpenAI-compatible endpoint.\n")
    endpoint = input("Endpoint [https://openrouter.ai/api/v1]: ").strip() or "https://openrouter.ai/api/v1"
    default_model = "openai/gpt-oss-120b" if "openrouter" in endpoint else "gpt-oss-120b"
    model = input(f"Model [{default_model}]: ").strip() or default_model
    key = getpass.getpass("API key (hidden; leave blank for local servers): ").strip()
    USER_ENV.parent.mkdir(parents=True, exist_ok=True)
    USER_ENV.write_text(f"GPT_OSS_ENDPOINT={endpoint}\nGPT_OSS_MODEL={model}\nGPT_OSS_API_KEY={key}\n", encoding="utf-8")
    try:
        USER_ENV.chmod(0o600)
    except OSError:
        pass
    print(f"\nSaved to {USER_ENV}")
    missing = [tool for tool in ("node", "npm", "npx") if not shutil.which(tool)]
    print("Node.js: " + (f"MISSING ({', '.join(missing)}). Install Node 18+ before building."
                         if missing else "found"))


# --- build -------------------------------------------------------------------

def cmd_build(args) -> None:
    project, instructions = _resolve_target(args)
    _log_to(project)
    _bootstrap(project)
    from brain import Brain
    from config import SPEC_PATH, load_config
    from specwriter import write_spec
    from tools.paths import ASSETS_DIR

    brain = Brain(load_config())
    print(f"Project: {project}")
    if args.respec or not SPEC_PATH.exists():
        assets = sorted(p.name for p in ASSETS_DIR.iterdir() if p.is_file()) if ASSETS_DIR.is_dir() else []
        print("\n== Spec writer: turning your instructions into the page spec ==")
        SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
        SPEC_PATH.write_text(write_spec(brain, instructions, assets), encoding="utf-8")
        print(f"  spec written: {SPEC_PATH}")
    else:
        print(f"Using existing spec: {SPEC_PATH} (pass --respec to rewrite it)")
    if args.review:
        print("\nReview or edit the spec, then run:\n"
              f"  groot build \"{project}\"")
        return
    page_works = _run_stages(brain, args.from_stage, args.rounds)
    _summary(project)
    if not page_works:
        sys.exit(1)


def _resolve_target(args) -> tuple[Path, str]:
    """Folder mode if target is an existing folder; otherwise target is the prompt."""
    target = Path(args.target).expanduser()
    if target.is_dir():
        project = target.resolve()
        name = args.instructions
        if name:
            path = project / name
        else:
            found = [project / n for n in INSTRUCTION_NAMES if (project / n).is_file()]
            others = sorted(p for p in project.glob("*.md") if p.is_file())
            path = found[0] if found else (others[0] if len(others) == 1 else None)
            if path is None:
                raise SystemExit(f"No instructions in {project}: add INSTRUCTIONS.md or pass --instructions FILE.")
        if not path.is_file():
            raise SystemExit(f"Instructions file not found: {path}")
        print(f"Instructions: {path.name}")
        return project, path.read_text(encoding="utf-8")

    prompt = args.target.strip()
    if len(prompt) < 10:
        raise SystemExit(f"'{args.target}' is not a folder, and too short to be a prompt.")
    slug = "-".join(re.findall(r"[a-z0-9]+", prompt.lower())[:5]) or "site"
    project = Path(args.out or slug).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    instructions_file = project / "INSTRUCTIONS.md"
    if not instructions_file.exists():  # Keep the prompt with the project so it can be rebuilt.
        instructions_file.write_text(prompt + "\n", encoding="utf-8")
    return project, prompt


def _run_stages(brain, from_stage: int, rounds: int) -> bool:
    """Run the stages; returns False when the final page does not build or renders blank."""
    from config import SPEC_PATH
    from main import run_stage3, select
    from loop import BUILDER_GROUPS
    from roles import load_roles
    from stage4 import run_stage4
    from stage5 import run_stage5

    spec = SPEC_PATH.read_text(encoding="utf-8")
    roles = load_roles()
    batch = brain.config.batch_size
    if from_stage <= 3:  # Stage 3 dispatches Stage 2 for any role without a slice.
        builders = [n for n, r in roles.items() if r.group in BUILDER_GROUPS]
        run_stage3(select(roles, builders), roles["assembly-merge"], brain, spec, batch, rounds)
    if from_stage <= 4:
        final = run_stage4(brain, spec, roles, batch)
        if not final.build_ok or final.blank:
            print("\nStage 5 skipped: the page does not build or renders blank. "
                  "See groot/results/stage-4-report.md.")
            return False
    run_stage5(brain, spec)
    return True


def _summary(project: Path) -> None:
    results = project / "groot" / "results"
    evaluation = results / "stage-5-evaluation.md"
    print("\n== Done ==")
    if evaluation.exists():
        overall = re.search(r"\*\*Overall: .*", evaluation.read_text(encoding="utf-8"))
        print(f"  {overall.group(0) if overall else 'evaluation written'}")
    for name in ("stage-4-report.md", "stage-5-test-results.md", "stage-5-evaluation.md"):
        if (results / name).exists():
            print(f"  report: {results / name}")
    print(f"  site:   {project / 'site'}")
    print(f"\nPreview: groot preview \"{project}\"   ->  http://localhost:{PREVIEW_PORT}")


# --- preview / test / status -------------------------------------------------

def cmd_preview(args) -> None:
    project = _existing_project(args.folder)
    site = project / "site"
    if not (site / "node_modules").is_dir():
        raise SystemExit(f"No built site in {site}. Run `groot build` first.")
    npx = shutil.which("npx") or sys.exit("npx not found: install Node.js 18+.")
    if not (site / "dist" / "index.html").exists():
        subprocess.run([npx, "vite", "build"], cwd=site, check=True)
    print(f"Serving {site} at http://localhost:{args.port}  (Ctrl+C to stop)")
    subprocess.run([npx, "vite", "preview", "--port", str(args.port), "--strictPort"], cwd=site)


def cmd_test(args) -> None:
    project = _existing_project(args.folder)
    _log_to(project)
    _bootstrap(project)
    from brain import Brain
    from config import SPEC_PATH, load_config
    from stage5 import run_stage5

    if not SPEC_PATH.exists():
        raise SystemExit(f"No spec at {SPEC_PATH}. Run `groot build` first.")
    run_stage5(Brain(load_config()), SPEC_PATH.read_text(encoding="utf-8"))
    _summary(project)


def cmd_status(args) -> None:
    project = _existing_project(args.folder)
    state, results = project / "groot", project / "groot" / "results"
    slices = sorted(results.glob("*-*.md")) if results.is_dir() else []
    role_slices = [p for p in slices if not p.name.startswith("stage-")]
    rows = [
        ("instructions", next((n for n in INSTRUCTION_NAMES if (project / n).exists()), "-")),
        ("spec", "yes" if (state / "spec.md").exists() else "no"),
        ("stage 2 slices", str(len(role_slices))),
        ("stage 3 log", "yes" if (results / "stage-3-log.md").exists() else "no"),
        ("stage 4 report", _first_line(results / "stage-4-report.md", r"\*\*Outcome: [^*]+\*\*")),
        ("stage 5 tests", _first_line(results / "stage-5-test-results.md", r"Final run: .*")),
        ("stage 5 score", _first_line(results / "stage-5-evaluation.md", r"\*\*Overall: [^*]+\*\*")),
        ("site", "built" if (project / "site" / "dist" / "index.html").exists() else "not built"),
    ]
    print(f"Project: {project}")
    for label, value in rows:
        print(f"  {label:<15} {value}")


def _first_line(path: Path, pattern: str) -> str:
    if not path.exists():
        return "-"
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    return match.group(0).strip("*") if match else "present"


def _existing_project(folder: str) -> Path:
    project = Path(folder).expanduser().resolve()
    if not (project / "groot").is_dir():
        raise SystemExit(f"{project} is not a groot project (no groot/ folder). Run `groot build` first.")
    return project


def _bootstrap(project: Path) -> None:
    """Point the harness at the project folder, then make its modules importable."""
    if not (HARNESS_DIR / "orchestrator").is_dir():
        raise SystemExit("groot must be installed from a clone of the repo: pip install -e <repo folder>")
    os.environ["GROOT_PROJECT_DIR"] = str(project)
    for path in (str(HARNESS_DIR / "orchestrator"), str(HARNESS_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)


if __name__ == "__main__":
    main()
