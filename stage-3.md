# Stage 3: Judge, Critique, and Rewrite Loop

## Goal
Take the 50 scored slices from Stage 2 and run iterative critique/rewrite passes until the assembled page converges on the spec. Frontier models get one careful pass; this stage spends unlimited free calls.

## 1. Judge Role
- One sub-agent using GPT-OSS 120B with a dedicated judge prompt (different from builder prompts)
- Reads: page spec, each role's slice, rationale, and confidence score
- Scores every slice 0-100 on three axes: structure, fidelity, polish
- Returns specific failure reasons per axis, e.g. "button lacks hover state defined in spec section 4" — never just "improve this"
- Flags slices below 60 as blockers; 60-79 as rework; 80+ as pass

## 2. Critique Pass
- Orchestrator feeds each failed slice back to its owning sub-agent
- The sub-agent receives: original mission, the judge's specific failures, the page spec section it maps to
- It must address every listed failure, not rewrite from scratch
- One revision per pass; no infinite loops on a single slice

## 3. Rewrite Pass
- After all slices in a batch are revised, the assembler merges them again
- The judge re-scores the merged result as a whole page, not individual slices
- If whole-page score is below 85, another critique/rewrite round begins
- Cap: 5 full rounds per page to prevent runaway cost

## 4. Convergence Check
- Stage 3 ends when: whole-page judge score is 85 or above, OR 5 rounds are exhausted
- Final output: the best-scoring merged page + a log of every round's scores and failure reasons in results/stage-3-log.md

## 5. Beat-Frontier Lever
- Frontier agents critique once or skip it. This stage makes critique mandatory, specific, and looped, turning the 120B's weaker single-pass reasoning into a multi-pass system.