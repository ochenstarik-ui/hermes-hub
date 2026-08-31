# Accessibility — Craft, Not Compliance

> Accessibility is where amateurs stop and pros begin — it is `SKILL.md` principle 7 applied to people. It is also the fastest way to tell real craft from generated output: slop pages are keyboard-hostile, unlabeled, and focus-invisible. The floor is **WCAG 2.2 AA**. The target is: nobody can tell this page was built by an LLM, including someone using a screen reader.

---

## The Mental Model

Accessibility is three habits, not a checklist bolted on at the end:

1. **Robust structure** — semantic HTML that means what it says.
2. **Visible states** — focus, hover, error, disabled (already required by `components.md`).
3. **Respect** — for motion sensitivity, zoom, touch, and slow connections.

If you build with these from Step 1 (see `SKILL.md` process), accessibility costs almost nothing extra. If you bolt it on at Step 10, it costs a rewrite.

---

## Semantic HTML First

### Landmarks, one of each where it matters

```html
<header>   <!-- site masthead -->
<nav aria-label="Primary">  <!-- main navigation -->
<main id="main">           <!-- THE one per page -->
<section aria-labelledby="features-title">
<aside>    <!-- truly tangential content -->
<footer>   <!-- colophon -->
```

### Heading order

- **One `<h1>`** per page — the page's claim.
- Never skip levels downward (`h2` → `h4`). Headings are the screen reader's table of contents.
- The visual hierarchy and the heading hierarchy must match. If a kicker looks bigger than the `h2`, fix the CSS, not the outline.

### Button or link? (decide correctly, agents get this wrong constantly)

| It does this | Use |
|---|---|
| Goes somewhere (URL changes) | `<a href="...">` |
| Does something (opens, submits, toggles, copies) | `<button>` |
| Submits a form | `<button type="submit">` |
| Toggles a menu that navigates | `<a>` styled as a control — not a `<div onclick>` |

A `<div>` with a click handler is not a button. No exceptions.

### Lists are lists

Indexes, catalogs, feature lists, nav items: use `<ol>`/`<ul>`/`<li>`. Screen readers announce "list, 8 items" — that announcement is design.

---

## Keyboard

- **Tab order = DOM order = visual order.** If they diverge, restructure the DOM — never "fix" it with `tabindex` above 0.
- `tabindex="0"` only for genuinely focusable custom components (a custom tab, a combobox — before you build one, check if a native element works).
- **Skip link** on any page longer than one screen:

```html
<a class="skip-link" href="#main">Skip to content</a>

.skip-link {
  position: absolute; left: var(--sp-4); top: var(--sp-4);
  transform: translateY(-200%);
  /* visible + on-brand when focused */
}
.skip-link:focus-visible { transform: none; outline: 2px solid var(--accent); }
```

### Key contracts

| Component | Keys |
|---|---|
| Buttons | Enter, Space |
| Links | Enter |
| Dialog / modal | Escape closes; **focus trapped** inside; focus returns to trigger on close |
| Menu / listbox | Arrow Up/Down, Home/End, Escape |
| Tabs | Arrow Left/Right between tabs, Home/End |
| Combobox / ⌘K palette | Arrow Up/Down, Enter selects, Escape closes — see `product-ui-patterns.md` §2 |
| Dismissible toast | Escape or timed auto-dismiss |

Test the whole page with the keyboard alone. If you can't reach it, click it, and dismiss it — it doesn't ship.

---

## Focus — Design It, Don't Delete It

```css
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* apply to everything interactive: a, button, input, select, textarea, [tabindex] */
a:focus-visible, button:focus-visible, input:focus-visible,
select:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

Rules:

- `:focus-visible` for mouse-dominant UI is correct; but keyboard focus must **always** show.
- **Never** `outline: none` without an equal-or-better replacement visible on keyboard use.
- Focus ring contrast: ≥ 3:1 against both the element and its background.
- After route/content changes, **move focus deliberately** — to the new page's `h1` (`tabindex="-1"` + `.focus()`) or the dialog. A screen reader left reading stale content is a broken page.

---

## Forms

- Every input has a **visible, persistent `<label>`**. Placeholder is not a label — it disappears on input and fails low-vision users.
- Group related inputs with `<fieldset>` + `<legend>` (plan selection, address blocks).
- Errors: name the problem and the fix, linked programmatically:

```html
<label for="email">Work email</label>
<input id="email" type="email" aria-describedby="email-error" aria-invalid="true">
<p id="email-error" class="field-error">
  Enter your work email — we'll send the invoice there.
