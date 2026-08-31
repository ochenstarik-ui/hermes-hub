# Changelog

All notable changes to this skill are documented here. Format follows [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added
- `code-style.md` — quality rules for AI-generated code, anti-slop patterns for code, comment style guide
- `minimal-ui-patterns.md` — 5 new sub-styles (Sublime, Height, Pitch, Figma, Notion)
- `editorial-patterns.md` — 6 editorial sub-styles (Pentagram, Bloomberg BW, NYT Mag, It's Nice That, Apartamento, The Gentlewoman)
- `brutalist-patterns.md` — 5 brutalist sub-styles (Bandcamp, Working Format, Bloomberg BW covers, Brutalist Websites gallery, Slam Jam)
- `product-ui-patterns.md` — code-first deep-dive into 10 Linear-style product UI components
- Russian translations for `README.md`
- `layout.md` — container system, spacing scale, grids and asymmetric splits, composition patterns, responsive strategy (mobile-first, 480/768/1024)
- `accessibility.md` — semantics, keyboard contracts, focus design, forms, ARIA minimalism, announcements, 15-minute testing protocol
- `performance.md` — budgets (LCP/INP/CLS, page weight), font loading, images, CSS/JS restraint, third-party costs, measuring
- `imagery.md` — the no-stock decision tree, CSS/SVG art direction vocabulary, photo art direction, icon systems, favicon & og-image
- `examples/example-swiss.html` — Swiss-style museum exhibition site (zero JavaScript) + `assets/screenshot-swiss.svg`

### Changed
- `SKILL.md` — added Agent Skills YAML frontmatter (`name`, `description`) for auto-discovery in Claude Code / claude.ai; process Steps 5–10 now reference `layout.md`, `accessibility.md`, `performance.md`, `imagery.md`; sub-skill table extended to 17 files; Quality Bar extended to 10 questions (accessibility + speed)
- `README.md` / `README.en.md` — accurate counts (18 files, 7,842 lines), new file table rows, Example 6, layout/a11y/perf steps, updated loading strategies
- Release notes (`release/`) — updated stale counts

### Fixed
- Mixed-language title in `brutalist-patterns.md` (English heading now consistent)
- `README.md` no longer marks `README.en.md` as "in progress" — the English version is complete


## [1.0.0] — 2026-04-15

### Added
- `SKILL.md` — core principles, process, identity
- `aesthetics.md` — 7 high-level style directions
- `typography.md` — typefaces, scale, pairs, anti-patterns
- `color.md` — token system, palettes, contrast, dark mode
- `anti-patterns.md` — 28 AI-slop patterns with before/after
- `components.md` — buttons, forms, cards, navigation, states
- `motion.md` — animation, easing, accessibility
- `content.md` — headlines, body copy, CTAs, microcopy
- `checklist.md` — pre-ship QA
- `minimal-ui-patterns.md` — initial 6 sub-styles (Linear, Stripe, Vercel, Arc, Mercury, Cron)

### Notes
First public release. 11 files, ~3,400 lines. Built from patterns observed across Linear, Stripe, Vercel, Arc, Pentagram, Müller-Brockmann, NYT Magazine, and others.
