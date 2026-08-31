# Contributing

Thanks for considering a contribution. This skill lives from people who spot slop, document it, and ship better patterns.

## What this repo is

A collection of markdown files that teach AI agents how to build websites that read as designed, not generated. The files are designed to be **loadable independently** — agents can pull just what they need.

## What we accept

- **New anti-patterns** with before/after examples. If you saw an AI ship it, we want it documented.
- **Refinements to existing rules** that make them more specific or more actionable.
- **New sub-styles** in `aesthetics.md` or one of the `*-patterns.md` files — with real references, real palettes, real typography.
- **New components** in `product-ui-patterns.md` or `components.md` — with HTML, CSS, and all states.
- **New motion patterns** in `motion.md` — with timing, easing, accessibility considerations.
- **Translations.** The skill is currently English-first. Russian, Chinese, Spanish, Japanese are all welcome.

## What we don't accept

- Generic design advice ("use whitespace", "be consistent") without specifics.
- Patterns without references or concrete examples.
- Copy that could apply to any product ("empowering teams to thrive").
- AI-slop patterns in the skill itself. If your PR introduces vague platitudes, it will be closed.

## Style guide for contributions

When writing for this repo, follow the same principles the repo teaches:

- **Specific > general.** Numbers, names, dates, real references.
- **One accent > many neutrals.** Pick a pattern, commit to it.
- **Asymmetry > symmetry.** Don't center everything.
- **Restraint > decoration.** Every line must earn its place.

## How to add an anti-pattern

The best contributions are new anti-patterns. Format:

```markdown
### [Number]. [Name of anti-pattern]

**Slop signature:** What does the AI-shipped version look like? Be specific.

**Why it's slop:** Why does this read as "AI generated"?

**Replace with:** The specific replacement. Concrete values where possible.
```

See `anti-patterns.md` for 28 examples.

## How to add a sub-style

Sub-styles live in `minimal-ui-patterns.md`, `editorial-patterns.md`, or `brutalist-patterns.md`. Each must have:

- **Live reference** (URL to a real product/studio that exemplifies it)
- **When to choose** (specific audience, project type)
- **Palette** (concrete hex tokens)
- **Typography** (specific typefaces, weights, sizes)
- **Layout patterns** (max-width, hero pattern, sidebar pattern)
- **Signature patterns** (what makes this sub-style recognizable)
- **Hallmarks** (what to preserve)
- **Anti-patterns** (what breaks the sub-style)

## Pull request process

1. Fork the repo.
2. Create a branch: `git checkout -b add-new-anti-pattern-x`.
3. Make your changes.
4. Run through `checklist.md` mentally for your own contribution.
5. Open a PR with a specific title: "Add: emoji-as-icon anti-pattern" not "Update docs".
6. Describe what you added and why. Link to real examples where possible.

## Reporting issues

Found an anti-pattern we missed? Open an issue with:

- The pattern (what the AI shipped)
- A real example (link or screenshot if possible)
- Your proposed fix

## Code of conduct

- Be specific. "This is bad" is not feedback. "This violates the 8px grid system because the buttons use 7px padding" is.
- Reference real work. If you critique, cite.
- No marketing language. We're documenting slop to fight it, not adding to it.
