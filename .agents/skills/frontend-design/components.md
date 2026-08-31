# Components — Build Them Once, Use Them Everywhere

> Every interactive element on the page must have: default, hover, focus-visible, active, disabled. Skip one and the design breaks on the edges.

---

## Buttons

### Anatomy
A button is a **promise to the user**: click me, this happens. It must look pressable. It must have a clear label.

### Variants (use 2–3 max)

**Primary**
- Background: `--ink` (or `--accent`)
- Text: `--surface`
- One per page, max. The thing the user should do.

**Secondary**
- Background: transparent
- Border: `1px solid var(--hairline-strong)` (or `--ink` for emphasis)
- Text: `--ink`
- The second thing the user could do.

**Tertiary / Ghost**
- Background: transparent
- Text: `--ink`
- Optional underline or arrow
- The third thing. Or a low-priority action.

**Destructive**
- Background: `--error`
- Text: `--surface`
- Use for irreversible actions. Always confirm before executing.

### Sizes

| Token | Height | Padding | Font size |
|---|---|---|---|
| `sm` | 32px | 0 12px | 14px |
| `md` (default) | 40px | 0 16px | 14–15px |
| `lg` | 48px | 0 20px | 16px |
| `xl` | 56px | 0 24px | 17–18px |

### States

| State | Treatment |
|---|---|
| Default | As designed |
| Hover | Slight darken of background, or border strengthens. Use `transition: background-color 120ms ease, border-color 120ms ease;` |
| Focus-visible | 2px ring, accent color, 2px offset |
| Active | Slight darken or scale(0.98). 80ms transition. |
| Disabled | Reduced opacity (0.5), no hover effects, `cursor: not-allowed` |
| Loading | Replace label with spinner, OR keep label and add small spinner before |

### Rules

- ❌ Don't use 5 button variants. Pick 2–3, max.
- ❌ Don't make buttons pills (`border-radius: 9999px`) by default. 6–8px is safer.
- ❌ Don't put icons inside button labels without text (icon-only buttons need `aria-label`).
- ❌ Don't stack a primary next to another primary. Primary is singular.
- ❌ Don't make buttons too small to tap. Minimum 40px tall, 44px on mobile.
- ❌ Don't use more than 2 buttons in a single CTA group.

### Sample HTML + CSS

```html
<button class="btn btn--primary">Get started</button>
<button class="btn btn--secondary">Read docs</button>
```

```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 40px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
  border: 1px solid transparent;
}

.btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.btn--primary {
  background: var(--ink);
  color: var(--surface);
}
.btn--primary:hover { background: #1F1F1F; }

.btn--secondary {
  background: transparent;
  border-color: var(--hairline-strong);
  color: var(--ink);
}
.btn--secondary:hover { border-color: var(--ink); }
```

---

## Forms

### Inputs

- **Height:** 40px default. 36px for compact.
- **Background:** `--surface-elevated` or `--surface-sunken` (slight contrast from page)
- **Border:** `1px solid var(--hairline-strong)`
- **Border-radius:** matches buttons (6–8px)
- **Padding:** `0 12px`
- **Font:** same as body, 14–16px
- **Placeholder:** `--ink-subtle`, NOT `--ink-muted` — distinguish placeholders from real values
- **Label:** Above the input, 13–14px, `--ink-muted`, margin-bottom 6px

### States

| State | Border |
|---|---|
| Default | `--hairline-strong` |
| Hover | `--ink` |
| Focus | `--accent`, 2px |
| Error | `--error` |
| Disabled | `--hairline`, opacity 0.6, `cursor: not-allowed` |

