"""Generate the 150-ticket eval dataset with Gemini — leakage-safe.

Design (see docs/BRIEF.md, config/taxonomy.yaml):
  * Cross-model: Gemini GENERATES, DeepSeek CLASSIFIES (different families, different
    stylistic tells). Gemini is deliberately NOT an LLMProvider — it's out of the eval path.
  * Unconditioned on labels: the generator is conditioned on SITUATIONS, never on our
    categories or urgency levels, and is barred from classifying/rating a ticket.
  * Realistic base rate: 120 ORDINARY tickets have tone that NATURALLY MATCHES severity.
    30 BAIT tickets (20%, 6 per archetype) are the exceptions where tone and severity
    deliberately MISMATCH — the mismatch instruction lives ONLY in the bait prompts.
  * Ground truth is physically separate: tickets.json holds INPUT fields only. The bait
    archetype tags live in generation_meta.json, keyed by ticket_id, never fed to the model.

Run:  uv run python scripts/generate_tickets.py
Needs GEMINI_API_KEY in .env. Override the model with GEMINI_MODEL if the default 404s.

This is a ONE-TIME artifact: the committed tickets.json is canonical. The script exists for
provenance and method-reproducibility, not byte-identical regeneration (LLM output varies).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Free-tier keys serve the rolling aliases gemini-flash-latest / gemini-flash-lite-latest
# (dated models like gemini-2.0-flash return limit:0). The resolved version is recorded in meta.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
TEMPERATURE = 0.9  # diversity; generation is NOT the eval, so temp > 0 is fine (recorded)

N_ORDINARY = 120
N_BAIT_PER = 6            # per archetype
BATCH_SIZE = 15          # tickets per Gemini call
SEED = 42                # seeds assembly (shuffle, account/time assignment), not the LLM
REFERENCE_NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Prompts — the single point of failure. No label vocabulary; no rating/classifying.
# ---------------------------------------------------------------------------
PREAMBLE = (
    "You write realistic inbound customer-support tickets for a fictional B2B SaaS company "
    "called Meridian — a platform offering: single sign-on (SSO) and user/role management; "
    "subscription billing; a REST API with webhooks; a web dashboard with reports and CSV/PDF "
    "data export; and prebuilt integrations (Slack, Salesforce, Zapier). You are simulating "
    "what real customers write to support. Output ONLY the ticket, in the customer's own words."
)

OUTPUT_RULES = (
    "STRICT RULES — these keep the dataset scientifically valid:\n"
    "- Never classify, rate, tag, prioritize, or categorize the ticket. Do not output any field "
    "or phrase like 'Priority: ...', 'Severity: ...', 'P0/P1/P2/P3', or 'Category: ...'.\n"
    "- Write only what a customer would type: a subject line and a body. Nothing else.\n"
    "- Real people vary: some terse, some rambling, some polite, some frustrated. Use everyday "
    "language, not corporate template speak.\n"
    'Return ONLY a JSON array of exactly {n} objects, no prose around it. Each object:\n'
    '{{"reporter_name": "<a person\'s name>", "channel": "email" | "chat" | "portal", '
    '"summary": "<one-line subject>", "description": "<the full ticket body>"}}'
)

ORDINARY_INSTRUCTION = (
    "These are ORDINARY, realistic support tickets — the everyday base rate. Tone should "
    "NATURALLY MATCH the severity of the problem: a mildly annoyed customer with a minor "
    "inconvenience; a worried or stressed customer with a real, serious problem; a neutral, "
    "matter-of-fact customer with a routine question or request. Do NOT force any mismatch "
    "between tone and severity — that correlation is what makes this the realistic base rate. "
    "Span the product's areas across the batch: login/SSO, users and roles, invoices/refunds/"
    "plan changes, API and webhook errors, dashboard and reports, CSV/PDF export, and third-party "
    "integrations — plus a few general questions or bits of feedback. Vary length (some one or "
    "two lines, some a few paragraphs) and specificity (some vague, some precise)."
)

# Mismatch / hard-case is scoped to bait ONLY. Each is described by SITUATION, never by a label.
BAIT_INSTRUCTIONS: dict[str, str] = {
    "angry-trivial": (
        "Generate tickets from this SPECIFIC hard case: a FURIOUS, aggressive customer — heavy "
        "caps, exclamation marks, threats to cancel — whose ACTUAL underlying problem is tiny or "
        "purely cosmetic: a typo on a page, a slightly misaligned button, a color they dislike, a "
        "minor wording nitpick. The emotional intensity should be wildly out of proportion to how "
        "small the real issue is. Vary the trivial issue and the flavor of anger across the batch."
    ),
    "calm-severe": (
        "Generate tickets from this SPECIFIC hard case: a CALM, polite, understated, matter-of-fact "
        "customer who mentions — almost in passing, without alarm — something actually severe: their "
        "production login has been down for hours, the API is returning errors for all their users, "
        "a chunk of their data has vanished or looks corrupted, or they noticed what might be a "
        "security exposure. The mild, unbothered tone should badly understate how serious it is. "
        "Vary the severe issue and the understated framing across the batch."
    ),
    "multi-issue": (
        "Generate tickets from this SPECIFIC hard case: a customer raising TWO genuinely unrelated "
        "problems in a single message — e.g. a billing/invoice question AND a login or API failure, "
        "or a feature question AND a data-export bug. Both problems should be real and non-trivial; "
        "neither is a throwaway aside. Vary the two problems across the batch."
    ),
    "feature-as-bug": (
        "Generate tickets from this SPECIFIC hard case: a customer who angrily demands that something "
        "be 'fixed' as though it is broken, when the capability they want never existed as a feature. "
        "For example: 'Your CSV export is BROKEN — it won't export to PDF' (PDF export was never "
        "offered), or 'the API is broken, it has no endpoint for X' (X was never built). Write it as "
        "an indignant bug report about missing functionality. Vary the nonexistent feature."
    ),
    "terse": (
        "Generate tickets from this SPECIFIC hard case: extremely TERSE, low-information one-liners "
        "that are genuinely hard to triage because there is almost nothing to go on — e.g. "
        "'doesn't work', 'help', 'still broken??', 'login?', 'refund'. A word or a short fragment, "
        "no detail, no context. Vary them across the batch."
    ),
}

REQUIRED_FIELDS = ("reporter_name", "channel", "summary", "description")


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------
_SEEN_MODEL_VERSIONS: set[str] = set()  # what the -latest alias actually resolved to


def call_gemini(instruction: str, n: int) -> list[dict]:
    """One Gemini call. Retries 429/5xx with backoff; hard-fails on 400/404."""
    prompt = f"{PREAMBLE}\n\n{instruction}\n\n{OUTPUT_RULES.format(n=n)}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": TEMPERATURE,
            "responseMimeType": "application/json",  # ask Gemini for pure JSON
            "maxOutputTokens": 8192,
        },
    }
    resp = None
    for attempt in range(5):
        resp = httpx.post(ENDPOINT, params={"key": GEMINI_KEY}, json=body, timeout=120.0)
        if resp.status_code == 200:
            break
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 10 * (attempt + 1)  # free-tier RPM is tight; back off and retry
            print(f"  (rate-limited/again {resp.status_code}; waiting {wait}s)")
            time.sleep(wait)
            continue
        sys.exit(  # 400/404 etc. — not transient
            f"\nGemini call failed ({resp.status_code}). If model-not-found, set GEMINI_MODEL "
            f"to a model your key can use.\nResponse: {resp.text[:500]}"
        )
    if resp is None or resp.status_code != 200:
        sys.exit("\nGemini kept rate-limiting after retries; try later or a smaller run.")
    data = resp.json()
    if data.get("modelVersion"):
        _SEEN_MODEL_VERSIONS.add(data["modelVersion"])
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        # e.g. safety block or empty candidate — skip this batch, caller will top up.
        print(f"  (no usable candidate this call: {json.dumps(data)[:200]})")
        return []
    items = _parse_json_array(text)
    return [it for it in items if _valid_item(it)]


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):  # strip markdown fences if present
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _valid_item(it: object) -> bool:
    return (
        isinstance(it, dict)
        and all(isinstance(it.get(f), str) and it[f].strip() for f in REQUIRED_FIELDS)
        and it["channel"] in ("email", "chat", "portal")
    )


def collect(instruction: str, target: int, label: str) -> list[dict]:
    """Loop Gemini calls until `target` valid items are gathered (capped to avoid loops)."""
    got: list[dict] = []
    attempts = 0
    while len(got) < target and attempts < target // 5 + 8:
        need = min(BATCH_SIZE, target - len(got))
        batch = call_gemini(instruction, need)
        got.extend(batch)
        attempts += 1
        print(f"  [{label}] {len(got)}/{target}")
        time.sleep(4.0)  # ~15 req/min ceiling on the free tier
    if len(got) < target:
        sys.exit(f"\nOnly gathered {len(got)}/{target} for {label}; aborting (nothing written).")
    return got[:target]


# ---------------------------------------------------------------------------
# Assembly — the script owns ids, accounts, timestamps, emails (control + reproducibility)
# ---------------------------------------------------------------------------
def slug_email(name: str, domain: str) -> str:
    parts = re.sub(r"[^a-z ]", "", name.lower()).split()
    handle = ".".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "customer")
    return f"{handle}@{domain}"


def assemble(raw: list[dict], accounts: list[dict], rng: random.Random) -> tuple[list[dict], dict]:
    """raw items carry a private '_provenance' key. Returns (tickets, provenance_map)."""
    order = raw[:]
    rng.shuffle(order)  # so bait isn't clustered; ids become a random mix

    # Weight ticket volume by tier (enterprise files more than free) — realistic.
    weights = {"enterprise": 3, "pro": 2, "free": 1}
    acct_pool = [a for a in accounts]
    acct_weights = [weights[a["tier"]] for a in accounts]

    tickets, provenance = [], {}
    for i, item in enumerate(order, start=1):
        tid = f"TKT-{i:03d}"
        acct = rng.choices(acct_pool, weights=acct_weights, k=1)[0]
        created = REFERENCE_NOW - timedelta(
            days=rng.randint(0, 120), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        tickets.append(
            {
                "ticket_id": tid,
                "account_id": acct["account_id"],
                "account_tier": acct["tier"],
                "reporter": {
                    "name": item["reporter_name"].strip(),
                    "email": slug_email(item["reporter_name"], acct["domain"]),
                },
                "channel": item["channel"],
                "created_at": created.isoformat(),
                "summary": item["summary"].strip(),
                "description": item["description"].strip(),
            }
        )
        provenance[tid] = item["_provenance"]  # "ordinary" or a bait archetype
    return tickets, provenance


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
ANSWER_KEYS = {"category", "urgency", "priority", "component", "severity", "label"}


def structural_checks(tickets: list[dict], accounts: list[dict]) -> None:
    assert len(tickets) == 150, f"expected 150, got {len(tickets)}"
    ids = [t["ticket_id"] for t in tickets]
    assert len(set(ids)) == 150, "duplicate ticket_ids"
    valid_accts = {a["account_id"] for a in accounts}
    for t in tickets:
        assert t["account_id"] in valid_accts, f"{t['ticket_id']}: bad account"
        assert t["summary"] and t["description"], f"{t['ticket_id']}: empty text"
        assert not (ANSWER_KEYS & t.keys()), f"{t['ticket_id']}: answer-bearing key present"
    descs = [t["description"] for t in tickets]
    assert len(descs) == len(set(descs)), "exact-duplicate descriptions present"
    print("  structural checks: PASS")


# Prose-leakage scan (report-only; the human judges each hit).
LABEL_TOKENS = [r"feature_request", r"\bP[0-3]\b", r"category:", r"priority:", r"severity:"]
META_WORDS = ["urgent", "critical", "severity", "priority", "blocker"]
NOISY_WORDS = ["billing", "technical", "account", "other", "high", "normal", "low"]


def _count(term: str, blobs: list[str], is_regex: bool) -> tuple[int, list[int]]:
    pat = re.compile(term if is_regex else rf"\b{re.escape(term)}\b", re.IGNORECASE)
    hits = [i for i, b in enumerate(blobs) if pat.search(b)]
    return len(hits), hits


def prose_scan(tickets: list[dict]) -> dict:
    blobs = [f"{t['summary']}\n{t['description']}" for t in tickets]
    result = {"label_tokens": {}, "meta_words": {}, "noisy_words": {}}
    print("\n--- PROSE-LEAKAGE SCAN (report-only; your judgment) ---")

    print("[label tokens] should be ~0 — investigate ANY hit:")
    for term in LABEL_TOKENS:
        n, idx = _count(term, blobs, is_regex=True)
        result["label_tokens"][term] = {"count": n, "tickets": [tickets[i]["ticket_id"] for i in idx]}
        flag = "  <-- INVESTIGATE" if n else ""
        print(f"    {term:16} {n}{flag}")
        for i in idx[:5]:
            print(f"        {tickets[i]['ticket_id']}: {tickets[i]['summary'][:70]}")

    print("[meta-severity words] customer venting vs generator tell — you decide:")
    for term in META_WORDS:
        n, idx = _count(term, blobs, is_regex=False)
        result["meta_words"][term] = {"count": n, "tickets": [tickets[i]["ticket_id"] for i in idx]}
        print(f"    {term:16} {n}")

    print("[generic words] NOISY (false-positive on ordinary English) — counts only:")
    for term in NOISY_WORDS:
        n, _ = _count(term, blobs, is_regex=False)
        result["noisy_words"][term] = n
        print(f"    {term:16} {n}")
    return result


def near_dup_scan(tickets: list[dict], threshold: float = 0.6) -> list[dict]:
    """Cheap word-set Jaccard over descriptions. Report-only."""
    toksets = [set(re.findall(r"[a-z0-9]+", t["description"].lower())) for t in tickets]
    pairs = []
    for a, b in combinations(range(len(tickets)), 2):
        sa, sb = toksets[a], toksets[b]
        if not sa or not sb:
            continue
        j = len(sa & sb) / len(sa | sb)
        if j >= threshold:
            pairs.append(
                {"a": tickets[a]["ticket_id"], "b": tickets[b]["ticket_id"], "jaccard": round(j, 3)}
            )
    pairs.sort(key=lambda p: p["jaccard"], reverse=True)
    print(f"\n--- NEAR-DUPLICATE SCAN (Jaccard >= {threshold}, report-only) ---")
    if not pairs:
        print("  none")
    for p in pairs[:20]:
        print(f"    {p['a']} ~ {p['b']}  (jaccard={p['jaccard']})")
    if len(pairs) > 20:
        print(f"    ... and {len(pairs) - 20} more (see generation_meta.json)")
    return pairs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    if not GEMINI_KEY:
        sys.exit("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")
    accounts = json.loads((DATA / "accounts.json").read_text())
    rng = random.Random(SEED)

    print(f"Generating with {GEMINI_MODEL} (temp={TEMPERATURE})")
    raw: list[dict] = []

    print(f"\nordinary ({N_ORDINARY}, tone matches severity):")
    for it in collect(ORDINARY_INSTRUCTION, N_ORDINARY, "ordinary"):
        it["_provenance"] = "ordinary"
        raw.append(it)

    for archetype, instruction in BAIT_INSTRUCTIONS.items():
        print(f"\nbait: {archetype} ({N_BAIT_PER}):")
        for it in collect(instruction, N_BAIT_PER, archetype):
            it["_provenance"] = archetype
            raw.append(it)

    tickets, provenance = assemble(raw, accounts, rng)

    print("\n=== VALIDATION ===")
    structural_checks(tickets, accounts)
    scan = prose_scan(tickets)
    near_dupes = near_dup_scan(tickets)

    # Sanity summary — never category/urgency (unlabeled).
    lengths = [len(t["description"]) for t in tickets]
    channels = {}
    for t in tickets:
        channels[t["channel"]] = channels.get(t["channel"], 0) + 1
    print(
        f"\nlengths(chars): min={min(lengths)} med={sorted(lengths)[75]} max={max(lengths)} | "
        f"channels={channels}"
    )
    bait_counts = {}
    for p in provenance.values():
        bait_counts[p] = bait_counts.get(p, 0) + 1
    print(f"provenance: {bait_counts}")

    # ---- write artifacts ----
    (DATA / "tickets.json").write_text(json.dumps(tickets, indent=2) + "\n")

    labels_lines = ["ticket_id,category,urgency,confidence,notes"]
    labels_lines += [f"{t['ticket_id']},,,," for t in tickets]
    (DATA / "labels.csv").write_text("\n".join(labels_lines) + "\n")

    prompts = {
        "preamble": PREAMBLE,
        "output_rules": OUTPUT_RULES,
        "ordinary": ORDINARY_INSTRUCTION,
        "bait": BAIT_INSTRUCTIONS,
    }
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "model": GEMINI_MODEL,
        "model_version_resolved": sorted(_SEEN_MODEL_VERSIONS),  # what -latest actually served
        "endpoint": ENDPOINT,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "counts": {"total": 150, "ordinary": N_ORDINARY, "bait": 5 * N_BAIT_PER, "bait_per_archetype": N_BAIT_PER},
        "prompts": prompts,
        "prompt_sha256": {k: hashlib.sha256(json.dumps(v).encode()).hexdigest() for k, v in prompts.items()},
        "ticket_provenance": provenance,  # keyed by ticket_id; NOT a label; classifier never sees it
        "prose_leakage_scan": scan,
        "near_duplicates": near_dupes,
        "note": "One-time artifact; tickets.json is canonical. Label from tickets.json ONLY — "
        "do not consult ticket_provenance while labeling (it would bias urgency).",
    }
    (DATA / "generation_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    print("\nWrote data/tickets.json, data/labels.csv, data/generation_meta.json")
    print("Review the scans above and spot-read tickets.json. NOT committed yet.")


if __name__ == "__main__":
    main()
