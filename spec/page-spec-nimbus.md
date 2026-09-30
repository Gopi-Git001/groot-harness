# Page Spec

Every sub-agent reads this file. It is the single source of truth for what the page must be.

## Prompt
Build a single-page marketing landing page for **Nimbus**, a note-taking app for teams.
The page must include, in order:
1. Top navigation: logo, links to Features, Pricing, FAQ, and a "Get started" button.
2. Hero: headline, one-sentence subheadline, primary and secondary call-to-action buttons, product illustration or screenshot placeholder.
3. Features: six feature cards in a grid, each with an icon, title, and two-line description.
4. Pricing: three tiers (Free, Pro, Team) with price, feature list, and a call-to-action; the middle tier is visually highlighted.
5. FAQ: at least five questions that expand and collapse.
6. Footer: link columns, copyright line, social links.

## Constraints
- One self-contained page; no backend calls.
- Responsive from 360px (mobile) to 1440px (desktop) with no horizontal scrolling.
- Accessible: semantic landmarks, keyboard-operable controls, visible focus states, alt text, WCAG AA color contrast.
- Consistent design system: one type scale, one spacing scale, one color palette.
- No console errors when the page loads or when any control is used.

## Stack
- React 18 + TypeScript (strict), built with Vite.
- Tailwind CSS with shadcn/ui-style components (`cva`, `cn()`, Radix-style accessible primitives), `lucide-react` icons.
- Source lives under `src/`: `components/ui/` for primitives, `components/` for page sections, `lib/` for utilities, `data/` for content.

## Success Criteria
- **Structure:** all six sections present in the specified order, with correct semantic HTML.
- **Fidelity:** every requirement in the Prompt and Constraints above is met.
- **Polish:** balanced layout, clear visual hierarchy, consistent spacing, and working interactive states (hover, focus, expanded).
- **Robustness:** loads and runs cleanly in a headless browser at mobile and desktop widths.
