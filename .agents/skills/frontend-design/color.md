# Color — Tokens, Palettes, Restraint

> Color is punctuation, not wallpaper. One accent, many neutrals, used surgically.

---

## The Token System

Every project defines these tokens. No raw hex in components.

```css
:root {
  /* Surface (background) */
  --surface: ...;             /* primary background */
  --surface-elevated: ...;    /* cards, modals — slightly different */
  --surface-sunken: ...;      /* inputs, code blocks — slightly darker/lighter */

  /* Ink (text) */
  --ink: ...;                 /* primary text */
  --ink-muted: ...;           /* secondary text */
  --ink-subtle: ...;          /* tertiary, placeholders */

  /* Lines */
  --hairline: ...;            /* borders, dividers, rules */
  --hairline-strong: ...;     /* emphasized borders */

  /* Accent */
  --accent: ...;              /* the brand color */
  --accent-ink: ...;          /* text on accent surfaces */
  --accent-soft: ...;         /* tinted backgrounds for accent states */

  /* State */
  --success: ...;
  --warning: ...;
  --error: ...;
  --info: ...;
}
```

---

## Neutral Palette Library

Pick ONE neutral system. Then add an accent.

### Bright / Paper (Refined Minimal, Editorial, Soft)
```
--surface:        #FFFFFF   /* or #FAFAFA */
--surface-elevated: #FFFFFF
--surface-sunken: #F7F7F5

--ink:            #0A0A0A
--ink-muted:      #6B6B6B
--ink-subtle:     #A3A3A3

--hairline:       #EAEAEA
--hairline-strong:#D4D4D4
```

### Warm / Cream (Editorial, Soft)
```
--surface:        #FAF6F0
--surface-elevated: #FFFFFF
--surface-sunken: #F0EBE3

--ink:            #1A1714
--ink-muted:      #6B5E51
--ink-subtle:     #9C8E7E

--hairline:       #E5DDD0
--hairline-strong:#D4C9B6
```

### Deep / Ink (Technical, Brutalist, Editorial)
```
--surface:        #0E0E0E
--surface-elevated: #161616
--surface-sunken: #050505

--ink:            #F5F5F5
--ink-muted:      #A3A3A3
--ink-subtle:     #6B6B6B

--hairline:       #262626
--hairline-strong:#3D3D3D
```

### Cold / Stone (Swiss, Technical)
```
--surface:        #F4F4F2
--surface-elevated: #FFFFFF
--surface-sunken: #ECECEA

--ink:            #1A1A1A
--ink-muted:      #595959
--ink-subtle:     #8C8C8C

--hairline:       #DCDCD8
--hairline-strong:#C2C2BD
```

### True Black (Brutalist, Manifestos)
```
--surface:        #000000
--surface-elevated: #0A0A0A
--surface-sunken: #000000

--ink:            #FFFFFF
--ink-muted:      #B3B3B3
--ink-subtle:     #808080

--hairline:       #1F1F1F
--hairline-strong:#404040
```

---

## Accent Library

Pick ONE. Use it on 5–10% of pixels max. If you find yourself using it everywhere, it's not an accent — it's a brand color that needs a different neutral system.

### Refined Minimal accents
- **Linear-style purple:** `#5E6AD2` (with `#0A0A0A` ink)
- **Stripe indigo:** `#635BFF`
- **Mercury green:** `#1B4332`
- **Cron red-orange:** `#E0533D`
- **Vercel on white:** no accent — pure black ink IS the accent

### Editorial accents
- **Editorial red:** `#C8281C` or `#A91D1D`
- **Newspaper yellow:** `#E6B800` (used as mark, not fill)
- **Ink blue:** `#1B3A5C`

### Swiss accents
- **Müller-Brockmann red:** `#E63946` or `#D62828`
- **Electric blue:** `#0066FF`
- **Often no accent.** Pure monochrome.

### Brutalist accents
- **Hot pink:** `#FF3EA5`
- **Hazard yellow:** `#FFE600`
- **Toxic green:** `#39FF14`
- **Often used in block shapes**, not fine details

### Soft / Warm accents
- **Terracotta:** `#C65D3A`
- **Sage:** `#7A8471`
- **Dusty blue:** `#5C7A8A`
- **Mustard:** `#C99632`
- **Plum:** `#6B3D5C`

### Technical accents
- **Terminal green:** `#00FF66` or `#00CC66` (softer)
- **Amber:** `#FFB000`
- **Cyan:** `#00C2FF`
- **Hot pink (Vercel-style):** `#FF0080`

### Playful accents
- **Multi-hue palette** — pick 3–4 working together:
  - Coral `#FF6B6B` + Mustard `#FFC857` + Teal `#3DCCC7` + Plum `#5B5F97`
  - Or simpler 2-color: Lime `#C5E063` + Deep Navy `#1A1A40`

---

## How to Use the Accent

### The 5–10% rule
If the accent fills more than 10% of the page, it's no longer an accent. It's a brand background. Pick a different neutral system or reduce accent usage.