### Inputs anti-patterns
- ❌ Placeholder used as label (loses on focus)
- ❌ Label inside input (accessibility disaster)
- ❌ No label at all (placeholder isn't a label)
- ❌ Border that disappears on focus with no replacement
- ❌ Default browser styling (especially checkboxes, radios, selects)

### Custom checkboxes / radios

```css
input[type="checkbox"] {
  appearance: none;
  width: 16px;
  height: 16px;
  border: 1.5px solid var(--hairline-strong);
  border-radius: 4px;
  background: var(--surface);
  cursor: pointer;
  position: relative;
}
input[type="checkbox"]:checked {
  background: var(--accent);
  border-color: var(--accent);
}
input[type="checkbox"]:checked::after {
  content: '';
  position: absolute;
  left: 4px;
  top: 1px;
  width: 5px;
  height: 9px;
  border: solid var(--surface);
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}
```

### Select dropdowns

Native `<select>` is ugly but accessible. Three options:

1. **Style the native element** as much as possible — works in most cases
2. **Custom dropdown** with full keyboard accessibility (much more code)
3. **Use a library** (Radix, Headless UI, React Aria) for safety

Whichever path: keep the visible trigger simple — same height and border as inputs.

### Form layout

- Labels above inputs (most common, fastest to scan)
- One column by default. Two-column only when columns are independent (e.g., First Name / Last Name).
- Help text below the input, smaller and muted.
- Error messages: red, specific, actionable ("Enter a valid email" not "Invalid input").
- Required field marker: `*` or "(required)" — pick one, be consistent.

---

## Cards

A card groups related content. Use sparingly. The more cards on a page, the less each one matters.

### Anatomy
- Surface: `--surface-elevated` (or same as page if minimal)
- Border: `1px solid var(--hairline)` — preferred over shadow
- Radius: 8–12px (or 0 in Swiss style)
- Padding: 24px (compact) to 32px (generous)
- Optional: header, body, footer zones, separated by hairline or padding

### Variants

**Flat card** — hairline border, no shadow. Default for content cards.
```css
.card {
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 24px;
}
```

**Elevated card** — subtle shadow, used for floating elements (popovers, modals). Rare for content cards.
```css
.card-elevated {
  background: var(--surface-elevated);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06);
}
```

**Interactive card** — entire card is clickable. Cursor pointer, hover lifts the border color or background.
```css
.card-interactive {
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: 12px;
  padding: 24px;
  cursor: pointer;
  transition: border-color 150ms ease, background 150ms ease;
}
.card-interactive:hover {
  border-color: var(--ink);
}
```

### Card content rules
- ❌ Don't put a card inside a card
- ❌ Don't make every card the same size if content varies wildly
- ❌ Don't add a small "category" tag to every card automatically
- ❌ Don't use cards as layout placeholders for non-card content (use proper sections)

---

## Navigation

### Top nav

- **Height:** 56–72px
- **Background:** same as surface (or slight elevation if scroll-aware)
- **Logo:** left, 24–32px tall
- **Links:** center or right, 14–15px, medium weight
- **CTA:** right side, distinct button
- **Sticky:** optional, but if sticky, add backdrop or shadow on scroll

**Mobile:** Hamburger menu OR a horizontal scroll of categories. Don't hide navigation behind gestures users don't know.

### Side nav (for apps, dashboards)

- **Width:** 240–280px (collapsible to 56–64px)
- **Sections:** grouped by purpose, with section labels
- **Active state:** clear visual — background tint or accent border on left edge
- **Icons:** 16–20px, single weight stroke, paired with labels
- ❌ Don't make icon-only navigation without tooltips

### Breadcrumbs

- Small, muted, 13–14px
- Separator: `/` or `›`, in `--ink-subtle`
- Last item: `--ink`, no link
- ❌ Don't make breadcrumbs interactive if the parent pages don't exist

### Footer

- **Layout:** can be 4-column (product / company / resources / legal) OR a single editorial line OR a technical mono footer with metadata
- **Tone:** smaller type (13–14px), muted
- **Content:** links + small print + small brand mark + maybe a single line of brand voice
- ❌ Don't fill it with content just to fill it
- ❌ Don't use the footer as a primary navigation surface

---

## Tables

Tables are for data. If it's not data, don't use a table.

### Style
- **Header row:** slightly different background, `--ink-muted`, smaller text (12–13px), often uppercase with tracking
- **Cells:** 12–16px vertical padding
- **Borders:** bottom-only hairlines between rows, not full grid
- **Numbers:** monospace font, tabular figures, right-aligned
- **Hover row:** subtle background (`--surface-sunken`) for readability in long tables
- **Actions:** last column, icon buttons or text links

### Table anti-patterns
- ❌ Full grid of borders (looks like Excel)
- ❌ Centered text in data cells (left-align text, right-align numbers)
- ❌ Wrapping headers (use shorter labels)
- ❌ Inconsistent row heights (vary them carefully)

---

## Badges & Tags

### Badges
Small inline labels. Two types:
- **Status badges:** rounded pill (4–6px radius), small (10–12px text), color-coded for state
- **Categorical badges:** rectangular or pill, neutral background, used for taxonomy

### Rules
- ❌ Don't use too many colors — limit to 2–3 states plus neutral
- ❌ Don't make badges too large (they're punctuation, not headlines)
- ❌ Don't make every list item have a badge — most shouldn't

