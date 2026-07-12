# Labeling Guide

This is the guide you label the 150 tickets from. The label set itself lives in
`config/taxonomy.yaml` — that file is the source of truth; this document is how to
*apply* it consistently.

## The one principle

A label is only worth what a human can reproduce. You are the sole annotator, and
your intra-annotator κ (the blinded re-label of a 20-ticket subset) will *measure*
whether these labels are reproducible. So the goal when in doubt is not the "cleverest"
label — it's the label you'd assign again next week from the same text.

Two standing rules:

- **Label from the text only. Do not invent facts.** If the impact isn't stated, don't
  imagine a crisis (or a triviality) that the ticket doesn't support.
- **You never look at the model's predictions while labeling.** Ground truth is set
  before, and independently of, anything the agent produces.

## Procedure for one ticket

1. Read the whole ticket. **Ignore the customer's tone** — anger and calm are noise.
2. **Category** — assign the one subsystem that owns the *fix*, not the symptom
   described. Run the category rules below.
3. **Urgency** — assign operational impact via the decision tree below. Ignore tone
   and account tier.
4. **Tier** — record `account_tier` as its own field. It does **not** affect either label.
5. If you had to make a close call, note it — those notes are gold in Phase 4 error
   analysis, where some of your own labels will turn out to be wrong.

---

## Category (single primary label)

Assign by **owner-of-fix, not symptom**. Hard rule: **`feature_request` beats a bug
framing** — if nothing that exists is broken and they want new behavior, it's
`feature_request` even when written as "X is broken."

**billing** — charges, invoices, payment methods, refunds, plan pricing.
- *"Charged twice this month"* → billing.
- *"I upgraded but I'm still on the old plan's limits"* → **account** (the complaint is
  entitlements/state, not the charge). If the complaint were the charge itself → billing.
- *"Your pricing page is confusing"* → **other** (feedback), unless they're asking you to
  change pricing → feature_request.

**technical** — the product is malfunctioning; the fix is code or infrastructure.
- *"API returns 500 on every call"* → technical.
- *"The dashboard takes 30s to load"* → technical (performance).
- *"Login says 'invalid password' but my password is correct"* → **technical** (auth is
  misbehaving). Contrast with account below — this is a known κ hotspot; the test is
  *system misbehaving* (technical) vs *account state/permission* (account).

**account** — access, auth, roles/permissions, org/user management, subscription state.
- *"Add my teammate as an admin"* → account.
- *"Cancel my subscription"* → **account** (the action is a subscription-state change).
  A dispute over *being charged after cancelling* → billing.
- *"I've been locked out / removed from my org"* → account (state/permission), not technical.

**feature_request** — nothing is broken; they want new or changed behavior.
- *"Export to PDF is broken"* — but PDF export doesn't exist yet → **feature_request**
  (the hard rule).
- *"You should support SSO"* → feature_request.
- *"Make the report load faster"* → feature_request if it works but they want it better;
  **technical** if it used to be fast and regressed. Fuzzy — note your call.

**other** — genuinely doesn't fit; general questions, feedback, spam.
- *"Just wanted to say thanks!"* → other.
- *"Are you HIPAA compliant?"* → other (general question), unless it's about *their*
  account's configuration → account.

> `other` is capped at 10% of tickets (`other_cap` in the taxonomy). If you're reaching
> for it more than that, the taxonomy is wrong — stop and revisit it, don't force tickets.

---

## Urgency (operational impact only)

Ordinal, P0 (worst) → P3 (least). **Ignore tone. Ignore tier.** For a multi-issue ticket,
score the **highest-impact** issue present.

Run top-down and stop at the first match:

- **P0 · Critical** — production down, data loss/corruption, security/privacy breach, or a
  complete block on a core workflow with **no workaround**. Broad or business-critical scope.
- **P1 · High** — a core function is broken or severely degraded; a workaround exists but is
  painful; **or** there's a hard external deadline/SLA. Not a full outage.
- **P2 · Normal** — partial or minor breakage with a clear workaround; not time-critical.
  The product is usable. *(Default here when the ticket states a problem but gives no
  impact signal — do not inflate to a crisis you can't justify.)*
- **P3 · Low** — cosmetic, general question, or a request with no functional impact.

### The mislabel-bait — these have defensible answers

- **Furious customer, trivial issue** — *"This is UNACCEPTABLE, there's a typo on your
  homepage!!!"* → **P3**. Tone is noise; a typo has no operational impact.
- **Calm customer, critical issue** — *"Morning — heads up, our checkout has been
  returning errors since about 9am."* → **P0**. Production is down regardless of the
  polite tone.
- **Painful workaround + hard deadline** — *"Can't export reports; I can copy-paste as a
  workaround but I need this for a board meeting Friday."* → **P1** (workaround exists,
  but a hard deadline).
- **One-liner, no impact signal** — *"it's broken"* → **P2** by the default rule; label the
  impact you can justify, flag low confidence, don't infer a P0.
- **Multi-issue** — *"my invoice is wrong AND I can't log in at all."* → category = the
  action-driving issue (here, access, if it blocks them); urgency = highest impact across
  both issues.

---

## Tier is separate

Record `account_tier` on each ticket (e.g. free / pro / enterprise). It never changes the
category or urgency label. It exists so a later routing/prioritization step — and the
Phase 7 account memory — can use it without contaminating the ground truth.
