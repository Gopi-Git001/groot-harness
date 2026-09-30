# Resolve a file conflict

Several slices provide competing versions of the same file or the same concern. Produce the version(s) the page should keep.

## Page spec
{{spec}}

## Competing versions
{{candidates}}

## Other page files (path: exports), so your result fits the rest of the page
{{inventory}}

## Instructions
- Usually keep ONE file. Pick the best version, merge in anything better from the others, and keep its public exports compatible with how the other page files use them.
- Keep two files only if they are genuinely different concerns that happen to share a name.
- Paths you do not return are removed; their imports are redirected to what you keep.

Reply in exactly this format:

## Files
One fenced block per kept file. The first line of each block is a comment with the file path. Complete contents.

## Notes
One bullet per decision: what conflicted and how you resolved it.
