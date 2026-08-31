# Layout — Grid, Space, Rhythm

> Layout is the skeleton the user never sees and always feels. A page with a real grid, a real spacing scale, and real breakpoints reads as designed. A page with guessed margins reads as generated. Layout is decided **before** the first component is built — see `SKILL.md` Step 5.

---

## The Container System

Decide container widths once, use them everywhere.

| Token | Width | Use |
|---|---|---|
| `--container-read` | `65ch`–`72ch` | Long-form body text (measure) |
| `--container-text` | `720px` | Article intros, single-column sections |
| `--container-main` | `1200px`–`1280px` | Default page container (nav, hero, features) |
| `--container-wide` | `1440px` | Index tables, image galleries, data-heavy pages |
| Full bleed | `100%` | One or two moments per page — a spread, a footer, a manifesto |

### Rules

- **One container per page, plus at most one full-bleed exception.** Mixing four content widths per page reads as accidental.
- Side padding: `clamp(20px, 4vw, 48px)` minimum; `clamp(24px, 6vw, 80px)` for editorial and Swiss pages where margins carry the design.
- **Never let body copy span `--container-main`.** Text columns cap at ~`40ch`–`45ch` inside a wide grid; the grid column holds it, not the container.
- Content must never touch the viewport edge below 400px — padding scales down, never below 20px.

```css
:root {
  --container-main: 1240px;
  --container-text: 720px;
  --container-read: 68ch;
  --pad-inline: clamp(20px, 4vw, 48px);
}

.container {
  max-width: var(--container-main);
  margin-inline: auto;
  padding-inline: var(--pad-inline);
}
```

---

## The Spacing Scale

One scale. Everything is spaced from it. No `margin: 37px`, no `padding: 22px`, no one-off gaps.

```css
:root {
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 24px;
  --sp-6: 32px;
  --sp-7: 48px;
  --sp-8: 64px;
  --sp-9: 96px;
  --sp-10: 128px;
}
```

### Section rhythm

| Viewport | Between sections | Inside a section |
|---|---|---|
| Mobile (< 720px) | `--sp-7` (48px) | `--sp-5` – `--sp-6` |
| Tablet (720–1024px) | `--sp-8` (64px) | `--sp-6` |
| Desktop (> 1024px) | `--sp-9` – `--sp-10` (96–128px) | `--sp-6` – `--sp-7` |

**Rules:**

- Space **before** a heading is larger than space after it (roughly 1.5–2×). The heading belongs to the text below it — proximity is hierarchy.
- If two sections need a divider **and** more space, the spacing was wrong. Whitespace separates; hairlines clarify (tables, indices). Not both everywhere.
- Space communicates hierarchy: **more space = more importance.** The hero gets the most air on the page. If every section has 128px around it, none of them is the hero.

---

## Grid Systems

### The default: 12 columns

```css
.grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  column-gap: var(--sp-5);
}
```

Use it for hero splits and multi-column zones. Not every zone needs all 12 — see splits below.

### Editorial / Swiss: 6 columns

Wider gutters, fewer columns, stronger verticals. Index pages, archives, tables of contents. Pair with hairline rules and mono metadata — see `editorial-patterns.md`.

### Asymmetric splits (the anti-slop move)

Equal 50/50 and identical thirds are the default AI output. Offset the split instead:

