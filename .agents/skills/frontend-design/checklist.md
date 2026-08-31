# Quality Checklist — Before You Ship

> Run this before declaring a page done. Each item is something an LLM tends to skip. Each item is what separates shipped-from-a-template from designed-by-a-human.

---

## Before You Start

- [ ] I can state the page's job in one sentence
- [ ] I know who the primary user is
- [ ] I've picked ONE aesthetic direction (from `aesthetics.md`)
- [ ] I've picked ONE display typeface and ONE text typeface
- [ ] I've built a color token system (surface, ink, muted, hairline, accent)
- [ ] I've written the headline. It's specific. It makes a claim.

---

## Typography

- [ ] Hero headline is 60–160px (not the default 36–48px)
- [ ] Display type has tight letter-spacing (-0.02em to -0.04em)
- [ ] All-caps labels have positive tracking (+0.05em or more)
- [ ] Line-height is tight on display (1.05–1.15), normal on body (1.5–1.65)
- [ ] Body text is 16–18px, left-aligned, never justified
- [ ] Only 2–3 weights used across the page
- [ ] No font-weight: 700 on every heading
- [ ] Tabular figures for data (pricing, stats, tables)

---

## Color

- [ ] One accent color, used on <10% of pixels
- [ ] No purple-blue gradients
- [ ] No glassmorphism on cards
- [ ] No tinted section backgrounds
- [ ] Body text contrast ≥ 4.5:1 (aim 7:1)
- [ ] Dark mode: not pure black background, not pure white text
- [ ] All colors come from the token system — no random hex

---

## Layout

- [ ] Hero is asymmetric or has a strong typographic moment (not centered-everything)
- [ ] Max-width is 1200–1280px on desktop
- [ ] Generous side padding (px-6 mobile, px-12+ desktop)
- [ ] Sections separated by whitespace, not dividers
- [ ] Mobile breakpoints tested at 375px, 768px, 1280px
- [ ] No content wider than its container

---

## Components

- [ ] Buttons have default, hover, focus-visible, active, disabled states
- [ ] Inputs have default, hover, focus, error, disabled states
- [ ] Focus-visible is visible, designed (not browser default)
- [ ] Touch targets are 44×44px minimum on mobile
- [ ] Cards have hairline borders, not stacked drop shadows
- [ ] Borders don't disappear on hover with no replacement
- [ ] Tables: header row distinct, numbers monospace, row hover subtle
- [ ] Icons are consistent (one set, one weight, one size)

---

## Content

- [ ] No "Lorem ipsum"
- [ ] No "Welcome to [Brand]"
- [ ] No "Empowering / enabling / unlocking"
- [ ] Headlines are specific — make a claim, name a user, or say something only this could say
- [ ] CTAs are first-person, specific verbs ("Start my free trial" not "Submit")
- [ ] Empty states explain what to do
- [ ] Error messages are human and actionable
- [ ] Real names, real numbers where possible

---

## Structure

- [ ] NOT the SaaS sandwich (hero → social proof → 3 cards → 3 cards → testimonials → pricing → FAQ → CTA)
- [ ] Each section has a job. No filler sections.
- [ ] Pricing has 2 or 4 tiers, not 3 with the middle one highlighted
- [ ] FAQ questions are specific (or no FAQ at all)
- [ ] Testimonials have real quotes with real names (or skip them)
- [ ] Footer is sized to its content — not filled with placeholder links

---

## Motion

- [ ] One entrance system, applied consistently (not different per section)
- [ ] Hover transitions are 80–150ms
- [ ] No `transition: all`
- [ ] Animations animate `transform` and `opacity` (not `width`, `height`, `top`)
- [ ] `@media (prefers-reduced-motion: reduce)` honored
- [ ] No infinite animations on critical UI elements
- [ ] Scroll animations don't replay on scroll back

---

## Accessibility

- [ ] Color contrast meets WCAG AA (4.5:1 body, 3:1 large text)
- [ ] Focus-visible state visible on every interactive element
- [ ] Semantic HTML (`<nav>`, `<main>`, `<article>`, `<section>`, `<aside>`)
- [ ] Alt text on all meaningful images; empty `alt=""` on decorative
- [ ] Form inputs have labels (not just placeholders)
- [ ] `aria-label` on icon-only buttons
- [ ] Tab order is logical
- [ ] Keyboard accessible: Tab, Enter, Escape, Arrow keys where needed
- [ ] Skip-to-content link on long pages
- [ ] Tested with screen reader (or at minimum, VoiceOver rotor pass)

---

## Edge Cases

- [ ] 404 page is designed (not default server page)
- [ ] Loading state visible (skeleton or spinner)
- [ ] Empty state visible (when no data)
- [ ] Error state visible (with clear next step)
- [ ] Long text doesn't break the layout
- [ ] Missing image has a fallback
- [ ] Slow connection tested (3G throttle)
- [ ] Offline behavior considered (or at least: page loads, doesn't break)

---

## Final Tests

### The Vignelli Test
> "Would Massimo Vignelli approve?"
- Is the grid clean?
- Is the typography doing the work?
- Is the color restrained?

### The Studio Test
> "Could you ship this at Linear / Stripe / Pentagram?"
- Would a senior designer here sign off on this without changes?

### The Screenshot Test
> "Would someone screenshot this for design inspiration?"
- Are there any moments worth capturing?
- Or is the whole page forgettable?

### The 2 AM Test
> "If you showed this at 2 AM with no context, would the visitor know what it is?"
- Does the hero do its job?
- Are the headlines legible and specific?

### The Critique Test
> "Could you defend every choice in a design critique?"
- The accent color choice?
- The spacing decisions?
- The copy?

### The Removal Test
> "If you removed one element, would the design be better?"
- If yes, remove it.
- Then ask again.
- Repeat until the answer is no.

---

## Ship Decision

- [ ] All checklist items above are addressed (or consciously skipped with reason)
- [ ] The design feels **considered**, not generated
- [ ] I would be proud to put my name on this
- [ ] I would recommend this to a friend who asked for a great website

If any answer is no: keep iterating. The goal is craft, not completion.
