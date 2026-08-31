# Typography — The Design

> Typography does 80% of the work. Choose faces with care, set them with intention, and never let defaults decide for you.

---

## The Two-Typeface Rule

Pick **one display face** and **one text face**. Two total. Mono can be a third if needed (numbers, code, kickers).

**Why:** A page with three different typefaces reads as confused. A page with one great family used well reads as designed.

### How to choose

**Display face** — used in headlines, hero, section markers, big moments.
- Ask: does it have **character**? Would I recognize it on a poster?
- Avoid: anything that looks like default system fonts. Roboto, Open Sans, Lato — these are *fine* but not *chosen*.
- Test: render the brand name in the display face at 96px. Does it look like a magazine? A poster? An interface? Good. If it looks like a template — pick another.

**Text face** — used in body, UI, forms, captions.
- Ask: is it **legible at 14–16px** for sustained reading?
- Ask: does it have a **complete weight range** (400, 500, 600, 700) and a **good italic**?
- Avoid: thin weights under 400 for body text. Avoid display serifs as body.

**Mono face** (optional) — for numbers, code, kickers, metadata.
- Must have good tabular figures (numbers align in tables).
- Use for: pricing, statistics, code, timestamps, IDs, environment variables.

---

## Recommended Faces (free / open license where possible)

### Sans (modern grotesque / neo-grotesque)
- **Inter** — workhorse, free, full range
- **Söhne** — Linear/Stripe-quality, paid
- **Geist** — Vercel's, free, beautiful
- **GT America** — paid, super versatile
- **ABC Diatype** — paid, elegant
- **Helvetica Now** — paid, the modern Helvetica
- **Neue Haas Grotesk** — paid, the original spirit
- **IBM Plex Sans** — free, distinctive

### Serif (display)
- **GT Super** — paid, warm, magazine
- **Tiempos Headline** — paid, editorial
- **Söhne Serif** — paid, modern serif
- **Editorial New** — paid, newspaper
- **Domaine Display** — paid, NYT-class
- **GT Sectra** — paid, contemporary serif
- **Lora / Source Serif / Newsreader** — free, good
- **Fraunces** — free, expressive, quirky
- **Instrument Serif** — free, elegant display
- **Playfair Display** — free, classic, use sparingly

### Mono
- **JetBrains Mono** — free, dev-friendly
- **IBM Plex Mono** — free, well-balanced
- **Berkeley Mono** — paid, the gold standard
- **GT America Mono** — paid
- **Geist Mono** — free, Vercel
- **Iosevka** — free, condensed
- **Fragment Mono** — free, modern

---

## Pairs That Work

| Display | Text | When |
|---|---|---|
| **Söhne / Inter Display** | Söhne / Inter | Refined Minimal, SaaS |
| **GT Super / Fraunces** | Inter / Söhne | Editorial, magazine |
| **GT America** | GT America Mono | Refined Minimal, technical |
| **Helvetica Now** | Helvetica Now | Swiss, manifestos |
| **Geist** | Geist Mono | Technical, dev tools |
| **IBM Plex Sans** | IBM Plex Mono | Technical, docs |
| **Instrument Serif** | Inter | Editorial, soft premium |
| **Editorial New / Tiempos** | Inter | Publishing, journalism |
| **GT Sectra** | ABC Diatype | Editorial premium |
| **Manrope / Inter** | JetBrains Mono | Playful, modern SaaS |

### Pairs that almost never work
- ❌ Two different serifs (one display, one text)
- ❌ Two different sans-serifs from different schools (e.g., a humanist + a geometric)
- ❌ Display serif + heavy industrial sans
- ❌ Comic Sans + anything
- ❌ Script + anything (only for one-off flourishes, never headlines)

---

## Scale & Sizes

**Default modular scale:** 1.250 (Major Third) — comfortable for product UI.
**Editorial scale:** 1.333 (Perfect Fourth) or hand-tuned — for content-heavy pages.

### Suggested scale (px, base 16px, ratio 1.250)

| Token | Size | Use |
|---|---|---|
| `text-xs` | 12px | Captions, labels, microcopy |
| `text-sm` | 14px | UI secondary, table cells, footnotes |
| `text-base` | 16px | Body, paragraphs, inputs |
| `text-lg` | 20px | Lead paragraphs, large UI |
| `text-xl` | 25px | H4, subhead small |
| `text-2xl` | 31px | H3, subhead medium |
| `text-3xl` | 39px | H2 |
| `text-4xl` | 49px | H1, section markers |
| `text-5xl` | 61px | Large section H1 |
| `text-6xl` | 76px | Page hero (small) |
| `text-7xl` | 95px | Page hero (medium) |
| `text-8xl` | 119px | Page hero (large) |
| `text-9xl` | 149px | Editorial hero, posters |

