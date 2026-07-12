# Project 1 (v2) — Ticket Triage Agent, Eval Harness, and Account Memory

> Paste everything below the line into a fresh Claude Code session in an empty repo directory.
> Supersedes v1. Changes: model-provider abstraction, Jira-shaped synthetic data, and a staged
> roadmap where memory/orchestration are *measured experiments*, not day-one architecture.

---

## Context for you (Claude)

I'm building a portfolio project I need to **defend in a technical interview**, not just ship.
Background: BS Computer Science, MS Business Analytics, now a Customer Success Programs Manager
working on AI agent projects. I've vibe-coded a lot; this time I want to genuinely understand
what I'm building. Target roles: Forward Deployed Engineer / Applied AI Engineer (Anthropic,
OpenAI, Sierra, Decagon, Glean).

**The point of this project is my learning, not your speed.**

## Working agreement (follow this throughout)

1. **Explain before you write.** Before any non-trivial code, explain in plain English what you're
   about to build and *why this design over the alternatives*. Wait for my go-ahead.
2. **Never write code I haven't understood.** If I say "just do it," push back once and make me
   restate the design in my own words first.
3. **Make me make the design calls.** At real forks (taxonomy, metrics, model choice, memory
   schema), lay out options with tradeoffs and let me choose. Don't default.
4. **Quiz me** at the end of each phase — 2–3 questions. If I can't answer, we go back.
5. **Maintain `LEARNING_LOG.md`.** After each phase I append: what we built, decisions and why,
   what surprised me, what I still don't understand. Prompt me; don't write my entries for me.
6. **No agent frameworks.** No LangChain, LlamaIndex, CrewAI. Raw SDK calls only. I want the primitives.
7. **Small commits with real messages** — the *why*, not the *what*.
8. **Guard the scope.** If I start reaching for a knowledge graph, a web UI, or a vector DB before
   the eval exists, remind me that unmeasured architecture is unfalsifiable and talk me down.

## What we're building

An LLM agent that triages inbound support tickets, **plus an evaluation harness that proves how
well it works and lets me improve it measurably** — then, and only then, a memory layer whose
value is *proven by the eval rather than assumed*.

The story I want to be able to tell:
> "Baseline scored X. v1 scored Y. Error analysis found three failure modes. v2 fixed two of them
> and scored Z. Adding per-account memory took it to W, at +$0.001 and +400ms per ticket — and here's
> the one place memory made things *worse*."

## Tech stack & constraints

- Python 3.11+, `uv` for deps (explain what `uv` does vs pip/venv the first time)
- **Model-provider abstraction from day one.** I do NOT have unlimited Anthropic API credits —
  my $20/mo Claude subscription covers Claude Code (the tool writing this code), NOT programmatic
  API calls (the eval runner). These are separate bills. So: one thin `LLMProvider` interface,
  swappable by env var, with adapters for Anthropic, Google Gemini (free tier), and DeepSeek.
  Everything downstream is provider-agnostic.
- Plain JSON/CSV for data. No database. No vector DB.
- `pytest` for harness tests.
- CLI only. **No web UI, no Streamlit, no dashboard.**

---

## Phases

Work through in order. Stop and check in at the end of each.

### Phase 0 — Scaffold, provider abstraction, fundamentals
Repo, deps, `.env` (gitignored — explain why and what happens if I forget).

Build the `LLMProvider` interface: one method in, normalized response out (text, token counts,
latency, cost estimate). Adapters for at least two providers. Then a script that makes one call
through it and prints the result.

Walk me through what actually goes over the wire — messages, roles, system prompts, token
accounting. I want to understand this cold, not by analogy.

**Explain to me why the abstraction is worth it here, and when it would be over-engineering.**

### Phase 1 — The dataset (Jira-shaped; I hand-label)
First, design with me:
- A **label taxonomy**. Starting point: `category` (billing / technical / account / feature_request /
  other) and `urgency` (P0–P3). Challenge it. Are classes mutually exclusive? Can *humans* reliably
  distinguish P1 from P2? A taxonomy humans disagree on is a broken eval.
- A short **labeling guide** with decision rules and 2–3 edge cases per class.
- A **Jira-shaped ticket schema** (ticket_id, account, reporter, component, summary, description,
  created_at, etc.) so this is genuinely reusable when I open-source it.

Then generate ~60 tickets across ~6 fictional accounts of different tiers.

