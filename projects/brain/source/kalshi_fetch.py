#!/usr/bin/env python3
"""kalshi_fetch.py — Pull OPEN Kalshi markets as forecastable questions (no API key)."""
import argparse, json
import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"


def get_markets(limit=100, status="open", cursor=None):
    params = {"limit": min(limit, 1000), "status": status}
    if cursor:
        params["cursor"] = cursor
    r = requests.get(f"{BASE}/markets", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def to_question(m):
    yes_price = m.get("yes_bid") or m.get("last_price") or m.get("yes_ask")
    if m.get("yes_bid") is not None and m.get("yes_ask") is not None:
        yes_price = (m["yes_bid"] + m["yes_ask"]) / 2
    implied = float(yes_price) if yes_price is not None else None
    return {
        "id": m.get("ticker"),
        "question": m.get("title") or m.get("subtitle") or m.get("ticker"),
        "resolution_criteria": m.get("rules_primary") or m.get("subtitle") or "See Kalshi market rules.",
        "resolution_date": (m.get("close_time") or "")[:10] or "unspecified",
        "category": m.get("category", "kalshi"),
        "market_implied_pct": implied,
        "kalshi_ticker": m.get("ticker"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--category")
    ap.add_argument("--min-volume", type=int, default=0)
    ap.add_argument("--out", default="kalshi_questions.json")
    args = ap.parse_args()
    collected, cursor = [], None
    while len(collected) < args.limit:
        data = get_markets(limit=100, status="open", cursor=cursor)
        markets = data.get("markets", [])
        if not markets:
            break
        for m in markets:
            if args.category and m.get("category", "").lower() != args.category.lower():
                continue
            if (m.get("volume") or 0) < args.min_volume:
                continue
            q = to_question(m)
            if q["market_implied_pct"] is None or q["resolution_date"] == "unspecified":
                continue
            collected.append(q)
            if len(collected) >= args.limit:
                break
        cursor = data.get("cursor")
        if not cursor:
            break
    json.dump(collected, open(args.out, "w"), indent=2)
    print(f"Saved {len(collected)} open Kalshi markets to {args.out}")
    if collected:
        print("\nSample (question | market implied %):")
        for q in collected[:8]:
            print(f"  [{q['market_implied_pct']:>4.0f}%] {q['question'][:70]}  (by {q['resolution_date']})")


if __name__ == "__main__":
    main()