### Hero size — choose deliberately

- **Confident / minimal:** `clamp(2.5rem, 5vw, 4rem)` — 40–64px
- **Strong:** `clamp(3.5rem, 6vw, 5.5rem)` — 56–88px
- **Bold / editorial:** `clamp(4rem, 8vw, 7rem)` — 64–112px
- **Magazine / poster:** `clamp(5rem, 10vw, 10rem)` — 80–160px
- **Always test:** if hero is set at the default 36–48px, it reads as a template. Push it.

### CSS clamp formula

```
font-size: clamp(<min>, <fluid>, <max>);

Example:
font-size: clamp(2.25rem, 5vw + 1rem, 4.5rem);
```

The fluid value uses `vw` so it scales with viewport, with the `+ rem` offset so it doesn't get tiny on small screens.

---

## Line Height (leading)

| Type | Line height |
|---|---|
| Display headlines (set tight) | **1.0 – 1.1** |
| Large H1 / H2 (60px+) | 1.05 – 1.15 |
| Standard headings (24–40px) | 1.15 – 1.3 |
| Lead paragraphs (18–22px) | 1.4 – 1.5 |
| Body copy (16–18px) | 1.5 – 1.65 |
| Small body / UI secondary (14px) | 1.45 – 1.55 |
| Captions / labels (12–13px) | 1.4 – 1.5 |

**Rule:** bigger the type → tighter the leading. Smaller the type → looser the leading. UI = around 1.4–1.5.

---

## Letter Spacing (tracking)

| Type | Tracking |
|---|---|
| Display headlines (large) | **-0.02em to -0.04em** (negative — pulls letters closer) |
| Standard headings | -0.01em to -0.02em |
| Body copy | **0** (default) |
| All-caps labels / kickers | **+0.05em to +0.12em** (positive — opens up) |
| Buttons (often all-caps small) | +0.02em to +0.05em |
| Numerical mono data | 0 (let the mono handle alignment) |

**Rule:** larger display type wants negative tracking. All-caps wants positive tracking. Body copy wants 0.

---

## Weights — Use With Restraint

A typeface has 4–9 weights. Use **2–3 max** per page. Here is the typical allocation:

- **400 (Regular)** — body copy, paragraphs, default UI
- **500 (Medium)** — buttons, labels, emphasized inline text, captions
- **600 (Semibold)** — subheads, H3/H4, important UI
- **700 (Bold)** — H1/H2, hero, key moments only

**Avoid:** 300 (Light) for body. Avoid 800/900 unless it's a display moment — and even then, only if the family is designed for it.

### When to bold, when to italic

- **Bold for hierarchy.** Italic for tone, foreign words, citations.
- **Italic in body:** titles of works, the *New York Times*, foreign phrases, internal thought.
- **Bold in body:** sparingly — for inline emphasis. Don't bold entire sentences; bold the word.
- **Display italic:** some serifs have a beautiful italic — use it for editorial pull quotes, byline accents.

---

## Color & Contrast for Type

