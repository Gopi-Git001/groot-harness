
---
# Stage 4 fix pass (round {{round}})
The merged page failed headless-browser verification. You own the errors below. Fix each one in the merged page files.

## Errors you must fix
{{errors}}

## Current merged files involved
{{files}}

## Other page files (path: exports)
{{inventory}}

## Instructions
- Fix every listed error with the smallest correct change. Do not rewrite working code.
- Imports must resolve to page files or these packages only: {{packages}}.
- You may create a new file under `src/` if a fix needs one. Never edit `src/main.tsx`.
- Return complete contents for every file you change.

Reply in exactly this format:

## Changes
One bullet per error: the error, then what you changed.

## Code
One fenced block per changed file. The first line of each block is a comment with the file path.