| Split | Effect | Typical use |
|---|---|---|
| `5fr / 7fr` | Text-led, support right | Hero: headline left, product/UI right |
| `3fr / 9fr` | Sidebar + content | Article with meta column, docs |
| `7fr / 5fr` | Support left, text right | Feature sections alternating with the hero |
| `4fr / 4fr / 4fr` | **Avoid** — identical thirds | (Only for genuinely equal data: pricing tiers you've already fixed per `anti-patterns.md` §13) |
| `2fr / 6fr / 4fr` | Meta + body + aside | Editorial spreads, catalog entries |

```css
.hero {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  column-gap: clamp(32px, 5vw, 80px);
  align-items: center;
}

/* Alternate the next feature section — mirror, don't repeat */
.feature--flipped { grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); }
```

### The meta-column pattern

A workhorse: a narrow fixed column (`180px`–`220px`) for labels, numbers, kickers; the rest for content. It forces asymmetry, gives metadata a home, and scales down to one column on mobile. Used by Pentagram archives, product docs, and every example in `examples/`.

```css
.section {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  column-gap: clamp(32px, 5vw, 64px);
}

@media (max-width: 720px) {
  .section { grid-template-columns: 1fr; }
}
```

---

## Composition Patterns

### The dominant element

Every page has **one** element that dominates (see `SKILL.md` Step 5): usually the hero headline or the product visual. Compose around it:

- Give it the largest type or the largest box on the page.
- Everything else steps down **deliberately** — second level at ~60% of its size, third at ~35%.
- One full-bleed or oversized moment per page. Two is noise.

### Reading paths

- **Z-pattern** for sparse, hero-led pages: strong top-left anchor, diagonal to a CTA bottom-right.
- **F-pattern** for text-heavy pages: reinforce with a strong left rule — meta column, numbered index, aligned labels.
- **Single-axis scroll** for editorial: one strong centerline, breaks only for full-bleed spreads.

### Alternation

Down the page, alternate section structures — never repeat one module twice in a row:

```
hero (5/7 split, type-led)
→ statement (full-width, large type, no grid)
→ index (meta-column list)
→ detail (7/5 split, visual-led)
→ quote or manifesto (full-bleed or inset)
→ action (2-column, type + form)
→ footer (colophon)
```

If two consecutive sections have the same structure, **flip the split or merge them.**

### Overlap and inset (use once)

An image bleeding out of its column by one gutter (`margin-right: calc(-1 * var(--sp-5))`), or a caption overlapping an image edge, adds craft. Once per page. More is decoration.

---

## Responsive Strategy

**Mobile-first, four breakpoints, tested at five widths.**

| Breakpoint | Change what |
|---|---|
| Base (320–479px) | Single column, type scale steps down ~1 tier, meta-columns collapse above content |
| `min-width: 480px` | Two-column utility layouts (stats, small cards), larger touch paddings |
| `min-width: 768px` | Grid splits appear (5/7 etc.), side nav space, larger section rhythm |
| `min-width: 1024px` | Full 12-col grid, meta-column pattern, `--sp-9`+ section spacing |

Test widths: **320, 375, 768, 1280, 1600.** (`checklist.md` tests 375/768/1280 — 320 catches overflow, 1600 catches lonely stretched content.)

### Collapse rules

- Multi-column zones collapse **column by column** — meta columns collapse to a top row, not to a wall of centered text.
- Left-aligned stays left-aligned at every size. Centering is not a mobile strategy.
- Hide nothing essential on mobile. If a section must be cut, cut it at the brief level, not in CSS.
- Tables: allow horizontal scroll inside the table wrapper (`overflow-x: auto`), never the page.
- Fluid type via `clamp()` means most text needs **no** breakpoint overrides — see `typography.md`. Breakpoints are for **structure**, not font sizes.

```css
/* Structure at breakpoints — not font sizes */
.hero { grid-template-columns: 1fr; }

@media (min-width: 768px) {
  .hero { grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); }
}
```

---

## Whitespace Rules

1. Whitespace is a **feature**, not leftovers (`SKILL.md` principle 4). If a section feels crowded, the fix is usually `--sp-9`, not a background tint.
2. **Air follows importance.** Hero > section intros > body > captions.
3. Never fill space with decoration because it feels empty. Empty is the design.
4. Dense is allowed — indices, tables, technical docs are dense **on purpose** (see `aesthetics.md` §3, §6). Density then needs hairline structure and mono numbers to read as order, not crowding.

---

## Layout Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| Centered everything, every section | One dominant left-aligned composition; center only short statements |
| Identical thirds repeated down the page | Asymmetric splits (5/7, 3/9), alternating structures |
| `max-width: none` full-window text | Container system with a measure for body copy |
| One-off margins (`17px`, `23px`, `40px`) | The spacing scale, as tokens |
| Dividers between every section | Whitespace between sections; hairlines inside data only |
| Hero with 200px padding and 36px headline | Big type or big visual **or** generous air — the hero must justify its space |
| Every section same structure, same rhythm | Alternate splits and densities; one full-bleed moment |
| Hiding whole sections on mobile | Simplify structure, keep the content |
| Fixed pixel widths on grid children (`width: 400px`) | `minmax(0, 1fr)` tracks and `max-width` in `ch`/`%` |
| Horizontal page scroll from a wide child | `minmax(0, 1fr)` tracks, `overflow-x: auto` on table wrappers, `max-width: 100%` on media |
| Breakpoints that only change font sizes | Breakpoints change **structure**; type is fluid via `clamp()` |

---

## A Working CSS Setup

```css
:root {
  --container-main: 1240px;
  --container-text: 720px;
  --container-read: 68ch;
  --pad-inline: clamp(20px, 4vw, 48px);

  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px; --sp-8: 64px;
  --sp-9: 96px; --sp-10: 128px;

  --section-gap: var(--sp-7);          /* mobile */
}

@media (min-width: 768px)  { :root { --section-gap: var(--sp-8); } }
@media (min-width: 1024px) { :root { --section-gap: var(--sp-9); } }

body { margin: 0; }

.container {
  max-width: var(--container-main);
  margin-inline: auto;
  padding-inline: var(--pad-inline);
}

.container--text { max-width: var(--container-text); }

section { padding-block: var(--section-gap); }

.grid        { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: var(--sp-5); }
.split       { display: grid; column-gap: clamp(32px, 5vw, 80px); }
.split--5-7  { grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); }
.split--3-9  { grid-template-columns: minmax(0, 3fr) minmax(0, 9fr); }
.split--meta { grid-template-columns: 200px minmax(0, 1fr); column-gap: clamp(32px, 5vw, 64px); }

.measure { max-width: var(--container-read); }

@media (max-width: 767px) {
  .split, .split--5-7, .split--3-9, .split--meta { grid-template-columns: 1fr; row-gap: var(--sp-6); }
}

*, *::before, *::after { box-sizing: border-box; }
img, svg, video { max-width: 100%; height: auto; }
```

---

## Layout QA

- [ ] One container system; body copy capped at ~45ch inside grids
- [ ] All spacing comes from the scale — zero one-off values
- [ ] Hero is asymmetric or has a deliberate typographic moment
- [ ] No two consecutive sections share a structure
- [ ] One full-bleed moment maximum
- [ ] Tested at 320, 375, 768, 1280, 1600 — no horizontal scroll at any width
- [ ] Breakpoints change structure, not font sizes
- [ ] Left alignment preserved at every size

See also: `typography.md` (fluid type), `color.md` (surface rhythm between sections), `anti-patterns.md` §6, §11, §12 (structural slop), `checklist.md` (Layout section).
