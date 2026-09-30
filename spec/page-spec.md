# Page Spec

Every sub-agent reads this file. It is the single source of truth for what the page must be.

## Prompt
Build a single-page landing page for **Driftwood Coffee**, an independent neighbourhood coffee shop. The page must feel innovative yet very simple: calm, warm, generous whitespace, one strong idea per section, and it must look beautiful.

The page must include, in order:
1. Top navigation: wordmark logo, links to Menu, Brew Finder, Our Story, Visit, and an "Order ahead" button.
2. Hero: short headline, one-sentence subheadline, primary CTA ("Order ahead") and secondary CTA ("See the menu"), and a hand-crafted coffee-cup illustration built with inline SVG or CSS (steam gently animating).
3. Brew Finder (the innovative centrepiece): the visitor picks a mood (Calm, Focused, Social) and a strength (Light, Balanced, Bold) using accessible toggle buttons, and the page instantly recommends one drink from the menu with its name, description, and price. Works entirely client-side.
4. Menu: six signature drinks as cards, each with name, one-line description, price, and a small tag (e.g. "Oat milk", "Seasonal").
5. Our Story: a short paragraph about the shop and three values (Sourcing, Roasting, Community), each with an icon and one sentence.
6. Visit: address, opening hours for each day of the week, and a "Get directions" link; a simple illustrated map placeholder (CSS or SVG, no external map).
7. FAQ: four questions that expand and collapse (e.g. Wi-Fi, dairy alternatives, pets, laptop-friendly hours).
8. Footer: wordmark, newsletter sign-up form (email field with validation and a success message, no backend), social links, copyright line.

The "Order ahead" buttons open an accessible dialog with a short pickup form (name, drink, pickup time) that shows a confirmation message on submit, without any backend call.

## Constraints
- One self-contained page; no backend calls, no external images or fonts: illustrations are inline SVG or CSS.
- Responsive from 360px (mobile) to 1440px (desktop) with no horizontal scrolling.
- Accessible: semantic landmarks, keyboard-operable controls, visible focus states, alt text or aria-labels, WCAG AA color contrast.
- Consistent design system: one type scale, one spacing scale, one warm color palette (coffee browns, cream, a single accent color).
- Motion is subtle and respects `prefers-reduced-motion`.
- No console errors when the page loads or when any control is used.

## Stack
- React 18 + TypeScript (strict), built with Vite.
- Tailwind CSS with shadcn/ui-style components (`cva`, `cn()`, Radix-style accessible primitives), `lucide-react` icons.
- Source lives under `src/`: `components/ui/` for primitives, `components/` for page sections, `lib/` for utilities, `data/` for content.

## Success Criteria
- **Structure:** all eight sections present in the specified order, with correct semantic HTML.
- **Fidelity:** every requirement in the Prompt and Constraints above is met, including a working Brew Finder, order dialog, FAQ, and newsletter form.
- **Polish:** simple, calm, and visually striking: balanced layout, clear hierarchy, consistent spacing, and working hover/focus/expanded states.
- **Robustness:** loads and runs cleanly in a headless browser at mobile and desktop widths.
