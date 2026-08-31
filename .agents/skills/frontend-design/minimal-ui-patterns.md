# Minimal UI Patterns — Linear, Stripe, Vercel, and friends

> A deep-dive into the six most useful minimal-SaaS sub-styles. Read this when `aesthetics.md` §1 (Refined Minimal) is right for the project, but you need to pick a *specific* direction. Each sub-style has concrete rules, palettes, components, and references — not vibes.

---

## How to use this file

`aesthetics.md` §1 says: **Refined Minimal** when the product is SaaS, fintech, dev tools, or B2B. That's the family.

This file says: **which Linear-style cousin** to ship. Because "minimal" without a specific direction is just empty.

Decision rule:
1. **Is the product B2B / SaaS / fintech / dev tools?** If no → wrong family, go back to `aesthetics.md`.
2. **Pick the sub-style** that matches the audience and tone (use the table below).
3. **Commit to it.** Don't blend Linear's purple with Stripe's indigo. Don't mix Vercel's pink with Arc's sage.

---

## Sub-style comparison

| Sub-style | Mood | Theme | Accent | Audience |
|---|---|---|---|---|
| **Linear** | Quiet confidence, dense, precise | Dark default | Purple `#5E6AD2` | Engineering teams, power users |
| **Stripe** | Authoritative, code-forward, premium | Light or dark | Indigo `#635BFF` | Developers, technical buyers |
| **Vercel** | Stark, geometric, opinionated | Either (often B/W) | None, or pink `#FF0080` | Frontend devs, designers, agencies |
| **Arc** | Warm, considered, premium browser | Light, warm tones | Subtle red or sage | Knowledge workers, writers, designers |
| **Mercury** | Editorial premium, banking-quality | Light, off-white | Deep green or deep blue | Finance teams, ops, founders |
| **Cron / Notion Calendar** | Friendly precise, soft personality | Off-white, warm | Multi-hue palette (semantic) | Creators, schedulers, knowledge workers |

When unsure → **Linear**. It is the safest high-quality baseline for dark-mode B2B SaaS.

---

## 1. Linear

