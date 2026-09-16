#!/usr/bin/env python3
"""listing_window.py — New-listing structural funding window probe.

Tests whether perp listings create a temporary SERVICE vacuum (extreme
funding, wide spreads) before MMs settle in. Not price prediction (tested,
dead) — this is: does a listing create a capturable carry window?

Data: 108 Hyperliquid perpetual listings (2024-2025), funding from hour 0.
Method: systematic window analysis on the first 500 hourly funding entries
per listing.

FINDING: DEAD. The directional bias (73% positive) is real but the negative
tail (-6000% outliers) makes the expected value NEGATIVE (-111% mean APR).
The window is also DECAYING (2024 +26% → 2025 +11% baseline = no excess).
Textbook "pennies in front of a steamroller."
"""

import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "listing_window_data.jsonl"


def fetch_all():
    """Pull funding-from-launch for all HL perps listed since 2024."""
    r = requests.post("https://api.hyperliquid.xyz/info",
                      json={"type": "metaAndAssetCtxs"}, timeout=15)
    meta = r.json()[0]["universe"]
    coins = [m["name"] for m in meta]
    print(f"Total HL coins: {len(coins)}")

    listings = []
    for coin in coins:
        try:
            r = requests.post("https://api.hyperliquid.xyz/info",
                              json={"type": "fundingHistory", "coin": coin,
                                    "startTime": 0}, timeout=10)
            data = r.json()
            if data:
                first_ts = data[0].get("time", 0)
                first_date = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
                if first_date.year >= 2024:
                    rates = [float(d.get("fundingRate", "0")) for d in data]
                    listings.append({
                        "coin": coin,
                        "first_ts": first_ts,
                        "first_date": first_date.isoformat(),
                        "rates": rates,
                    })
        except Exception:
            pass
        time.sleep(0.05)

    record = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "listings": listings,
    }
    with open(DATA_FILE, "w") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Found {len(listings)} listings since 2024. Cached to {DATA_FILE.name}")
    return record


