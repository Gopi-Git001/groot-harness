# Stage 4: Assembly and Verification

## Goal
Merge the best-scoring slices from Stage 3 into one coherent front-end page, then verify it runs correctly in a real browser before the benchmark.

## 1. Assembler Role
- One sub-agent using GPT-OSS 120B with a dedicated assembler prompt
- Reads: page spec, all scored slices from Stage 3, stage-3-log.md
- Merges slices into a single page: resolves import conflicts, dedupes shared styles and utilities, wires components in correct order
- Self-check: no broken imports, no dead code, no duplicate definitions, all spec requirements present
- Output: one merged page file + merge report listing every conflict and resolution

## 2. Verifier Role
- One sub-agent using GPT-OSS 120B with Playwright as a real tool (registered in Stage 4)
- Runs the merged page in a headless browser
- Catches: console errors, runtime crashes, unhandled rejections, layout breaks, missing elements
- Spec-compliance audit: every page-spec requirement present in rendered page, nothing extra
- Output: pass/fail per check + verification report in results/stage-4-report.md

## 3. Fix Loop
- Verifier errors go back to the owning sub-agent with the specific error
- One fix pass per error; two failed attempts logs it as a known limitation
- Re-verify after each fix round
- Cap: 3 fix rounds

## 4. Stage 4 Done When
- Merged page loads in headless Playwright with zero console errors and zero runtime crashes
- Spec-compliance audit passes every requirement
- results/stage-4-report.md exists with full error and fix log

## 5. Beat-Frontier Lever
- Frontier agents verify shallowly or skip it. This stage makes browser verification mandatory, specific, and looped, catching the bugs that single-pass generation misses.