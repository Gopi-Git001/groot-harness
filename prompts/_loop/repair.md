# Repair broken imports

`{{path}}` has import problems:
{{broken}}

## The file
{{content}}

## Available page files (path: exports)
{{inventory}}

## Instructions
- For each problem, point the import at an existing page file that has the right export, fix the import form (default vs named) to match what the target exports, or replace the dependency with an allowed package or plain code.
- Do not change anything else.

Reply with one fenced block starting with `// {{path}}` containing the complete repaired file.
