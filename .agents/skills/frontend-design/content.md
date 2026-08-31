# Content — Specific, Real, Useful

> The design is the container. The content is the reason. If the words are slop, the design can't save them.

---

## The Cardinal Rule

**Write content the way you'd talk to a smart friend who asked "what is this?" — not the way a marketing department writes.**

Before writing any copy, ask:
- What does this product DO? (specific verb, specific object)
- Who is it FOR? (specific person, not "users" or "businesses")
- WHY should they care? (specific outcome, not "saving time")

---

## Headlines

The headline is the page. It's the one piece of copy users actually read.

### The four patterns that work

**1. The claim**
Make a specific promise.
- "Ship features 3x faster"
- "Cut your AWS bill in half"
- "Find any bug in under 60 seconds"
- "The invoicing app for people who hate invoicing"

**2. The user**
Name the specific person.
- "For designers who'd rather think than fiddle."
- "The trading platform built for serious retail traders."
- "Email for people who send 200 emails a day."

**3. The contrast**
Position against the alternative.
- "Stop writing CSS. Start describing what you want."
- "The CRM that doesn't feel like a spreadsheet."
- "A wiki that's actually fun to write in."

**4. The specific weirdness**
Say something only this product could say.
- "Less software, more wood."
- "Open tabs: 47. Active tabs: 3. (We close the rest.)"
- "Postgres, but it's 2026."

### Headlines anti-patterns

| ❌ Don't | ✅ Do |
|---|---|
| "Welcome to [Brand]" | Specific claim or user statement |
| "The platform for [audience]" | "For [specific person] who [specific need]" |
| "Empowering businesses to thrive" | "Cut your [specific thing] by [specific number]" |
| "Built for the modern [audience]" | "Built for [specific audience] doing [specific thing]" |
| "Revolutionizing the [industry]" | Specific outcome, named |
| "Fast. Simple. Beautiful." | One true adjective, or a sentence |
| "The future of [thing] is here" | Anything else |

### Headlines checklist

- [ ] Does it make a claim?
- [ ] Is the claim specific?
- [ ] Could a competitor use the same headline? (If yes, rewrite.)
- [ ] Is it under 12 words? (Ideal: 6–10 words. Hard cap: 15.)
- [ ] Does it work without the surrounding context? (If someone screenshots just the headline, does it still communicate?)

---

## Subheads

The subhead explains the headline or adds context. Two jobs:

1. **Extend the headline** — add the "how" or "why" or "for whom"
2. **Earn the click** — give enough detail that the reader knows what's next

### Examples

Headline: "Ship features 3x faster"
Subhead: "Linear's AI agents handle issue triage, status updates, and standup notes — so your team ships instead of plans."

Headline: "The invoicing app for people who hate invoicing"
Subhead: "Made for designers, writers, and freelancers who'd rather be making things than chasing payments."

Headline: "Stop writing CSS. Start describing what you want."
Subhead: "Tempo turns Figma designs into production-ready components — no round-trip, no translation loss."

### Subheads anti-patterns
- ❌ Restating the headline in different words
- ❌ Generic context: "We help businesses..."
- ❌ Two sentences that could be one
- ❌ A second claim that contradicts or competes with the headline

---

## Body Copy

### Rules

1. **Specific > general.** "We saved 12 hours a week" beats "We saved time."
2. **Short sentences.** Mix short and long. Never three long sentences in a row.
3. **One idea per paragraph.** If a paragraph has two ideas, split it.
4. **Left-aligned, ragged right.** Never justified. Never centered (except short quotes).
5. **Active voice.** "We shipped X" beats "X was shipped."
6. **Cut every word that doesn't earn its place.** Read aloud. If you stumble, rewrite.

### Structure

For landing pages:
- Lead with the most important sentence
- One idea per paragraph
- Short paragraphs (2–4 sentences)
- Use lists / structured content where appropriate

For long-form (articles, docs):
- Strong first sentence — not a throat-clearing intro
- Subheadings every 200–400 words
- Pull quotes for emphasis
- Images / diagrams to break up text

### Body copy anti-patterns
- ❌ Lorem ipsum left in production
- ❌ Throat-clearing intros: "In today's fast-paced world..."
- ❌ Three adjectives in a row: "fast, simple, beautiful"
- ❌ Buzzwords: "leverage," "synergy," "ecosystem," "paradigm," "disrupt"
- ❌ Empty intensifiers: "very," "really," "extremely," "incredibly"
- ❌ Vague pronouns: "this," "it," "that" without clear referent

---

## Calls to Action (CTAs)

### The label is the promise

❌ "Submit" → ✅ "Get my report"
❌ "Learn more" → ✅ "See how it works"
❌ "Click here" → ✅ (literally never)
❌ "Sign up" → ✅ "Start free" / "Create my account"
❌ "Buy now" → ✅ "Get [Product] for $X"

### CTA principles

