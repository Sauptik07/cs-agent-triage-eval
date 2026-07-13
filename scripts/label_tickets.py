"""Interactive labeling CLI for the 150-ticket set.

Reads data/tickets.json and config/taxonomy.yaml ONLY. It must never read
data/generation_meta.json — its ticket_provenance would tell you the intended
answer and bias the ground truth. That is asserted in _safe_read_text().

Behavior (deliberately minimal):
  * Presents tickets in a SHUFFLED, fixed-seed order (recorded below) so fatigue
    drift doesn't align with generation batch order and become a systematic confound.
  * Writes labeled_at per row (for later fatigue analysis of your own annotations).
  * Saves after EVERY ticket (atomic) and resumes where you left off across sittings.
  * Per ticket: category / urgency / confidence(1-3) / optional notes / flag-for-re-review.

Run:  uv run python scripts/label_tickets.py   (Ctrl-C or Ctrl-D to pause; re-run to resume)
"""

from __future__ import annotations

import csv
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TICKETS = ROOT / "data" / "tickets.json"
TAXONOMY = ROOT / "config" / "taxonomy.yaml"
LABELS = ROOT / "data" / "labels.csv"

SEED = 1234  # fixed shuffle seed — recorded here in version control for reproducibility.
FIELDNAMES = ["ticket_id", "category", "urgency", "confidence", "flag_review", "notes", "labeled_at"]
FORBIDDEN = "generation_meta.json"


def _safe_read_text(path: Path) -> str:
    # The guard the brief asked for: labeling must never read provenance.
    assert path.name != FORBIDDEN, "labeling must never read generation_meta.json (it would bias labels)"
    return path.read_text()


def load_tickets() -> dict[str, dict]:
    return {t["ticket_id"]: t for t in json.loads(_safe_read_text(TICKETS))}


def load_taxonomy() -> tuple[list[str], list[tuple[str, str]]]:
    tx = yaml.safe_load(_safe_read_text(TAXONOMY))
    cats = [c["id"] for c in tx["category"]["labels"]]
    urg = [(lvl["id"], lvl["name"]) for lvl in tx["urgency"]["levels"]]
    return cats, urg


def load_existing() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if LABELS.exists():
        with open(LABELS, newline="") as f:
            for r in csv.DictReader(f):
                rows[r["ticket_id"]] = r
    return rows


def save(rows: dict[str, dict], all_ids: list[str]) -> None:
    tmp = LABELS.with_name("labels.csv.tmp")  # atomic: write temp, then replace
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for tid in all_ids:
            r = rows.get(tid, {"ticket_id": tid})
            w.writerow({k: (r.get(k) or "") for k in FIELDNAMES})
    os.replace(tmp, LABELS)


def choose(label: str, options: list[tuple[str, str]]) -> str:
    """Numbered menu; accepts the number or the value. 'q' quits (pause)."""
    while True:
        print(label)
        for i, (_val, text) in enumerate(options, 1):
            print(f"    {i}  {text}")
        s = input("> ").strip().lower()
        if s in ("q", "quit"):
            raise KeyboardInterrupt
        if s.isdigit() and 1 <= int(s) <= len(options):
            return options[int(s) - 1][0]
        for val, _text in options:
            if s == val.lower():
                return val
        print("  invalid — enter a number or the name")


def main() -> None:
    tickets = load_tickets()
    cats, urg = load_taxonomy()
    all_ids = sorted(tickets)                     # file is stored in ticket_id order
    present = all_ids[:]
    random.Random(SEED).shuffle(present)          # but presented shuffled, fixed seed

    rows = load_existing()
    for tid in all_ids:
        rows.setdefault(tid, {"ticket_id": tid})

    def is_labeled(tid: str) -> bool:
        return bool((rows[tid].get("category") or "").strip())

    done = sum(is_labeled(t) for t in all_ids)
    todo = [t for t in present if not is_labeled(t)]
    print(f"seed={SEED}   labeled {done}/{len(all_ids)}   remaining {len(todo)}")
    if not todo:
        print("All tickets already labeled.")
        return

    cat_opts = [(c, c) for c in cats]
    urg_opts = [(uid, f"{uid} ({name})") for uid, name in urg]
    conf_opts = [("1", "1  low"), ("2", "2  medium"), ("3", "3  high")]

    try:
        for n, tid in enumerate(todo, 1):
            t = tickets[tid]
            print("\n" + "=" * 72)
            print(
                f"[ {done + n} / {len(all_ids)} ]  {tid}   {t['account_id']} ({t['account_tier']})"
                f"   channel={t['channel']}   {t['created_at'][:10]}"
            )
            print(f"SUBJECT: {t['summary']}")
            print("-" * 72)
            print(t["description"])
            print("-" * 72)

            category = choose("category:", cat_opts)
            urgency = choose("urgency:", urg_opts)
            confidence = choose("confidence:", conf_opts)
            notes = input("notes (optional, Enter to skip): ").strip()
            flag = input("flag for re-review? [y/N]: ").strip().lower().startswith("y")

            rows[tid] = {
                "ticket_id": tid,
                "category": category,
                "urgency": urgency,
                "confidence": confidence,
                "flag_review": "yes" if flag else "",
                "notes": notes,
                "labeled_at": datetime.now(timezone.utc).isoformat(),
            }
            save(rows, all_ids)  # save after EVERY ticket
    except (KeyboardInterrupt, EOFError):
        print("\nSaved and paused. Re-run to resume where you left off.")
        return

    print("\nAll tickets labeled. data/labels.csv is complete.")


if __name__ == "__main__":
    main()
