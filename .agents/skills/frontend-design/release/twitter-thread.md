1/

I curated 7,842 lines of markdown to fight AI slop.

Not a product. Not a framework. A **skill file** for AI agents that build websites.

Because every AI agent I work with produces the same five patterns:

Purple-to-blue gradients. Centered hero. Three identical feature cards. "Trusted by 10,000+." Lorem ipsum in disguise.

That's not design. That's the default output of an LLM. 🧵

---

2/

The patterns are predictable because they're in every training set ten thousand times.

`linear-gradient(135deg, #667eea 0%, #764ba2 100%)` is the visual shorthand for "an AI made this."

`border-radius: 9999px` on every button is the structural shorthand for the same thing.

If your output looks like this, it doesn't matter how good your prompt was. It reads as generated.

---

3/

So I wrote a skill that says "no."

Not in a hand-wavy way. With **28 specific anti-patterns**, each with an example and a replacement.

Not "avoid generic design." Instead: *Purple-to-blue gradients are slop. Replace with warm paper + ink + editorial red.*

Not "use good typography." Instead: *Fraunces + Inter + JetBrains Mono. Hero at 60–160px. Display tracking -0.035em. All-caps tracking +0.14em.*

---

4/

It's modular. 18 files. Each loadable independently.

```
SKILL.md          Identity, principles, process
aesthetics.md     7 style directions
*-patterns.md     22 sub-styles (Linear, NYT Mag, Bandcamp, ...)
typography.md     Type system
color.md          Token system
layout.md         Grids, spacing, responsive
anti-patterns.md  What to reject
components.md     What to build
motion.md         What to animate
content.md        What to write
a11y + perf       The floors most agents skip
checklist.md      Pre-ship QA
```

The agent pulls only what it needs. Doesn't burn context on irrelevant guidance.

---

5/

The most important file is `aesthetics.md`.

It defines 7 directions — Refined Minimal, Editorial, Swiss, Brutalist, Soft, Technical, Playful — and tells the agent to **pick one, commit to it, don't mix them.**

Because "modern web design" as a single style is itself AI slop. The best sites are opinionated. The skill teaches the agent to be opinionated.

---

6/

It also teaches the agent to **write specific copy.**

❌ "Empowering businesses to thrive"
✅ "Ship features 3x faster"

❌ "Welcome to [Brand]"
✅ "Design that doesn't need explaining."

❌ "Fast. Simple. Beautiful."
✅ "A magazine for readers, not scrollers."

The cardinal rule: write the way you'd talk to a smart friend, not a marketing department.

---

7/

Last thing: a pre-ship checklist of 70+ items.

Not "does it look good?" — that's vibes. Specific questions:

- Hero headline 60–160px?
- One accent color, used <10% of pixels?
- No `transition: all`?
- Focus-visible defined on every interactive element?
- Real names, real numbers, no lorem ipsum?
- `prefers-reduced-motion` honored?
- Would a senior designer ship this?

If 6+ answers are "no" — keep iterating.

---

8/

It's open source. MIT license.

If you build AI agents that touch frontend — Cursor, Claude Code, Cline, custom — this should be in your context window.

If you design and use AI as a tool, this is the missing piece between "AI-generated" and "AI-assisted."

Link in next tweet. /fin

---

9/

[link to repo / gist]

If it works for you, ship something good with it. That's the thanks.

If it doesn't — open an issue. The skill is meant to evolve with the slop it pushes against.