### Where accents go
- ✅ Primary CTA button (one per page)
- ✅ Active nav item, current page marker
- ✅ Links (or use ink color with underline)
- ✅ Focus rings
- ✅ Key data point in a statistic block
- ✅ A small mark (a dot, a bar, a single character)
- ✅ Selected state in a list
- ✅ Logo

### Where accents DON'T go
- ❌ Hero background
- ❌ Section backgrounds (full-bleed tints)
- ❌ Every card border
- ❌ Every icon
- ❌ Multiple CTA buttons on the same page (pick the one that matters)
- ❌ Body text (links are the exception)
- ❌ Drop shadows (use ink, not accent)
- ❌ Every heading

---

## Contrast (WCAG)

| Use | Min ratio | Aim for |
|---|---|---|
| Body text | 4.5:1 (AA) | 7:1 (AAA) |
| Large text (18px+ or 14px bold+) | 3:1 (AA) | 4.5:1+ |
| UI components, icons | 3:1 | 4.5:1+ |
| Non-essential decorative | none | — |
| Focus rings | 3:1 vs adjacent | visible |

**Tools:** Stark (Figma plugin), WebAIM Contrast Checker, Polypane.

**Rule of thumb:**
- Pure black `#000` on pure white `#FFF` = 21:1
- `#0A0A0A` on `#FFFFFF` = 19.4:1
- `#6B6B6B` on `#FFFFFF` = 5.7:1 (acceptable for secondary text)
- `#A3A3A3` on `#FFFFFF` = 2.8:1 (only for placeholders, never for real text)
- `#5E6AD2` on `#FFFFFF` = 5.1:1 (acceptable as text or UI)

---

## Dark Mode

Dark mode is not "invert the colors." Build it intentionally.

### Principles
- **Don't use pure black `#000`** for surfaces. It creates harsh contrast against text. Use `#0E0E0E` or `#121212` — there's a reason Material Design picked these.
- **Don't use pure white `#FFF`** for text. Soften to `#F5F5F5` or `#EDEDED`.
- **Reduce contrast slightly** — text doesn't need to be 21:1 on dark. Aim for 12:1+ (more comfortable).
- **Accents usually brighten in dark mode.** A `#5E6AD2` purple becomes `#7B85E6` or `#8B95FF`.
- **Shadows become subtle borders or glows.** Dark UIs rarely use shadows; they use hairlines and elevation via lighter surfaces.

### Token approach
```css
:root {
  /* Light */
  --surface: #FFFFFF;
  --ink: #0A0A0A;
  /* ... */
}

[data-theme="dark"] {
  --surface: #0E0E0E;
  --ink: #F5F5F5;
  /* Don't redefine everything — only invert what needs inverting */
}
```

### Dark mode anti-patterns
- ❌ Pure black `#000` background (harsh, increases eye strain)
- ❌ Pure white `#FFF` text (vibrates against dark backgrounds)
- ❌ Same accent as light mode (often too dark to read)
- ❌ Drop shadows that were already wrong in light mode (now invisible)
- ❌ Inverting images with CSS `filter: invert()` (breaks photos)

---

## Gradients

**Default:** don't use them.

### When gradients ARE appropriate
- Hero text on dark backgrounds (subtle, low-contrast, mostly for atmosphere)
- Loading states / skeleton screens
- Data visualization (color scales)
- Photo overlays (dark gradient over image for legibility)

### When gradients are NOT appropriate
- ❌ Hero backgrounds (the #1 AI slop signal)
- ❌ CTA buttons
- ❌ Section dividers
- ❌ "Mesh gradient" backgrounds
- ❌ Animated gradient backgrounds
- ❌ Purple → pink → orange "sunset" effects
- ❌ Multi-stop gradients on text

### If you must use one
```css
/* Subtle, dark, for atmosphere only */
background: linear-gradient(
  to bottom,
  rgba(0, 0, 0, 0) 0%,
  rgba(0, 0, 0, 0.4) 100%
);

/* Image overlay */
background: linear-gradient(
  180deg,
  rgba(0, 0, 0, 0.2) 0%,
  rgba(0, 0, 0, 0.8) 100%
);
```

Avoid: `linear-gradient(135deg, #667eea 0%, #764ba2 100%)` and all its cousins.

---

## Color Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| `#667eea → #764ba2` purple gradient hero | White background, ink-black headline |
| Multiple accent colors competing | One accent, used 5–10% |
| `#999` gray for body text | Use a tested muted ink (`#6B6B6B`+) |
| Random hex everywhere (`#3B82F6` next to `#1D4ED8`) | Token system, semantic names |
| Color-coded everything (red/yellow/green for non-state things) | Restraint. State colors for state only. |
| Hard-coded brand colors in components | Use `--accent` token |
| Inverting colors for dark mode | Re-tune the palette, don't invert |
| Tint backgrounds behind every paragraph | White space, not tinted space |
| Box-shadows in accent color | Ink-colored shadows, or no shadows |
| Stock-photo color overlays | Let photos speak, use overlays only for legibility |
| 4 brand colors in the logo, used equally | One brand color + a system of neutrals |