</p>
```

- Use `autocomplete="email"`, `autocomplete="cc-number"`, etc. — they are free conversion wins.
- Mark required in text (`*` only if you also explain it). Never rely on color alone — pair it with a word or icon.
- Inputs at `16px`+ font size to prevent mobile Safari auto-zoom.

---

## ARIA — Less Is More

**First rule of ARIA: don't use ARIA if a native element exists.** A `<button>` needs zero ARIA. A `<div role="button" tabindex="0">` needs four attributes and still works worse.

| Need | Native first | ARIA only if you must |
|---|---|---|
| Clickable action | `<button>` | `role="button"` + `tabindex="0"` + Enter/Space handlers |
| Expand/collapse | `<details>`/`<summary>` | `aria-expanded` on trigger, `aria-controls` |
| Current page in nav | class + link styling | `aria-current="page"` |
| Icon-only button | — | `aria-label="Close menu"` |
| Live announcement | — | `aria-live="polite"` region |
| Dialog | `<dialog>` | `role="dialog"` + `aria-modal="true"` + focus trap |

### The four ARIA attributes worth knowing cold

- `aria-label` — **only on interactive elements** with no visible text (icon buttons, close buttons).
- `aria-expanded` — on disclosure triggers (menu, accordion, ⌘K).
- `aria-current="page"` — on the active nav item.
- `aria-hidden="true"` — on decorative duplicates (icon next to a text label, CSS artwork).

Never both `aria-hidden` and focusable on the same element. Never `role="presentation"` on a table that holds data.

---

## Color & Contrast Beyond Body Text

- Body text ≥ 4.5:1, large display ≥ 3:1 (details in `typography.md` / `color.md`).
- **Non-text contrast:** icons, input borders, focus rings, chart lines — ≥ 3:1 against their background. The `#E5E5E5` hairline on white fails for input borders; use it for dividers only, `#9B9B9B`+ for interactive outlines.
- **Color is never the only signal.** Errors need text, statuses need labels or shapes (●/▲/■ — see `product-ui-patterns.md` §5), links need underline or weight, not hue alone.
- Test both themes — dark mode accent often needs a lighter variant (`color.md` §Dark Mode).

---

## Images & Media

The alt decision tree:

| Image | Alt |
|---|---|
| Decorative (CSS art, texture, divider) | `alt=""` + it's probably CSS, not `<img>` |
| Informative (photo of the product) | Describe **what the user needs to know**: "Latch dashboard with three flag rows, all toggled on" |
| Functional (image is a link/button) | Describe the **action**: "View issue 14" |
| Complex (chart, diagram) | Short alt + the data in adjacent text/table |

- No autoplaying audio, ever. Video: captions on, pause control reachable by keyboard.
- `alt` text is copy — write it like copy (`content.md`), not like a filename. `"IMG_2841.jpg"` is slop.

---

## Motion & Vestibular Safety

Full system in `motion.md`. The accessibility floor:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- No parallax, no scroll-jacking, no autoplaying carousels without a pause — with or without the media query honored.
- Nothing flashes more than 3 times per second.
- Motion is never the only way information is conveyed.

---

## Touch & Zoom

- Touch targets ≥ **44×44px** (36px minimum where space is genuinely scarce, with ≥ 8px between targets).
- Do **not** disable pinch zoom: `content="width=device-width, initial-scale=1"` — no `maximum-scale`, no `user-scalable=no`.
- Respect `100%`–`200%` zoom and `320px` width without horizontal scroll (also in `layout.md` QA).
- Gestures need single-pointer alternatives — swipe is a bonus, not a requirement.

---

## Announcing Dynamic Changes

Agents build UIs that change silently. Screen readers must hear what changed:

| Change | Mechanism |
|---|---|
| Toast / saved state | `aria-live="polite"` region, always in the DOM, text swapped in |
| Form errors on submit | `aria-live` or move focus to the error summary |
| Search results count | Announce "12 results" politely |
| Route change (SPA) | Move focus to new `h1` (`tabindex="-1"`) |
| Critical failure | `role="alert"` (assertive) — use at most once per page |

```html
<div class="sr-only" aria-live="polite" id="live-status"></div>
```

---

## The Testing Protocol (15 minutes, before every ship)

1. **Keyboard pass:** unplug the mouse. Tab through everything. Reachable? Visible? Dismissible? Logical order?
2. **Screen reader pass:** VoiceOver (Mac: Cmd+F5) or NVDA (free, Windows). Navigate by headings and landmarks. Does the outline make sense?
3. **Contrast audit:** run axe DevTools or Lighthouse — zero violations, not "close enough."
4. **Zoom pass:** 200% browser zoom at 1280px — no clipped content, no horizontal scroll.
5. **Grayscale pass:** can you still tell error from success, primary from secondary?

---

## Accessibility Anti-Patterns

| ❌ Don't | ✅ Do |
|---|---|
| `<div onclick>` controls | `<button>` / `<a href>` |
| `outline: none` with no replacement | Designed `:focus-visible` on everything interactive |
| Placeholder as label | Persistent `<label>`, placeholder as example |
| `aria-label` on non-interactive elements | Visible text or `sr-only` text |
| Icon-only buttons with no name | `aria-label="Search"` |
| Headings chosen by visual size | One `h1`, ordered outline, CSS handles size |
| Color as the only error/status signal | Text + color, shape + color |
| Autoplay carousel, no pause | Static content or user-driven with pause |
| `user-scalable=no` in viewport meta | Leave zoom alone |
| Modals that don't trap or return focus | Trap inside, return to trigger, Escape closes |
| Live changes nobody announces | `aria-live` status region |
| Accessibility "added later" | Semantics from the first tag written |

---

## Ship Gate

- [ ] Keyboard pass complete — every control reachable, visible, dismissible
- [ ] One `h1`, ordered headings, landmarks present
- [ ] All inputs labeled; errors linked and actionable
- [ ] `:focus-visible` designed, never removed
- [ ] Contrast AA on text and 3:1 on interactive outlines, both themes
- [ ] `prefers-reduced-motion` honored
- [ ] Alt text on every meaningful image; decorative marked empty
- [ ] Dynamic changes announced; focus managed on dialogs and routes

Zero known violations. Not "minor issues" — zero. See `checklist.md` §Accessibility for the pre-ship list.
