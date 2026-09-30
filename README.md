# GPT-OSS 120B Front-End Harness

One agent, full harness. The brain is GPT-OSS 120B (open source, free, no token limits). The harness coordinates 50 sub-agents as a front-end team, using unlimited critique/rewrite loops, judge scoring, and headless verification to match or beat Claude Code, Codex, Cursor, and Gemini on the same prompt.

## Install
Requires Python 3.10+, Node.js 18+, and an OpenAI-compatible endpoint serving GPT-OSS 120B (e.g. OpenRouter).

```
git clone <this repo> groot && cd groot
pip install -e .          # installs the `groot` command (editable: it runs from this checkout)
groot init                # endpoint, model, API key -> ~/.groot/.env
```

## Use
Give it a prompt:
```
groot build "A landing page for my coffee shop: innovative, very simple, looks great" --out ./coffee
```
or a folder with an instructions file (free-form markdown) and optional assets:
```
my-site/
  INSTRUCTIONS.md     # what you want: sections, text, colors, features
  assets/             # optional: logo.svg, photos (the page can use them at /assets/<name>)

groot build ./my-site
```
Then:
```
groot preview ./my-site     # http://localhost:4173
groot status ./my-site      # what has been produced, test results, scores
groot test ./my-site        # re-run Stage 5 (tests, debugging, evaluation)
```
Useful flags: `--review` stops after the spec is written so you can edit `groot/spec.md`; `--respec` rewrites it; `--from-stage 4` resumes a run; `--instructions notes.md` picks a different file.

What lands in your folder:
```
my-site/
  INSTRUCTIONS.md     # yours, never modified (prompt mode writes your prompt here)
  groot/spec.md       # the structured spec the spec writer (GPT-OSS) produced from your instructions
  groot/results/      # Stage 2-5 slices, logs, reports, test results, evaluation
  site/               # the finished React + Vite + Tailwind project (npm run dev / npm run build)
```

## Architecture
- Design and stages: [CLAUDE.md](CLAUDE.md), [agent-harness-procedure.md](agent-harness-procedure.md)
- Stage docs: [stage-1.md](stage-1.md) (brain connection), [stage-2.md](stage-2.md) (roles + dispatch), [stage-3.md](stage-3.md) (judge + critique/rewrite loop), [stage-4.md](stage-4.md) (assembly + headless verification) — current
- Generated page stack: React + TypeScript + Tailwind (shadcn/ui style), see [spec/page-spec.md](spec/page-spec.md)

```
groot/cli.py    # the `groot` command: init, build, preview, test, status
orchestrator/
  specwriter.py # GPT-OSS spec writer: prompt or instructions file -> structured page spec
  main.py       # developer CLI (repo mode): --stage 2, 3, 4, 5
  dispatch.py   # Stage 2: parallel batches of 10, writes/reads results/<role>.md
  loop.py       # Stage 3: judge slices -> critique failures -> merge -> judge page, up to 5 rounds
  judge.py      # Stage 3 judge: structure/fidelity/polish scores + specific failure reasons
  stage4.py     # Stage 4: assemble -> verify -> fix loop (3 rounds), writes stage-4-report.md
  stage5.py     # Stage 5: testing role writes/runs a Playwright suite -> debugging role -> evaluation role
  assembler.py  # Stage 4 assembler: collect all slice files, resolve conflicts, wire App.tsx, self-check
  verifier.py   # Stage 4 verifier: GPT-OSS + real Playwright tool, owner attribution, spec audit
  pagefiles.py  # deterministic file extraction, import resolution, exports, dead-code graph
  parallel.py   # run named tasks concurrently
  agent.py      # per-role thinking loop: plan+code+tools -> self-review -> revise once if < 80
  roles.py      # loads prompts/<group>/<role>.md and fills {{spec}} / {{prior_drafts}}
  brain.py      # OpenAI-compatible client for GPT-OSS 120B (chat + tool calls)
  config.py     # endpoint, model, temperature, max tokens, timeouts, batch size
prompts/        # 50 role templates (Role, Mission, Context, Tools, Output), one folder per group
  _loop/        # harness prompts: Stage 3 (judge-*, critique, merge), Stage 4 (assembler, resolve, wire,
                #   repair, selfcheck, verifier, fix)
scaffold/       # harness-owned Vite + React + Tailwind project, verify.mjs (Stage 4) and run-tests.mjs (Stage 5)
build/          # scaffold copy + merged src/, built and verified here (node_modules kept)
tools/
  paths.py      # where state is written: the user's project folder (CLI) or this repo (developer mode)
  registry.py   # tool schemas + per-group allowlists (enforced at call time)
  files.py      # read_file / write_file / diff (writes confined to workspace/<role>/)
  browser.py    # playwright tool: build the page in build/ and run verify.mjs
  skills/       # component library skill (shadcn/Tailwind conventions)
  stubs.py      # linter, test runner, a11y, API mock: registered, built later
spec/page-spec.md  # shared page spec every sub-agent reads
results/        # Stage 2: <role>.md | Stage 3: stage-3-page.md, stage-3-log.md, stage-3/
                # Stage 4: stage-4-page.md, stage-4-merge-report.md, stage-4-report.md
                # Stage 5: stage-5-test-results.md, stage-5-debug-log.md, stage-5-evaluation.md,
                #          stage-5-tests.mjs, stage-5-page.md
workspace/      # files each role writes with write_file
```

## Developer mode (run stages from the repo)
Requires Python 3.10+ and Node 18+ (Stage 4). The first Stage 4 run installs the page dependencies and Chromium into `build/`.

```
pip install -r requirements.txt
cp .env.example .env          # set GPT_OSS_ENDPOINT, GPT_OSS_MODEL, GPT_OSS_API_KEY
python orchestrator/main.py                 # proof batch: one role per group (10 roles)
python orchestrator/main.py --roles components-hero,styling-colors
python orchestrator/main.py --all           # all 50 roles in batches of 10
python orchestrator/main.py --stage 3       # Stage 3 over the 32 builder slices (runs missing Stage 2 slices first)
python orchestrator/main.py --stage 3 --roles components-hero,layout-grid --rounds 2
python orchestrator/main.py --stage 4       # assemble Stage 3 slices, verify in headless Chromium, fix (3 rounds)
python orchestrator/main.py --stage 5       # test suite, debugging, evaluation of the Stage 4 page
```

To build a page from your own prompt: write it into `spec/page-spec.md` (keep the Prompt / Constraints / Stack / Success Criteria headings), move any previous `results/` and `workspace/` aside, then run `--stage 3`, `--stage 4`, `--stage 5`. View the page with `cd build; npx vite preview` (http://localhost:4173). Benchmarking against other tools is done manually outside the harness.

Stage 3 ends when the whole-page judge score is 85+ or 5 rounds are exhausted. Output: the best merged page in `results/stage-3-page.md` and every round's scores and failure reasons in `results/stage-3-log.md`.

Stage 4 is done when the merged page loads in headless Playwright with zero console errors and zero runtime crashes, and the spec-compliance audit passes every requirement. Output: `results/stage-4-page.md` (merged source), `results/stage-4-merge-report.md`, and `results/stage-4-report.md` (checks, audit, full error and fix log).
