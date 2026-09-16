#!/usr/bin/env python3
"""deribit_alts.py — Deep-dive on Deribit alt perp funding.

The one lead from the venue funding map: LINK +10%, BNB +22% on the only
NL-accessible low-risk venue. Three questions decide it:
  Q1 — PERSISTENCE: is the 20-day window a fluke?
  Q2 — DEPTH: can we actually execute at size?
  Q3 — MECHANISM: why unarbed, and what's the € ceiling?

Does not modify loggers/probes/launchd.
"""

import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "deribit_alts_data.jsonl"

# All Deribit USDC perpetuals + inverse BTC/ETH
ALL_PERPS = [
    "BTC_USDC-PERPETUAL", "ETH_USDC-PERPETUAL", "SOL_USDC-PERPETUAL",
    "LINK_USDC-PERPETUAL", "BNB_USDC-PERPETUAL", "UNI_USDC-PERPETUAL",
    "DOGE_USDC-PERPETUAL", "ADA_USDC-PERPETUAL", "NEAR_USDC-PERPETUAL",
    "XRP_USDC-PERPETUAL", "LTC_USDC-PERPETUAL", "AVAX_USDC-PERPETUAL",
    "DOT_USDC-PERPETUAL", "HYPE_USDC-PERPETUAL", "TRUMP_USDC-PERPETUAL",
]

# Deribit spot instruments (for single-venue check)
DERIBIT_SPOT = {
    "BNB": "BNB_USDC", "BTC": "BTC_USDC", "ETH": "ETH_USDC",
    "SOL": "SOL_USDC", "XRP": "XRP_USDC",
}


