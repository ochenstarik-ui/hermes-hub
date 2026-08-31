# Anti-Patterns — The Full Rejection Catalog

> When in doubt about whether something is slop, look it up here. If it's listed, redesign.

---

## Visual Anti-Patterns

### 1. The Purple-Blue Gradient Hero
**Slop signature:** Hero section with full-bleed `linear-gradient(135deg, #667eea 0%, #764ba2 100%)`, centered headline in white, sometimes with a stock photo of a person at a laptop faintly visible.

**Why it's slop:** It was the default output of every AI image generator circa 2022 and became the visual shorthand for "AI made this." It carries zero information.

**Replace with:**
- White/off-white background, ink-colored headline set tight and large
- Or a single full-bleed photograph with no gradient
- Or a deliberately designed gradient (e.g., terminal green→black, monochrome, single hue at low opacity)

---

### 2. Glassmorphism on Everything
**Slop signature:** Every card, modal, and nav has `backdrop-filter: blur(20px)`, translucent white background, soft border. Floating UI elements look like they're made of frosted glass.

**Why it's slop:** Used to signal "modern app" but now signals "AI-generated template." Real apps (Linear, Stripe, Arc) avoid this because it hurts legibility and performance.

**Replace with:**
- Solid surface colors with hairlines for separation
- Or one focal glass element used sparingly (a key modal, the active nav)
- Hairline borders (`1px solid var(--hairline)`)

---

### 3. The Emoji Icon
**Slop signature:** Feature cards with 🚀 ⚡ 🎨 💡 as the icon. Service descriptions with ✨ sprinkled.

**Why it's slop:** Emoji are not icons. They render differently across systems, are not part of a designed system, and read as "we didn't bother with real icons."

**Replace with:**
- Real icon set (Lucide, Phosphor, Tabler, Heroicons — but used with intent, not all of them everywhere)
- Custom SVG icons that match the visual weight of the type
- No icon at all (typography alone can structure a section)

---

### 4. The Pill Button Soup
**Slop signature:** Every interactive element has `border-radius: 9999px`. Buttons, badges, cards, images, inputs.

**Why it's slop:** Reads as "we applied the default rounded-corner treatment to everything." Real design systems vary radius by component type.

**Replace with:**
- Buttons: 6–8px radius (subtle) OR 0 (Swiss) OR pill (only for very specific cases like tags)
- Cards: 8–12px radius OR 0
- Images: 0 OR 4–8px (within cards)
- Inputs: 6–8px radius OR 0
- Set a **radius scale** (`--radius-sm`, `--radius-md`, `--radius-lg`) and stick to it.

---

### 5. The Gummy Shadow
**Slop signature:** Cards and elements with `box-shadow: 0 4px 6px rgba(0,0,0,0.1), 0 10px 15px rgba(0,0,0,0.1), 0 20px 25px rgba(0,0,0,0.1)` — multiple soft layers making everything look like it's made of marshmallow.

**Why it's slop:** Heavy shadows + translucent surfaces = everything looks the same depth = nothing has hierarchy.

**Replace with:**
- One precise shadow, not multiple. `box-shadow: 0 1px 2px rgba(0,0,0,0.06), 0 4px 12px rgba(0,0,0,0.04)`
- Or no shadow at all — use hairlines to separate surfaces
- Or use a single elevated shadow for modals/popovers only

---

### 6. The Centered Hero Section
**Slop signature:** Centered headline, centered subhead, centered CTA button(s), centered "trusted by" logo bar.

**Why it's slop:** Centered alignment for primary content is the universal default. It signals no design decision was made.

**Replace with:**
- Left-aligned headline, support element (image, product UI) on the right
- Or a deliberate asymmetric composition
- Or a single, oversized centered display headline (editorial style — make it a poster, not a template)

---

### 7. The "Aurora" Background
**Slop signature:** Animated, multi-color blob shapes behind content. Sometimes labeled as "mesh gradient" or "aurora UI."

**Why it's slop:** Decorative noise that actively hurts the content. The user came for information, not a screensaver.

**Replace with:**
- Nothing. White space is the background.
- Or a single, restrained decorative element (one geometric shape, one texture)
- Or full-bleed photography that earns its place

---

### 8. The Blob Illustration
**Slop signature:** Abstract 3D shapes — blobs, spheres, twisted toruses, often in pastel colors with soft gradients. Used as hero images or section dividers.

**Why it's slop:** Looks like an AI image generator's default output. Carries no meaning.

**Replace with:**
- Real product photography
- Real illustration with intent (editorial, custom, meaningful)
- A diagram, a chart, a piece of UI shown larger
- Typography alone — sometimes the strongest hero has no image

---

### 9. Drop Shadow on Text
**Slop signature:** `text-shadow: 0 2px 4px rgba(0,0,0,0.5)` on headlines.

**Why it's slop:** It's a Photoshop effect from 2008. Headlines should be set clean.

