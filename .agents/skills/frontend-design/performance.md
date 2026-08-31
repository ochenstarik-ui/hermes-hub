# Performance — Speed Is Design

> A beautiful page that loads in 5 seconds reads as broken. Speed is not engineering garnish — it is part of the aesthetic. Quiet, fast, immediate: the same words that describe good design describe good performance. Agents over-ship: three fonts, a framework, and a chat widget for a page that could be HTML and 40KB of CSS. This file is the counterweight.

---

## Budgets (decide before building)

| Metric | Budget | Why |
|---|---|---|
| **LCP** | < 2.5s (mobile, 4G throttled) | The "is this page real?" moment |
| **INP** | < 200ms | Interaction feels instant, not sluggish |
| **CLS** | < 0.1 | Nothing jumps while reading |
| Page weight — marketing page | < 1 MB, and < 300 KB on the wire critical path | Respect the visitor |
| Page weight — content page | < 500 KB | Text is cheap; bloat is chosen |
| Fonts | ≤ 2 families, ≤ 4 files total, ≤ ~300 KB | See below |
| JS — mostly-static page | ≤ 50 KB, or **none** | If CSS can do it, CSS does it |

If a requirement breaks the budget, say so and cut the requirement — don't ship the slow version silently.

---

## Fonts (the #1 agent-made slowdown)

The full setup is in `typography.md` §Loading Fonts. The floor:

```html
<link rel="preload" href="/fonts/InterVariable.woff2" as="font" type="font/woff2" crossorigin>
```

```css
@font-face {
  font-family: 'Inter';
  src: url('/fonts/InterVariable.woff2') format('woff2-variations');
  font-weight: 100 900;
  font-display: swap;
  unicode-range: U+0000-00FF; /* subset to what you actually use */
}
```

Rules:

- **Variable font > family of static weights.** One file, every weight.
- Load **woff2 only.** No ttf, no eot, no woff fallback chain from 2015.
- `font-display: swap` (or `optional` for non-critical faces) — invisible text is a broken page.
- Preload **only** the display face used above the fold. Preloading everything defeats preloading.
- Google Fonts is acceptable for demos; self-host for production — privacy, one fewer origin, no third-party CSS chain.
- **Fallback metrics** kill the swap "jump" (`size-adjust`, `ascent-override`) — CLS goes to near zero:

```css
@font-face {
  font-family: 'Inter-fallback';
  src: local('Arial');
  size-adjust: 107%;
  ascent-override: 90%;
  descent-override: 22%;
}
```

---

## Images

Agents love full-bleed PNGs. Kill them:

1. **Format:** AVIF > WebP > JPEG. PNG only for flat graphics that SVG can't do.
2. **Responsive:** every content image ships `srcset` + `sizes`:

```html
<img src="/work/cover-800.avif"
     srcset="/work/cover-400.avif 400w, /work/cover-800.avif 800w, /work/cover-1600.avif 1600w"
     sizes="(max-width: 768px) 100vw, 50vw"
     width="800" height="533"
     alt="Halftone studio — shelving system installed for Mira Almeida, Lisbon"
     loading="lazy" decoding="async">
```

3. **Reserve space:** `width` + `height` attributes (or CSS `aspect-ratio`) on **every** image. Unreserved images are the top cause of CLS.
4. **Lazy-load below the fold; never lazy-load the LCP image.** The hero image gets the opposite treatment:

```html
<link rel="preload" as="image" href="/hero-1600.avif" fetchpriority="high">
```

5. Hero/background images ≤ 200 KB after compression. If it can't compress, it should be CSS or SVG — see `imagery.md`.
6. `prefers-reduced-data` exists; treat giant decorative media as optional, not mandatory.

---

## CSS

- **One stylesheet** for a marketing page, hand-written, token-driven (`color.md`, `layout.md`). It will be smaller than any utility purge.
- No `@import` chains (serialized downloads). `<link rel="stylesheet">` in `head`, once.
- The examples in `examples/` embed CSS in a single HTML file for portability. **In production, split it out** — page cacheability matters from visitor two onward.
- Critical CSS is a last resort for heavy pages, not a default. A 30KB stylesheet doesn't need inlining logic.
- `content-visibility: auto` on long below-the-fold sections is free render speed:

```css
.section { content-visibility: auto; contain-intrinsic-size: auto 600px; }
```

---

## JavaScript — Ship None If You Can

Ask in order:

1. **Does this need JS at all?** Menus (`<details>`), accordions (`<details>`), carousels (scroll-snap), tabs (radio inputs), dialogs (`<dialog>`), theme toggle (no — server/inline), hover reveals (CSS).
2. If yes — **progressive enhancement**: the content works with JS disabled, JS upgrades it.
3. If a framework is already justified by the brief (real app state, product UI), fine — but a landing page in a SPA is slop with extra steps.

