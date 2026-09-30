
---
# Merge task: {{scope}}
The Prior drafts above are the slices to merge. Merge them into {{target}}.

## Rules
- One implementation per concern: when slices duplicate a component, token, utility, or file path, keep one and adapt its callers.
- Resolve conflicts (names, props, tokens, file paths) by choosing the option that best meets the page spec.
- Keep every spec requirement that any slice implements. Do not invent features no slice or spec asks for.
- Code must be complete: no placeholders such as "..." or "rest unchanged".

Reply in exactly this format:

## Files
One fenced block per file. The first line of each block is a comment with the file path. Complete contents.

## Merge notes
One bullet per conflict or duplicate: what clashed and how you resolved it.