- **Primary text:** ink color on surface. Contrast ratio **≥ 7:1** (AAA) where possible. **≥ 4.5:1** (AA) at minimum for body.
- **Secondary text:** muted ink. Contrast ratio **≥ 4.5:1** minimum.
- **Tertiary / placeholders:** even more muted — acceptable to dip to **3:1** for non-essential.
- **Never:** light gray (#999) on white for body. Use #6B6B6B at lightest.
- **Headlines:** can dip lower contrast (3.5:1+) for stylistic effect — but never for body.
- **Links:** color or underline, not just color (accessibility).
- **Focus state:** visible focus ring, 2px offset, accent color.

See `color.md` for palette construction.

---

## Special Treatments

### Drop caps
- Use only in long-form articles, editorial spreads
- 3–4 lines tall, set in display face
- Indent the rest of the paragraph

### Pull quotes
- Display face, 1.5–2x body size
- Left-aligned, often with rule lines
- Sometimes quote marks in a much larger size (decorative)

### Numerals
- Use **tabular figures** (`font-variant-numeric: tabular-nums`) for tables, pricing, statistics
- Use **lining figures** (default in most fonts) for headlines and prose
- Old-style figures (with descenders) are a beautiful editorial choice — use consistently

### Hyphenation & justification
- Left-align body. **Never justify body text** — it creates ugly rivers.
- Use `hyphens: auto` sparingly; better to enable it for narrow columns, disable for wide ones
- Use `text-wrap: pretty` (modern CSS) when available — improves line breaks

### All-caps
- For kickers, labels, navigation, small UI elements
- Always positive tracking (+0.05em+)
- Never for body. Never for headlines over 24px (reads as shouting).

### Underlines
- Default browser underlines on links are ugly. Replace with custom underlines:
  - `text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 4px;`
- Or use a `border-bottom` on inline elements for more control

---

## Typography Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| `font-weight: 700` on every heading regardless of family | Use 600 for headings, 700 only for hero moments |
| Letter-spacing `0` on all-caps labels | Add `+0.05em to +0.12em` to all-caps |
| Default browser font stack (`-apple-system, sans-serif`) | Choose a face. Even Inter is a choice. |
| Two different type families from different schools | Stick to ONE family for display + text |
| Body text in a display serif | Use display serif for display only |
| Justified text in a narrow column | Left-align, ragged right |
| `font-size: 16px` hero headlines | Hero should be 60–160px |
| Heading set with `line-height: 1.5` (looks loose) | Tighten to 1.05–1.15 on display |
| Letter-spacing `-0.05em` on body text (cramped) | Use -0.02em max for body, more for display |
| Inline `style="font-size: ..."` everywhere | Define a scale in tokens, use them |
| Mixing px and rem inconsistently | Use rem everywhere (or use a token system) |
| Setting font-size on `<p>` manually | Let the base size + scale handle it |
| Italic body copy in a font with no italic (auto-faked) | Pick a face with a real italic |

---

## A Working CSS Setup

```css
:root {
  /* Type tokens */
  --font-display: 'GT Super', 'Tiempos', Georgia, serif;
  --font-text: 'Inter', -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;

  /* Scale (1.250) */
  --text-xs: 0.75rem;     /* 12px */
  --text-sm: 0.875rem;    /* 14px */
  --text-base: 1rem;      /* 16px */
  --text-lg: 1.25rem;     /* 20px */
  --text-xl: 1.5625rem;   /* 25px */
  --text-2xl: 1.953rem;   /* 31px */
  --text-3xl: 2.441rem;   /* 39px */
  --text-4xl: 3.052rem;   /* 49px */
  --text-5xl: 3.815rem;   /* 61px */
  --text-6xl: 4.768rem;   /* 76px */
  --text-7xl: 5.96rem;    /* 95px */

  /* Leading */
  --leading-tight: 1.05;
  --leading-snug: 1.2;
  --leading-normal: 1.5;
  --leading-loose: 1.65;

  /* Tracking */
  --tracking-tightest: -0.04em;
  --tracking-tight: -0.02em;
  --tracking-normal: 0;
  --tracking-wide: 0.05em;
  --tracking-widest: 0.12em;
}

body {
  font-family: var(--font-text);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--ink);
  background: var(--surface);
  font-feature-settings: 'kern' 1, 'liga' 1;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3 {
  font-family: var(--font-display);
  line-height: var(--leading-tight);
  letter-spacing: var(--tracking-tight);
  font-weight: 600;
}

h1 {
  font-size: clamp(3.5rem, 6vw + 1rem, 6rem);
}

h2 {
  font-size: clamp(2.25rem, 4vw, 3.5rem);
}

.kicker {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-widest);
  color: var(--ink-muted);
}

.measure {
  max-width: 65ch; /* reading measure */
}
```

---

## Loading Fonts

1. **Self-host** when possible (privacy, performance, no FOUT).
2. **Subset** to Latin (or relevant script). Don't load 9 weights of 9 fonts.
3. **Preload** the display face used above the fold.
4. **Use `font-display: swap`** to avoid invisible text.
5. **Variable fonts** when available — one file, full weight range.
6. **Fallback metrics** — set `size-adjust`, `ascent-override`, `descent-override` on fallback to minimize layout shift.

```html
<link rel="preload" href="/fonts/InterVariable.woff2" as="font" type="font/woff2" crossorigin>
```

```css
@font-face {
  font-family: 'Inter';
  src: url('/fonts/InterVariable.woff2') format('woff2-variations');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}
```
