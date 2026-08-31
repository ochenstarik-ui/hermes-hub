# Brutalist Patterns — Bandcamp, Working Format, early Bloomberg Businessweek

> A deep-dive into brutalist and raw sub-styles. Read this when `aesthetics.md` §4 (Brutalist / Raw) is right for the project, but you need a specific reference direction. Each sub-style has concrete rules, typography, layouts, and references.

---

## How to use this file

`aesthetics.md` §4 says: **Brutalist / Raw** for music, fashion, streetwear, art, counterculture, alternative media, edgy tech.

This file says: **which brutalist cousin** to ship. Because "brutalism" without specificity is unstyled HTML, not designed brutalism. The principle: **brutalism is a choice, not a lack of effort.**

Decision rule:
1. **Is the project music, fashion, art, counterculture, edgy tech, or alternative media?** If no → wrong family, go back to `aesthetics.md`.
2. **Pick the sub-style** that matches the audience and tone.
3. **Commit to it.** The sub-style is the design system, not a decoration.

---

## Sub-style comparison

| Sub-style | Mood | Type | Color | Audience |
|---|---|---|---|---|
| **Bandcamp** | Functional raw, album-archive | Mixed sans + mono | Mostly monochrome with album art | Music listeners, musicians, indie labels |
| **Working Format** | Editorial-influenced raw, considered | Sans display, restrained | B/W with bold accent | Music industry, fashion editorial |
| **Bloomberg BW covers (2010–2015)** | Loud, dense, graphic, opinionated | Mixed sans/serif/mono | Flat saturated blocks | News readers, designers, intellectuals |
| **Brutalist Websites gallery** | Pure HTML aesthetic, geometric | Often default system | Often no color | Designers studying history, art students |
| **Slam Jam / Italian fashion** | Loud typography, mixed media | Often condensed display | Black + one bold accent | Fashion, streetwear, art |

When unsure → **Working Format**. It's the safest brutalist baseline for "considered raw."

---

## The brutalist principle (read first)

Before choosing a sub-style, internalize the principle:

> **Brutalism is a choice, not a lack of effort.**

True brutalism has:
- ✅ **Strong typography decisions** (often louder, not quieter)
- ✅ **Considered asymmetry** (deliberately off, not careless)
- ✅ **One or two moments of polish** inside the rawness (a beautiful spread, a perfect composition)
- ✅ **Loud + quiet alternation** (not constant noise)
- ✅ **Self-aware** (the roughness is a *statement*, not an accident)

False brutalism has:
- ❌ Default system fonts without choice
- ❌ Random colors with no logic
- ❌ Sloppy where sloppiness isn't the point
- ❌ No considered moments — just noise throughout
- ❌ Inaccessible by design (low contrast, missing alt text)

**If your brutalism has no deliberate moments, it's not brutalism — it's unfinished.** Add at least one perfect composition per page.

---

## 1. Bandcamp

