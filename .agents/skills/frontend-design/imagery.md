# Imagery & Icons — No Stock, No Emoji

> Pictures are where generated sites collapse. The AI default is: stock photo with a gradient overlay, emoji instead of icons, and blobs for "visual interest." All three are instant tells (`anti-patterns.md` §3, §7, §8, §10). This file is what to do instead — in order of preference.

---

## The Imagery Decision Tree

Before adding any image, ask in order:

1. **Does this need an image at all?** Most marketing pages are improved by removing images. Typography is the design (`SKILL.md` principle 2). A strong headline on generous whitespace beats a mediocre photo.
2. **Can it be a CSS/SVG composition?** Covers, mockups, product visuals, data — abstract compositions read as designed and cost kilobytes (`performance.md`).
3. **Can it be a real photo with real art direction?** Only if real photographs exist (client photos, product shots, documentary sources). Never invented stock.
4. **Nothing above works?** Then the section is the wrong section. Cut it.

The tell: if you're searching a stock site for "team collaborating laptop" — the image has no reason to exist.

---

## CSS/SVG Art Direction (the default)

Abstract compositions are the house style for generated UI: they always match the token system, they never look stock, and they ship in bytes. Build them from the same tokens as the page — same surface, ink, hairline, accent.

### The vocabulary

| Composition | Build | Use for |
|---|---|---|
| **Rules & columns** | 1px lines, `repeating-linear-gradient` | Architecture, editorial, "structure" |
| **Concentric circles** | Nested `border` circles, one accent ring | Sound, music, focus |
| **Halftone / dot grid** | `radial-gradient` repeated | Print heritage, texture |
| **Grid artifacts** | Visible column rules + one filled cell | Swiss, data, "system" |
| **Layered planes** | 2–3 offset rectangles, one in accent | Product surfaces, layers |
| **Chart as image** | Simple SVG bars/lines with mono labels | Metrics, proof |
| **Poster crop** | Big numeral or letter, cropped by overflow | Covers, features |

```css
/* Dot grid — pure CSS texture */
.art--halftone {
  aspect-ratio: 4 / 5;
  background-image: radial-gradient(var(--ink) 1px, transparent 1.2px);
  background-size: 14px 14px;
  /* fade it: one clean idea, not wallpaper */
  -webkit-mask-image: linear-gradient(#000 40%, transparent);
          mask-image: linear-gradient(#000 40%, transparent);
}

/* Concentric — one accent ring as the "subject" */
.art--rings {
  aspect-ratio: 1 / 1;
  border-radius: 50%;
  border: 1px solid var(--hairline);
  display: grid; place-items: center;
}
.art--rings::before {
  content: ''; width: 62%; height: 62%;
  border-radius: 50%;
  border: 1px solid var(--accent);
}
```

Rules:

- **One idea per composition.** Rules + circles + dots + gradient = mush. Pick one, execute precisely.
- Compositions live inside a defined box (`aspect-ratio`), like a print plate — not floating decor behind text.
- The accent gets one moment: one ring, one filled cell, one label. (`color.md` 5–10% rule still applies.)
- Mark decorative art `aria-hidden="true"` (`accessibility.md`); if it *carries* information, it's an `<svg>` with a `<title>` or adjacent text.
- Working examples: the cover plates in `examples/example-magazine.html`, the album covers in `examples/example-brutalist.html`, the CSS dashboard in `examples/example-saas.html`.

---

## If Photography Is Real

Photography is only an option when real photographs exist. Then direct it like a photo editor, not a stock buyer:

### The art direction brief (write it before choosing)

- **One light source, one lens, one palette.** Mixed light and mixed lenses read as assembled, not shot.
- **Documentary, not posed.** The workshop, not the handshake. Hands on work, not people pointing at whiteboards.
- **No smiling-person-with-laptop.** Ever. (`anti-patterns.md` §10.)
- **Crop with intent.** Full-bleed, hard edges, cropped off-grid — a brave crop is design; a centered subject is a placeholder.
- **Treatment is a system:** same ratio family, same caption style, same edge treatment across the page. Two ratios maximum.

### Sourcing, honestly

| Source | Verdict |
|---|---|
| Client/team photos (even phone-shot) | Best — real beats polished |
| Real product photography | Required for products |
| Public archives (museum/library, CC-licensed) | Great for editorial and history |
| UGC with permission | Good for lifestyle and community |
| Any stock site, any "similar images" | No |

### Treatment rules

