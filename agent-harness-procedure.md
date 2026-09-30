# Agent Idea — GPT-OSS 120B Front-End Harness

## The Idea
One agent, full harness. Brain is GPT-OSS 120B — open source, free, no token limits, so the harness can call it as many times as needed. The harness runs fifty sub-agents as a coordinated team building one front-end page. The thesis: the model alone can't match frontier reasoning, but unlimited iterations, critique, and rewrite loops in the harness close that gap. Success means the same prompt and instructions produce a page equal to or better than what Claude, Codex, or Cursor output. Build step by step in one to two hours using Claude Code or Codex as scaffolding tool, not as the brain. Agent two comes after this one ships.

## Build Procedure (6 Steps)
1. Scaffold the repo: thin orchestrator loop calling GPT-OSS 120B via API, shared task spec, result folder per sub-agent.
2. Define fifty sub-agent roles as prompt templates — layout, components, styling, state, testing — each gets the same page spec, different slice.
3. The loop: orchestrator dispatches sub-agents in parallel batches, collects drafts, runs critique and rewrite passes against the spec until convergence. A judge sub-agent scores each draft and sends failures back with specific reasons.
4. Final assembly: merge best pieces into one page, run a final self-check pass.
5. Debugging, testing, evaluation: dedicated sub-agent runs the page in a headless browser, catches errors, evaluates before comparison.
6. Benchmark: same prompt to Claude, Codex, and Cursor; score on structure, fidelity, polish; log wins and losses to target harness gaps.

## Key Lever
Iteration depth. Frontier models get one careful pass; this harness can afford twenty. Free unlimited calls to the open model is the real edge.