**Replace with:** No text shadow. Make the headline legible through contrast and size.

---

### 10. The Stock Photo Smile
**Slop signature:** Hero image of a young professional smiling at a laptop with a coffee, often with a slight gradient overlay. Or a diverse group of four people laughing around a whiteboard.

**Why it's slop:** Says nothing about your specific product. Reads as "we didn't take our own photos."

**Replace with:**
- Real product UI screenshot (this is the most powerful hero for B2B SaaS)
- Real photograph of the actual product / team / space
- An abstract / editorial image that sets mood without being literal
- No image — sometimes the strongest hero is pure typography

---

## Structural Anti-Patterns

### 11. The SaaS Sandwich
**Slop signature:** Every page follows this exact structure:
1. Hero (centered headline + 2 buttons)
2. "Trusted by 10,000+" logo bar
3. Three feature cards in a row
4. "How it works" — three numbered steps with icons
5. Three more feature cards (with screenshots)
6. Testimonial carousel
7. Pricing (three columns)
8. FAQ accordion (8 questions)
9. Big CTA section
10. Footer with 5 columns of links

**Why it's slop:** This is what every AI generates when asked to "make a SaaS landing page." It signals zero information architecture thinking.

**Replace with:**
- Question the structure for THIS product. What's the one thing the visitor needs to know?
- Editorial structure: maybe it's just a strong headline, a product screenshot, a few specific use cases, and a sign-up. No "trusted by," no FAQ.
- Varied sections: a big quote, a data visualization, a side-by-side comparison, a real customer story — mix the rhythm.

---

### 12. The Identical 3-Column Row
**Slop signature:** Three identical cards in a row, repeated as a section. Each card has: small icon, headline, paragraph, optional link. Used 2–3 times down the page.

**Why it's slop:** The 3-column card row is the universal placeholder for "show some features." Repeating it compounds the problem.

**Replace with:**
- Make the cards different from each other — one has a screenshot, one has a number, one has a quote
- Use varied layouts: 2-column, side-by-side, magazine-style spread
- Sometimes the strongest feature presentation is a single sentence with a big number behind it

---

### 13. The Middle-Pricing-Card Highlight
**Slop signature:** Three pricing tiers, middle one has a different color border, "Most Popular" badge, slightly larger, sometimes a glow.

**Why it's slop:** The pattern is so universal it's invisible — and it forces the user into a fake choice (the middle one). Also, who is it "most popular" for? Usually nobody.

**Replace with:**
- Two tiers (most products only need two)
- Or four tiers with the third one genuinely best (not the third by index, but the third by what makes sense for the buyer)
- Or no pricing cards — a single page explaining pricing, with a calculator or contact form

---

### 14. The FAQ That Asks Nothing
**Slop signature:** "What is [Product]?" "How does [Product] work?" "Is [Product] secure?" "How much does [Product] cost?" — generic questions that nobody actually asked.

**Why it's slop:** Real FAQs come from real support tickets. If yours reads like a template, it didn't.

**Replace with:**
- Real questions from real customers (check your support inbox)
- Specific, surprising questions: "Can I use this with [specific competitor]?" "What happens to my data if I cancel?"
- Or no FAQ at all — link to a real docs page

---

### 15. The Logo Bar of Lies
**Slop signature:** "Trusted by" with 8–12 logos of companies you've never heard of. Or logos of real companies that aren't actually customers (a famous slop move).

**Why it's slop:** Users notice. Investors notice. Anyone technical notices. It's a credibility-destroying move.

**Replace with:**
- Real customers with permission to use their logo
- If you don't have many, show 3 prominently, not 12 dishonestly
- Or skip this section entirely — it's not required

---

### 16. The Testimonial Carousel
**Slop signature:** Three testimonials rotating every 5 seconds, each with a stock headshot, name, title, company, and a 2-sentence quote full of marketing words.

**Why it's slop:** No one reads rotating testimonials. Each one is too brief to convince. The carousel hides weak content.

**Replace with:**
- One long-form customer story (interview format, real photos, real numbers)
- Or 3–6 static testimonials with full quotes, names, photos, no rotation
- Or a case study link: "Read how [Company] used [Product] to [Specific Outcome]"

---

## Copy Anti-Patterns

### 17. The Verb Stack
**Slop examples:**
- "Empowering businesses to thrive"
- "Enabling teams to unlock their potential"
- "Seamlessly integrate, effortlessly scale"
- "Revolutionizing the future of work"

**Why it's slop:** Empty verbs. They sound like they say something but don't.

**Replace with:**
- Specific verbs with specific objects: "Ship features 3x faster" / "Cut your AWS bill in half" / "Find any bug in under 60 seconds"
- Or claims with evidence: "We moved 4TB of data in 8 minutes. Here's how."

---

### 18. The Noun Without a Referent
**Slop examples:**
- "The future of work is here"
- "Modern solutions for modern problems"
- "A better way to [do vague thing]"

