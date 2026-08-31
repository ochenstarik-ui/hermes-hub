# Editorial Patterns — Pentagram, Bloomberg BW, NYT Mag, and friends

> A deep-dive into the editorial sub-styles. Read this when `aesthetics.md` §2 (Editorial / Magazine) is right for the project, but you need a specific reference direction. Each sub-style has concrete rules, typefaces, layouts, and references.

---

## How to use this file

`aesthetics.md` §2 says: **Editorial / Magazine** for publishing, journalism, premium content, manifestos, agency sites.

This file says: **which Pentagram cousin** to ship. Because "editorial" without specificity is a generic magazine page, not a designed one.

Decision rule:
1. **Is the project publishing, journalism, premium brand, content-heavy, or manifesto-style?** If no → wrong family, go back to `aesthetics.md`.
2. **Pick the sub-style** that matches the audience and tone.
3. **Commit to it.** Don't blend NYT Magazine's black/white with Bloomberg BW's color. Don't mix Pentagram's restraint with Apartamento's warmth.

---

## Sub-style comparison

| Sub-style | Mood | Type pairing | Color | Audience |
|---|---|---|---|---|
| **Pentagram (archive)** | Authoritative, restrained, considered | Serif display + sans body | Often monochrome | Brands, institutions, design-aware clients |
| **Bloomberg Businessweek** | Loud, dense, opinionated, graphic | Mixed sans/serif | Bright accent as punctuation | News readers, designers, intellectuals |
| **NYT Magazine** | Classic, literary, calm | Serif throughout | B/W minimal | Long-form readers, literary audience |
| **It's Nice That** | Contemporary, bright, friendly | Mixed sans + occasional serif | Multi-hue but restrained | Creative industry, design students |
| **Apartamento** | Warm, intimate, considered | Sans display + serif body | Warm tones, soft | Interior design, lifestyle, slow living |
| **The Gentlewoman** | Restrained, portrait-led | Sans display | Often monochrome | Fashion, design, considered culture |

When unsure → **Pentagram archive** — it's the safest editorial baseline.

---

## 1. Pentagram (archive work)

