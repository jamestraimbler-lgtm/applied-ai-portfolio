#!/usr/bin/env python3
"""manifold.py — Pull Manifold Markets questions + AUTO-RESOLVE predictions."""
import argparse, json, time
from datetime import datetime, timezone

import requests

from brain import classify_category

BASE = "https://api.manifold.markets/v0"

# Skip these in targeted mode — sports, entertainment, meta-platform noise.
SKIP_KEYWORDS = [
    "nfl", "nba", "mlb", "nhl", "soccer", "football", "baseball",
    "basketball", "world cup", "super bowl", "oscars", "grammy", "emmy",
    "box office", "movie", "tv show", "manifold", " mana ", "metaculus",
    "will i ", "personal goal",
]


def fetch_markets(limit, before=None):
    params = {"limit": min(limit, 1000)}
    if before:
        params["before"] = before
    r = requests.get(f"{BASE}/markets", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_market(market_id):
    r = requests.get(f"{BASE}/market/{market_id}", timeout=20)
    r.raise_for_status()
    return r.json()


def to_question(m):
    prob = m.get("probability")
    if prob is None:
        return None
    close_ms = m.get("closeTime")
    close_date = (datetime.fromtimestamp(close_ms/1000, tz=timezone.utc).strftime("%Y-%m-%d")
                  if close_ms else "unspecified")
    return {
        "id": m.get("id"),
        "question": m.get("question"),
        "resolution_criteria": (m.get("textDescription") or m.get("question") or "")[:500] or "See Manifold market.",
        "resolution_date": close_date,
        "category": classify_category(m.get("question", "")),
        "market_implied_pct": round(prob * 100, 1),
        "manifold_url": m.get("url"),
    }


def _is_skip(question_text):
    q = question_text.lower()
    return any(kw in q for kw in SKIP_KEYWORDS)


def cmd_fetch(args):
    collected, before = [], None
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    scanned = 0
    raw_limit = args.limit * 4 if args.targeted else args.limit
    scan_cap = 5000 if args.targeted else 2000
    while len(collected) < raw_limit and scanned < scan_cap:
        markets = fetch_markets(200, before=before)
        if not markets:
            break
        for m in markets:
            scanned += 1
            before = m.get("id")
            if m.get("outcomeType") != "BINARY":
                continue
            if m.get("isResolved"):
                continue
            if (m.get("uniqueBettorCount") or 0) < args.min_traders:
                continue
            close_ms = m.get("closeTime")
            if not close_ms or close_ms < now_ms:
                continue
            q = to_question(m)
            if not q:
                continue
            if args.targeted and _is_skip(q["question"]):
                continue
            collected.append(q)
            if len(collected) >= raw_limit:
                break
        time.sleep(0.1)

    if args.targeted:
        target_cats = {"macro_rates", "regulation", "crypto_struct"}
        collected.sort(key=lambda q: (0 if q["category"] in target_cats else 1,
                                      -q["market_implied_pct"]))
    collected = collected[:args.limit]

    # Validate each market ID via the API (dead-ID guard)
    validated = []
    for q in collected:
        try:
            get_market(q["id"])
            validated.append(q)
        except Exception as e:
            print(f"  SKIP {q['id']}: API validation failed ({e})")
        time.sleep(0.1)
    collected = validated

    json.dump(collected, open(args.out, "w"), indent=2)
    mode = " (targeted)" if args.targeted else ""
    print(f"Saved {len(collected)} open Manifold binary markets to {args.out}{mode}  (scanned {scanned})")
    for q in collected[:10]:
        print(f"  [{q['market_implied_pct']:>5.1f}%] [{q['category']:>14}] "
              f"{q['question'][:55]}  (by {q['resolution_date']})")


def cmd_resolve(args):
    preds = [json.loads(l) for l in open(args.pred_log) if l.strip()]
    open_preds = [p for p in preds if p.get("outcome") is None
                  and p.get("category") == "manifold"
                  and p.get("status") != "invalid"]
    print(f"Checking {len(open_preds)} open Manifold predictions for resolution...")
    resolved_count = 0
    for p in preds:
        if p.get("outcome") is not None or p.get("category") != "manifold":
            continue
        if p.get("status") == "invalid":
            continue
        market_id = p.get("base_id") or p["id"]
        try:
            m = get_market(market_id)
        except Exception as e:
            print(f"  {p['id']}: fetch error {e}")
            continue
        if m.get("isResolved"):
            res = m.get("resolution")
            if res == "YES":
                p["outcome"] = 1
            elif res == "NO":
                p["outcome"] = 0
            elif res == "MKT":
                rp = m.get("resolutionProbability", 0.5)
                p["outcome"] = 1 if rp >= 0.5 else 0
            else:
                print(f"  {p['id']}: resolved {res} (CANCEL/other) — skipping")
                continue
            p["resolved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            resolved_count += 1
            print(f"  {p['id']}: {res}  (brain said {p['probability_pct']}%, "
                  f"market {p.get('market_implied_pct')}%)  | {p['question'][:45]}")
        time.sleep(0.1)
    with open(args.pred_log, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    print(f"Auto-resolved {resolved_count} predictions. Run: python3 brain.py score")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--limit", type=int, default=25)
    f.add_argument("--min-traders", type=int, default=15)
    f.add_argument("--out", default="manifold_questions.json")
    f.add_argument("--targeted", action="store_true",
                   help="Prefer macro/regulation/crypto questions, skip sports/entertainment noise")
    f.set_defaults(func=cmd_fetch)
    r = sub.add_parser("resolve")
    r.add_argument("--pred-log", default="predictions.jsonl")
    r.set_defaults(func=cmd_resolve)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