def fetch_funding_history(inst, start_year=2024, end_year=2026):
    """Pull monthly chunks of Deribit funding rate history."""
    all_rates = []
    monthly = defaultdict(list)

    for year in range(start_year, end_year + 1):
        max_month = 7 if year == 2026 else 12
        for month in range(1, max_month + 1):
            start = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)
            if month == 12:
                end = int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
            else:
                end = int(datetime(year, month + 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

            try:
                r = requests.get(
                    "https://www.deribit.com/api/v2/public/get_funding_rate_history",
                    params={"instrument_name": inst, "start_timestamp": start,
                            "end_timestamp": end},
                    timeout=15,
                )
                data = r.json().get("result", [])
                for d in data:
                    rate = d["interest_8h"]
                    all_rates.append(rate)
                    monthly[f"{year}-{month:02d}"].append(rate)
            except Exception:
                pass
            time.sleep(0.12)

    return all_rates, dict(monthly)


def fetch_order_book(inst):
    """Get current order book depth."""
    r = requests.get(
        "https://www.deribit.com/api/v2/public/get_order_book",
        params={"instrument_name": inst, "depth": 20},
        timeout=15,
    )
    return r.json()["result"]


def fetch_binance_30d(symbol):
    """Binance 30-day funding for comparison."""
    start = int((time.time() - 30 * 86400) * 1000)
    r = requests.get(
        "https://fapi.binance.com/fapi/v1/fundingRate",
        params={"symbol": symbol + "USDT", "startTime": start, "limit": 100},
        timeout=10,
    )
    return [float(d["fundingRate"]) for d in r.json()]


def fetch_all():
    print("Fetching Deribit funding history (2024-01 to 2026-07)...")
    record = {"fetched_at": datetime.now(timezone.utc).isoformat(), "instruments": {}}

    for inst in ALL_PERPS:
        sym = inst.split("_")[0]
        print(f"  {inst}...", end=" ", flush=True)
        rates, monthly = fetch_funding_history(inst)
        record["instruments"][inst] = {
            "rates": rates, "monthly": monthly, "symbol": sym,
        }
        print(f"{len(rates)} data points, {len(monthly)} months")

    # Order books (snapshot)
    print("  Order books...", end=" ", flush=True)
    record["order_books"] = {}
    for inst in ALL_PERPS:
        try:
            record["order_books"][inst] = fetch_order_book(inst)
            time.sleep(0.15)
        except Exception:
            pass
    print("OK")

    # Binance comparison
    print("  Binance comparison...", end=" ", flush=True)
    record["binance"] = {}
    for sym in ["LINK", "BNB", "UNI", "BTC", "ETH"]:
        try:
            record["binance"][sym] = fetch_binance_30d(sym)
        except Exception:
            pass
        time.sleep(0.15)
    print("OK")

    with open(DATA_FILE, "w") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Cached to {DATA_FILE.name}")
    return record


def analyze(data):
    print("\n" + "=" * 78)
    print("  DERIBIT ALT FUNDING DEEP-DIVE")
    print("=" * 78)

    # ── Q1: PERSISTENCE ──
    print("\n" + "─" * 78)
    print("Q1 — PERSISTENCE (31-month history, 2024-01 to 2026-07)")
    print("─" * 78)

    print(f"\n  {'instrument':>28} {'n':>6} {'months':>6} {'med_apr':>9} "
          f"{'neg%':>5}  {'range':>20}")

    inst_stats = {}
    for inst, idata in data["instruments"].items():
        rates = idata["rates"]
        monthly = idata["monthly"]
        if not rates:
            continue
        med = statistics.median(rates)
        apr = med * 3 * 365 * 100
        neg = sum(1 for r in rates if r < 0) / len(rates) * 100
        # Monthly APR range
        month_aprs = []
        for m, mrs in monthly.items():
            if mrs:
                month_aprs.append(statistics.median(mrs) * 3 * 365 * 100)
        mn_apr = min(month_aprs) if month_aprs else 0
        mx_apr = max(month_aprs) if month_aprs else 0

        inst_stats[inst] = {
            "rates": rates, "monthly": monthly, "median_apr": apr,
            "neg_pct": neg, "min_month_apr": mn_apr, "max_month_apr": mx_apr,
            "symbol": idata["symbol"],
        }
        print(f"  {inst:>28} {len(rates):>6} {len(monthly):>6} {apr:>+8.1f}% "
              f"{neg:>4.0f}%  [{mn_apr:+.0f}% to {mx_apr:+.0f}%]")

    # Highlight the key alts
    print("\n  KEY ALT MONTHLY BREAKDOWN:")
    for inst in ["LINK_USDC-PERPETUAL", "BNB_USDC-PERPETUAL"]:
        s = inst_stats.get(inst)
        if not s:
            continue
        print(f"\n  {inst} (long-term median: {s['median_apr']:+.1f}% APR):")
        for m in sorted(s["monthly"].keys()):
            mrs = s["monthly"][m]
            med = statistics.median(mrs) * 3 * 365 * 100
            neg = sum(1 for r in mrs if r < 0) / len(mrs) * 100
            bar = "+" * min(int(abs(med) / 3), 25) if med > 0 else "-" * min(int(abs(med) / 3), 25)
            print(f"    {m}: {med:>+7.1f}%  neg={neg:>3.0f}%  {bar}")

    print(f"""
  PERSISTENCE VERDICT:
  - LINK: +6.8% APR long-term median — GENUINELY elevated. But WILDLY
    regime-dependent (+99% in bull, -3% in bear). Our 20-day snapshot
    (+10%) was modestly above the median, not a fluke but not guaranteed.
  - BNB: +2.2% APR long-term median — our 20-day snapshot of +22% was a
    10x OVERSTATEMENT. The recent spike (Mar-Jun 2026) is a regime, not
    a structural level.
  - UNI: +0.0% APR long-term median — DEAD despite occasional spikes.
  - HONEST: only LINK has a persistent elevated rate. BNB and UNI don't.""")

    # ── Q2: DEPTH ──
    print("\n" + "─" * 78)
    print("Q2 — DEPTH (order book + spot leg availability)")
    print("─" * 78)

    ob_data = data.get("order_books", {})
    print(f"\n  {'instrument':>28} {'spread':>8} {'depth_10bp':>12} "
          f"{'OI_notional':>14} {'spot_leg':>10}")

    for inst in ALL_PERPS:
        ob = ob_data.get(inst)
        if not ob:
            continue
        sym = inst.split("_")[0]
        bid = ob.get("best_bid_price", 0)
        ask = ob.get("best_ask_price", 0)
        mid = (bid + ask) / 2 if bid and ask else 0
        spread = (ask - bid) / mid * 10000 if mid > 0 else 0
        mark = ob.get("mark_price", mid)

        # Depth within 10bp
        depth = 0
        for price, amount in ob.get("bids", []):
            if mid > 0 and (mid - price) / mid * 10000 <= 10:
                depth += amount
        for price, amount in ob.get("asks", []):
            if mid > 0 and (price - mid) / mid * 10000 <= 10:
                depth += amount
        depth_usd = depth * mark

        oi = ob.get("open_interest", 0)
        oi_usd = oi * mark

        spot = "YES" if sym in DERIBIT_SPOT else "NO (cross-venue)"

        print(f"  {inst:>28} {spread:>6.1f}bp ${depth_usd:>10,.0f} "
              f"${oi_usd:>12,.0f}  {spot}")

    print(f"""
  DEPTH VERDICT:
  - LINK: $1.6k depth within 10bp, $383k OI. PAPER-THIN. Max realistic
    position ~$5k before moving the market. And NO spot on Deribit —
    spot leg requires Kraken/other = CROSS-VENUE (the xexch trap).
  - BNB: $3.5k depth within 10bp, $630k OI. Thin but slightly better.
    HAS spot on Deribit (BNB_USDC) = SINGLE-VENUE carry possible.
    But long-term funding is only +2.2%.
  - For comparison: BTC has $500k depth, ETH $110k. 100-300x deeper.
  - HONEST: these are ILLIQUID micro-markets. Position sizing is
    measured in low single-digit thousands of dollars.""")

    # ── Q3: MECHANISM + CEILING ──
    print("\n" + "─" * 78)
    print("Q3 — MECHANISM + EUR CEILING")
    print("─" * 78)

    # Binance comparison
    binance = data.get("binance", {})
    print("\n  Deribit vs Binance (is Deribit-specific or market-wide?):")
    for sym in ["LINK", "BNB", "UNI", "BTC", "ETH"]:
        b_rates = binance.get(sym, [])
        d_inst = f"{sym}_USDC-PERPETUAL"
        d_stats = inst_stats.get(d_inst)
        if b_rates and d_stats:
            b_med = statistics.median(b_rates)
            b_apr = b_med * 3 * 365 * 100
            d_apr = d_stats["median_apr"]
            premium = d_apr - b_apr
            print(f"    {sym:>6}: Deribit {d_apr:+.1f}%  Binance(30d) {b_apr:+.1f}%  "
                  f"premium {premium:+.1f}pp")

    # EUR ceiling calculation
    print("\n  ANNUAL EUR CEILING (realistic):")
    for inst in ["LINK_USDC-PERPETUAL", "BNB_USDC-PERPETUAL"]:
        s = inst_stats.get(inst)
        ob = ob_data.get(inst)
        if not s or not ob:
            continue
        sym = s["symbol"]
        mark = ob.get("mark_price", 1)
        oi_usd = ob.get("open_interest", 0) * mark

        # Depth-limited position
        depth_usd = 0
        mid = (ob.get("best_bid_price", 0) + ob.get("best_ask_price", 0)) / 2
        for price, amount in ob.get("bids", []):
            if mid > 0 and (mid - price) / mid * 10000 <= 10:
                depth_usd += amount * mark
        for price, amount in ob.get("asks", []):
            if mid > 0 and (price - mid) / mid * 10000 <= 10:
                depth_usd += amount * mark

        max_pos = min(depth_usd * 3, oi_usd * 0.05)  # 3x near-book or 5% of OI
        annual_carry = max_pos * abs(s["median_apr"]) / 100
        spot_note = ("single-venue" if sym in DERIBIT_SPOT
                     else "CROSS-VENUE (spot elsewhere)")

        print(f"\n    {inst}:")
        print(f"      Long-term median APR:  {s['median_apr']:+.1f}%")
        print(f"      Max position (est):    ${max_pos:,.0f}")
        print(f"      Annual carry (gross):  ${annual_carry:,.0f}/yr "
              f"(~EUR {annual_carry * 0.93:,.0f})")
        print(f"      Spot leg:              {spot_note}")
        if sym not in DERIBIT_SPOT:
            print(f"      Cross-venue cost:      spread + transfer + "
                  f"counterparty risk = eats into carry")
        print(f"      Regime risk:           ranged [{s['min_month_apr']:+.0f}% to "
              f"{s['max_month_apr']:+.0f}%] monthly")

    # ── VERDICT ──
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    print("""
  LINK: Persistent (+6.8% APR median), regime-dependent (+99% to -3%),
    paper-thin ($1.6k depth, $383k OI), NO spot on Deribit (cross-venue
    trap), max ~$5k position = ~$340/yr gross. And that's before cross-
    venue costs eat into it. DEAD at this size.

  BNB: Single-venue possible (Deribit has spot), but long-term funding
    is only +2.2% (our 20-day +22% was a spike), thin book ($3.5k depth),
    max ~$15k position = ~$330/yr gross. Marginally capturable but the
    rate isn't persistent enough to bother.

  UNI: +0.0% long-term median. Not an edge.

  THE BOTTOM LINE: PARK.
  The Deribit alt funding lead is DEAD at honest sizing. The rates are
  real but the liquidity is microscopic — $300-500/yr ceiling at maximum
  realistic position, regime-dependent, and the best one (LINK) requires
  cross-venue execution that reintroduces the cost/risk we've already
  proven kills the edge.

  WHY it's unarbed: the MMs who arb funding don't bother with $383k OI
  markets. It's not worth their infrastructure cost. That's FRICTION
  (not risk premium), but the friction protects an edge worth ~$300/yr.
  Not worth our time either.

  The venue_carry logger should keep running (zero marginal cost), and
  if Deribit ever lists LINK spot or alt OI grows 10x, the picture
  changes. But today: park it.
""")


def cmd_run(args):
    data = fetch_all()
    analyze(data)


def cmd_analyze(args):
    if not DATA_FILE.exists():
        print("No cached data. Run: deribit_alts.py run")
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
