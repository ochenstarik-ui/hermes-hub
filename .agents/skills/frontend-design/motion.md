# Motion — Restraint, Intent, Feel

> Animation is feedback, not decoration. Every motion must communicate: state changed, content arrived, attention needed. If it doesn't communicate — remove it.

---

## The Three Questions

Before adding any animation, ask:

1. **What does this motion communicate?** ("The button is now active" / "This content is new" / "Loading finished")
2. **What happens if I remove it?** (Usually: nothing — and that's the test)
3. **Is it accessible?** (Does it respect `prefers-reduced-motion`?)

If you can't answer #1, delete it.

---

## Principles

### 1. Less motion, more meaning
A page with 12 different entrance animations feels unstable. A page with ONE entrance system feels considered.

**Pick one entrance system. Pick one hover system. Pick one page-transition pattern. Use them throughout.**

### 2. Easing is everything
- **`ease-out`** for things arriving (decals landing on screen, modals opening, content appearing)
- **`ease-in`** for things leaving (modals closing, content dismissed)
- **`ease-in-out`** for things that loop or oscillate
- **`linear`** for things that are continuous and infinite (rare — loading spinners)
- **Custom cubic-bezier** for character: `cubic-bezier(0.32, 0.72, 0, 1)` (Apple-style, "expressive out") or `cubic-bezier(0.4, 0, 0.2, 1)` (Material standard)

**Avoid:** `ease` (default — the default is rarely the right answer for important moments).

### 3. Duration is the dial
Faster = more responsive. Slower = more dramatic.

| Type | Duration |
|---|---|
| Hover state change | 80–150ms |
| Button press | 60–100ms |
| Modal open | 150–250ms |
| Modal close | 100–200ms |
| Tooltip appear | 100–150ms |
| Content fade in | 200–400ms |
| Page transition | 250–500ms |
| Hero entrance | 500–800ms (one moment — not every section) |
| Skeleton shimmer loop | 1500ms |
| Marquee / infinite scroll | 30000–60000ms (very slow) |

**Rule of thumb:** the smaller the change, the faster the transition. The bigger the change, the longer it can take.

### 4. Distance is small
Things should move **a little**. A modal opening from `scale(0.9) → scale(1)` (10% growth) feels elegant. From `scale(0.5) → scale(1)` (50% growth) feels cartoonish.

**Default:** content shifts 4–12px. Modals scale 0.96–1. Cards lift 2–4px. Hover scale 1.02–1.05 max.

---

## Entrance Animations

### The system
Choose ONE entrance pattern. Apply to:
- Hero elements (on load)
- Content sections (on scroll into view)
- Modal/dialog content
- Toast notifications

**Options:**

**Fade** — most subtle, almost universal
```css
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
.fade-in {
  animation: fadeIn 400ms ease-out both;
}
```

**Fade + rise** — slightly more dramatic, good for text
```css
@keyframes fadeRise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
```

**Fade + slide** — for sidebar items, list items
```css
@keyframes fadeSlide {
  from { opacity: 0; transform: translateX(-12px); }
  to { opacity: 1; transform: translateX(0); }
}
```

**Stagger** — for groups of items (lists, grids)
```css
.stagger-item { opacity: 0; animation: fadeRise 400ms ease-out forwards; }
.stagger-item:nth-child(1) { animation-delay: 0ms; }
.stagger-item:nth-child(2) { animation-delay: 60ms; }
.stagger-item:nth-child(3) { animation-delay: 120ms; }
.stagger-item:nth-child(4) { animation-delay: 180ms; }
/* etc — or use CSS variables for delay */
```

### Entrance anti-patterns
- ❌ Every section animating in as you scroll (exhausting)
- ❌ Long durations (1s+) for routine content
- ❌ Bouncy easing (`cubic-bezier(0.68, -0.55, 0.265, 1.55)`) on serious interfaces
- ❌ Slide-in from random directions (left, right, top, bottom — pick one)
- ❌ Different animation types per section (no system)

---

## Hover Animations

### The system
Pick a hover pattern. Apply to all interactive elements of a kind.

**Buttons**
- Background color change: 120ms
- Optional: subtle scale `transform: scale(1.02)` — only on prominent CTAs

**Cards**
- Border color strengthens OR background tints slightly OR 2px lift via translateY
- Pick ONE. Don't combine.

**Links**
- Underline grows from left (preferred) OR color change
- 150ms

**Icons**
- Slight rotate (5–10deg) OR slight scale (1.1)
- Pick the right direction for the meaning (e.g., arrow rotates forward, chevron rotates down)

### Hover anti-patterns
- ❌ `transform: scale(1.1)` on every hover — feels unstable
- ❌ Color shifts that don't match the palette (random bright colors)
- ❌ Multiple property changes at once (color + size + shadow + rotate)
- ❌ Long durations on hover (anything > 200ms feels laggy)

---

## Scroll-triggered Animations

**Default:** don't animate on scroll. Content appears when it appears.

**When scroll animations ARE appropriate:**
- Long-form editorial pages (sections reveal as you read)
- Image galleries (lazy reveal as you scroll)
- Data visualizations (animate in as they enter viewport)
- Storytelling / product tours

**How to do it well:**
- Trigger once (`IntersectionObserver`, threshold 0.1–0.2)
- Animation is subtle (fade + small rise)
- Don't replay on scroll back
- Provide a no-JS fallback (content visible by default)

```js
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('in-view');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.15 });

document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
```

```css
.reveal {
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 600ms ease-out, transform 600ms ease-out;
}
.reveal.in-view {
  opacity: 1;
  transform: translateY(0);
}
```

### Scroll animation anti-patterns
- ❌ Parallax everywhere (rarely adds value)
- ❌ Horizontal scroll as the only way to navigate a section
- ❌ Content invisible until JS loads (broken without JS)
- ❌ Replaying animations on every scroll back through
- ❌ "Scroll to discover" with no clear signal of what comes next

---

## Page Transitions

For SPAs and multi-page sites with shared chrome.

**The rule:** fast, consistent, and barely noticeable.

- **Fade transition:** 200ms cross-fade between pages
- **Slide (subtle):** outgoing content slides 20px left, incoming slides in from right — only if the navigation is forward/back in a clear sequence
- **Duration:** 200–300ms max

**Avoid:**
- ❌ Heavy transitions that delay content (users notice delay as "broken")
- ❌ Different transition styles for different navigation actions
- ❌ Animated logos or brand marks on every page load

---

## Micro-interactions Worth Their Weight

- **Toggle switches** — smooth slide with color change
- **Checkbox check** — satisfying tick animation
- **Drag handles** — feedback as user drags
- **Form validation** — color change + small shake on error (subtle, not aggressive)
- **Toast notifications** — slide in from corner, auto-dismiss with progress bar
- **Number counters** — counting up to value (data viz, hero stats)
- **Progress bars** — width transitions smoothly, not jumps
- **Loading completion** — content fades in smoothly, skeleton → real

---

## Performance

### Animate these properties (cheap, GPU-accelerated):
- `transform` (translate, scale, rotate)
- `opacity`

### Avoid animating these (expensive, layout-thrashing):
- `width`, `height`
- `top`, `left`, `right`, `bottom`
- `margin`, `padding`
- `border-width`
- `box-shadow` (acceptable for small elements; expensive for large)

### Tips
- Use `will-change: transform` sparingly (only on elements about to animate)
- Use `transform: translateZ(0)` or `will-change` to promote to GPU layer
- Use `requestAnimationFrame` for JS animations
- For long-running animations, use `transform` and `opacity` only

---

## Accessibility — `prefers-reduced-motion`

**Required.** Some users get nauseous, dizzy, or worse from motion. Respect their setting.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Or be more selective — only kill the heavy stuff:

```css
@media (prefers-reduced-motion: reduce) {
  .reveal { opacity: 1; transform: none; transition: none; }
  .parallax { transform: none !important; }
}
```

**Always test:** toggle "Reduce motion" in your OS settings. Visit the site. Does it still work? Is content still visible?

---

## Motion Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| Animate every section on scroll | Animate selectively, or none |
| `transition: all` on every element | Specify which properties animate |
| Bouncy spring physics on every UI | Most UI should be linear-feeling ease-out |
| Parallax on every image | Parallax only when it adds to the narrative |
| Long page transitions (>400ms) | Keep page transitions under 300ms |
| `infinite` animations | Animations should have a clear end |
| Hover scale of 1.1+ | Subtle scale (1.02–1.05) if any |
| Different motion styles in different sections | One system, applied consistently |
| Animations that require JS to see content | Content visible by default; animations enhance |
| Skipping `prefers-reduced-motion` | Always honor it |
| Animated gradient backgrounds | Static backgrounds or no backgrounds |
| Marquee text scrolling fast | Slow, considered (or don't) |
| Number counting from 0 with 4s duration | Count quickly (1–2s) or show the final value |
| Loading spinner that takes 30s | Show progress, not just a spinner |
| Toast that bounces in | Slide in, fade out |
