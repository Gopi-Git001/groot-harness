# Claude.md

## Project
GPT-OSS 120B Front-End Harness. One agent, full harness. Brain: GPT-OSS 120B (open source, free, no token limits). 50 sub-agents as a coordinated front-end team. Thesis: unlimited iterations, critique/rewrite loops, judge scoring, and headless verification close the gap with frontier reasoning. Success: same prompt beats Claude Code, Codex, Cursor, Gemini on structure, fidelity, polish. Scaffold with Claude Code/Codex; they are not the brain.

## Stages
Stage 1: scaffold repo + orchestrator skeleton (brain connection proof)
Stage 2: sub-agent role templates + dispatch loop
Stage 3: judge + critique/rewrite loop
Stage 4: assembler + verifier (Playwright headless browser)
Stage 5: benchmark harness + logging

## Rules
- Follow stages in order. Do not skip or merge.
- Brain = GPT-OSS 120B via API only.
- Stack choices (TypeScript/JavaScript, React, etc.) decided in Stage 2, not Stage 1.
- Stage 1 is tech-agnostic skeleton only.