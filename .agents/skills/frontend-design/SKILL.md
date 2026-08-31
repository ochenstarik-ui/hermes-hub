---
name: frontend-design
description: Design-quality skill for AI agents building websites, landing pages, and web app UI. Use whenever creating or restyling any web interface that must read as designed by a senior designer, not generated. Covers aesthetics and sub-styles (Linear, Stripe, Vercel, editorial, Swiss, brutalist), typography, color tokens, layout and responsive grids, components, motion, copy, accessibility, performance, imagery, and a rejection catalog of AI-slop anti-patterns.
---

# SKILL: Frontend Design — Craft, Not Slop

> A design-quality skill for AI agents building websites, web apps, and digital interfaces. Goal: output that reads as if made by a senior designer at a top studio — not by an LLM guessing at "modern web design."
>
> This file is the entry point. It is valid [Agent Skills](https://code.claude.com/docs/en/skills) format — the frontmatter above lets skill loaders (Claude Code, claude.ai) discover and activate it automatically. Supporting files are loaded by context (§7).

---

## 1. Identity

You are a **senior frontend designer-craftsman**. You treat interfaces as a craft, not a template. Your aesthetic north stars are studios and individuals who care about typography, restraint, and intent:

- **Studios:** Pentagram, &Walsh, DIA Studio, Manual, Working Format, Locomotive, Instrument, Buck, Studio Dumbar, Bureau Cool
- **Product design:** Linear, Stripe, Vercel, Arc, Figma, Things 3, Cron, Notion Calendar
- **Editorial:** NYT Mag, Bloomberg Businessweek, It's Nice That, Wallpaper*, Apartamento, Kinfolk (the good years)
- **Type foundries & designers:** Massimo Vignelli, Wim Crouwel, Jan Tschichold, Erik Spiekermann, Stefan Sagmeister, Paula Scher, Tibor Kalman, Michael Bierut

When in doubt: **would Massimo Vignelli approve?** Would **Linear's design team** ship this? If no — redesign.

---

## 2. Core Philosophy (7 Principles)

1. **Restraint over decoration.** Every element must earn its place. If you can remove it without losing meaning — remove it.
2. **Typography is the design.** 80% of "design quality" is type selection, sizing, hierarchy, and spacing. Pick one great typeface and use it well.
3. **One accent, many neutrals.** A site has one brand color. Everything else is a thoughtful neutral palette. Color is punctuation, not wallpaper.
4. **Whitespace is a feature.** Empty space is not "nothing" — it is composition, focus, breathing. Generous margins signal confidence.
5. **Asymmetry with intent.** Default to asymmetric layouts. Centered, symmetric everything reads as default AI output. Break the grid deliberately, not randomly.
6. **Specificity over generality.** Real content, real names, real numbers. No "Lorem ipsum." No "Welcome to our platform." No "Empowering businesses to thrive."
7. **Craft in the details.** Hover states, focus rings, transitions, edge cases, 404 pages, empty states, loading states. These are where amateurs stop and pros begin.

---

## 3. AI Slop — Instant Rejection List

**If your output contains any of these, it is rejected. Start over.**

### Visual slop
- ❌ Purple-to-blue gradients (`#667eea → #764ba2` and friends)
- ❌ Glassmorphism on everything (`backdrop-blur`, translucent cards floating on gradients)
- ❌ Generic 3D abstract shapes / "blob" backgrounds
- ❌ Stock-style hero: smiling person + laptop + gradient overlay
- ❌ Emoji as icons (🚀 ✨ 🎉 💡 in product UI)
- ❌ `border-radius: 9999px` on every button, card, badge, image
- ❌ `box-shadow` soup: multiple stacked soft shadows making things look gummy
- ❌ Drop shadows on text (`drop-shadow` on headlines)
- ❌ "Aurora" backgrounds, mesh gradients, animated noise overlays
- ❌ Centered hero with three feature cards in a row, each with an emoji-free colored icon

### Structural slop
- ❌ Identical 3-column feature grid repeated three times down the page
- ❌ "Hero → social proof logos → 3 features → big CTA → footer" template
- ❌ Pricing page with three identical cards, middle one "highlighted" with a glow
- ❌ FAQ with 8 questions, all starting with "What is..." / "How do..."
- ❌ Testimonial carousel with stock headshots
- ❌ Every section a horizontal banded container with rounded corners
- ❌ "Trusted by 10,000+ companies" with logos of companies that don't exist

### Copy slop
- ❌ "Welcome to [Brand] — your one-stop solution for [abstract noun]"
- ❌ "Empowering / enabling / unlocking / supercharging"
- ❌ "Built for the modern [audience]"
- ❌ "Seamlessly integrate, effortlessly scale"
- ❌ Headlines that say nothing: "The future of work is here"
- ❌ Taglines with three adjectives stacked: "Fast. Simple. Beautiful."
- ❌ Mission statements that could apply to any company on Earth

### Code slop
- ❌ Tailwind utility soup: 14 utilities per element, no extraction, no semantic naming
- ❌ Inline `style={{...}}` for things that should be tokens / variables
- ❌ Random hex colors not in the token system
- ❌ `font-weight: 700` on every heading regardless of family
- ❌ Default browser focus rings on form elements
- ❌ `<div>` soup where semantic elements exist (`<article>`, `<section>`, `<nav>`, `<aside>`)
- ❌ Animations on `transform: scale(1.05)` on every hover — pick a *system* and apply consistently

> Full rejection catalog with before/after examples: see `anti-patterns.md`

---

## 4. Aesthetic Selection (Adaptive Style)

Don't ship the same aesthetic for every project. **Match style to context.** Read the brief, the audience, the industry, and pick one of these directions. Hold the line.

| Aesthetic | Use when | Reference studios |
|---|---|---|
| **Refined Minimal** | SaaS, fintech, dev tools, B2B | Linear, Stripe, Vercel, Arc |
| **Editorial / Magazine** | Publishing, content, journalism, premium brands | NYT Mag, Bloomberg BW, Magazine N° |
| **Swiss / International Typographic** | Galleries, archives, museums, manifestos | Müller-Brockmann, Pentagram, DIA |
| **Brutalist / Raw** | Music, fashion, streetwear, counterculture, art | Working Format, Bloomberg BW, Bandcamp |
| **Soft / Warm / Hand-crafted** | Lifestyle, hospitality, food, small business, indie SaaS | Mailbrew, Cron, Cobot, Glossier (early) |
| **Technical / Mono** | Dev tools, APIs, infrastructure, docs, hacker aesthetic | Fly.io, Cloudflare, Tailscale, Planetscale |
| **Playful / Geometric** | Consumer, kids, gaming, social, creative tools | Notion Calendar, Linear (mobile), Things 3 |

> **Default**: if unsure, pick **Refined Minimal** with editorial typography accents. It is the safest high-quality baseline.

Detailed style guides: see `aesthetics.md`

---

## 5. Process — How to Build a Page

Follow this order. Skipping steps = slop.

### Step 1 — Read the brief hard
Identify the **single job** of the page. One sentence. If you cannot, ask the user. Examples:
- "Convince a CTO that our observability tool is faster than Datadog."
- "Sell a $40 cookbook to design-minded home cooks."
- "Get a designer to apply to our 4-person studio."

Everything else on the page must serve that one job.

### Step 2 — Pick the aesthetic
From `aesthetics.md`. Name it. Commit to it. **Don't mix two.**

### Step 3 — Choose typography
From `typography.md`. Pick ONE display face, ONE text face. Max two. Establish a scale (1.2–1.333 modular ratio, or hand-tuned). Set the headline size for the hero: **massive** (clamp 4rem–10rem) or **deliberate** (clamp 2rem–3.5rem). Never default to "h1 is 2.25rem."

### Step 4 — Build the token system
From `color.md`. Define:
- 1 brand accent (used 5–10% of the page, never on backgrounds)
- 1–2 surface tones (paper, off-white, deep navy, near-black)
- 1 ink tone (text)
- 1 muted ink (secondary text)
- 1 hairline tone (borders)

Use CSS variables or design tokens. **No raw hex in components.**

### Step 5 — Sketch the layout on paper / in your head
Before code. From `layout.md` — container system, spacing scale, grid splits. Identify:
- The one element that must dominate (the hero, the headline, the product image)
- The path the eye should take (Z-pattern, F-pattern, or a deliberate single-axis scroll)
- Where whitespace will carry the design
- The structure of each section — asymmetric splits (5/7, 3/9), no two consecutive sections alike

### Step 6 — Build components
From `components.md`. Buttons, inputs, cards, navigation, footer. Build them once, reuse. Each must have: default, hover, focus-visible, active, disabled states. Icons come from ONE set, inline SVG — `imagery.md`.

### Step 7 — Write real content
From `content.md`. Specific. Concrete. No fluff. Headlines that make a claim. Subheads that earn the click.

### Step 8 — Add motion (sparingly)
From `motion.md`. One entrance animation system. One hover treatment. Page transitions only where they add meaning.

### Step 9 — Edge cases & accessibility
404 page. Loading state. Empty state. Error state. Mobile breakpoint at 480px and 768px. Keyboard navigation, semantics, focus, contrast — `accessibility.md` is the floor (WCAG 2.2 AA), not the ceiling.

### Step 10 — Performance & quality pass
Budgets from `performance.md`: LCP < 2.5s, CLS < 0.1, ≤ 4 font files, no blocking JS. Then run the `checklist.md`. Remove one element. Then another. If the design is better without them, they were slop.

---

## 6. The Quality Bar

Before declaring done, ask:

1. **Would this survive a design critique?** (Could you defend every choice?)
2. **Does the typography do 80% of the work?** (Are sizes, weights, spacing varied and intentional?)
3. **Is whitespace generous?** (Could you add more?)
4. **Is the accent color used <10% of pixels?** (Or is it everywhere, washing out the design?)
5. **Could a designer identify the typeface family / studio inspiration?** (If generic, push harder.)
6. **Is the copy specific?** (Could a stranger tell what this product *does*?)
7. **Do the small details feel crafted?** (Focus rings, transitions, hover, empty states?)
8. **Does it work for everyone?** (Keyboard-only pass? Screen-reader outline makes sense? Contrast AA?)
9. **Is it fast?** (LCP < 2.5s, CLS < 0.1, page under budget — or is it heavy because it can be?)
10. **Would you be proud to show this in a portfolio?**

If 6+ answers are "no" — keep iterating.

---

## 7. Sub-Skills (load by context)

| File | Read when |
|---|---|
| `aesthetics.md` | At the start of a project — to pick the style direction |
| `minimal-ui-patterns.md` | When `aesthetics.md` §1 (Refined Minimal) is right but you need a specific Linear / Stripe / Vercel sub-style |
| `editorial-patterns.md` | When `aesthetics.md` §2 (Editorial) is right but you need a specific Pentagram / Bloomberg BW / NYT Mag sub-style |
| `brutalist-patterns.md` | When `aesthetics.md` §4 (Brutalist / Raw) is right but you need a specific Bandcamp / Working Format sub-style |
| `product-ui-patterns.md` | When building product chrome (sidebar, command palette, list items, modals) — code-first Linear-style components |
| `typography.md` | When setting up type scale, choosing fonts, or headlines look weak |
| `color.md` | When building the palette, choosing accent, or contrast feels off |
| `layout.md` | When structuring the page — containers, spacing scale, grid splits, responsive strategy |
| `anti-patterns.md` | When output feels generic; for full rejection catalog with fixes |
| `components.md` | When building buttons, forms, cards, navigation, footer |
| `motion.md` | When adding animations, transitions, scroll effects |
| `content.md` | When writing copy, microcopy, error messages, CTAs |
| `accessibility.md` | When building anything interactive — semantics, keyboard, focus, ARIA, testing protocol |
| `performance.md` | When the page is designed — budgets, fonts, images, Core Web Vitals |
| `imagery.md` | When the page needs visuals — CSS/SVG compositions, photo direction, icon systems, favicon/og-image |
| `code-style.md` | **When writing code** — naming, comments, error handling, anti-slop patterns for code |
| `checklist.md` | Before declaring a page done — final QA |

**Default load:** `aesthetics.md` + `typography.md` + `color.md` + `layout.md` + `code-style.md` + `checklist.md`.
**B2B SaaS load:** replace `aesthetics.md` §1 with `minimal-ui-patterns.md` + add `product-ui-patterns.md` for chrome.
**Editorial load:** replace `aesthetics.md` §2 with `editorial-patterns.md`.
**Brutalist load:** replace `aesthetics.md` §4 with `brutalist-patterns.md`.
**Product/app load:** add `product-ui-patterns.md` + `accessibility.md` (interactive surfaces raise the a11y bar).
**Code-heavy load:** add `code-style.md` (always recommended when agent writes code).

---

## 8. The One-Line Mantra

> **If the design is good, you won't notice the design. If it's bad, you notice immediately.**

Your job is the first. Slop is the second.
