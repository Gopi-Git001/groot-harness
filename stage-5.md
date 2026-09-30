# Stage 5: Testing, Debugging, and Evaluation

## Goal
Systematically test the assembled page, debug every failure, and evaluate the final result against the page spec. Benchmarking is done manually by the user outside the harness.

## 1. Testing Role
- One sub-agent using GPT-OSS 120B with Playwright as a real tool
- Runs the merged page from Stage 4 in a headless browser
- Test suite: page load, interactive elements respond, forms validate, navigation works, responsive breakpoints render, dark mode toggles, no console errors, no runtime crashes
- Output: pass/fail per test case in results/stage-5-test-results.md

## 2. Debugging Role
- One sub-agent using GPT-OSS 120B receiving every failed test case
- Reads: the failing test, the relevant source slice, the page spec section it maps to
- Produces a minimal fix addressing the root cause
- Re-runs the specific failing test after the fix
- One fix attempt per failure; two failed attempts logs it as a known limitation in results/stage-5-debug-log.md

## 3. Evaluation Role
- One sub-agent using GPT-OSS 120B with a dedicated evaluation prompt
- Reads: the final page, the page spec, the test results, the debug log
- Scores the page 0-100 on structure, fidelity, polish
- Checks spec compliance: every requirement present, nothing extra
- Output: evaluation report in results/stage-5-evaluation.md with scores, compliance checklist, remaining gaps