**Live reference:** [linear.app](https://linear.app)

### Identity
The reference standard for dark-mode minimal SaaS. Quiet, dense, precise. Every pixel is a decision. The interface gets out of the way. The accent is purple, the chrome is hairline, the typography is Inter, the geometry is exact.

### When to choose
- Engineering teams, product teams, ops teams
- Power users who live in the app 8 hours a day
- Products that compete on density of information
- Dark mode by default is appropriate

### Palette
```
--surface:         #08090A   /* deep, near-black */
--surface-1:       #1B1C1F   /* panels, sidebar */
--surface-2:       #26272B   /* elevated cards */
--surface-3:       #2F3034   /* hover */

--ink:             #F7F8F8   /* warm-tinted near-white */
--ink-muted:       #8A8F98   /* secondary */
--ink-subtle:      #62666D   /* tertiary */

--hairline:        #1F2024
--hairline-strong: #2C2D31

--accent:          #5E6AD2   /* Linear purple — the signature */
--accent-strong:   #7176E0   /* hover */
--accent-soft:     rgba(94, 106, 210, 0.14)

--good:            #4CB782
--warn:            #E2B203
--bad:             #EB5757
```

### Typography
- **All sans.** Inter Display for headlines, Inter for UI, Inter (or Geist) for body.
- **No mono in chrome**, except for keyboard shortcut hints (`⌘K`).
- **Weights:** 400 body, 500 medium for UI controls, 600 semibold for headings and primary actions. Almost never 700.
- **Hero size:** `clamp(2.75rem, 5vw, 4.5rem)` — confident, not dramatic.
- **Line-height:** tight on display (1.05–1.15), 1.5 on body.
- **Tracking:** -0.02em on display, 0 elsewhere. Linear doesn't track all-caps positive in chrome.

### Layout
- **Max content width:** ~1100px
- **Sidebar:** ~240px wide, collapsible to 56px (icon-only). Always dark, always present in app.
- **Top nav (marketing):** 60–64px tall, sticky, blur backdrop, hairline bottom border.
- **Asymmetric hero:** headline left (5/12 cols), product UI right (7/12 cols). Never centered.
- **Padding:** generous (px-12 desktop, px-6 mobile).

### Signature patterns

**The sidebar**
- Section labels in caps mono, +0.1em tracking
- Active item: 4px left border in `--accent`, OR background tint in `--accent-soft`
- Icon + label, 32px row height, 14px font
- Section dividers as 1px hairlines, generous vertical spacing between sections

**The "New Issue" modal (or any command modal)**
- Centered, max-width 560px
- Input field at the top, full-width, no border, large
- List of suggestions below, keyboard-driven (`↑ ↓ ↵`)
- `Esc` closes, `⌘K` opens
- Background dimmed to ~50% opacity
- Subtle scale-in (0.98 → 1, 120ms ease-out)

**The empty state**
- Centered, single illustration or icon (geometric, 1.5px stroke)
- One sentence explaining what's missing
- One action button ("Create your first issue")
- Linear's empty states are famously restrained — almost no decoration

**The list item**
- 40–48px tall
- Single line of content
- Status dot (left), title (center), metadata (right, mono)
- Hover: background tints to `--surface-2`
- Selected: background tints to `--accent-soft` (subtle)
- No drop shadows, no rounded corners beyond 6px

**The button**
- Two heights: 32px (compact) and 40px (default)
- Border radius: 6px
- Primary: `--accent` background, white text
- Secondary: transparent, 1px hairline-strong border
- Hover (secondary): border becomes white
- Active: `transform: scale(0.98)` 80ms

### Hallmarks to preserve
- ✅ Hairline borders instead of shadows
- ✅ Tabular numerals everywhere (font-feature-settings: 'tnum')
- ✅ Inter (or close cousin — Geist) as the *only* family
- ✅ 6px radius on everything — never pill
- ✅ Information density is high, density is comfortable
- ✅ Keyboard-first (visible shortcuts, ⌘K command palette)

### Anti-patterns to avoid
- ❌ Drop shadows on cards
- ❌ Bright/saturated colors anywhere
- ❌ Glassmorphism
- ❌ Animations beyond 150ms
- ❌ Centering hero content
- ❌ Decorative illustrations in chrome
- ❌ Bouncy/spring easing

---

## 2. Stripe

**Live reference:** [stripe.com](https://stripe.com)

### Identity
Authoritative. Code-forward. Premium. Stripe uses code as marketing — every page has a code block, every product has a curl example. The typography is Söhne (paid) or a careful sans substitute. The accent is a distinctive indigo, present but never loud.

### When to choose
- Developer-facing products
- API products, infrastructure, fintech, payments
- Audiences who read code on landing pages
- Products where the API IS the value proposition

### Palette
```
--surface:         #FFFFFF   /* or #F6F9FC for sections */
--surface-1:       #F6F9FC   /* soft cool tint */
--surface-2:       #FFFFFF
--surface-3:       #E8EDF2

--ink:             #0A2540   /* Stripe's deep navy, not black */
--ink-muted:       #425466
--ink-subtle:      #8898AA

--hairline:        #E8EDF2
--hairline-strong: #D4DBE3

--accent:          #635BFF   /* Stripe indigo */
--accent-strong:   #5247DB
--accent-soft:     #EBF0FF

--good:            #00875A
--warn:            #FFB300
--bad:             #E25950
```

Note: Stripe's primary ink is `#0A2540` (deep navy), not pure black. This is a signature choice — softer than black, more authoritative than gray.

### Typography
- **Söhne** (paid) for everything; substitute with **Inter Display** + **Inter** for free.
- Weights: 400 body, 500 for UI, 600 for headings.
- **Hero size:** `clamp(2.5rem, 5vw, 4.25rem)` — confident, restrained.
- **Section H2:** `clamp(1.875rem, 3vw, 2.5rem)`.
- **Tracking:** -0.02em on display, 0 on body.

### Layout
- Max-width 1080–1140px (Stripe is slightly narrower than typical SaaS)
- Hero: text left, abstract visualization right (gradients OK here, used with restraint and brand-color)
- Below the fold: dense sections, often with code blocks
- Code block as a marketing surface — never decorative

### Signature patterns

**The "gradient hero" (Stripe-specific)**
Stripe is one of the few brands that uses a gradient hero well — and only because the gradient is *internal*, not purple-to-blue:
```
background: linear-gradient(180deg, #F6F9FC 0%, #FFFFFF 100%);
/* or a subtle radial in brand color */
background: radial-gradient(ellipse at top, rgba(99, 91, 255, 0.12) 0%, transparent 50%);
```
The gradient is atmosphere, not decoration. Pure white below the fold.

**The code block**
- This is the marketing surface. Make it look like a real terminal.
- Dark background (`#0A2540` or `#1B1B3A`)
- Syntax highlighting in brand palette (indigo, light cyan, light pink)
- Window chrome (red/yellow/green dots) for terminal feel
- Inline cursor blinking on one line
- Comment line explaining what the code does, in italic

```
$ stripe listen --forward-to localhost:3000/webhook
> Ready! Listening for events...
> 2026-04-12 14:32:11  [200] checkout.session.completed
```

**The "stacked cards" pricing**
Stripe uses stacked card preview — three cards with subtle offset and shadow, showing the product from multiple angles. Used in payment-method pages.

**The numbered grid**
Often Stripe presents features as a numbered list (01, 02, 03) with a description and a small visualization. Not the generic 3-card row.

### Hallmarks
- ✅ Code block is a hero element
- ✅ Stripe indigo used precisely (links, focus, primary CTA, syntax highlighting)
- ✅ Navy ink `#0A2540` instead of pure black
- ✅ Generous whitespace, dense info
- ✅ Real product screenshots in context, not abstract
- ✅ Subtle gradients (atmospheric, not decorative)

### Anti-patterns to avoid
- ❌ Generic "3-card features" grid
- ❌ Stock photos of developers
- ❌ "Empowering developers to..." copy
- ❌ Code blocks with fake/lorem code (Stripe uses real examples)
- ❌ Loud hero gradients that compete with content

---

## 3. Vercel

**Live reference:** [vercel.com](https://vercel.com)

### Identity
Stark. Geometric. Opinionated. Vercel often ships pure black on white or pure white on black, with a single accent color (often none, sometimes a hot pink). The type is Geist (their own). The geometry is sharp — square corners, dense info, sharp typography.

### When to choose
- Frontend developer tools, frameworks, deployment platforms
- Products that need to feel fast and modern
- Audiences that respect B/W restraint
- Anything that needs to feel "opinionated"

### Palette

**Default (white):**
```
--surface:         #FFFFFF
--surface-1:       #FAFAFA
--surface-2:       #F4F4F5

--ink:             #000000   /* Vercel uses pure black */
--ink-muted:       #71717A
--ink-subtle:      #A1A1AA

--hairline:        #E4E4E7
--hairline-strong: #D4D4D8

--accent:          #FF0080   /* Vercel pink, used sparingly */
--accent-soft:     rgba(255, 0, 128, 0.08)
```

**Dark (also common):**
```
--surface:         #000000
--surface-1:       #0A0A0A
--surface-2:       #111111

--ink:             #FFFFFF   /* Vercel uses pure white */
--ink-muted:       #A1A1AA
--ink-subtle:      #71717A

--hairline:        #1F1F1F
--hairline-strong: #2E2E2E

--accent:          #FF0080
--accent-soft:     rgba(255, 0, 128, 0.12)
```

Vercel uses *pure* black and *pure* white — this is a deliberate choice. Most brands shouldn't, but Vercel can because the rest of the design carries the weight.

### Typography
- **Geist Sans** (their own, free) or **Inter** as substitute
- **Geist Mono** for code, kickers
- Weights: 400 body, 500 UI, 600 headings. Very rarely 700.
- **Hero size:** `clamp(3rem, 6vw, 5rem)` — confident, often large.
- **Tracking:** -0.04em on display headlines (Vercel tracks tight, even tighter than Linear).
- **Line-height:** 1.0 on display headlines (very tight).

### Layout
- Max-width 1200px
- Hero: usually large headline left or centered, with a sharp product UI mockup (often a terminal or dashboard).
- Sharp grid, generous spacing between sections.
- Sharp corners (radius 0 or 4px max).

### Signature patterns

**The black/white inversion**
Vercel often ships the same product in both themes. The dark theme is *pure black* with white text — not the "not-quite-black" pattern of Linear.

**The terminal-as-hero**
Terminal screenshots as the hero image. Pure black background, monospace text, sometimes a subtle gradient at the edge. The terminal is the product.

```
$ vercel deploy
> Production: https://my-app.vercel.app [copied to clipboard]
> Completed in 1.247s
```

**The "all caps micro labels"**
Section labels and metadata in uppercase mono, but with Vercel's tight tracking (not the wide tracking common elsewhere). Reads as a system, not a decoration.

**The geometric icons**
Custom or Lucide icons, 16–20px, 1.5px stroke. Sharp, no rounded corners on icons.

### Hallmarks
- ✅ Pure black or pure white backgrounds (Vercel breaks the "don't use pure" rule, intentionally)
- ✅ Geist Sans + Geist Mono pairing
- ✅ Very tight tracking (-0.04em on display)
- ✅ Sharp corners (radius 0–4px)
- ✅ Terminals as hero images
- ✅ Hot pink accent used on one CTA per page max

### Anti-patterns to avoid
- ❌ Rounded corners > 8px
- ❌ Soft pastels
- ❌ Decorative illustrations
- ❌ Multiple accent colors
- ❌ Centered everything (Vercel often centers hero, but it's deliberate — a *statement* of restraint, not a default)
- ❌ Heavy animations

---

## 4. Arc

**Live reference:** [arc.net](https://arc.net)

### Identity
Warm, considered, premium. Arc's marketing is editorial-influenced — generous typography, soft warm tones, restrained accents, considered spacing. The browser itself is also designed this way. The aesthetic is "premium software for thoughtful people."

### When to choose
- Consumer products with premium positioning
- Tools for writers, designers, knowledge workers
- Products where personality is a feature
- Anything that wants to feel "considered" without feeling cold

### Palette
```
--surface:         #FBFBF8   /* warm off-white, Arc's signature */
--surface-1:       #FFFFFF
--surface-2:       #F4F4EE   /* slightly warmer */

--ink:             #191919
--ink-muted:       #6E6E6E
--ink-subtle:      #A8A8A8

--hairline:        #E8E8E0
--hairline-strong: #D4D4C8

--accent:          #FF554A   /* Arc red — used very sparingly */
--accent-soft:     rgba(255, 85, 74, 0.1)

--good:            #2E7D32
--warn:            #ED6C02
--bad:             #D32F2F
```

The accent is red — used like editorial red (subhead accents, focus, "go" indicators). Almost never on backgrounds.

### Typography
- **GT Walsheim** (paid) or **Inter** substitute
- Generous display sizes, often with serif influence
- Hero size: `clamp(2.75rem, 5vw, 4.5rem)` — confident, generous
- Tracking: -0.02em on display
- Line-height: 1.05 on display

### Layout
- Max-width 1200px
- Hero: large headline, product UI as visual (often the browser window itself)
- Section H2s often have serif italic emphasis on key word
- Asymmetric but warm

### Signature patterns

**The browser-as-hero**
The product is the browser, so the hero *is* a browser window. Rendered in CSS, sharp, considered.

**The "red emphasis"**
Italic word or short phrase in display face, set in accent red. Like an editorial pull quote, used inline in headlines.

```
The browser<br>
that <em>thinks</em><br>
with you.
```

**The "small card, big moment"**
Arc uses small product moments (a single feature panel) with very generous surrounding whitespace. Less is more.

### Hallmarks
- ✅ Warm off-white background (not pure white)
- ✅ Considered italic emphasis in headlines
- ✅ Soft product screenshots (browser windows with internal UI)
- ✅ Generous whitespace
- ✅ Red accent on maybe 5% of pixels

### Anti-patterns to avoid
- ❌ Pure white background (breaks warmth)
- ❌ Cold blue accents
- ❌ Glassmorphism
- ❌ Multiple accent colors
- ❌ Bouncy animations

---

## 5. Mercury / premium fintech

**Live reference:** [mercury.com](https://mercury.com)

### Identity
Editorial premium. Banking-quality. Mercury positions itself as the bank for startups, and its design language is "Stripe for finance" — clean, dense, considered, with serif influence in some headlines.

### When to choose
- Fintech products
- Banking, payments, treasury
- Premium positioning in any B2B vertical
- Products where the audience expects "considered" design

### Palette
```
--surface:         #FFFFFF
--surface-1:       #FAFAF8   /* warm tint */
--surface-2:       #F4F2EE

--ink:             #1A1A1A
--ink-muted:       #6E6E6E
--ink-subtle:      #999999

--hairline:        #E8E5DE
--hairline-strong: #D4D0C6

--accent:          #1B4332   /* Mercury deep green */
--accent-soft:     #E8F0EC
```

Mercury uses a deep, considered green as accent — almost no other brand does this, so it reads as "premium banking" instantly.

### Typography
- **Söhne** (paid) + occasional serif (Tiempos) for editorial moments
- Substitute: **Inter** for sans, **GT Super** or **Fraunces** for serif
- Hero size: `clamp(2.5rem, 5vw, 4rem)` — confident
- Section H2: `clamp(1.875rem, 3vw, 2.5rem)`

### Layout
- Max-width 1200px
- Hero: headline left, product UI right (always — never centered)
- Dense sections below with data and tables
- Generous whitespace between sections

### Signature patterns

**The "table as hero"**
Fintech products often show tables of data (transactions, balances) in hero sections. Mercury does this well — clean rows, tabular numerals, hairline dividers.

**The "data visualization"**
Numbers are presented as design — not as decoration. Big numbers with context, comparison, trend indicators.

**The serif moment**
A serif word in an otherwise sans context. Used sparingly. Signals "we have time to consider this."

### Hallmarks
- ✅ Deep green or deep blue accent (premium banking colors)
- ✅ Serif moment in headlines (sparingly)
- ✅ Tables as design elements
- ✅ Editorial influence in copy and rhythm
- ✅ Generous whitespace

### Anti-patterns to avoid
- ❌ Bright/banking-blue accents (#1E88E5 etc.)
- ❌ Decorative charts (charts should be data, not decoration)
- ❌ Centered hero
- ❌ Generic fintech marketing copy

---

## 6. Cron / Notion Calendar (friendly precise)

**Live reference:** [cron.com](https://cron.com), [notion.so/product/calendar](https://notion.so/product/calendar)

### Identity
Friendly but precise. Off-white backgrounds, warm tones, multi-hue palette used *semantically* (each color = a category, state, or feature). Rounded but not pill. Custom illustrations. Has personality without losing professionalism.

### When to choose
- Productivity tools, calendars, schedulers
- Knowledge work products
- Consumer B2B (Notion, Cron, Things)
- Anything where delight is part of the value

### Palette
```
--surface:         #FAF8F5   /* warm off-white */
--surface-1:       #FFFFFF
--surface-2:       #F2EFEA

--ink:             #1F1F1F
--ink-muted:       #6B6B6B
--ink-subtle:      #A8A8A8

--hairline:        #E8E5DE

/* Multi-hue semantic palette — used like categories */
--hue-1:           #FF6B6B   /* coral */
--hue-2:           #4ECDC4   /* teal */
--hue-3:           #FFD93D   /* mustard */
--hue-4:           #6C5CE7   /* soft purple */
--hue-5:           #95E1D3   /* mint */
```

Each color is used for a specific category. The palette is coherent (all desaturated, similar value).

### Typography
- **GT Walsheim** (paid) or **Inter** substitute
- Display: `clamp(2.5rem, 5vw, 4rem)`
- Friendly but not casual
- Tracking: -0.02em on display

### Layout
- Max-width 1200px
- Hero: large headline + product UI (calendar view)
- Custom illustrations as visual texture
- Rounded corners: 8–12px

### Signature patterns

**The semantic color**
Each product category, feature, or user has a color. The color is *meaningful*, not decorative.

**The custom illustration**
Cron and Notion Calendar use custom illustrations as visual texture — geometric, friendly, consistent style. Not stock, not emoji.

**The "personality in microcopy"**
Microcopy has a voice. Empty states have a sentence that makes you smile. Tooltips have one-liners.

### Hallmarks
- ✅ Multi-hue palette used semantically
- ✅ Custom illustrations (geometric, friendly)
- ✅ Off-white warm backgrounds
- ✅ Rounded but not pill (8–12px)
- ✅ Microcopy with personality

### Anti-patterns to avoid
- ❌ Emoji as icons
- ❌ Stock photos
- ❌ Generic 3-card row with icons
- ❌ Loud/bright colors with no logic
- ❌ Corporate throat-clearing copy

---

## 7. Sublime

**Live reference:** [sublime.app](https://sublime.app)

### Identity
macOS-native email client with a calm, considered, premium feel. Generous spacing, light, airy. Subtle warm off-white. The aesthetic of "premium productivity software" applied to email — quiet confidence, soft depth, restraint.

### When to choose
- Productivity tools with macOS / native feel
- Email, notes, calendar apps
- Anything targeting "thoughtful" professional users
- Premium positioning in consumer productivity

### Palette
```
--surface:         #FBFBFA   /* warm off-white, very subtle tint */
--surface-1:       #FFFFFF
--surface-2:       #F4F4F1

--ink:             #1A1A1A
--ink-muted:       #6B6B6B
--ink-subtle:      #A0A0A0

--hairline:        #E8E8E5
--hairline-strong: #D4D4D0

--accent:          #1A73E8   /* Sublime's restrained blue */
--accent-soft:     #E8F0FE

--good:            #1E8E3E
--warn:            #F9AB00
--bad:             #D93025
```

Note: Sublime uses a quiet blue, not a loud one. Almost editorial in restraint.

### Typography
- **SF Pro Display / SF Pro Text** (Apple system) or **Inter** as substitute
- Weights: 400 body, 500 for UI, 600 for headings
- Hero size: `clamp(2rem, 4vw, 3rem)` — calm, not dramatic
- Tracking: -0.01em on display (subtle)
- Generous line-height: 1.6 on body

### Layout
- Max-width 1100px (narrower than typical SaaS)
- Hero: small headline + generous space + product UI screenshot
- Section H2s often in serif (subtle editorial influence)

### Signature patterns
- ✅ Sidebar with subtle hover state, no harsh borders
- ✅ Generous line-height in lists (each row has air)
- ✅ Soft shadows only on floating elements (modals, popovers)
- ✅ "Premium native app" feel — like Apple Mail, but better designed
- ✅ Soft depth via very subtle backgrounds, not shadows

### Anti-patterns to avoid
- ❌ Heavy drop shadows
- ❌ Loud accent colors
- ❌ Dense data tables (Sublime is about calm, not density)
- ❌ Aggressive animations

---

## 8. Height (project management)

**Live reference:** [height.app](https://height.app)

### Identity
Auto-updating project management with a clean, professional aesthetic. Light by default (rare for PM tools). Specific to "tasks that update themselves" — the interface gets out of the way, the data does the talking.

### When to choose
- Project management, task tools
- Tools where automation is the value proposition
- B2B tools that want to feel "modern but professional"
- Audiences that want clarity over personality

### Palette
```
--surface:         #FFFFFF
--surface-1:       #FAFAFA
--surface-2:       #F4F4F5

--ink:             #18181B   /* near-black, slightly cool */
--ink-muted:       #71717A
--ink-subtle:      #A1A1AA

--hairline:        #E4E4E7
--hairline-strong: #D4D4D8

--accent:          #5D5FEF   /* Height's blue-purple */
--accent-soft:     #EEEEFE

--good:            #10B981
--warn:            #F59E0B
--bad:             #EF4444
```

### Typography
- **Inter** for everything (Height's choice)
- Mono for keyboard shortcuts and metadata
- Hero size: `clamp(2.25rem, 4.5vw, 3.5rem)` — calm, confident
- Tracking: -0.02em on display
- Line-height: 1.05 on display, 1.5 on body

### Layout
- Max-width 1200px
- Sidebar (in app) — collapsible
- Marketing hero: text left, product UI right
- Generous section spacing

### Signature patterns
- ✅ Clean, light professional aesthetic (rare for PM tools)
- ✅ Strong, clear status indicators
- ✅ Property-based UI (custom fields visible, machine-readable)
- ✅ Generous whitespace, low visual noise
- ✅ Dense info but never cluttered

### Anti-patterns to avoid
- ❌ Heavy dark themes (Height is light-first)
- ❌ Loud, marketing-y hero
- ❌ Decorative illustrations
- ❌ Generic "3-card features" presentation

---

## 9. Pitch

**Live reference:** [pitch.com](https://pitch.com)

### Identity
Presentation tool with more personality than Linear, more polish than Notion. Modern, warm, with strong color usage (multi-hue semantic palette like Cron). Custom illustrations. Generous whitespace.

### When to choose
- Creative tools, presentation software
- Collaboration products
- Tools that want personality without losing professionalism
- Anything targeting designers, marketers, agencies

### Palette
```
--surface:         #FAFAF7
--surface-1:       #FFFFFF
--surface-2:       #F4F2EC

--ink:             #1F1F1F
--ink-muted:       #6B6B6B
--ink-subtle:      #A8A8A8

--hairline:        #E8E5DE

/* Multi-hue semantic — each color has meaning */
--hue-primary:     #FF4D6D   /* coral pink — primary CTA */
--hue-secondary:   #5B5FED   /* purple-blue — secondary */
--hue-tertiary:    #00C2A8   /* teal — status */
--hue-warning:     #FFB800
```

### Typography
- **Inter** for UI + **GT Super** or **Fraunces** for display moments
- Display: `clamp(2.5rem, 5vw, 4rem)`
- Tracking: -0.02em on display
- Line-height: 1.1 on display

### Layout
- Max-width 1200px
- Hero: text + product UI mockup (a slide being edited)
- Custom illustrations as visual texture
- Asymmetric sections with mixed media

### Signature patterns
- ✅ Multi-color semantic palette (each color = a category or feature)
- ✅ Custom geometric illustrations
- ✅ Personality in microcopy
- ✅ Slight serif influence (display moments)
- ✅ Generous whitespace between bold moments

### Anti-patterns to avoid
- ❌ Boring single-accent palette
- ❌ Stock illustrations
- ❌ Generic 3-card features
- ❌ Loud animations

---

## 10. Figma

**Live reference:** [figma.com](https://figma.com)

### Identity
Design tool marketing that's technical, dense, and full of personality. Multi-color palette (each Figma product has its color). Mixed sans typography. Strong grid. Custom iconography. Code-forward in some pages (CSS, SVG, Figma plugin code).

### When to choose
- Developer / designer tools
- Products where extensibility / API is a feature
- Tools with multiple sub-products (each can have its own color)
- Anything that wants to feel "made by designers, for designers"

### Palette
```
--surface:         #FFFFFF
--surface-1:       #F5F5F5
--surface-2:       #E5E5E5

--ink:             #1E1E1E
--ink-muted:       #5C5C5C
--ink-subtle:      #8C8C8C

--hairline:        #E5E5E5
--hairline-strong: #C7C7C7

/* Multi-product palette — each Figma product = a color */
--hue-figma:       #F24E1E   /* orange-red */
--hue-figjam:      #A259FF   /* purple */
--hue-dev:         #0ACF83   /* green */
--hue-make:        #9747FF   /* deeper purple */
--hue-slides:      #FF7262   /* coral */
```

### Typography
- **Inter** for everything (Figma's choice)
- Mono for code blocks (JetBrains Mono)
- Hero size: `clamp(2.5rem, 5vw, 4rem)` — confident
- Tracking: -0.02em on display
- Sometimes uses serif for editorial moments (rare)

### Layout
- Max-width 1280px
- Hero: large headline + product UI screenshot (a Figma canvas with shapes)
- Code blocks as marketing surfaces (CSS, plugin code)
- Strong grids, dense info

### Signature patterns
- ✅ Multi-product color coding
- ✅ Custom geometric icons (Figma's famous logomark family)
- ✅ CSS / SVG / plugin code shown as marketing
- ✅ "Designed by designers" aesthetic — slightly meta
- ✅ Mixed media: UI + illustration + code on one page

### Anti-patterns to avoid
- ❌ Single-accent palette (defeats Figma's multi-product identity)
- ❌ Heavy drop shadows
- ❌ Generic "tools for designers" marketing
- ❌ Stock photos

---

## 11. Notion (main app / workspace)

**Live reference:** [notion.so](https://notion.so)

### Identity
All-in-one workspace with the most distinctive illustration system in modern SaaS. Off-white warm background, custom hand-drawn-feeling illustrations (geometric, friendly, slightly weird), generous whitespace, restrained accents, personality in microcopy.

### When to choose
- Productivity, notes, docs tools
- All-in-one workspace products
- Tools targeting "creative knowledge workers"
- Anything that wants warmth + utility

### Palette
```
--surface:         #FAF9F7   /* warm off-white */
--surface-1:       #FFFFFF
--surface-2:       #F4F2EE

--ink:             #2F2F2F
--ink-muted:       #6B6B6B
--ink-subtle:      #A8A8A8

--hairline:        #E8E5DE
--hairline-strong: #D4D0C6

--accent:          #2383E2   /* Notion's blue */
--accent-soft:     #E6F0FB
```

Notion's "accent" is blue, but it's used very sparingly. The illustrations carry the color.

### Typography
- **Inter** for UI
- Sometimes **Source Serif** for editorial moments
- Hero size: `clamp(2.5rem, 5vw, 4rem)` — confident, generous
- Tracking: -0.02em on display
- Line-height: 1.1 on display, 1.55 on body

### Layout
- Max-width 1200px
- Hero: text + product UI (a Notion page being edited)
- Custom illustrations throughout, often as the visual focus of a section

### Signature patterns
- ✅ **Custom illustrations** — hand-drawn feel, geometric, slightly weird, friendly. This is Notion's signature. Don't try to copy exactly; understand the principle: illustrations have *personality*, are *consistent in style*, and are *the visual focus* of sections.
- ✅ Generous whitespace
- ✅ Personality in microcopy: "Welcome back", "Add a thing", empty states that say something
- ✅ Sidebar with sections, page tree, simple icons
- ✅ Minimal chrome — the page is the focus

### Anti-patterns to avoid
- ❌ Generic 3-card features with stock icons
- ❌ Loud bright colors
- ❌ Heavy drop shadows
- ❌ Corporate throat-clearing copy

---

## Decision tree (updated)



```
B2B SaaS / fintech / dev tool?
├── Yes
│   ├── Dark mode primary?
│   │   ├── Yes → Linear
│   │   └── No (or both) → continue
│   ├── Code-forward / API-first?
│   │   ├── Yes → Stripe
│   │   └── No → continue
│   ├── B/W stark minimal?
│   │   ├── Yes → Vercel
│   │   └── No → continue
│   ├── Premium fintech / banking?
│   │   ├── Yes → Mercury
│   │   └── No → continue
│   ├── Premium consumer with personality?
│   │   ├── Yes → Arc
│   │   └── No → continue
│   └── Friendly productive tool?
│       └── Yes → Cron / Notion Calendar
└── No → wrong family, return to aesthetics.md
```

---

## Hybrid rules (when forced to combine)

Sometimes a project sits between two sub-styles. Rules:

1. **Pick the dominant one** — 70/30, not 50/50.
2. **Share typography family** — if Linear + Stripe, both use Inter. Don't mix Söhne and Inter.
3. **Share accent philosophy** — don't blend purple + indigo + sage. Pick one.
4. **Surface consistency** — if dark in some places and light in others, ensure the chrome (nav, footer) is consistent.
5. **Different sub-styles for marketing vs product** is fine — Linear-style marketing, Mercury-style dashboard, etc. They share typography and tokens.

---

## What to read next

- For typography system setup → `typography.md`
- For color token implementation → `color.md`
- For component patterns (buttons, forms, tables) → `components.md`
- For motion principles → `motion.md`
- For anti-patterns to reject → `anti-patterns.md`
- For final QA → `checklist.md`