**Live reference:** [pentagram.com](https://pentagram.com)

### Identity
Pentagram is a partner-led studio where each partner has their own aesthetic voice, but the studio shares principles: **strong typography, asymmetric grids, real photography, considered whitespace, restrained color, no decoration.** Their archive work is the reference standard for editorial design.

### When to choose
- Institutional clients (museums, galleries, foundations)
- Brand systems for considered brands
- Editorial sites that want gravitas
- Anything where "designed by humans" is the message

### Palette
Pentagram work is mostly **monochrome** with one accent used sparingly:

```
--surface:         #FFFFFF
--surface-1:       #FAFAFA

--ink:             #1A1A1A
--ink-muted:       #6B6B6B
--ink-subtle:      #A0A0A0

--hairline:        #E5E5E5
--hairline-strong: #C7C7C7

--accent:          (varies by project; often red #C8281C or no accent)
```

### Typography
- **Serif display + sans body** is the dominant pairing
- Examples: GT Super / Tiempos for display + Söhne / Inter for body
- **Hero size:** massive — `clamp(4rem, 9vw, 9rem)` or larger
- **Tracking:** -0.03em to -0.05em on display
- **Line-height:** tight (1.0–1.1) on display
- **Body:** generous (1.55–1.65)

### Layout
- **Strong vertical rhythm.** Generous gutters.
- **Asymmetric grids.** Image bleeds off one edge, text column offset.
- **No decorative borders.** Hairlines only where they organize information.
- **Section numbers / folio numbers as design elements.**

### Signature patterns
- ✅ **Asymmetric hero with massive headline + small image.** Not centered, not balanced.
- ✅ **Section markers as design.** "§ 01 — On the work", "§ 02 — On the studio", etc.
- ✅ **Real photography** (or none — typography-only is also valid).
- ✅ **Image captions** in italic, often with photographer credit.
- ✅ **Long-form considered scrolling** — sections are big, scroll is intentional.
- ✅ **Colophon** — a page describing the typographic and technical choices.

### Hallmarks
- ✅ Display type sets the design
- ✅ Whitespace carries the design (not decoration)
- ✅ Strong asymmetry, never centered
- ✅ Section markers in mono / small caps
- ✅ One accent used <5% of pixels

### Anti-patterns to avoid
- ❌ SaaS-style 3-card row
- ❌ Decorative gradient backgrounds
- ❌ Stock photography
- ❌ Centered hero with two CTA buttons
- ❌ "Trusted by" logo bar
- ❌ Multi-color rainbow palette

---

## 2. Bloomberg Businessweek

**Live reference:** [bloomberg.com/businessweek](https://www.bloomberg.com/businessweek)

### Identity
Bloomberg BW is famous for its **distinctive covers** (since 2010 redesign by Richard Turley) and dense, opinionated editorial design. Mixed typefaces, bright accent colors used as punctuation, magazine-spread layouts, no fear of density or color. The early Bloomberg BW covers were especially brutalist-influenced.

### When to choose
- News / current affairs brands
- Editorial products with strong opinions
- Publications that want to be noticed
- Anything that needs editorial "edge"

### Palette
Bloomberg BW is unafraid of color. Pairs of saturated colors used as punctuation:

```
--surface:         #FFFFFF   /* or #F5F0E8 cream */
--ink:             #000000   /* true black */

--accent-red:      #FF0000
--accent-yellow:   #FFD700
--accent-blue:     #0033A0
--accent-green:    #00A651
```

Colors are used in **flat blocks** — not gradients. They mark sections, callouts, pull quotes, issue numbers.

### Typography
- **Mixed typefaces.** Bloomberg BW covers combine sans, serif, and mono often in one composition.
- Common pairings: **Akzidenz-Grotesk** + **Tiempos** + **Berkeley Mono**
- Free substitutes: **Inter** + **Fraunces** + **JetBrains Mono**
- **Hero size:** massive — covers often set type at 200pt+
- **Tracking:** varies wildly (Bloomberg BW uses both tight and wide tracking as a design move)

### Layout
- **Magazine spreads.** Two-page compositions that read as one design.
- **Asymmetric, dense.** Multiple columns, varied scale.
- **No whitespace fear** — but no whitespace waste either.
- **Section dividers as color blocks**, not hairlines.

### Signature patterns
- ✅ **Cover-as-hero.** Treat each section's opening like a magazine cover — massive type, big image (or solid color block), issue number, date, kicker.
- ✅ **Pull quotes at display size.** Set in display face, often with rule lines above and below.
- ✅ **Mixed sans/serif/mono in single compositions.** This is the signature.
- ✅ **Bright accent blocks** as design elements — full-bleed rectangles of color, not gradients.
- ✅ **Numbered issue markers**, datelines, "in this issue" panels.
- ✅ **Loud + quiet alternation.** Not constant noise. A few loud moments, many calm moments.

### Hallmarks
- ✅ Type mixing as a design move
- ✅ Color as punctuation (full blocks)
- ✅ Mag density with mag elegance
- ✅ Cover-style openings for sections
- ✅ Pull quotes at display scale

### Anti-patterns to avoid
- ❌ Generic SaaS feature presentation
- ❌ Centered everything
- ❌ Pastel colors (Bloomberg BW uses saturated)
- ❌ Gradients (Bloomberg BW uses flat color)
- ❌ Tailwind default aesthetic

---

## 3. NYT Magazine

**Live reference:** [nytimes.com/section/magazine](https://www.nytimes.com/section/magazine), [@nymag on Instagram](https://instagram.com/nymag)

### Identity
The NYT Magazine is the reference standard for literary editorial design. **Large serif typography, strong vertical rhythm, black/white minimal with one accent, issue / section markers as design, pull quotes, photography-led, masthead-style headers.**

### When to choose
- Long-form journalism
- Literary brands, publishing houses
- Premium editorial products
- Anything that wants to feel "literary" without being dusty

### Palette
```
--surface:         #FFFFFF   /* pure white, classic */
--ink:             #000000   /* true black */

--accent:          #C8281C   /* editorial red — used on kickers, section markers */
--accent-soft:     #FAE6E2

--rule-line:       #000000   /* often uses true black for rule lines */
```

NYT Magazine is overwhelmingly **black/white**. The red is punctuation, not background.

### Typography
- **Serif throughout.** NYT Magazine uses Cheltenham (custom) — substitutes:
  - **Charter** (free, similar character)
  - **GT Super** (paid, editorial)
  - **Tiempos** (paid, contemporary serif)
  - **Source Serif** or **Newsreader** (free)
- **Mono for kickers / metadata:** NYT Magazine uses a custom mono — substitute **JetBrains Mono** or **GT America Mono**.
- **Hero size:** massive — `clamp(4rem, 10vw, 10rem)`
- **Tracking:** -0.02em to -0.03em on display
- **Line-height:** tight on display (1.0), generous on body (1.6)
- **Drop caps:** 3–4 lines, in display face, on long-form articles.

### Layout
- **Strong vertical rhythm.** Generous gutters.
- **Measure (line length):** 60–75 characters for body.
- **Asymmetric grids:** image bleeds, text columns offset.
- **Section markers:** "THE WEEKEND", "THE LOOK", "THE STORY" in caps mono.
- **Footnotes / margin notes** where appropriate.

### Signature patterns
- ✅ **Masthead-style header.** Issue date, volume, section name in small caps mono.
- ✅ **Section dividers as text markers**, not decorative lines.
- ✅ **Drop caps on long-form articles.**
- ✅ **Pull quotes at display scale.** Set in display face, often with rule lines.
- ✅ **Photography-led design.** Cover and inside spreads are image-driven.
- ✅ **Captions in italic, smaller type**, often with photo credits.
- ✅ **One accent (red) used <5% of pixels.** Almost everything is black on white.

### Hallmarks
- ✅ Serif throughout (display + body in same family)
- ✅ Generous body line-height (1.6+)
- ✅ Strong vertical rhythm
- ✅ Section markers in mono, all-caps, wide tracking
- ✅ Drop caps on long-form
- ✅ Photography as primary visual

### Anti-patterns to avoid
- ❌ Sans-serif body
- ❌ SaaS-style feature presentation
- ❌ Generic stock photos
- ❌ Centered body text
- ❌ Justified body text (always left-aligned)
- ❌ Multi-color palette

---

## 4. It's Nice That

**Live reference:** [itsnicethat.com](https://www.itsnicethat.com)

### Identity
Contemporary editorial with bright accents. Mixed sans + occasional serif. Friendly, considered. The aesthetic of "design publication that respects the design industry" — informed, opinionated, generous.

### When to choose
- Design publications
- Creative industry marketing
- Award sites, festival sites
- Anything targeting design students and professionals

### Palette
```
--surface:         #FFFFFF
--ink:             #1A1A1A

--accent-coral:    #FF5C39
--accent-blue:     #0050FF
--accent-yellow:   #FFD23F
--accent-green:    #00C896
```

It's Nice That uses **bright but flat** accent colors. Each accent has meaning (different categories of content).

### Typography
- **Sans primary** (Inter, Söhne substitute) + **occasional serif** for editorial pull quotes
- Hero size: `clamp(2.5rem, 6vw, 5rem)`
- Tracking: -0.02em on display
- Body: 16–18px, line-height 1.55

### Layout
- Max-width 1200–1400px (wider than typical editorial)
- Asymmetric grids with mixed media
- Strong use of photography
- Article cards with cover images

### Signature patterns
- ✅ **Bright accent categories.** Each content type gets a color.
- ✅ **Hero with featured article** — large image + headline + meta.
- ✅ **Mixed sans + serif.** Use the serif for emphasis on key word in headline.
- ✅ **Photography-led.** Real photos, not stock.
- ✅ **Article cards** with hover effects (image lifts or shifts).
- ✅ **Generous whitespace** between dense moments.

### Hallmarks
- ✅ Multi-hue semantic accents
- ✅ Mixed typography (sans + serif)
- ✅ Editorial pull quotes
- ✅ Photography as primary visual
- ✅ Friendly but considered microcopy

### Anti-patterns to avoid
- ❌ Generic "3-card features" presentation
- ❌ Stock photography
- ❌ Centered hero with two CTA buttons
- ❌ Loud gradients
- ❌ Tailwind defaults

---

## 5. Apartamento

**Live reference:** [apartamentomagazine.com](https://www.apartamentomagazine.com)

### Identity
Interior design magazine with a warm, intimate, considered aesthetic. Photography-led. Soft warm tones. Long-form interviews. Restrained typography. The aesthetic of "magazine you keep on your coffee table."

### When to choose
- Lifestyle, hospitality, interior design
- Long-form interview-style content
- Brands with "slow" positioning
- Premium consumer with editorial feel

### Palette
```
--surface:         #FAF6F0   /* warm cream */
--surface-1:       #F4EFE6

--ink:             #2B2522   /* warm near-black */
--ink-muted:       #6B5E51
--ink-subtle:      #9C8E7E

--hairline:        #E5DDD0
--hairline-strong: #D4C9B6

--accent:          #8B3A2F   /* deep terracotta — used very sparingly */
--accent-soft:     #F2E2DC
```

Apartamento's palette is **all warm**. No cold tones anywhere.

### Typography
- **Sans display** (Söhne, Inter) + **serif body** (Tiempos, GT Super)
- Hero size: `clamp(2.5rem, 6vw, 5rem)` — calm, generous
- Tracking: -0.02em on display
- Line-height: 1.1 on display, 1.6 on body

### Layout
- Max-width 1100px (narrower than typical magazine)
- Photography-led spreads
- Long-form interview formatting
- Generous whitespace

### Signature patterns
- ✅ **Photography as primary design element.** Every spread is image-first.
- ✅ **Warm cream backgrounds** (never pure white).
- ✅ **Long-form interview structure** — Q&A format, generous line-height.
- ✅ **Restrained accent** (terracotta) used on section markers, never as background.
- ✅ **Sans display + serif body** — editorial influence.
- ✅ **Considered micro-copy** with personality.

### Hallmarks
- ✅ Warm palette throughout (no cold tones)
- ✅ Photography-led design
- ✅ Long-form interview formatting
- ✅ Sans display + serif body pairing
- ✅ Personal, intimate voice

### Anti-patterns to avoid
- ❌ Pure white background (breaks warmth)
- ❌ Cold accents (blue, green)
- ❌ SaaS-style feature presentation
- ❌ Stock photography
- ❌ Loud animations

---

## 6. The Gentlewoman

**Live reference:** [thegentlewoman.com](https://www.thegentlewoman.com)

### Identity
Restrained, portrait-led magazine. Sans display throughout. Often monochrome. Considered spacing. The aesthetic of "magazine about interesting people, designed quietly."

### When to choose
- Fashion, design, considered culture brands
- Premium lifestyle publications
- Anything where portraits are the content
- Restrained, premium positioning

### Palette
Often **pure monochrome**:
```
--surface:         #FFFFFF   /* or off-white #F5F2EC */
--ink:             #1A1A1A
--hairline:        #E5E5E5

--accent:          (rarely — often no accent, or single warm tone)
```

When there's an accent, it's often a single muted color (terracotta, deep red).

### Typography
- **Sans display throughout** (the magazine uses a custom sans — substitute Söhne, GT Walsheim, Inter)
- Hero size: `clamp(2.5rem, 5vw, 4.5rem)` — confident, restrained
- Tracking: -0.02em on display
- Body: 16px, line-height 1.55

### Layout
- Max-width 1100px
- Portrait-led spreads (large portraits dominate)
- Asymmetric grids with portrait as anchor
- Generous whitespace

### Signature patterns
- ✅ **Portrait as hero.** Each issue's cover and key spreads are dominated by a portrait.
- ✅ **Restrained typography.** Sans throughout, no display serif.
- ✅ **Generous whitespace** around portraits.
- ✅ **Issue number, date, "in this issue"** as design elements.
- ✅ **Long-form interviews** with thoughtful typography.
- ✅ **Monochrome or single-accent palette.**

### Hallmarks
- ✅ Sans display throughout (no serif)
- ✅ Portrait-led design
- ✅ Monochrome or single-accent palette
- ✅ Restrained, considered spacing
- ✅ Editorial interview formatting

### Anti-patterns to avoid
- ❌ Multi-color palette
- ❌ Sans-serif body (use a considered sans)
- ❌ Generic SaaS feature presentation
- ❌ Stock photography
- ❌ Decorative elements

---

## Decision tree

```
Editorial project?
├── Yes
│   ├── Institutional / authoritative / archival?
│   │   ├── Yes → Pentagram (archive)
│   │   └── No → continue
│   ├── News / current affairs / opinionated?
│   │   ├── Yes → Bloomberg Businessweek
│   │   └── No → continue
│   ├── Literary / long-form / journalism?
│   │   ├── Yes → NYT Magazine
│   │   └── No → continue
│   ├── Design publication / contemporary editorial?
│   │   ├── Yes → It's Nice That
│   │   └── No → continue
│   ├── Warm / intimate / interior / lifestyle?
│   │   ├── Yes → Apartamento
│   │   └── No → continue
│   └── Fashion / portrait-led / restrained?
│       └── Yes → The Gentlewoman
└── No → wrong family, return to aesthetics.md
```

---

## Hybrid rules

When forced to combine editorial sub-styles:

1. **Pick dominant 70/30.** Don't blend evenly.
2. **Share typography family.** NYT Magazine + Pentagram both use serif — easy. Bloomberg BW + It's Nice That both use mixed sans/serif — easy.
3. **Share accent philosophy.** Don't blend B/W with multi-color.
4. **Different sub-styles for different surfaces is fine.** Pentagram-style landing, NYT Magazine-style article reading. Share typography and tokens.

---

## What to read next

- For typography system setup → `typography.md`
- For color tokens → `color.md`
- For component patterns → `components.md`
- For motion → `motion.md`
- For anti-patterns → `anti-patterns.md`
- For final QA → `checklist.md`
