# Aesthetics — Style Direction Library

> Read this at the start of every project. Pick ONE direction. Hold the line. Mixing styles = slop.

---

## How to Choose

Answer these three questions in order. The answer drives the pick.

1. **Who is the primary user?** (CTO vs. designer vs. consumer vs. journalist)
2. **What is the emotional job?** (Trust, desire, curiosity, delight, urgency)
3. **What would a senior designer at [relevant studio] do?** (Don't pick a studio — pick a *kind* of decision-making.)

If still unsure → **Refined Minimal**.

---

## 1. Refined Minimal

**For:** SaaS dashboards, fintech, dev tools, B2B products, professional services.

**Reference:** Linear, Stripe, Vercel, Arc browser, Cron, Mercury bank, Pitch, Height, Notion (settings), Sublime.

**Vibe:** Quiet confidence. The interface gets out of the way. Everything you see was decided.

### Typography
- **Display:** Söhne, Inter Display, GT America, Söhne Breit, ABC Diatype Mono (for headings)
- **Text:** Inter, IBM Plex Sans, Söhne, Geist
- **Pairs that work:** Söhne Mono + Söhne, Inter Display + Inter, GT America + GT America Mono
- **Hero size:** `clamp(3.5rem, 7vw, 6rem)` for primary H1
- **Line height:** tight on display (1.05–1.15), normal on body (1.5–1.65)

### Color
- **Surface:** Pure white (#FFFFFF) or off-white (#FAFAFA / #F7F7F5)
- **Ink:** Near-black (#0A0A0A), not pure black
- **Muted:** #6B6B6B / #8A8A8A
- **Hairline:** #E5E5E5 / #EDEDED
- **Accent:** ONE — saturated, often a desaturated jewel tone. Examples: Linear purple (#5E6AD2), Stripe indigo, Vercel black-on-white, Mercury deep green (#1B4332). Used on links, one CTA per page, focus rings.

### Layout
- 12-column grid, max-width 1200–1280px
- Generous side padding (px-6 mobile, px-12 desktop)
- Sections separated by **whitespace**, not dividers
- Hero is asymmetric — headline left-aligned, supporting element (image, product UI) on the right at large sizes, stacked on mobile
- Tables and data dense? Use compact spacing, hairline borders, monospace numbers

### Hallmarks
- No background colors on hero (or extremely subtle gradient-to-paper)
- Buttons are crisp rectangles or 6px radius — not pills
- Icons are 16px or 20px, single-weight stroke
- Focus rings are precise (2px offset, not blurry glows)
- Numbers are monospace (alignment matters)
- Empty states have personality but restraint

### Hallmarks to avoid
- ❌ Adding background tint "to make it pop"
- ❌ Centered everything
- ❌ Drop shadows on cards (use hairlines or nothing)
- ❌ Gradient hero backgrounds

---

## 2. Editorial / Magazine

**For:** Publishing, journalism, premium content, books, high-end consumer brands, manifestos, agency sites.

**Reference:** NYT Magazine, Bloomberg Businessweek, It's Nice That, Wallpaper*, Apartamento, The Gentlewoman, Magazine N°, Pin–Up, Cabana, Courier (studio), Olympia (NYT).

**Vibe:** Considered. Authorial. The page is a page, the headline is a headline, the photo is a photo. Long-form and confident.

### Typography
- **Display:** A serif with character. Tiempos Headline, Lyon, Söhne Serif, GT Sectra, Domaine Display, Canela, Playfair Display (used sparingly), GT Super, Editorial New, Reckless
- **Text:** Same serif at smaller sizes, or a paired humanist sans (Söhne, GT America)
- **Mono (for kickers/byline):** IBM Plex Mono, JetBrains Mono, GT America Mono
- **Hero size:** Massive. `clamp(4rem, 9vw, 9rem)` or larger. Set tight (line-height 0.95–1.05).
- **Drop caps** OK on long-form articles, sparingly.

### Color
- **Surface:** Warm off-white (#FAF7F2, #F4F1EB) or deep editorial black (#0E0E0E)
- **Ink:** True black (#000) on cream, warm white (#F5F0E8) on black
- **Accent:** Editorial red (#C8281C) or a single ink color. Often used on pull-quotes, kickers, section markers.
- **Rule lines:** 1px hairlines in muted ink.

### Layout
- Strong vertical rhythm. Generous gutters.
- Use a measure (line length) of 60–75 characters for body
- Asymmetric grids: image bleeds off one edge, text column offset
- Pull quotes: large, set in display face, often with rule lines above/below
- Section numbers / folio numbers as design elements
- Footnotes / margin notes where appropriate

### Hallmarks
- Image-led. Photography is the design.
- Captions in smaller, often italic, type
- Issue / volume / date markers in masthead style
- Long-form scroll is encouraged — reading time, chapter markers
- Treat the page as a magazine spread

### Hallmarks to avoid
- ❌ SaaS-style "3 features in a row" sections — use full-bleed spreads instead
- ❌ Generic sans-serif throughout — bring the serif
- ❌ Centered body text — left-aligned, ragged right
- ❌ Stock photography with overlaid gradient

---

## 3. Swiss / International Typographic

**For:** Galleries, museums, archives, design studios, manifestos, annual reports, anything where information is the design.

**Reference:** Müller-Brockmann, Vignelli, Pentagram (archive work), Bureau Mirko Borsche, Studio Dumbar, Werkplaats Typografie, HfG Karlsruhe output, MoMA design.

**Vibe:** The grid is the design. Typography is precise. Information architecture = visual architecture.

### Typography
- **Display & Text:** One neutral grotesque used ruthlessly. Akzidenz-Grotesk, Helvetica Now, Söhne, Neue Haas Grotesk, GT America, Inter, ABC Diatype
- **Mono:** Same family in mono variant, or IBM Plex Mono for tabular data
- **Hero size:** Often smaller than expected. The Swiss move is restraint. `clamp(2.5rem, 5vw, 4.5rem)`. Big headlines feel loud here.
- **Type as image:** large numerals, dates, indices as visual anchors

### Color
- **Surface:** White or black. Nothing in between.
- **Ink:** Pure black or pure white
- **Accent:** Used very rarely. A red, a fluorescent, an electric blue — as a single punctuation mark.
- **Often NO accent.** Pure monochrome is a valid Swiss choice.

### Layout
- Strict modular grid. 12-col or 6-col. Visible or invisible.
- Left-aligned everything. No centering.
- Numbered sections. Folio numbers. Indices.
- Lots of metadata shown: dates, locations, dimensions, edition numbers
- Diagrams and tables treated as typography, not decoration

### Hallmarks
- Captions and labels are part of the design (often small, mono)
- Information density is high — whitespace used as separator, not filler
- Manifestos / mission statements set large, no decoration
- Photographic imagery is documentary, full-bleed, unretouched

### Hallmarks to avoid
- ❌ Decorative elements — there are none, that's the point
- ❌ Multiple fonts
- ❌ Centered headlines
- ❌ "Friendly" rounded corners

---

## 4. Brutalist / Raw

**For:** Music, fashion, streetwear, art, counterculture, alternative media, edgy tech, "we're not like other brands."

**Reference:** Bandcamp, Working Format, Bloomberg Businessweek (early 2010s), Acne Studios (early), Balenciaga (creative pages), Slam Jam, Internet-Troll aesthetic done well, Bottega (web), SSENSE editorial, Brutalist Websites (gallery), Yung Lean / Drain Gang visual world.

**Vibe:** Rejection of polish. Anti-design that is itself designed. Raw HTML energy, but precise.

### Typography
- **Display:** Anything goes — Helvetica (the original sin), Times New Roman used ironically, monospace terminals, custom condensed faces
- **Text:** Often same family throughout, or a chaotic mix that's clearly intentional
- **Hero size:** Either massive and crude OR tiny and clinical — the contrast IS the design
- **Use of system fonts** (`Helvetica, Arial, sans-serif`) is OK if it's a statement. Default browser styles can be part of the look.

### Color
- **Surface:** Pure white, pure black, or one crude color (lime, hot pink, hazard yellow)
- **Accent:** Loud. Used liberally but in block shapes.
- **High contrast** is mandatory. Anti-design ≠ low contrast.

### Layout
- Visible grid artifacts (alignment is sometimes deliberately off by 1px)
- Tables as layout
- Underlined links in default blue
- Image crops unexpected
- Scrolling text, marquee, but used surgically
- Negative space used aggressively — emptiness is confrontational

### Hallmarks
- Loudness and quietness alternated — not constant noise
- A few perfect moments (one beautiful spread) inside the rawness
- Self-aware: the brutalism is a choice, not a lack of effort
- Often uses stock imagery, scans, photocopies — texture

### Hallmarks to avoid
- ❌ Calling it "brutalist" but shipping unstyled HTML — that's not brutalism, that's unfinished
- ❌ Random colors with no logic
- ❌ Sloppy where sloppiness isn't the point
- ❌ Inaccessible by design (low contrast, missing alt text, no keyboard nav) — see `motion.md` on accessibility

---

## 5. Soft / Warm / Hand-crafted

**For:** Lifestyle, hospitality, food, small business, indie SaaS, personal brands, creative practices, parenting, wellness (without woo).

**Reference:** Mailbrew, Cron, Glossier (2014–2018), Away (early), Sweetgreen, Oatly (web), Cobot, Hem, Fellow, Pattern Brands (the goods), Studio Neat, Areaware.

**Vibe:** Considered warmth. Soft, but not saccharine. Rounded but not gummy. Personality without performance.

### Typography
- **Display:** GT Super, Tiempos, Editorial New, Söhne (soft weight), a humanist sans with warmth: ABC Diatype, Inter, Söhne
- **Text:** Same family
- **Avoid:** Geometric sans (Futura, Avenir) — too cold. Heavy weights — too assertive.
- **Hero size:** Comfortable, not massive. `clamp(2.5rem, 5vw, 4.5rem)`.

### Color
- **Surface:** Cream (#FAF6F0, #F4EFE6), warm white, soft taupe
- **Ink:** Warm near-black (#1A1A1A, #2B2522)
- **Accent:** Terracotta, sage, dusty blue, mustard, plum. Desaturated, not pastel.
- **Accent usage:** Generous — can be on backgrounds, but in soft washes.

### Layout
- Generous padding (more than refined minimal)
- Rounded corners allowed (12–20px), but not on everything
- Photography-led: warm, natural light, lifestyle contexts
- Cards exist but feel like objects, not data containers
- Type can overlap images slightly (intentional, not careless)

### Hallmarks
- Texture: subtle paper grain, soft shadows, hand-drawn marks (used once or twice)
- Product photography is real, not stock
- Microcopy has voice: "Hey there" not "Welcome"
- Soft transitions, never aggressive

### Hallmarks to avoid
- ❌ Pastel overload
- ❌ Hand-drawn icons everywhere — pick one or none
- ❌ Handwritten fonts for body copy (display OK)
- ❌ Confusing softness with low contrast

---

## 6. Technical / Mono

**For:** Dev tools, APIs, infrastructure, docs, CLI tools, terminals, hacker-native products, data products.

**Reference:** Fly.io, Cloudflare, Tailscale, Planetscale, Supabase (docs), Vercel (docs), Railway, Render, Cloudflare Workers docs, Wing, Terminal aesthetic, ASCII art used well.

**Vibe:** The interface is the documentation. Code is a first-class citizen. Numbers and logs feel like home.

### Typography
- **Display & Text:** Mono family — JetBrains Mono, IBM Plex Mono, Berkeley Mono, GT America Mono, Geist Mono, Iosevka
- **Pair with:** A clean grotesque for long-form prose (IBM Plex Sans, Inter, Söhne)
- **Hero size:** Often smaller, with the headline being literal (file path, command, status). `clamp(2rem, 4vw, 3.5rem)`.

### Color
- **Surface:** True black (#000) or terminal green-tinted black, or off-white (#F4F4F2)
- **Ink:** Pure white on black, pure black on white
- **Accent:** Terminal green (#00FF00), amber (#FFB000), red for errors, cyan for links. Or single accent like Vercel pink.
- **Syntax highlighting palette** if showing code: muted, not rainbow

### Layout
- Dense. Information-rich. Multi-column where it helps.
- Tables of specifications, environment variables, endpoints
- Code blocks are the design — make them beautiful
- Status indicators (● ◯) used semantically
- Footer often shows: build hash, region, version, last deployed

### Hallmarks
- ASCII diagrams used as visual elements (boxes made of `+`, `-`, `|`)
- Real numbers shown (latency, throughput, cost)
- Logs as UI patterns
- Keyboard-first design (visible shortcuts)
- Easter eggs for nerds

### Hallmarks to avoid
- ❌ Fake "hacker" aesthetic without technical content — reads as costume
- ❌ Green-on-black that's actually painful to read
- ❌ Emoji as status indicators
- ❌ Pretending to be a terminal when the product is a marketing site

---

## 7. Playful / Geometric

**For:** Consumer, social, gaming, creative tools, kids, education, anything where delight is a feature.

**Reference:** Notion Calendar, Linear (mobile), Things 3, Headspace (used well), Duolingo (engagement surfaces), Pitch (presentations), Arcade, Cron, editorial sections of The Browser Company.

**Vibe:** Geometric, colorful, considered-but-joyful. Play is the design system, not the decoration.

### Typography
- **Display:** Geometric with character: ABC Diatype, GT Walsheim, Söhne (rounded weights), Inter, Manrope
- **Pair with:** A mono for accents (GT America Mono, JetBrains Mono)
- **Hero size:** Confident. `clamp(3rem, 6vw, 5.5rem)`.

### Color
- **Surface:** Off-white or a tinted near-white
- **Palette:** Multiple accents used deliberately — a 4-color palette of well-chosen hues, not rainbow
- **Color is meaningful:** each color = a category, a state, a feature

### Layout
- Asymmetric, often tilted elements
- Cards with bold outlines (2px) rather than subtle shadows
- Generous whitespace between bold moments
- Icons are large, custom or weighty — never emoji
- Motion is part of the design (not garnish)

### Hallmarks
- Custom illustrations as primary imagery
- Microcopy that has a voice
- Achievement / state moments (delight)
- Sound used well (or not at all)

### Hallmarks to avoid
- ❌ Comic Sans or "playful" = bad typography
- ❌ Rainbow palettes with no logic
- ❌ Bouncy animations on everything — be selective
- ❌ Confusing play with chaos

---

## Hybrid Rules

Sometimes a project sits between two aesthetics. The rules:

1. **Pick the dominant one.** The other can contribute a single technique (e.g., Refined Minimal layout + Editorial headline typography). Don't blend 50/50.
2. **Aesthetic components are atomic.** Don't mix and match components across aesthetics. One button system, one card system.
3. **Typography pairs must be in the same family.** Söhne + Söhne Mono. GT America + GT America Mono. Inter + JetBrains Mono. Don't pair random faces.
4. **Color palette stays in one aesthetic.** Don't mix Refined Minimal neutrals with Soft palette accents.

If a project needs more than one aesthetic (e.g., marketing site + product), treat them as **separate surfaces** with different design systems, sharing only typography family.