Rules when JS is used:

```html
<script type="module" src="/app.js"></script>  <!-- module = deferred by default -->
```

- `defer` / `async` / `type="module"` — never a blocking `<script>` in `head`.
- One file beats five on first load; five beat one after first visit (cache). For demos: one.
- No spinner for operations under 300ms — see perceived performance below.
- Event handlers on scroll/input: `passive: true` where you don't `preventDefault()`; debounce real work.
- No JS "framework CDN + await hydration" for a static page. HTML is already interactive.

---

## Third Parties (the silent budget killers)

| Third party | Real cost | Decision |
|---|---|---|
| Chat widget | 300 KB–1.5 MB, main-thread | Marketing page: a link to email/open chat. Never autoload |
| Analytics | 10–100 KB | One script, deferred, or server-side |
| Font CDN | Extra origin + CSS chain | Self-host in production |
| Map embed | 1 MB+ | Screenshot + link, or static map tiles |
| Video embed | 1 MB+ on "view" | Facade: poster image + click-to-load |
| A/B tool | Blocking script | Question the tool |

Every third-party script is a budget decision. Add one = remove weight somewhere else.

---

## Core Web Vitals in Practice

**LCP** — usually the hero headline or hero image.
- Nothing blocking it: fonts preloaded, hero image `fetchpriority="high"`, no render-blocking JS.
- No lazy-load, no `display:none` at mobile then swap.

**CLS** — movement after render.
- Every image/video/iframe has reserved dimensions.
- Fonts: `font-display: swap` + fallback metrics (above).
- No banners/modals injected on load. Nothing slides in from the top.

**INP** — interaction latency.
- Handlers do one small thing; heavy work is chunked (`requestIdleCallback`) or in a worker.
- Debounce input-driven recalculation; don't re-render lists on every keystroke past what's visible.
- Animations stay on `transform`/`opacity` (`motion.md` §Performance) so the main thread is free.

---

## Perceived Performance (the design half)

- **< 100ms:** feels instant — do the thing, show nothing.
- **100–300ms:** still instant — no spinner needed.
- **300ms–1s:** show *something real*: skeleton of actual layout, button → "Working…" state.
- **> 1s:** progress with meaning (steps, not a liar's progress bar); keep the page usable.
- Skeletons must **match final layout** (`components.md` §States) — wrong-shaped skeletons cause their own CLS.
- Optimistic UI for reversible actions (toggle on immediately, reconcile after).

---

## Measuring (never guess)

1. **Lighthouse** (DevTools, mobile, throttled) — LCP/INP/CLS + the page-weight waterfall.
2. **PageSpeed Insights** — lab + real-user field data when available.
3. **WebPageTest** — 4G Moto G profile for the honest truth.
4. DevTools Network tab, "Disable cache," throttled — count requests and KB **before** being told to.

The examples in `examples/` should each score 95+ on Performance/Best-Practices out of the box. If a change drops it below 90, the change needs a reason.

---

## Performance Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| React/Vue SPA for a static landing page | HTML + CSS, JS where it earns its bytes |
| Blocking `<script>` in `<head>` | `type="module"` / `defer` |
| Full-bleed 3 MB PNG hero | Compressed AVIF/WebP ≤ 200 KB, or CSS/SVG composition |
| Lazy-loading the hero image | Preload + `fetchpriority="high"` |
| Images without `width`/`height` | Dimensions or `aspect-ratio`, always |
| Nine font files in four families | ≤ 2 families, variable, woff2, subset |
| `@import`-chained CSS | One `<link>` stylesheet |
| Spinner for a 150ms action | Nothing — it's already done |
| Chat widget autoloading on a landing page | Link; load on intent |
| Tracking pixels accumulated "just in case" | One deferred analytics script |
| Page "works" only after hydration | Progressive enhancement |
| Deciding speed is "later, optimization" | Budgets are decided before building |

---

## Ship Gate

- [ ] LCP < 2.5s, CLS < 0.1, INP < 200ms (throttled mobile)
- [ ] Total transfer < budget (1 MB marketing / 500 KB content)
- [ ] ≤ 4 font files, all woff2, swap + fallback metrics
- [ ] Every image: format, srcset, dimensions, correct loading strategy
- [ ] No blocking JS; JS justified per feature
- [ ] Third parties enumerated and costed
- [ ] Tested on throttled 4G, not just the dev machine

See also: `typography.md` §Loading Fonts, `imagery.md` (cheaper visuals), `motion.md` §Performance, `checklist.md` §Edge Cases.