**Why it's slop:** Could apply to any company on Earth.

**Replace with:**
- The noun made specific: "The future of invoicing for French freelancers" / "A better way to ship pull requests"

---

### 19. The Generic Headline
**Slop examples:**
- "Welcome to [Brand]"
- "The platform for [audience]"
- "Built for the modern [audience]"

**Why it's slop:** Says nothing. Adds friction. User bounces.

**Replace with:**
- A headline that makes a claim: "Stop writing CSS. Start describing what you want."
- A headline that names the user: "For designers who'd rather think than fiddle."
- A headline that's specific enough to be slightly weird: "The invoicing app for people who hate invoicing."

---

### 20. The Three-Adjective Stack
**Slop examples:**
- "Fast. Simple. Beautiful."
- "Powerful. Flexible. Reliable."
- "Modern. Elegant. Open."

**Why it's slop:** Says nothing while sounding like it does. Also: the words contradict each other often (can something be powerful AND simple?).

**Replace with:**
- One word that actually means something specific to your product: "Quiet." / "Honest." / "Yours."
- Or a full sentence that makes a claim.

---

### 21. The Lorem Ipsum in Disguise
**Slop examples:**
- "Lorem ipsum dolor sit amet" (literally)
- "Description goes here"
- "Subheading about the value proposition"
- "Tagline"
- Placeholder copy left in by a careless draft

**Why it's slop:** If the copy is placeholder, the design is a sketch. Ship real content.

**Replace with:**
- Real copy. Even if imperfect. Especially if imperfect — it shows you've thought about the actual words.
- If you must use placeholder: write lorem ipsum clearly, mark it as placeholder, and ASK the user for real copy.

---

## Code Anti-Patterns

### 22. Tailwind Utility Soup
**Slop signature:** `<div class="bg-white rounded-xl shadow-md p-6 hover:shadow-lg transition-all duration-300 hover:-translate-y-1">` — 14 utilities, no extraction, no semantic naming.

**Why it's slop:** No design system. No consistency. Can't change one thing in one place.

**Replace with:**
- Components (`.card`, `.button`, `.input`)
- CSS layers with custom properties
- `@apply` for utility composition
- Or at minimum: extract repeating patterns into named classes

---

### 23. Inline Styles for Tokens
**Slop signature:** `style={{ color: '#5E6AD2', padding: '24px', fontSize: '14px' }}` — raw values inline, no token system.

**Why it's slop:** Can never change globally. No design system = no design.

**Replace with:**
- Use token CSS variables (`color: var(--accent)`)
- Or Tailwind theme values, not arbitrary values

---

### 24. The `transition-all` Everything
**Slop signature:** `transition-all duration-200` on every interactive element.

**Why it's slop:** Transitions specific properties (`color`, `background`, `transform`), not all. `transition-all` includes layout properties, causing jank.

**Replace with:**
- Specify: `transition: color 150ms ease, background-color 150ms ease, transform 200ms ease;`
- Or use Tailwind's specific: `transition-colors duration-150`

---

### 25. Default Focus Rings
**Slop signature:** No `:focus-visible` styles. Browser default dotted outline on form elements only. Or `outline: none` with no replacement.

**Why it's slop:** Inaccessible. Keyboard users can't tell where they are.

**Replace with:**
```css
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: inherit;
}
```

---

### 26. Div Soup
**Slop signature:** `<div><div><div class="..."></div></div></div>` where `<section>`, `<article>`, `<nav>`, `<header>`, `<footer>`, `<main>`, `<aside>` exist.

**Why it's slop:** No semantic meaning. Screen readers can't navigate. Search engines can't parse.

**Replace with:** Use semantic HTML. Always. The right element is almost always available.

---

### 27. `font-weight: 700` on Everything
**Slop signature:** Every heading, every button, every label is `font-weight: 700`.

**Why it's slop:** The face was chosen for its 400 weight. Ignoring the weight range loses the typeface's character.

**Replace with:** Use 400, 500, 600 — reserve 700 for hero moments only.

---

### 28. Emoji in Source Code
**Slop signature:** Commit messages, comments, console output with 🎉 🚀 ✨.

**Why it's slop:** Same reason as emoji icons. Use words.

---

## What to Do When You Catch Yourself

When you realize you're producing slop — and you will, because it's the default gravity of LLM output — apply this recovery protocol:

1. **Stop.** Don't keep refining the slop.
2. **Name it.** "I am about to ship [specific anti-pattern]."
3. **Identify the real job.** "This section is supposed to [specific job]. What's a non-slop way to do that?"
4. **Look at a reference.** Open Linear.com / Stripe.com / a Pentagram project / a magazine spread. What did they do?
5. **Redo the smallest version.** Strip back to the smallest correct version. Then add one detail.
6. **Ship the smallest version.** It's better than the largest slop version.
