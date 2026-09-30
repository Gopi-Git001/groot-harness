# Wire the page

Write `src/App.tsx`: the default-exported `App` component that composes the page's sections in exactly the order the spec requires, inside correct semantic landmarks.

## Page spec
{{spec}}

## Available page files (path: exports)
{{inventory}}

## Known page-level failures from Stage 3 (avoid repeating them)
{{stage3_failures}}

## Instructions
- Import each section component from the files above using the exact export names listed; use the `@/` alias.
- Include every section the spec requires. If a required section has no component, implement it inside App.tsx.
- Every in-page link target (`#id`) must exist as an element id on the page.
- Use exactly one `<main>` and one `<h1>`. Do not wrap a component in a landmark it already renders itself.
- Wire shared providers (theme, state contexts) around the page if such files exist.

Reply with one fenced block starting with `// src/App.tsx`, followed by:

## Notes
One bullet per wiring decision.
