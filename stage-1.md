# Stage 1: Scaffold the Repo

## Idea Recap
One agent, full harness. Brain: GPT-OSS 120B. 50 sub-agents as a front-end team. Unlimited free calls replace frontier reasoning depth. Scaffold with Claude Code/Codex; brain is the model only.

## Stage 1 Goal
A runnable repo skeleton: orchestrator can call GPT-OSS 120B once and print the response. Nothing else works yet — this stage proves the brain connection.

## What to Implement
1. README.md — project goal, architecture pointer, run instructions
2. spec/page-spec.md — the shared front-end page spec (prompt + constraints + success criteria) that every sub-agent will read
3. orchestrator/main.py — thin loop: load spec, call brain API, print raw output
4. orchestrator/brain.py — API client for GPT-OSS 120B (OpenAI-compatible endpoint, model name, temperature, max tokens as config)
5. orchestrator/config.py — model endpoint, model name, timeouts, batch size placeholder
6. results/ — empty folder; each sub-agent's output will land here later
7. requirements.txt — openai (or httpx if raw HTTP), python-dotenv
8. .env.example — GPT_OSS_ENDPOINT=, GPT_OSS_MODEL=gpt-oss-120b

## Skills / MCPs / Plugins Needed
- None required in Stage 1. No MCP servers, no plugins.
- Optional nice-to-have: a skills/ folder stub for future component-library skills (shadcn/Tailwind prompts). Leave empty.

## Out of Scope (Later Stages)
- Sub-agent dispatch, judge, assembler, Playwright verifier, benchmark logging

## Stage 1 Done When
python orchestrator/main.py returns a coherent response from GPT-OSS 120B about the page spec, proving the harness can talk to the brain.