1. **First person, present tense.** "Start my free trial" > "Start your free trial."
2. **Specific outcome.** "Get the template" > "Download."
3. **Verb, not noun.** "Compare plans" > "Comparison."
4. **What happens next.** If the button leads to a checkout, say so. If it opens a modal, the label can be more casual.

### CTA anti-patterns
- ❌ "Submit" (the default for forms — never use it without context)
- ❌ "Click here" (accessibility and clarity failure)
- ❌ "Yes" / "No" (always describe what yes/no means)
- ❌ "Continue" (continue to what?)
- ❌ Three different CTAs in a row competing for attention

---

## Microcopy

The small text that makes interfaces feel human.

### Buttons (secondary actions)
- "Cancel" — clear
- "Maybe later" — softer
- "Not now" — most polite
- ❌ "No thanks" (passive-aggressive)

### Empty states
- ❌ "No data" ✅ "No projects yet. Create your first one to get started."
- ❌ "Nothing here" ✅ "Once you add a task, it'll show up here."

### Error messages
- ❌ "An error occurred" ✅ "We couldn't save your changes. Check your connection and try again."
- ❌ "Invalid input" ✅ "Enter a valid email address (you used an extra @)."

### Success messages
- ❌ "Success" ✅ "Saved. Your changes are live."
- ❌ "Done" ✅ "Sent. We'll let you know when [Recipient] responds."

### Loading states
- ❌ "Loading..." ✅ "Loading your projects..."
- ❌ "Please wait" ✅ "Hang tight — this usually takes a few seconds."

### Tooltips
- Be brief. One sentence max.
- Explain the WHY, not just the WHAT.
- ❌ "Bold" ✅ "Bold (⌘B)"

### Placeholders
- ❌ Used as labels
- ✅ Used as examples: "e.g. acme.com" or "Search projects..."

---

## Tone of Voice

Pick a tone and hold it. Voice should be consistent across the page.

### Voices that work for tech/SaaS
- **Linear / Vercel style:** Calm, confident, precise. Lowercase headlines. Direct verbs.
- **Stripe style:** Clear, specific, evidence-led. They show numbers and case studies.
- **Arc style:** Warm, confident, slightly playful. Premium without being formal.

### Voices that work for editorial/creative
- **Magazine style:** Considered, varied sentence rhythm, occasional editorial voice.
- **Studio style:** Insider language, occasional opinions, knows the audience.

### Voices that work for indie / small biz
- **Warm, plain, human.** Talk like a person, not a brand.
- First-person, plural: "We make X for people who Y."
- Acknowledge the reader's reality.

### Tone anti-patterns
- ❌ Switching tone mid-page (formal headline, casual button)
- ❌ Corporate throat-clearing: "At [Company], we believe..."
- ❌ Forced friendliness: "Hey there! 👋 Ready to get started? Let's go!"
- ❌ Trying too hard to be cool: "This ain't yo mama's CRM"

---

## Real Names, Real Numbers

The single biggest content upgrade: replace generic with specific.

### Names
- ❌ "John D., CEO of Acme Corp"
- ✅ "Jane Park, Head of Design at Linear"
- ❌ "A major financial institution"
- ✅ "Stripe moved $X through our platform in 2025"

### Numbers
- ❌ "Faster" ✅ "3.4x faster (median, n=240)"
- ❌ "Thousands of users" ✅ "Used by 4,200 teams, including Linear, Vercel, and Stripe"
- ❌ "Significant cost savings" ✅ "Saved $2.3M in AWS costs in 2025"

### Times / Dates
- ❌ "Recently" ✅ "Last week"
- ❌ "Coming soon" ✅ "Q3 2026"

### Specificity rules
- If you can't name a number, name the source of your estimate
- If you can't name a customer, say what kind of customer ("used by YC-backed startups")
- If you can't say a date, say the quarter
- "Soon" / "recently" / "many" are placeholders. Replace them.

---

## Localization

If shipping in multiple languages:

1. **Don't auto-translate and ship.** Have a native speaker review.
2. **Strings in one place** — i18n keys, not inline text.
3. **Planned space for 30–50% longer text** in German, French, Spanish, etc.
4. **Date, number, currency formatting** per locale (`Intl.DateTimeFormat`).
5. **Right-to-left support** if Arabic/Hebrew — test layout.

---

## Content Checklist (before shipping)

- [ ] Every headline makes a claim (or names a user, or says something specific)
- [ ] No "Lorem ipsum" anywhere
- [ ] No placeholder text ("Tagline", "Description goes here")
- [ ] CTAs are specific verbs with specific outcomes
- [ ] Empty states explain what to do next
- [ ] Error messages are human and actionable
- [ ] All names (people, companies) are real (or clearly fictional)
- [ ] Numbers are specific (or sources are cited)
- [ ] Tone is consistent across the page
- [ ] No buzzwords left in ("empower," "leverage," "synergy")
- [ ] Reading aloud works (no awkward phrasing)