- **No gradient overlays on text.** If text needs a scrim to be readable, the photo is wrong or the text is misplaced. (Scrim = gradient = `anti-patterns.md` §1's family.)
- Captions are design: mono or small italic, real information — who, where, when. "Image: ..." with a real fact, not "photo."
- Duotone/grayscale only as a system across all photos, using tokens.
- Grain/texture: once per page, subtle. (Also `aesthetics.md` §5.)

---

## Iconography

Icons are typography for concepts: one voice, measured precisely.

### The system

| Rule | Value |
|---|---|
| Sets | **Lucide**, **Phosphor**, **Tabler**, **Feather** — pick ONE per project |
| Stroke | 1.5px (2px at 24px+), `stroke-linecap="round"` or `square` — consistent |
| Sizes | 16px (inline), 20px (UI), 24px (feature) — one size per context |
| Color | `currentColor`, always — icons inherit ink/muted like text |
| Alignment | Optically centered; 16px icons align to the x-height of body text |
| In UI chrome | Icon + label for anything ambiguous; icon-only with `aria-label` |

### The correct way to ship an icon

```html
<!-- Icon + text label (default) -->
<a href="/docs" class="nav-link">
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24"
       fill="none" stroke="currentColor" stroke-width="1.5"
       stroke-linecap="round" stroke-linejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
  </svg>
  <span>Docs</span>
</a>

<!-- Icon-only button (needs a name) -->
<button aria-label="Close menu" class="icon-btn"> … </button>
```

- **Inline SVG, not icon fonts** (fonts break, shift, and announce garbage).
- Same set means same grid (24×24 viewBox), same stroke, same corner philosophy. Never mix Lucide with Font Awesome on one page.
- `aria-hidden="true"` on decorative icons; labels do the naming (`accessibility.md`).
- **Emoji are not icons.** In product UI: never. In content (a genuinely playful brand voice): maybe once, on purpose. (`anti-patterns.md` §3.)

---

## Avatars & Logo Bars

### Avatars

- **Initials, not mystery silhouettes.** Two letters in a circle using tokens beat every default placeholder.

```css
.avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: grid; place-items: center;
  background: var(--surface-sunken);
  color: var(--ink);
  font-size: var(--text-xs);
  font-weight: 500;
  letter-spacing: 0.02em;
}
```

- Real photos only if they're real people (testimonials: real quotes or no testimonials — `checklist.md` §Content).

### Logo bars ("trusted by")

- Only logos of **real, permissioned customers.** Invented logos for invented companies is the definition of `anti-patterns.md` §15 — lying.
- Treatment: monochrome at ~60% ink, hover restores full ink; uniform optical height (18–24px), real wordmarks, no fake " Inc.".
- No logo bar at all > a fake one. A single specific sentence ("Vercel's design team uses this weekly") beats twelve gray rectangles.

---

## Favicon & Social Image (the 10-minute craft pass)

Agents ship pages with no favicon and a blank social card — the two places everyone *will* look.

### Favicon

```html
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon.png" sizes="32x32"> <!-- fallback -->
<link rel="apple-touch-icon" href="/apple-touch-icon.png"> <!-- 180×180 -->
```

Design it like a poster at 16px: the mark's single element (one letter, one ring, one bar) in accent or ink on surface. Test at 16px — if unreadable, simplify.

### Open Graph / Twitter card

```html
<meta property="og:image" content="https://example.com/og/issue-14.png">
<meta name="twitter:card" content="summary_large_image">
```

- 1200×630, designed like a print cover: brand type, issue/product name, one accent moment, real metadata.
- It should look like the site — same face, same tokens. Not a screenshot of the hero, not a logo centered in gray.
- Zero-OG-image pages render as blank gray rectangles in every share. That's the first impression most visitors get.

---

## Imagery Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| Stock photo + gradient overlay + headline on top | CSS/SVG composition, or photo with real crop and real caption |
| Emoji as feature/status icons | One icon set, inline SVG, `currentColor` |
| Blob/mesh backgrounds "for depth" | Whitespace, hairlines, one composition per section |
| Mystery-man avatar placeholder | Initials in a token circle |
| Fake logo bar of invented companies | Real customers, or a specific sentence, or nothing |
| Icon fonts / emoji symbols for UI glyphs | Inline SVG from one set |
| Mixing icon styles (solid + outline, two sets) | One set, one stroke, one size per context |
| alt="image" / alt="IMG_2841" | Real alt text or `alt=""` when decorative |
| Photos in 5 aspect ratios across one page | One ratio family, treated as a system |
| No favicon, no og:image | Designed 16px mark + 1200×630 social cover |
| AI-generated "photo of our team" | No photography exists → composition or no image |

---

## Ship Gate

- [ ] Every image passed the decision tree (needed? composition? real photo? otherwise cut)
- [ ] Compositions: one idea each, built from tokens, `aria-hidden` or titled
- [ ] Photos (if any): real, one light, one crop system, captioned with facts
- [ ] Icons: one set, one stroke, `currentColor`, labeled or `aria-label`-ed
- [ ] Favicon designed and tested at 16px
- [ ] og:image designed like a cover, same type system
- [ ] No emoji in UI, no stock, no blobs — zero exceptions

See also: `anti-patterns.md` (§3, §7, §8, §10, §15, §16), `performance.md` §Images, `accessibility.md` §Images & Media, `content.md` (captions are copy).