```css
.badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  background: var(--surface-sunken);
  color: var(--ink-muted);
}

.badge--success { background: #DCFCE7; color: #14532D; }
.badge--warning { background: #FEF3C7; color: #78350F; }
.badge--error   { background: #FEE2E2; color: #7F1D1D; }
```

---

## Avatars

- **Sizes:** 24px (inline), 32px (list), 40px (comment), 64px (profile), 96px (hero)
- **Shape:** circle by default; rounded square OK in some contexts
- **Fallback:** initials on a muted background, in mono or display type
- **Image:** always set `alt` (use empty `alt=""` for decorative)
- **Border:** optional 1px hairline if on a similar-colored background

---

## Empty / Loading / Error States

These are where amateurs stop and pros begin. **Always design them.**

### Empty state
- Centered or left-aligned
- Single sentence explaining why it's empty
- One action to fix it ("Create your first project")
- Optional small illustration or icon — restrained

### Loading state
- Skeleton: same layout as loaded content, animated shimmer or pulse
- Spinner: only for short waits (<2s), centered
- Progress: for long operations, with meaningful stages
- ❌ Don't show a spinner for under 200ms — it flashes and feels broken

### Error state
- What happened, in plain language
- What the user can do
- A way to retry or contact support
- ❌ Don't show raw error messages (`"TypeError: undefined is not a function"`)
- ❌ Don't use a sad emoji or stock illustration of someone frustrated

### 404 page
- A real, designed page — not the default server one
- One clear explanation ("This page doesn't exist.")
- A way back (link to home, search bar, navigation)
- An opportunity for voice: a small editorial moment, a real photo, a piece of brand personality
- ❌ Don't use a 404 page as a place to be clever at the expense of utility

---

## Tooltips & Popovers

- Appear on hover (desktop) or tap (mobile)
- Disappear on escape, on click outside, on scroll
- Maximum 2 lines of text
- Background: `--ink` with white text OR `--surface-elevated` with a stronger shadow
- Animation: fade-in 100ms, no movement
- Always include an arrow pointing to the trigger (unless context makes it obvious)
- ❌ Don't put interactive content inside a tooltip (use a popover for that)
- ❌ Don't show tooltips on touch devices (they don't have hover)

---

## Modal / Dialog

- Centered, max-width 480–560px for forms, larger for content
- Backdrop: `rgba(0, 0, 0, 0.4–0.6)` — enough to focus, not so much it blacks out
- Surface: `--surface-elevated`
- Border-radius: 12px (or match cards)
- Padding: 24–32px
- Close: visible X button (top-right) AND `Escape` key
- Focus trap: keyboard focus stays inside the modal
- Scroll: inside the modal if content overflows
- Animation: fade + slight scale (0.98 → 1), 150ms

---

## Component Checklist (before shipping)

For every component on the page, verify:

- [ ] Default state is designed
- [ ] Hover state is defined
- [ ] Focus-visible state is defined (and looks intentional)
- [ ] Active / pressed state is defined
- [ ] Disabled state is defined
- [ ] Loading state (if async)
- [ ] Empty state (if data-driven)
- [ ] Error state (if forms or data)
- [ ] Keyboard accessible (Tab, Enter, Escape)
- [ ] Screen reader labels present (`aria-label` where needed)
- [ ] Mobile breakpoint at 480px and 768px
- [ ] Touch targets at least 44×44px on mobile