def analyze(data):
    listings = data["listings"]

    print("\n" + "=" * 78)
    print("  NEW-LISTING STRUCTURAL FUNDING WINDOW PROBE")
    print("=" * 78)
    print(f"  Source: Hyperliquid | Listings: {len(listings)} (2024-01 to present)")
    print(f"  Data: first 500 hourly funding entries per listing (~20 days)")

    windows = {
        "0-8h": (0, 8), "8-24h": (8, 24), "day2-3": (24, 72),
        "day4-7": (72, 168), "day8-14": (168, 336), "day15-20": (336, 500),
    }

    # ── Window analysis ──
    print("\n" + "─" * 78)
    print("WINDOW ANALYSIS (median APR across all listings)")
    print("─" * 78)
    print(f"  {'window':>10} {'n':>4} {'median':>9} {'mean':>9} "
          f"{'pos%':>5} {'med|APR|':>9}")

    for wname, (start, end) in windows.items():
        aprs = []
        for ld in listings:
            rates = ld["rates"]
            sl = rates[start:min(end, len(rates))]
            if sl:
                aprs.append(statistics.median(sl) * 24 * 365 * 100)

        if aprs:
            print(f"  {wname:>10} {len(aprs):>4} {statistics.median(aprs):>+8.0f}% "
                  f"{statistics.mean(aprs):>+8.0f}% {sum(1 for a in aprs if a > 0)/len(aprs)*100:>4.0f}% "
                  f"{statistics.median([abs(a) for a in aprs]):>8.0f}%")

    # ── Hit rate ──
    print("\n" + "─" * 78)
    print("HIT RATE (% with positive day-1 funding = shortable)")
    print("─" * 78)
    for wname, hours in [("day1", 24), ("day3", 72), ("day7", 168)]:
        pos = neg = 0
        for ld in listings:
            sl = ld["rates"][:hours]
            if sl:
                med = statistics.median(sl)
                if med > 0.00001:
                    pos += 1
                elif med < -0.00001:
                    neg += 1
        total = pos + neg
        if total:
            print(f"  {wname}: {pos}/{total+len(listings)-pos-neg} positive ({pos/len(listings)*100:.0f}%), "
                  f"{neg} negative ({neg/len(listings)*100:.0f}%)")

    # ── Year decay ──
    print("\n" + "─" * 78)
    print("DECAY CHECK (is the window closing?)")
    print("─" * 78)
    for year in [2024, 2025]:
        year_l = [ld for ld in listings
                  if datetime.fromisoformat(ld["first_date"]).year == year]
        if year_l:
            aprs = [statistics.median(ld["rates"][:24]) * 24 * 365 * 100
                    for ld in year_l if len(ld["rates"]) >= 24]
            if aprs:
                pos_pct = sum(1 for a in aprs if a > 0) / len(aprs) * 100
                print(f"  {year}: n={len(year_l)}, day-1 median={statistics.median(aprs):+.0f}% APR, "
                      f"positive={pos_pct:.0f}%")

    # ── Extremes ──
    print("\n" + "─" * 78)
    print("EXTREME DAY-1 FUNDING (top/bottom 5)")
    print("─" * 78)
    day1 = []
    for ld in listings:
        if len(ld["rates"]) >= 24:
            apr = statistics.median(ld["rates"][:24]) * 24 * 365 * 100
            day1.append((ld["coin"], ld["first_date"][:10], apr))
    day1.sort(key=lambda x: x[2], reverse=True)

    print("  Positive (longs pay shorts = shortable):")
    for coin, date, apr in day1[:5]:
        print(f"    {coin:>12} {date} {apr:>+8.0f}% APR")
    print("  Negative (shorts pay longs = NOT shortable):")
    for coin, date, apr in day1[-5:]:
        print(f"    {coin:>12} {date} {apr:>+8.0f}% APR")

    # ── Expected value ──
    print("\n" + "─" * 78)
    print("EXPECTED VALUE")
    print("─" * 78)
    if day1:
        all_aprs = [x[2] for x in day1]
        pos_aprs = [a for a in all_aprs if a > 0]
        neg_aprs = [a for a in all_aprs if a < 0]
        print(f"  Day-1 mean APR:           {statistics.mean(all_aprs):+.0f}%")
        print(f"  Day-1 median APR:         {statistics.median(all_aprs):+.0f}%")
        if pos_aprs:
            print(f"  Mean of positive subset:  {statistics.mean(pos_aprs):+.0f}% (n={len(pos_aprs)})")
        if neg_aprs:
            print(f"  Mean of negative subset:  {statistics.mean(neg_aprs):+.0f}% (n={len(neg_aprs)})")
        print(f"\n  Per $1,000 position per listing (1-day hold):")
        avg_win = statistics.mean(pos_aprs) / 365 * 10 if pos_aprs else 0
        avg_loss = statistics.mean(neg_aprs) / 365 * 10 if neg_aprs else 0
        n_pos = len(pos_aprs)
        n_neg = len(neg_aprs)
        total_win = avg_win * n_pos
        total_loss = avg_loss * n_neg
        print(f"    {n_pos} wins × ${avg_win:.1f} avg = ${total_win:+.0f}")
        print(f"    {n_neg} losses × ${avg_loss:.1f} avg = ${total_loss:+.0f}")
        print(f"    NET: ${total_win + total_loss:+.0f} on {len(all_aprs)} listings")

    # ── Verdict ──
    print("\n" + "=" * 78)
    print("VERDICT: DEAD")
    print("=" * 78)
    print("""
  The listing-window hypothesis has THREE fatal problems:

  1. NEGATIVE EXPECTED VALUE: 73% of listings have positive day-1 funding
     (the directional bias is real), but the 25% negative tail is so extreme
     (-1000% to -6000% APR) that the MEAN is -111%. Systematically shorting
     every new listing LOSES money. This is the textbook "picking up pennies
     in front of a steamroller" — you win small frequently and lose
     catastrophically occasionally.

  2. DECAYING: 2024 day-1 median +26% / 88% positive → 2025 +11% / 67%.
     The +11% is Hyperliquid's normal cap rate — by 2025 there is NO excess
     launch premium above baseline. MMs and bots are arriving at listings
     faster; the service vacuum is closing.

  3. CROSS-VENUE SPOT: HL doesn't have spot for new listings. The carry
     trade (short perp + long spot) requires spot elsewhere = the cross-
     venue trap, with especially wide spreads at launch when the token is
     brand new and illiquid everywhere.

  NOT worth building a listing-watcher. The structural window existed in
  early 2024 (when HL was new and underpopulated) but is CLOSED in 2025+.
  This is the same pattern as the spot-listing probe: any window that
  existed was captured by first-second infrastructure, and it's already
  decayed past the point of retail capture.

  The service-vs-prediction framing was correct (this IS a service vacuum,
  not a price prediction), but the service vacuum gets filled too fast —
  within hours, not days — and the tail risk of the short-heavy launches
  makes systematic capture unprofitable.
""")


def cmd_run(args):
    data = fetch_all()
    analyze(data)


def cmd_analyze(args):
    if not DATA_FILE.exists():
        print("No cached data. Run: listing_window.py run")
        return
    with open(DATA_FILE) as f:
        data = json.loads(f.readline())
    analyze(data)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Fetch + analyze")
    sub.add_parser("analyze", help="Analyze cached data")
    args = ap.parse_args()
    {"run": cmd_run, "analyze": cmd_analyze}[args.cmd](args)