**Critical — avoid label leakage.** If you generate tickets *knowing* the target label, you'll write
"P0" tickets in P0-flavored language, and any classifier will ace a test real tickets would fail.
So: generate without conditioning on the label, and deliberately include mislabel-bait — furious
customer with a trivial issue, calm customer whose production is down, multi-issue tickets, one-line
tickets, tickets that are actually feature requests dressed as bugs.

**Do not label them.** I label all 60 by hand. Then split: 10 dev / 50 held-out test.

**Before I start, explain why the model that generates the eval data must not label it, and why
I must not look at the test set while iterating on prompts.** I want to say this cleanly in an interview.

### Phase 2 — Agent v1 (deliberately naive)
Simplest thing that works: one prompt, structured output via tool calling. Explain why tool calling
beats "please respond in JSON," and what to do when the model returns malformed output anyway.

Don't optimize. v1 is the baseline and it's supposed to be mediocre.

### Phase 3 — The eval harness (the core deliverable)
A runner that executes the agent across the 50-ticket test set and scores it. Before coding, walk
me through the metric choices:
- Why raw accuracy misleads on imbalanced classes
- Per-class precision / recall / F1 — what each actually tells me
- Confusion matrix — what am I looking for?
- Urgency is **ordinal**: P0 predicted as P3 is far worse than P1 as P2. How do we capture that?
- Track **cost and latency per ticket**. FDE work is judged on these.

Include a **naive baseline** (always predict majority class). If the agent can't beat it, the agent
is worthless — that number goes in the README.

Persist `results/run-<timestamp>.json` so runs are comparable. This is what makes every later
change an experiment instead of a guess.

**Then: run the same eval across 2–3 providers/models and produce a cost-vs-quality table.**

### Phase 4 — Error analysis (do NOT skip to fixing)
Dump every failure. Categorize together: prompt problem, taxonomy problem, genuinely ambiguous
ticket, or **a bad label of mine**? Make me read the raw text of failures rather than jumping to fixes.
Some of my labels will be wrong. Finding that is the exercise.

Failure taxonomy goes in `LEARNING_LOG.md`. This is the heart of the blog post.

### Phase 5 — Agent v2 (one variable at a time)
Changes driven *only* by the error analysis, ranked by expected impact. Change **one thing**, re-run
the eval, record the delta. Three changes at once teaches me nothing.

Levers to discuss: prompt specificity, few-shot from the dev set, tool-schema field descriptions,
reasoning-before-answering, model routing (cheap model for easy tickets, expensive for ambiguous ones).

### Phase 6 — Stage the pipeline
Split the single classify call into explicit stages: **categorize → assess/score → recommend next action.**
Re-run the eval after each split. Does decomposition actually help, or just add cost and latency?
I want the real answer, including if it's "no."

### Phase 7 — Account memory (as a *measured experiment*)
Now, and not before, add a per-account context layer.

Start **flat, not graph**: an "account card" per account — tier, known issues, recurring themes, past
resolutions, notable history. Retrieved by `account_id`, injected into context. No vector DB, no
knowledge graph.

Then measure honestly:
- Accuracy delta vs Phase 6
- **Cost and latency delta** — memory adds context tokens; it does not save money. Push back if I
  claim otherwise.
- Where memory *hurt*: did stale account context cause the agent to anchor on a past issue and
  misread a new one? Find at least one case. This is the most interesting finding in the project.

Also cover the three *actual* cost levers so I don't confuse them with memory: **prompt caching**,
**model routing**, and **deterministic short-circuits** (don't call an LLM when a rule will do).

**Only if the flat cards demonstrably fail** in a way a graph would fix — propose the graph, and
make me articulate exactly what traversal buys us. Otherwise, we don't build it, and the README says why.

### Phase 8 — README and write-up
Aimed at a hiring manager with 90 seconds:
- Problem, taxonomy, and why the taxonomy was hard
- Baseline → v1 → v2 → staged → memory, with real numbers and confusion matrices
- Cost/quality frontier across models
- **Honest limitations** (synthetic data and what I did about label leakage)
- **What I got wrong and what I'd do next** — the section that signals seniority
- One-command reproduction

Then help me pull raw material for a blog post out of `LEARNING_LOG.md`. I write the post.

---

## Start here

No code yet.
1. Give me your honest read on this brief — what's badly scoped, what's missing, what I'm wrong about.
2. Then start Phase 0: explain what we're setting up and why, and wait for my go-ahead.
