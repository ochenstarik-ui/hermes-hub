# Product UI Patterns — Linear-style components, in code

> A practical deep-dive into the components that make Linear-style product UI feel considered. Each pattern includes concrete HTML + CSS, all states, and what to avoid. Use this when building product chrome (sidebar, command palette, lists, modals) — not for marketing pages.

---

## How to use this file

This file is **code-first**. When you need to build a sidebar, command palette, segmented control, or status indicator for a Linear-style product, come here.

Each component has:
1. **When to use it**
2. **Anatomy** (what it's made of)
3. **HTML** (semantic markup)
4. **CSS** (with tokens, all states)
5. **States covered** (default, hover, focus, active, disabled, loading)
6. **Anti-patterns** (what breaks the pattern)

All CSS assumes the Linear-style dark token system (see `minimal-ui-patterns.md` §1 for tokens). Adapt colors to your palette.

---

## 1. Sidebar (navigation)

**Used in:** Linear, Notion, Figma, most SaaS apps.

### Anatomy
- Container with hairline right border
- Section labels (in caps mono, wide tracking)
- List of nav items (icon + label)
- Active state (background tint or left accent border)
- Hover state (subtle background tint)
- Footer (user avatar, workspace switcher)

### HTML

```html
<aside class="sidebar" aria-label="Primary navigation">
  <div class="sidebar__inner">
    <header class="sidebar__head">
      <button class="workspace-switch" aria-label="Switch workspace">
        <span class="workspace-mark">◆</span>
        <span class="workspace-name">Acme</span>
        <span class="workspace-chevron">⌄</span>
      </button>
    </header>

    <nav class="sidebar__nav">
      <div class="sidebar__section">
        <p class="sidebar__label">Workspace</p>
        <ul role="list">
          <li>
            <a href="#" class="sidebar__item sidebar__item--active">
              <svg class="sidebar__icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                <rect x="2" y="2" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/>
              </svg>
              <span>Inbox</span>
              <span class="sidebar__count">12</span>
            </a>
          </li>
          <li>
            <a href="#" class="sidebar__item">
              <svg class="sidebar__icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
              </svg>
              <span>My issues</span>
            </a>
          </li>
        </ul>
      </div>

      <div class="sidebar__section">
        <p class="sidebar__label">Your teams</p>
        <ul role="list">
          <li>
            <a href="#" class="sidebar__item">
              <span class="sidebar__team-mark">▲</span>
              <span>Engineering</span>
            </a>
          </li>
        </ul>
      </div>
    </nav>

    <footer class="sidebar__foot">
      <button class="user-menu" aria-label="User menu">
        <span class="avatar">JD</span>
        <span class="user-menu__name">Jane Doe</span>
      </button>
    </footer>
  </div>
</aside>
```

### CSS

```css
.sidebar {
  width: 240px;
  height: 100vh;
  background: var(--surface-1);
  border-right: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
}

.sidebar__inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--sp-3);
}

.sidebar__head {
  padding: var(--sp-2) var(--sp-3);
  margin-bottom: var(--sp-3);
}

.workspace-switch {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--ink);
  transition: background 120ms ease;
}
.workspace-switch:hover { background: var(--surface-2); }
.workspace-switch:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

.workspace-mark { color: var(--accent); }
.workspace-name { flex: 1; text-align: left; }
.workspace-chevron { color: var(--ink-muted); font-size: 11px; }

.sidebar__nav { flex: 1; overflow-y: auto; }

.sidebar__section { margin-bottom: var(--sp-5); }

.sidebar__label {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-subtle);
  padding: 0 var(--sp-3);
  margin-bottom: var(--sp-2);
  font-weight: 500;
}

.sidebar__section ul { list-style: none; margin: 0; padding: 0; }

.sidebar__item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 6px var(--sp-3);
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  color: var(--ink-muted);
  text-decoration: none;
  transition: background 100ms ease, color 100ms ease;
}

.sidebar__item:hover {
  background: var(--surface-2);
  color: var(--ink);
}

.sidebar__item:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.sidebar__item--active {
  background: var(--accent-soft);
  color: var(--ink);
  font-weight: 500;
}

.sidebar__icon { color: currentColor; flex-shrink: 0; }

.sidebar__count {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--surface-2);
  color: var(--ink-muted);
}

.sidebar__team-mark {
  font-size: 11px;
  color: var(--ink-muted);
  width: 16px;
  text-align: center;
}

.sidebar__foot {
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-3);
  margin-top: var(--sp-3);
}

.user-menu {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  font-size: var(--text-sm);
  color: var(--ink);
  transition: background 120ms ease;
}
.user-menu:hover { background: var(--surface-2); }

.avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--surface);
  font-size: 10px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-menu__name { flex: 1; text-align: left; }
```

### Anti-patterns
- ❌ Sidebar > 280px wide (consumes too much horizontal space)
- ❌ Active state as bold text only (no background or border)
- ❌ Icon-only nav without tooltips
- ❌ Section labels in regular case (must be mono caps with tracking)
- ❌ Hover state that shifts layout (causes jank)

---

## 2. Command palette (⌘K)

**Used in:** Linear, GitHub, Vercel, Raycast, every modern SaaS.

### Anatomy
- Centered modal, max-width 560–640px
- Input field at top, large, no border
- List of results below, keyboard-driven
- Keyboard shortcuts visible on right side of each row
- Categories separated by hairline + section label
- Empty state for "no results"

### HTML

```html
<div class="command-palette" role="dialog" aria-modal="true" aria-labelledby="cp-title">
  <div class="command-palette__backdrop"></div>
  <div class="command-palette__panel">
    <h2 id="cp-title" class="sr-only">Command palette</h2>

    <div class="cp-input-wrap">
      <svg class="cp-search-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.5"/>
        <line x1="11" y1="11" x2="14" y2="14" stroke="currentColor" stroke-width="1.5"/>
      </svg>
      <input
        type="text"
        class="cp-input"
        placeholder="Search or jump to anywhere…"
        aria-label="Search"
        autofocus
      >
      <kbd class="cp-esc">esc</kbd>
    </div>

    <div class="cp-results">
      <div class="cp-group">
        <p class="cp-group__label">Recent</p>
        <ul role="list">
          <li class="cp-result cp-result--selected">
            <span class="cp-result__icon">▢</span>
            <span class="cp-result__main">
              <span class="cp-result__title">ENG-1421</span>
              <span class="cp-result__sub">Reduce LCP on checkout page</span>
            </span>
            <span class="cp-result__meta">2h ago</span>
            <kbd class="cp-result__kbd">↵</kbd>
          </li>
          <!-- More results -->
        </ul>
      </div>

      <div class="cp-group">
        <p class="cp-group__label">Actions</p>
        <ul role="list">
          <li class="cp-result">
            <span class="cp-result__icon">+</span>
            <span class="cp-result__main">
              <span class="cp-result__title">Create new issue</span>
            </span>
            <kbd class="cp-result__kbd">C</kbd>
          </li>
        </ul>
      </div>
    </div>

    <footer class="cp-foot">
      <span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span>
      <span><kbd>↵</kbd> Select</span>
      <span><kbd>esc</kbd> Close</span>
    </footer>
  </div>
</div>
```

### CSS

```css
.command-palette {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}

.command-palette__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(2px);
}

.command-palette__panel {
  position: relative;
  width: 100%;
  max-width: 600px;
  background: var(--surface-1);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--r-lg);
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.5);
  overflow: hidden;
  animation: cp-in 140ms ease-out;
}

@keyframes cp-in {
  from { opacity: 0; transform: scale(0.98) translateY(-8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

.cp-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--hairline);
}

.cp-search-icon { color: var(--ink-muted); flex-shrink: 0; }

.cp-input {
  flex: 1;
  font-size: var(--text-md);
  color: var(--ink);
  background: transparent;
  border: 0;
  outline: 0;
}
.cp-input::placeholder { color: var(--ink-subtle); }

.cp-esc {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--surface-2);
  border: 1px solid var(--hairline);
  color: var(--ink-muted);
}

.cp-results {
  max-height: 60vh;
  overflow-y: auto;
  padding: var(--sp-3);
}

.cp-group { margin-bottom: var(--sp-3); }
.cp-group:last-child { margin-bottom: 0; }

.cp-group__label {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-subtle);
  padding: var(--sp-2) var(--sp-3);
  margin: 0;
  font-weight: 500;
}

.cp-group ul { list-style: none; margin: 0; padding: 0; }

.cp-result {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border-radius: var(--r-sm);
  cursor: pointer;
  font-size: var(--text-sm);
  transition: background 80ms ease;
}

.cp-result:hover { background: var(--surface-2); }
.cp-result--selected { background: var(--accent-soft); }
.cp-result--selected .cp-result__title { color: var(--accent); }

.cp-result__icon {
  width: 20px;
  height: 20px;
  border-radius: 3px;
  background: var(--surface-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--ink-muted);
  flex-shrink: 0;
}

.cp-result__main { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.cp-result__title { color: var(--ink); font-weight: 500; }
.cp-result__sub { color: var(--ink-muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.cp-result__meta { font-family: var(--font-mono); font-size: 11px; color: var(--ink-subtle); }

.cp-result__kbd {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
  background: var(--surface-2);
  border: 1px solid var(--hairline);
  color: var(--ink-muted);
}

.cp-foot {
  display: flex;
  gap: var(--sp-5);
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--hairline);
  font-size: 11px;
  color: var(--ink-subtle);
}

.cp-foot kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--surface-2);
  border: 1px solid var(--hairline);
  margin-right: 4px;
}
```

### Behavior (JS sketch)

```js
// Open on ⌘K / Ctrl+K
// Close on Esc or click outside
// Up/Down to navigate
// Enter to select
// Auto-focus input on open
// Reset query on close
```

### Anti-patterns
- ❌ Backdrop too dark (0.7+) — feels oppressive
- ❌ Animation > 200ms (feels slow for power-user feature)
- ❌ No keyboard navigation (this is a keyboard-first feature)
- ❌ Hidden close button (must be discoverable)
- ❌ Results without categories (hard to scan)
- ❌ No "no results" empty state

---

## 3. Empty states

**Used in:** Every list view, dashboard, settings page.

### Anatomy
- Centered or left-aligned container
- Single illustration or geometric icon (subtle, restrained)
- One headline explaining what should be here
- One sentence of context (optional)
- One primary action button
- Optional secondary link (e.g., "Read docs")

### HTML

```html
<div class="empty-state" role="status">
  <div class="empty-state__icon" aria-hidden="true">
    <!-- Geometric SVG, ~64px -->
    <svg width="64" height="64" viewBox="0 0 64 64">
      <rect x="8" y="8" width="48" height="48" rx="6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4"/>
      <line x1="20" y1="24" x2="44" y2="24" stroke="currentColor" stroke-width="1.5"/>
      <line x1="20" y1="32" x2="36" y2="32" stroke="currentColor" stroke-width="1.5"/>
      <line x1="20" y1="40" x2="40" y2="40" stroke="currentColor" stroke-width="1.5"/>
    </svg>
  </div>

  <h3 class="empty-state__title">No issues yet</h3>
  <p class="empty-state__desc">Issues track the work your team needs to do. Create your first one to get started.</p>

  <div class="empty-state__actions">
    <button class="btn btn--primary">Create issue</button>
    <a href="#" class="empty-state__link">Read the docs →</a>
  </div>
</div>
```

### CSS

```css
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--sp-9) var(--sp-5);
  max-width: 400px;
  margin: 0 auto;
}

.empty-state__icon {
  color: var(--ink-subtle);
  margin-bottom: var(--sp-5);
}

.empty-state__title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--ink);
  margin: 0 0 var(--sp-2) 0;
  letter-spacing: -0.01em;
}

.empty-state__desc {
  font-size: var(--text-sm);
  color: var(--ink-muted);
  line-height: 1.5;
  margin: 0 0 var(--sp-5) 0;
}

.empty-state__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}

.empty-state__link {
  font-size: var(--text-sm);
  color: var(--ink-muted);
  text-decoration: none;
  border-bottom: 1px solid var(--hairline);
  padding-bottom: 1px;
  transition: color 120ms ease, border-color 120ms ease;
}

.empty-state__link:hover {
  color: var(--accent);
  border-color: var(--accent);
}
```

### Anti-patterns
- ❌ Stock illustration of confused person
- ❌ Sad emoji
- ❌ Two action buttons competing
- ❌ Empty state that says "No data" (meaningless)
- ❌ Centered illustration that's huge (200px+) — feels desperate

---

## 4. List items

**Used in:** Inbox, tables-of-contents, search results, settings lists.

### Anatomy
- 40–48px row height
- Single line of primary content
- Optional secondary line (subdued)
- Left: icon or status indicator
- Right: metadata or actions
- Hairline divider between rows
- Hover: subtle background tint
- Selected: accent-tinted background

### HTML

```html
<ul class="list" role="list">
  <li class="list__item">
    <a href="#" class="list__link">
      <span class="list__status list__status--in-progress" aria-label="In progress"></span>
      <span class="list__main">
        <span class="list__id">ENG-1421</span>
        <span class="list__title">Reduce LCP on checkout page</span>
      </span>
      <span class="list__priority" aria-label="High priority">
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
          <path d="M7 2 L12 12 L2 12 Z" fill="currentColor"/>
        </svg>
      </span>
      <span class="list__assignee">
        <span class="avatar avatar--xs">JD</span>
      </span>
      <time class="list__date" datetime="2026-04-12">Apr 12</time>
    </a>
  </li>
  <!-- More items -->
</ul>
```

### CSS

```css
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--hairline);
}

.list__item {
  border-bottom: 1px solid var(--hairline);
}

.list__link {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto auto auto;
  gap: var(--sp-3);
  align-items: center;
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--text-sm);
  color: var(--ink);
  text-decoration: none;
  transition: background 100ms ease;
}

.list__link:hover {
  background: var(--surface-2);
}

.list__link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.list__status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.list__status--todo        { background: var(--ink-subtle); }
.list__status--in-progress { background: var(--warn); }
.list__status--done        { background: var(--good); }
.list__status--blocked     { background: var(--bad); }

.list__main {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  min-width: 0;
}

.list__id {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-subtle);
  flex-shrink: 0;
}

.list__title {
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list__priority {
  color: var(--warn);
  display: inline-flex;
}

.list__assignee { display: inline-flex; }

.avatar--xs {
  width: 18px;
  height: 18px;
  font-size: 9px;
}

.list__date {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-subtle);
  white-space: nowrap;
}
```

### Anti-patterns
- ❌ Row height > 56px (consumes too much space)
- ❌ Multiple status indicators stacked
- ❌ Right-side metadata that wraps
- ❌ Hover that shifts content (causes jank)
- ❌ Border between every row + border-radius (conflicting)

---

## 5. Status indicators (badges, dots, pills)

**Used in:** Issue trackers, project management, notifications.

### Anatomy — three types

**Dot** (8px circle, semantic color)
- Inbox counts, status indicators, presence
- One color, no text

**Badge** (rounded rectangle with text)
- Status labels ("In review", "Blocked")
- Small (11–12px text), padded

**Pill** (full-rounded rectangle with text)
- Tags, categories
- Slightly larger than badge

### HTML + CSS

```html
<!-- Dot -->
<span class="status-dot status-dot--in-progress" aria-label="In progress"></span>

<!-- Badge -->
<span class="status-badge status-badge--review">In review</span>

<!-- Pill / tag -->
<span class="tag">Engineering</span>
```

```css
/* Dot */
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot--todo        { background: var(--ink-subtle); }
.status-dot--in-progress { background: var(--warn); }
.status-dot--done        { background: var(--good); }
.status-dot--blocked     { background: var(--bad); }

/* Badge */
.status-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--r-sm);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0;
  white-space: nowrap;
}

.status-badge--todo        { background: var(--surface-2); color: var(--ink-muted); }
.status-badge--in-progress { background: rgba(251, 191, 36, 0.15); color: var(--warn); }
.status-badge--review      { background: rgba(99, 91, 255, 0.15); color: var(--accent); }
.status-badge--done        { background: rgba(76, 183, 130, 0.15); color: var(--good); }
.status-badge--blocked     { background: rgba(248, 113, 113, 0.15); color: var(--bad); }

/* Pill / tag */
.tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 10px;
  border-radius: 9999px;     /* pill is OK for tags — they're meant to be pills */
  font-size: 12px;
  font-weight: 500;
  background: var(--surface-2);
  color: var(--ink-muted);
  border: 1px solid var(--hairline);
}
```

### Anti-patterns
- ❌ Using pill on every interactive element (only for tags/categories)
- ❌ Too many color states (stick to 3–4 semantic colors)
- ❌ Badges with no text (just a dot) — ambiguous
- ❌ Text inside badges too long (truncate or shorten label)

---

## 6. Segmented control

**Used in:** Time range selectors (1h / 24h / 7d / 30d), view toggles.

### Anatomy
- Container with hairline border, subtle background
- Buttons inside, equal-width or content-width
- Active button: surface background, slight shadow
- Hover: ink color change
- Mono font for time labels (technical feel)

### HTML

```html
<div class="segmented" role="tablist" aria-label="Time range">
  <button role="tab" aria-selected="false" class="segmented__btn">1h</button>
  <button role="tab" aria-selected="false" class="segmented__btn">24h</button>
  <button role="tab" aria-selected="true"  class="segmented__btn segmented__btn--active">7d</button>
  <button role="tab" aria-selected="false" class="segmented__btn">30d</button>
</div>
```

### CSS

```css
.segmented {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--hairline);
  border-radius: var(--r-sm);
  padding: 2px;
  gap: 0;
}

.segmented__btn {
  padding: 4px 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  border-radius: 3px;
  transition: color 120ms ease, background 120ms ease;
  white-space: nowrap;
}

.segmented__btn:hover { color: var(--ink); }

.segmented__btn--active {
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

.segmented__btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
```

### Anti-patterns
- ❌ Active state as bold text only (no background change)
- ❌ Buttons without aria-selected (a11y failure)
- ❌ Sans font for time labels (mono reads as more precise)
- ❌ Animated transitions on click (sluggish for power users)

---

## 7. Tables (data tables)

**Used in:** Settings, admin panels, lists with structured data.

### Anatomy
- Header row: caps mono, muted, smaller text
- Body rows: 48px height, hairline bottom border
- Numbers: mono font, tabular figures, right-aligned
- Text columns: left-aligned
- Hover row: subtle background tint
- Action column: right-aligned, icon buttons or text links

### HTML

```html
<table class="data-table">
  <thead>
    <tr>
      <th>Name</th>
      <th>Role</th>
      <th>Last active</th>
      <th class="data-table__num">Sessions</th>
      <th class="data-table__actions"></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Jane Doe</td>
      <td>Admin</td>
      <td>2 hours ago</td>
      <td class="data-table__num">1,247</td>
      <td class="data-table__actions">
        <button class="icon-btn" aria-label="Edit Jane Doe">
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path d="M2 10 L2 12 L4 12 L10 6 L8 4 L2 10 Z" fill="currentColor"/>
          </svg>
        </button>
      </td>
    </tr>
  </tbody>
</table>
```

### CSS

```css
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.data-table thead th {
  text-align: left;
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-muted);
  font-weight: 500;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
}

.data-table tbody td {
  padding: var(--sp-4);
  border-bottom: 1px solid var(--hairline);
  color: var(--ink);
  vertical-align: middle;
}

.data-table tbody tr {
  transition: background 80ms ease;
}

.data-table tbody tr:hover {
  background: var(--surface-2);
}

.data-table__num {
  text-align: right;
  font-family: var(--font-mono);
  font-feature-settings: 'tnum' 1;
}

.data-table__actions {
  text-align: right;
  width: 40px;
}

.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  color: var(--ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 120ms ease, color 120ms ease;
}

.icon-btn:hover {
  background: var(--surface-2);
  color: var(--ink);
}

.icon-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
```

### Anti-patterns
- ❌ Full grid of borders (looks like Excel)
- ❌ Centered data cells (left-align text, right-align numbers)
- ❌ Wrapping headers (use shorter labels)
- ❌ Inconsistent row heights
- ❌ Sortable columns without visual indicator

---

## 8. Modal / dialog

**Used in:** Create flows, confirmations, settings panels.

### Anatomy
- Centered, max-width 480–560px (forms), 720px+ (content)
- Backdrop: rgba(0,0,0, 0.4–0.6)
- Surface: elevated panel
- Border-radius: 8–12px
- Padding: 24–32px
- Close: X button (top-right) + Esc key
- Focus trap (keyboard focus stays inside)
- Animation: fade + slight scale (0.98 → 1), 150ms

### HTML

```html
<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <div class="modal__backdrop"></div>
  <div class="modal__panel">
    <header class="modal__head">
      <h2 id="modal-title" class="modal__title">Create new issue</h2>
      <button class="modal__close" aria-label="Close">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <line x1="3" y1="3" x2="13" y2="13" stroke="currentColor" stroke-width="1.5"/>
          <line x1="13" y1="3" x2="3" y2="13" stroke="currentColor" stroke-width="1.5"/>
        </svg>
      </button>
    </header>

    <div class="modal__body">
      <!-- Form content -->
    </div>

    <footer class="modal__foot">
      <button class="btn btn--ghost">Cancel</button>
      <button class="btn btn--primary">Create issue</button>
    </footer>
  </div>
</div>
```

### CSS

```css
.modal {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-5);
}

.modal__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  animation: modal-backdrop-in 150ms ease-out;
}

@keyframes modal-backdrop-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

.modal__panel {
  position: relative;
  width: 100%;
  max-width: 520px;
  background: var(--surface-1);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--r-lg);
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  max-height: 90vh;
  animation: modal-panel-in 180ms ease-out;
}

@keyframes modal-panel-in {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}

.modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-5) var(--sp-6);
  border-bottom: 1px solid var(--hairline);
}

.modal__title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
  letter-spacing: -0.01em;
}

.modal__close {
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  color: var(--ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 120ms ease, color 120ms ease;
}

.modal__close:hover { background: var(--surface-2); color: var(--ink); }
.modal__close:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

.modal__body {
  padding: var(--sp-6);
  overflow-y: auto;
  flex: 1;
}

.modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-6);
  border-top: 1px solid var(--hairline);
}
```

### Anti-patterns
- ❌ Backdrop > 0.6 opacity (oppressive)
- ❌ Animation > 250ms (feels slow)
- ❌ No Esc key handler
- ❌ No focus trap (Tab escapes modal)
- ❌ Two competing primary buttons in footer
- ❌ Modal that can't scroll on small screens

---

## 9. Form inputs (Linear-style)

**Used in:** All forms, settings, search.

### Anatomy
- 36–40px height
- 1px hairline-strong border, surface-sunken background
- Border-radius: 6px
- Focus: border becomes accent, 2px focus ring with offset
- Label above input, mono caps, small
- Help text below, smaller, muted

### HTML

```html
<div class="field">
  <label for="title" class="field__label">Title</label>
  <input
    id="title"
    type="text"
    class="field__input"
    placeholder="What needs to be done?"
    value=""
  >
  <p class="field__help">Use a verb-led sentence. "Fix checkout error" not "Checkout error".</p>
</div>

<div class="field">
  <label for="status" class="field__label">Status</label>
  <select id="status" class="field__select">
    <option>Backlog</option>
    <option selected>In progress</option>
    <option>In review</option>
    <option>Done</option>
  </select>
</div>
```

### CSS

```css
.field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin-bottom: var(--sp-5);
}

.field__label {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-muted);
  font-weight: 500;
}

.field__input,
.field__select,
.field__textarea {
  width: 100%;
  height: 36px;
  padding: 0 var(--sp-3);
  background: var(--surface-sunken);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--r-md);
  font-size: var(--text-sm);
  color: var(--ink);
  transition: border-color 120ms ease, background 120ms ease;
}

.field__input::placeholder { color: var(--ink-subtle); }

.field__input:hover,
.field__select:hover { border-color: var(--ink-muted); }

.field__input:focus,
.field__select:focus {
  border-color: var(--accent);
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.field__input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.field__textarea {
  height: auto;
  min-height: 80px;
  padding: var(--sp-3);
  resize: vertical;
  font-family: inherit;
  line-height: 1.5;
}

.field__help {
  font-size: 12px;
  color: var(--ink-subtle);
  margin: 0;
  line-height: 1.4;
}

.field--error .field__input,
.field--error .field__select {
  border-color: var(--bad);
}

.field--error .field__help {
  color: var(--bad);
}
```

### Anti-patterns
- ❌ Placeholder as label (loses on focus)
- ❌ Label inside input (accessibility disaster)
- ❌ No focus state (browser default is fine but design your own)
- ❌ Border that disappears on focus with no replacement
- ❌ Native select without styling (looks like 2005)

---

## 10. Notifications (toasts)

**Used in:** Action confirmations, alerts, system messages.

### Anatomy
- Fixed position (top-right or bottom-right)
- Slides in from edge, fades out on auto-dismiss
- Icon + title + optional description + close button
- Severity variants: info, success, warning, error
- Auto-dismiss after 4–6s (with progress bar)
- Stack vertically if multiple

### HTML

```html
<div class="toast toast--success" role="status" aria-live="polite">
  <span class="toast__icon" aria-hidden="true">✓</span>
  <div class="toast__body">
    <p class="toast__title">Issue created</p>
    <p class="toast__desc">ENG-1421 has been added to your backlog.</p>
  </div>
  <button class="toast__close" aria-label="Dismiss">
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <line x1="3" y1="3" x2="11" y2="11" stroke="currentColor" stroke-width="1.5"/>
      <line x1="11" y1="3" x2="3" y2="11" stroke="currentColor" stroke-width="1.5"/>
    </svg>
  </button>
  <div class="toast__progress" aria-hidden="true"></div>
</div>
```

### CSS

```css
.toast {
  position: fixed;
  bottom: var(--sp-5);
  right: var(--sp-5);
  z-index: 90;
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  width: 360px;
  padding: var(--sp-4);
  background: var(--surface-1);
  border: 1px solid var(--hairline-strong);
  border-radius: var(--r-lg);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  animation: toast-in 200ms ease-out;
}

@keyframes toast-in {
  from { opacity: 0; transform: translateX(20px); }
  to   { opacity: 1; transform: translateX(0); }
}

.toast--success { border-left: 3px solid var(--good); }
.toast--warning { border-left: 3px solid var(--warn); }
.toast--error   { border-left: 3px solid var(--bad); }
.toast--info    { border-left: 3px solid var(--accent); }

.toast__icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.toast--success .toast__icon { background: var(--good); color: var(--surface); }
.toast--warning .toast__icon { background: var(--warn); color: var(--surface); }
.toast--error   .toast__icon { background: var(--bad);  color: var(--surface); }
.toast--info    .toast__icon { background: var(--accent); color: var(--surface); }

.toast__body { flex: 1; min-width: 0; }
.toast__title { font-size: var(--text-sm); font-weight: 600; color: var(--ink); margin: 0 0 2px 0; }
.toast__desc  { font-size: 12px; color: var(--ink-muted); margin: 0; line-height: 1.4; }

.toast__close {
  color: var(--ink-muted);
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  transition: background 120ms ease, color 120ms ease;
}

.toast__close:hover { background: var(--surface-2); color: var(--ink); }

.toast__progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  background: var(--accent);
  animation: toast-progress 5s linear forwards;
}

@keyframes toast-progress {
  from { width: 100%; }
  to   { width: 0; }
}
```

### Anti-patterns
- ❌ Toasts that don't auto-dismiss (stale UI)
- ❌ Toasts at top-center (covers content)
- ❌ Bouncy entrance animation (distracting)
- ❌ No severity distinction (all toasts look the same)
- ❌ No close button (user feels trapped)

---

## Component states summary

Every component above must have:

| State | Treatment |
|---|---|
| **Default** | As designed |
| **Hover** | Subtle background tint or border strengthen |
| **Focus-visible** | 2px accent ring, 1–2px offset |
| **Active / pressed** | `transform: scale(0.98)` 80ms OR slight darken |
| **Disabled** | Opacity 0.5, no hover, `cursor: not-allowed` |
| **Loading** | Spinner OR skeleton, never both |
| **Empty** | One sentence + one action (see §3) |
| **Error** | Border + text in `--bad`, specific message |

If any state is missing, the design breaks on the edges. Don't ship without all 8.

---

## Component checklist (before shipping)

For every component on the page, verify:

- [ ] All 8 states defined
- [ ] Keyboard accessible (Tab, Enter, Escape where applicable)
- [ ] Screen reader labels (`aria-label` on icon-only)
- [ ] Touch targets ≥ 44×44px on mobile
- [ ] No layout shift on hover/focus
- [ ] Reduced motion respected
- [ ] Tested in light AND dark theme

---

## What to read next

- For token system → `color.md`
- For typography setup → `typography.md`
- For motion → `motion.md`
- For anti-patterns → `anti-patterns.md`
- For specific sub-styles → `minimal-ui-patterns.md`, `editorial-patterns.md`, `brutalist-patterns.md`
- For final QA → `checklist.md`
