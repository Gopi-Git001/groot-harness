"""Orchestrator entry point.

Stage 2: dispatch role templates in parallel batches against the page spec.
Stage 3: judge, critique, and rewrite the builder slices until the merged page converges.

    python orchestrator/main.py                        # Stage 2 proof batch (one role per group + 1)
    python orchestrator/main.py --roles a,b,c          # Stage 2, specific roles
    python orchestrator/main.py --all                  # Stage 2, all 50 roles
    python orchestrator/main.py --stage 3              # Stage 3 over all 32 builder roles
    python orchestrator/main.py --stage 3 --roles a,b --rounds 2
    python orchestrator/main.py --stage 4              # assemble Stage 3 slices, verify in headless Chromium, fix
    python orchestrator/main.py --stage 5              # test, debug, and evaluate the Stage 4 page
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make tools/ importable

from brain import Brain  # noqa: E402
from config import SPEC_PATH, load_config  # noqa: E402
from dispatch import load_result, run_batches  # noqa: E402
from loop import BUILDER_GROUPS, LOG_PATH, MAX_ROUNDS, PAGE_PATH, Slice, Stage3  # noqa: E402
from roles import Role, load_roles  # noqa: E402
from stage4 import run_stage4  # noqa: E402
from stage5 import run_stage5  # noqa: E402

PROOF_BATCH = [
    "layout-page-structure",
    "components-hero",
    "components-navigation",
    "styling-colors",
    "state-local-state",
    "data-mocking",
    "quality-a11y",
    "assembly-merge",
    "judge-fidelity",
    "verifier-console",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the front-end harness against the page spec.")
    parser.add_argument("--stage", type=int, choices=[2, 3, 4, 5], default=2)
    parser.add_argument("--roles", help="Comma-separated role names")
    parser.add_argument("--all", action="store_true", help="Stage 2: run all roles")
    parser.add_argument("--rounds", type=int, default=MAX_ROUNDS, help="Stage 3: round cap")
    args = parser.parse_args()

    config = load_config()
    roles = load_roles()
    spec = SPEC_PATH.read_text(encoding="utf-8")
    brain = Brain(config)

    if args.stage == 2:
        names = list(roles) if args.all else args.roles.split(",") if args.roles else PROOF_BATCH
        run_stage2(select(roles, names), brain, spec, config.batch_size)
    elif args.stage == 4:
        run_stage4(brain, spec, roles, config.batch_size)
    elif args.stage == 5:
        run_stage5(brain, spec)
    else:
        builders = [n for n, r in roles.items() if r.group in BUILDER_GROUPS]
        names = args.roles.split(",") if args.roles else builders
        not_builders = [n for n in names if n in roles and n not in builders]
        if not_builders:
            raise SystemExit(f"Stage 3 only takes builder roles ({', '.join(BUILDER_GROUPS)}): {', '.join(not_builders)}")
        run_stage3(select(roles, names), roles["assembly-merge"], brain, spec, config.batch_size, args.rounds)


def select(roles: dict[str, Role], names: list[str]) -> list[Role]:
    unknown = [n for n in names if n not in roles]
    if unknown:
        raise SystemExit(f"Unknown roles: {', '.join(unknown)}")
    return [roles[n] for n in names]


def run_stage2(selected: list[Role], brain: Brain, spec: str, batch_size: int) -> None:
    print(f"Dispatching {len(selected)} roles to {brain.config.model} in batches of {batch_size}")
    results = run_batches(selected, brain, spec, batch_size)
    print(f"\n{len(results)}/{len(selected)} roles produced scored slices.")
    if results:
        print(f"Average confidence: {sum(r.score for r in results) / len(results):.0f}/100")


def run_stage3(selected: list[Role], merger: Role, brain: Brain, spec: str, batch_size: int, rounds: int) -> None:
    missing = [r for r in selected if load_result(r) is None]
    if missing:
        print(f"{len(missing)} roles have no Stage 2 slice yet; dispatching them first.")
        run_stage2(missing, brain, spec, batch_size)

    slices = [Slice(r, *loaded) for r in selected if (loaded := load_result(r))]
    if not slices:
        raise SystemExit("No Stage 2 slices available for Stage 3.")
    print(f"\nStage 3: {len(slices)} slices, up to {rounds} rounds")

    best = Stage3(brain, spec, merger, workers=batch_size, max_rounds=rounds).run(slices)
    if best:
        print(f"\nBest page: round {best.number}, score {best.page_verdict.score}/100 -> "
              f"{PAGE_PATH.relative_to(PAGE_PATH.parent.parent)}")
        print(f"Log: {LOG_PATH.relative_to(LOG_PATH.parent.parent)}")


if __name__ == "__main__":
    main()