**Live reference:** [bandcamp.com](https://bandcamp.com)

### Identity
Functional, raw, archive-first. Bandcamp's design treats each album as an object. The interface gets out of the way — the album art and metadata carry the design. Strong typography, hairline rules, considered density.

### When to choose
- Music platforms, audio tools
- Archives, libraries, databases
- Anything where *content objects* are the focus
- Indie, considered, low-decoration

### Palette
```
--surface:         #FFFFFF   /* or #1A1A1A for dark mode */
--ink:             #1A1A1A   /* near-black on light, white on dark */

--hairline:        #E5E5E5   /* on light */
--hairline-strong: #C7C7C7

--accent:          #629AA9   /* Bandcamp teal — used sparingly */
--accent-soft:     #E0EEF1
```

The teal is used on tags, links, and active states. Most of the design is monochrome.

### Typography
- **ITC Avant Garde Gothic** (paid, the original Bandcamp face) — substitute **Inter** or **Söhne**
- Sometimes **Verdana** for body (Bandcamp's signature body choice) — substitute **Source Sans** or **Inter**
- Mono for metadata: **IBM Plex Mono** or **JetBrains Mono**
- Hero size: `clamp(2rem, 4vw, 3rem)` — calm, not dramatic
- Tracking: 0 or -0.01em (Bandcamp doesn't track tight aggressively)
- Line-height: 1.4 on body

### Layout
- **Dense, archive-first.** Lists are long, info is packed.
- **Generous use of metadata visible.** Track count, runtime, date, label, tags.
- **Asymmetric grids** for editorial features.
- **Strong use of hairlines** to organize dense info.

### Signature patterns
- ✅ **Album-art-as-anchor.** Each item is dominated by cover art + minimal metadata.
- ✅ **Dense list views.** Long lists of items, hairline-separated.
- ✅ **Visible metadata.** Tags, dates, runtimes — all visible, not hidden.
- ✅ **Strong typography hierarchy** through size, not weight.
- ✅ **Player UI** as a design element (the bottom player is part of the page).
- ✅ **Tag system** with semantic color (each tag = teal accent).

### Hallmarks
- ✅ Dense, archive-first
- ✅ Metadata visible and considered
- ✅ Hairline rules for organization
- ✅ Album art / content objects as primary visual
- ✅ Restrained accent (teal)

### Anti-patterns to avoid
- ❌ Loud gradients
- ❌ Heavy drop shadows
- ❌ Decorative illustrations
- ❌ Generic "3-card features"
- ❌ Centering everything

---

## 2. Working Format

**Live reference:** [workingformat.com](https://www.workingformat.com)

### Identity
Music industry design studio with editorial-influenced raw aesthetic. Strong typography, black/white with bold accent, asymmetric layouts, considered spacing. Working Format treats each project as a magazine spread — image + text + structure, designed quietly.

### When to choose
- Music industry / record labels
- Editorial projects with raw feel
- Studios that want to be "considered but not corporate"
- Anything targeting designers, musicians, fashion people

### Palette
```
--surface:         #FFFFFF
--ink:             #000000   /* true black */

--accent:          #FF0000   /* bold red — used as punctuation */
--accent-soft:     #FFE5E5
```

Working Format often uses **pure black + white + one bold accent** (often red or hot pink). High contrast is mandatory.

### Typography
- **Sans display throughout** (Inter, Söhne substitute)
- **Mono for metadata** (JetBrains Mono, IBM Plex Mono)
- Hero size: `clamp(3rem, 7vw, 6rem)` — confident, often large
- Tracking: -0.03em to -0.04em on display
- Line-height: 1.0 to 1.05 on display (tight)

### Layout
- Max-width 1280px
- **Asymmetric, considered.** Image bleeds, text columns offset.
- **Project spreads** treated like magazine layouts.
- **Section markers** in mono, all-caps, wide tracking.

### Signature patterns
- ✅ **Project spread as primary design.** Each case is a magazine-style spread.
- ✅ **Bold typography set tight.** Headlines at large size, very tight leading.
- ✅ **High contrast** (true black on pure white).
- ✅ **One bold accent** used as a punctuation mark, not as background.
- ✅ **Asymmetric grids** with deliberate imbalance.
- ✅ **Mono metadata** (project name, year, type) in caps, wide tracking.

### Hallmarks
- ✅ Pure black + white + one accent
- ✅ Tight display type, often large
- ✅ Asymmetric magazine-spread layouts
- ✅ Mono metadata in caps
- ✅ Image + text composition as design

### Anti-patterns to avoid
- ❌ Pastel colors
- ❌ Gradients
- ❌ Decorative borders
- ❌ Generic SaaS feature presentation
- ❌ Centering everything

---

## 3. Bloomberg Businessweek covers (2010–2015)

**Live reference:** Bloomberg Businessweek archive

### Identity
The Bloomberg BW covers under Richard Turley (2010–2015) became a reference for editorial brutalism: **loud, dense, graphic, opinionated.** Mixed typefaces (sans, serif, mono) in single compositions. Flat color blocks. Massive type. No fear of density or color.

This is a specific subset of the broader Bloomberg BW aesthetic covered in `editorial-patterns.md` — the cover work specifically.

### When to choose
- News / current affairs brands with strong opinions
- Editorial products that want to be noticed
- Magazine covers, posters, hero sections
- Anything that needs editorial "edge"

### Palette
Bloomberg BW covers used **flat color blocks** as design elements:
```
--surface:         #FFFFFF   /* or black, or saturated color */

--accent-red:      #FF0000
--accent-yellow:   #FFD700
--accent-blue:     #0033A0
--accent-green:    #00A651
--accent-magenta:  #FF0080
```

These are used as **full-block backgrounds** or as accent rectangles — never as gradients.

### Typography
- **Mixed typefaces** in single compositions (this is the signature)
- Sans: Akzidenz-Grotesk, Inter substitute
- Serif: Tiempos, GT Super substitute
- Mono: Berkeley Mono, JetBrains Mono substitute
- Hero size: massive — 200pt+ on covers
- Tracking: varies wildly (Bloomberg BW uses both tight and wide as a design move)

### Layout
- **Magazine covers** as primary composition
- **Mixed scale** — multiple type sizes on one spread
- **No whitespace fear** — covers are dense
- **Color blocks** as compositional elements

### Signature patterns
- ✅ **Cover as hero.** Each section opening is a magazine cover — massive type, big image (or solid color), issue number, kicker.
- ✅ **Mixed typefaces in one composition.** Sans + serif + mono often overlap or sit together.
- ✅ **Flat color blocks** as design elements — full-bleed rectangles.
- ✅ **Issue markers**, datelines, "in this issue" panels.
- ✅ **Loud + quiet alternation.** Some spreads are quiet, others are loud.
- ✅ **Pull quotes at display scale.**

### Hallmarks
- ✅ Type mixing as a design move (not as indecision)
- ✅ Flat color blocks (not gradients)
- ✅ Cover-style compositions
- ✅ Magazine density with considered elegance
- ✅ Loud + quiet alternation

### Anti-patterns to avoid
- ❌ Generic SaaS feature presentation
- ❌ Centered everything
- ❌ Pastels (Bloomberg BW uses saturated)
- ❌ Gradients (flat color blocks only)
- ❌ Default Tailwind aesthetic

---

## 4. Brutalist Websites (gallery inspiration)

**Live reference:** [brutalistwebsites.com](https://brutalistwebsites.com)

### Identity
A curated gallery of websites that embrace raw, unstyled-feeling design — but each is a deliberate choice. The aesthetic varies wildly, but the unifying principle is **honest materials, visible structure, anti-decoration.**

### When to choose
- Art projects, experimental sites
- Counterculture, alternative media
- Anything that wants to feel "honest" or "raw"
- Design student / academic projects

### Patterns common across the gallery

**Typography**
- ✅ **Default system fonts** are sometimes used as a *statement* (Helvetica, Arial, Times)
- ✅ **Custom condensed or display fonts** for impact moments
- ✅ **Mono for technical / metadata content**
- ✅ **Massive scale contrasts** — 12pt next to 200pt

**Color**
- ✅ **Pure white, pure black, or one crude color** (lime, hot pink, hazard yellow)
- ✅ **High contrast mandatory**
- ✅ **No gradients.** Flat blocks only.

**Layout**
- ✅ **Visible grid artifacts** (alignment deliberately off by 1px)
- ✅ **Tables as layout** (sometimes)
- ✅ **Underlined links in default browser blue**
- ✅ **Image crops unexpected**
- ✅ **Marquee / scrolling text** used surgically
- ✅ **Negative space as confrontation** — emptiness used aggressively

**Detail**
- ✅ **HTML validity** is respected (semantic markup even when raw-looking)
- ✅ **Keyboard navigation** still works (raw ≠ broken)
- ✅ **Self-aware** — the roughness is a *choice*

### Signature patterns
- ✅ **System fonts used as statement** ("Helvetica, because Helvetica").
- ✅ **Massive headline next to small body** — extreme scale contrast.
- ✅ **Underlined links** in default browser blue (no custom underline).
- ✅ **Image at unexpected crops** — not centered, not balanced.
- ✅ **Marquee text** (very slow, used surgically).
- ✅ **Visible HTML structure** (sometimes borders, debug info).

### Hallmarks
- ✅ Self-aware rawness
- ✅ Anti-decoration
- ✅ High contrast
- ✅ Extreme scale contrast
- ✅ Default system fonts (sometimes)

### Anti-patterns to avoid
- ❌ Calling it "brutalist" but shipping unstyled HTML — that's not brutalism, that's unfinished.
- ❌ Random colors with no logic.
- ❌ Sloppy where sloppiness isn't the point.
- ❌ **Inaccessible by design** — low contrast, missing alt text, no keyboard nav. Brutalism ≠ broken.
- ❌ Loud throughout — there must be quiet moments too.

---

## 5. Slam Jam / Italian fashion editorial

**Live reference:** [slamjam.com](https://www.slamjam.com), [ssense.com editorial](https://www.ssense.com)

### Identity
Loud typography, mixed media, fashion-led. Often condensed display type, bold sans, black + one accent. Image-led with strong typographic overlays. The aesthetic of "fashion editorial that wants to be noticed."

### When to choose
- Fashion, streetwear, art
- Editorial commerce (high-end)
- Anything targeting fashion-literate audience
- Counterculture with premium positioning

### Palette
```
--surface:         #FFFFFF   /* or #0A0A0A for dark */
--ink:             #000000   /* true black */

--accent:          #FF0080   /* hot pink — fashion signature */
--accent-soft:     #FFE0F0

--accent-secondary: #FFD700   /* sometimes yellow, lime, electric blue */
```

Slam Jam often uses **black + hot pink + one secondary** (yellow or electric blue). High contrast mandatory.

### Typography
- **Condensed display** (Druk, Aktiv Grotesk Black, or substitute via free condensed fonts)
- **Sans body** (Inter, Söhne substitute)
- **Mono for technical content** (JetBrains Mono)
- Hero size: massive — `clamp(4rem, 10vw, 9rem)` or larger
- Tracking: -0.02em to -0.04em on display
- Line-height: 1.0 on display

### Layout
- Max-width 1280px (sometimes wider, full-bleed)
- **Image-led.** Photography dominates.
- **Typographic overlays** on images (text set directly on photo, often with subtle contrast adjustment).
- **Asymmetric grids.** Deliberate imbalance.

### Signature patterns
- ✅ **Image + type composition.** Text set directly on photos, often white or accent color.
- ✅ **Massive condensed display.** Narrow, tall, loud.
- ✅ **Black + one bold accent** (often hot pink or yellow).
- ✅ **Asymmetric, full-bleed.**
- ✅ **Marquee or scrolling text** for editorial moments.
- ✅ **Strong image crops** — not safe, not centered.

### Hallmarks
- ✅ Condensed display type, often massive
- ✅ Image + type overlay
- ✅ Black + one bold accent
- ✅ High contrast
- ✅ Editorial fashion voice

### Anti-patterns to avoid
- ❌ Pastels
- ❌ Gradients
- ❌ Generic SaaS feature presentation
- ❌ Tailwind default aesthetic
- ❌ Safe image crops

---

## Decision tree

```
Brutalist / raw project?
├── Yes
│   ├── Music platform / archive / functional raw?
│   │   ├── Yes → Bandcamp
│   │   └── No → continue
│   ├── Music industry / fashion editorial / considered raw?
│   │   ├── Yes → Working Format
│   │   └── No → continue
│   ├── News / current affairs / loud editorial?
│   │   ├── Yes → Bloomberg BW covers (2010–2015)
│   │   └── No → continue
│   ├── Art / experimental / pure HTML aesthetic?
│   │   ├── Yes → Brutalist Websites gallery
│   │   └── No → continue
│   └── Fashion / streetwear / loud editorial commerce?
│       └── Yes → Slam Jam / Italian fashion
└── No → wrong family, return to aesthetics.md
```

---

## Hybrid rules

When combining brutalist sub-styles:

1. **Pick dominant 70/30.** Don't blend evenly.
2. **Share color philosophy.** Don't blend monochrome with multi-accent.
3. **Share type philosophy.** Don't blend Bandcamp's Verdana-style with Bloomberg BW's mixed typefaces (unless intentional).
4. **One perfect moment per page.** Even in the rawness, have one composition that's polished — that's the design.

---

## Accessibility in brutalism

Critical: brutalism ≠ broken.

Even when shipping raw-feeling design, you MUST:

- ✅ **Maintain WCAG AA contrast** (4.5:1 for body text). Pure black on pure white is fine (21:1).
- ✅ **Provide alt text** for all meaningful images. Empty `alt=""` for decorative.
- ✅ **Respect keyboard navigation.** Tab, Enter, Escape must work.
- ✅ **Honor `prefers-reduced-motion`**. Even brutalist motion should be reducible.
- ✅ **Use semantic HTML.** Even when it looks raw.
- ✅ **Provide skip-to-content** links on long pages.

If your brutalism is inaccessible, it's not brutalism — it's unfinished. Period.

---

## What to read next

- For typography setup → `typography.md`
- For color → `color.md`
- For components → `components.md`
- For motion → `motion.md`
- For anti-patterns → `anti-patterns.md`
- For final QA → `checklist.md`
