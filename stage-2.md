# Stage 2: Sub-Agent Roles, Prompts, Tools, and Thinking

## Goal
50 sub-agents, each a specialist with its own prompt template, tool access, and reasoning loop. Slices combine to beat frontier output on the same page spec.

## Role Template (markdown, five sections)
- Role: one-line identity
- Mission: the slice to produce
- Context: shared page spec + prior drafts
- Tools: allowed tool list only
- Output: code slice + rationale + confidence score 0-100

## The 50 Roles by Group
Layout: page structure, grid, flex, spacing, breakpoints (5 roles)
Components: buttons, cards, nav, modals, forms (8 roles)
Styling: colors, typography, themes, dark mode, animations (7 roles)
State: global store, local state, derived state, persistence (5 roles)
Data: fetching, caching, mocking, WebSocket, API integration (7 roles)
Quality: unit tests, e2e tests, lint, a11y, performance, SEO (6 roles)
Assembly: merge, dedupe, resolve conflicts, final self-check (4 roles)
Judge: score drafts, list specific failure reasons (4 roles)
Verifier: Playwright headless run, console/runtime/layout errors (4 roles)
Total: 50. Fill remaining slots by splitting large groups finer.

## Thinking Loop (per sub-agent)
1. Read spec and context
2. Plan the slice in 3-5 bullet points before writing code
3. Write code
4. Self-review against mission
5. Run allowed tools
6. Revise once if score below 80
7. Emit slice + rationale + score

## Tool Access by Group
- Layout/Components/Styling: file read/write, component library skill (shadcn/Tailwind prompts)
- State/Data: file read/write, API mock generator
- Quality: linter, test runner, a11y checker
- Assembly/Judge/Verifier: file read/write, Playwright, diff tool
No sub-agent gets tools outside its group. Tools live in tools/ as skills and MCP servers. Each role prompt references only its allowed set.

## Dispatch
Orchestrator sends roles in parallel batches of 10. Each batch shares the same page spec. Results land in results/<role-name>.md. Roles scoring below 60 get one retry with the judge's failure reasons appended to context.

## Beat-Frontier Levers
- Unlimited retries (frontier models stop early)
- Specific failure feedback, not vague "try again"
- Parallel diversity: 50 angles on one spec
- Cross-review: each role sees 5 peer drafts before finalizing
- Confidence scoring surfaces weak slices for the assembler

## Stage 2 Done When
All 50 role templates exist in prompts/, the dispatch loop runs one full batch, and at least one role produces a scored slice in results/.