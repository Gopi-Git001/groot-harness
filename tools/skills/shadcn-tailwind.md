# Skill: shadcn/ui + Tailwind Conventions

Follow these rules for every component, layout, and style slice.

## Stack
- React 18 function components, TypeScript strict mode, `.tsx` files.
- Tailwind CSS utility classes only; no inline `style` objects, no CSS-in-JS.
- shadcn/ui patterns: components live in `src/components/ui/` (primitives) and `src/components/` (page sections).
- Merge classes with `cn()` from `src/lib/utils.ts` (`clsx` + `tailwind-merge`).
- Variants with `class-variance-authority` (`cva`), exported alongside the component.
- Interactive primitives (accordion, dialog, dropdown) follow Radix UI semantics: correct roles, `aria-*` state, keyboard support.

## Design tokens
- Colors come from CSS variables in `src/index.css` (`--background`, `--foreground`, `--primary`, `--primary-foreground`, `--muted`, `--accent`, `--border`, `--ring`), mapped in `tailwind.config.ts` as `hsl(var(--token))`.
- Dark mode via the `class` strategy: `.dark` redefines the same variables.
- Spacing: Tailwind's default 4px scale only. Type scale: `text-sm` / `text-base` / `text-lg` / `text-xl` / `text-2xl` / `text-4xl` / `text-5xl`.
- Radius from `--radius`; use `rounded-md` / `rounded-lg` consistently.

## Component rules
- `React.forwardRef` for primitives that render a DOM element; set `displayName`.
- Accept `className` and spread remaining props onto the root element.
- Every interactive element is a real `<button>` or `<a>`; visible focus via `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`.
- Images and icons: meaningful `alt`, decorative icons get `aria-hidden="true"`. Use `lucide-react` icons.
- Mobile first: base classes target 360px, then `sm:` `md:` `lg:` `xl:` upward. Never cause horizontal scroll.

## Example
```tsx
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        outline: "border border-border bg-background hover:bg-accent",
      },
      size: { default: "h-10 px-4 py-2", lg: "h-11 px-8" },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  )
);
Button.displayName = "Button";
```
