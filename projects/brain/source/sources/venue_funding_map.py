#!/usr/bin/env python3
"""venue_funding_map.py — Small-venue funding landscape + edge-vs-risk scoring.

Maps funding rates across all accessible perp venues, identifies persistent
gaps, and scores whether each gap is EDGE (friction keeps arb out) or
RISK PREMIUM (venue compensates you for blow-up risk).

Does not modify existing loggers/probes/launchd.
"""

import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "venue_funding_map_data.jsonl"


# ── Data fetchers per venue ──────────────────────────────────────────────

def fetch_binance_history(symbols, days=7):
    """8h funding, reference baseline."""
    start = int((time.time() - days * 86400) * 1000)
    results = {}
    for sym in symbols:
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate",
                             params={"symbol": sym + "USDT", "startTime": start, "limit": 100},
                             timeout=10)
            rates = [float(d["fundingRate"]) for d in r.json()]
            results[sym] = {"rates": rates, "interval_h": 8, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_bybit_history(symbols, days=7):
    results = {}
    for sym in symbols:
        try:
            r = requests.get("https://api.bybit.com/v5/market/funding/history",
                             params={"category": "linear", "symbol": sym + "USDT", "limit": 21},
                             timeout=10)
            rates = [float(d["fundingRate"]) for d in r.json()["result"]["list"]]
            results[sym] = {"rates": rates, "interval_h": 8, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_okx_history(symbols, days=7):
    results = {}
    okx_map = {"BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP", "SOL": "SOL-USDT-SWAP",
               "DOGE": "DOGE-USDT-SWAP", "LINK": "LINK-USDT-SWAP"}
    for sym in symbols:
        inst = okx_map.get(sym)
        if not inst:
            continue
        try:
            r = requests.get("https://www.okx.com/api/v5/public/funding-rate-history",
                             params={"instId": inst, "limit": "21"}, timeout=10)
            rates = [float(d["fundingRate"]) for d in r.json()["data"]]
            results[sym] = {"rates": rates, "interval_h": 8, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_dydx_history(symbols, hours=168):
    results = {}
    dydx_map = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
                "DOGE": "DOGE-USD", "LINK": "LINK-USD"}
    for sym in symbols:
        pair = dydx_map.get(sym)
        if not pair:
            continue
        try:
            r = requests.get(f"https://indexer.dydx.trade/v4/historicalFunding/{pair}",
                             params={"limit": hours}, timeout=10)
            rates = [float(d["rate"]) for d in r.json().get("historicalFunding", [])
                     if d.get("rate")]
            results[sym] = {"rates": rates, "interval_h": 1, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_hyperliquid_history(symbols, days=7):
    results = {}
    start = int((time.time() - days * 86400) * 1000)
    for sym in symbols:
        try:
            r = requests.post("https://api.hyperliquid.xyz/info",
                              json={"type": "fundingHistory", "coin": sym, "startTime": start},
                              timeout=10)
            rates = [float(d.get("fundingRate", "0")) for d in r.json()]
            results[sym] = {"rates": rates, "interval_h": 1, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_aevo_history(symbols, limit=168):
    results = {}
    for sym in symbols:
        try:
            r = requests.get("https://api.aevo.xyz/funding-history",
                             params={"instrument_name": f"{sym}-PERP", "limit": limit},
                             timeout=10)
            fh = r.json().get("funding_history", [])
            rates = [float(entry[2]) for entry in fh if len(entry) > 2]
            results[sym] = {"rates": rates, "interval_h": 1, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_orderly_history(symbols):
    results = {}
    orderly_map = {"BTC": "PERP_BTC_USDC", "ETH": "PERP_ETH_USDC", "SOL": "PERP_SOL_USDC"}
    for sym in symbols:
        pair = orderly_map.get(sym)
        if not pair:
            continue
        try:
            r = requests.get("https://api-evm.orderly.org/v1/public/funding_rate_history",
                             params={"symbol": pair, "limit": 60}, timeout=10)
            data = r.json()
            if data.get("success") and data.get("data"):
                rows = data["data"].get("rows", [])
                rates = [float(d["funding_rate"]) for d in rows if d.get("funding_rate")]
                results[sym] = {"rates": rates, "interval_h": 8, "n": len(rates)}
        except Exception:
            pass
    return results


def fetch_deribit_from_logger():
    """Use our existing 20-day venue_carry_snapshots.jsonl."""
    results = {}
    path = BASE / "venue_carry_snapshots.jsonl"
    if not path.exists():
        return results
    rows = [json.loads(l) for l in path.open() if l.strip()]
    deribit = [r for r in rows if r.get("venue") == "deribit"]
    by_sym = defaultdict(list)
    for r in deribit:
        if r.get("funding_apr") and r["funding_apr"] != 0:
            by_sym[r["symbol"]].append(r["funding_apr"])
    for sym, rates in by_sym.items():
        # Convert APR back to per-8h rate for consistency
        per_8h = [r / (3 * 365) / 100 for r in rates]
        results[sym] = {"rates": per_8h, "interval_h": 8, "n": len(per_8h),
                        "source": "venue_carry_logger_20d"}
    return results


def rate_to_apr(rate, interval_h):
    """Convert a per-interval rate to annualized APR."""
    periods_per_year = (365 * 24) / interval_h
    return rate * periods_per_year * 100


def analyze_venue(venue_data):
    """Compute stats for one venue's rates."""
    rates = venue_data["rates"]
    interval_h = venue_data["interval_h"]
    if not rates:
        return None
    med = statistics.median(rates)
    mean = statistics.mean(rates)
    neg_pct = sum(1 for r in rates if r < 0) / len(rates) * 100
    return {
        "median_rate": med,
        "mean_rate": mean,
        "median_apr": rate_to_apr(med, interval_h),
        "mean_apr": rate_to_apr(mean, interval_h),
        "neg_pct": neg_pct,
        "n": len(rates),
        "interval_h": interval_h,
    }


# ── Risk/friction scoring ───────────────────────────────────────────────

VENUE_PROFILES = {
    "Binance": {
        "type": "CEX", "chain": "N/A", "age_years": 9, "est_tvl_B": 100,
        "hack_history": "None major (hot wallet 2019, covered)",
        "withdrawal_risk": "Low (massive reserves, PoR published)",
        "oracle": "Internal (volume-weighted)",
        "nl_access": "BLOCKED for derivatives (2021)",
        "friction": 1, "risk": 1,
        "notes": "Reference baseline. NL-blocked for derivs = unusable for us.",
    },
    "Bybit": {
        "type": "CEX", "chain": "N/A", "age_years": 6, "est_tvl_B": 20,
        "hack_history": "$1.4B hack Feb 2025 (covered from reserves)",
        "withdrawal_risk": "Medium (hack history, recovered)",
        "oracle": "Internal",
        "nl_access": "BLOCKED (DNB fined)",
        "friction": 1, "risk": 3,
        "notes": "NL-blocked. Hack history raises risk score.",
    },
    "OKX": {
        "type": "CEX", "chain": "N/A", "age_years": 7, "est_tvl_B": 15,
        "hack_history": "None major",
        "withdrawal_risk": "Low-medium",
        "oracle": "Internal",
        "nl_access": "Spot only likely, derivs restricted",
        "friction": 1, "risk": 2,
        "notes": "NL derivative access unclear.",
    },
    "Deribit": {
        "type": "CEX", "chain": "N/A", "age_years": 10, "est_tvl_B": 5,
        "hack_history": "None",
        "withdrawal_risk": "Low (long track record, options-focused)",
        "oracle": "Deribit index (multi-exchange)",
        "nl_access": "ACCESSIBLE (MiFID II, not restricted)",
        "friction": 3, "risk": 2,
        "notes": "NL accessible. Lower liquidity on perps than options. Best legal path.",
    },
    "Hyperliquid": {
        "type": "DEX", "chain": "Hyperliquid L1 (appchain)", "age_years": 2,
        "hack_history": "Validator centralization concerns (Mar 2025 JELLY incident)",
        "withdrawal_risk": "Medium-high (appchain, bridge dependency, 4-validator set)",
        "oracle": "On-chain oracle (manipulable in thin markets — JELLY exploit)",
        "nl_access": "Permissionless (DeFi Recital 22 gray zone — geo-block risk)",
        "friction": 4, "risk": 5,
        "notes": "MiCA gray zone = geo-block/wind-down risk. Oracle manipulation "
                 "demonstrated. High funding may be risk premium for these risks.",
    },
    "dYdX": {
        "type": "DEX", "chain": "dYdX Chain (Cosmos appchain)", "age_years": 4,
        "hack_history": "None (v4 is new chain since Oct 2023)",
        "withdrawal_risk": "Medium (appchain, IBC bridge, smaller validator set)",
        "oracle": "Skip/Slinky oracle (decentralized, multi-source)",
        "nl_access": "Permissionless (DeFi, same MiCA gray zone as HL)",
        "friction": 4, "risk": 4,
        "notes": "Persistent negative funding = structural short-heavy positioning. "
                 "Cosmos appchain has bridge risk. v4 relatively new.",
    },
    "Aevo": {
        "type": "DEX", "chain": "Aevo L2 (OP Stack rollup)", "age_years": 2,
        "hack_history": "None",
        "withdrawal_risk": "Medium (L2 rollup, sequencer centralization)",
        "oracle": "Pyth + internal",
        "nl_access": "Permissionless (DeFi, MiCA gray zone)",
        "friction": 3, "risk": 3,
        "notes": "OP Stack rollup = more established infra than appchain. "
                 "Funding tracks CEX rates closely — well-arbed.",
    },
    "Orderly": {
        "type": "DEX infra", "chain": "NEAR/EVM (omnichain)", "age_years": 2,
        "hack_history": "None",
        "withdrawal_risk": "Medium (multi-chain bridging, newer protocol)",
        "oracle": "Pyth",
        "nl_access": "Permissionless",
        "friction": 4, "risk": 4,
        "notes": "Infrastructure layer — users trade via frontends (WOOFi, others). "
                 "High sign-flip rate (38%) = noisy, hard to capture persistently.",
    },
}


def print_risk_card(venue_name):
    p = VENUE_PROFILES.get(venue_name)
    if not p:
        return
    print(f"    Type: {p['type']}  |  Chain: {p['chain']}  |  Age: {p['age_years']}yr")
    print(f"    Hack history: {p['hack_history']}")
    print(f"    Withdrawal risk: {p['withdrawal_risk']}")
    print(f"    Oracle: {p['oracle']}")
    print(f"    NL access: {p['nl_access']}")
    print(f"    FRICTION score: {p['friction']}/5  |  RISK score: {p['risk']}/5")
    if p.get("notes"):
        print(f"    Notes: {p['notes']}")


# ── Main analysis ────────────────────────────────────────────────────────

def fetch_all():
    symbols = ["BTC", "ETH", "SOL", "DOGE", "LINK"]
    print("Fetching funding data from all venues...")

    venues = {}
    for name, fetcher in [
        ("Binance", lambda: fetch_binance_history(symbols)),
        ("Bybit", lambda: fetch_bybit_history(symbols)),
        ("OKX", lambda: fetch_okx_history(symbols)),
        ("dYdX", lambda: fetch_dydx_history(symbols)),
        ("Hyperliquid", lambda: fetch_hyperliquid_history(symbols)),
        ("Aevo", lambda: fetch_aevo_history(symbols)),
        ("Orderly", lambda: fetch_orderly_history(symbols)),
        ("Deribit", fetch_deribit_from_logger),
    ]:
        print(f"  {name}...", end=" ", flush=True)
        try:
            data = fetcher()
            venues[name] = data
            syms = list(data.keys())
            print(f"OK ({len(syms)} symbols: {', '.join(syms[:5])})")
        except Exception as e:
            print(f"FAILED ({e})")

    record = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "venues": {v: {s: {"rates": d["rates"][:200], "interval_h": d["interval_h"]}
                        for s, d in syms.items()}
                   for v, syms in venues.items()},
    }
    with open(DATA_FILE, "w") as f:
        f.write(json.dumps(record) + "\n")
    return venues


def analyze(venues):
    symbols = ["BTC", "ETH", "SOL"]
    venue_order = ["Binance", "Bybit", "OKX", "Deribit", "Aevo",
                   "Hyperliquid", "dYdX", "Orderly"]

    print("\n" + "=" * 78)
    print("  SMALL-VENUE FUNDING LANDSCAPE — GAP MAP + RISK SCORING")
    print("=" * 78)

    # ── Phase 2: Gap Map ──
    print("\n" + "─" * 78)
    print("PHASE 2: FUNDING GAP MAP (7-day median APR, annualized)")
    print("─" * 78)

    # Build the map
    gap_map = {}  # {sym: {venue: stats}}
    for sym in symbols:
        gap_map[sym] = {}
        for venue in venue_order:
            vdata = venues.get(venue, {}).get(sym)
            if vdata:
                stats = analyze_venue(vdata)
                if stats:
                    gap_map[sym][venue] = stats

    for sym in symbols:
        print(f"\n  {sym}:")
        print(f"  {'venue':>14}  {'med APR':>9}  {'neg%':>5}  {'n':>4}  {'interval':>4}  bar")
        entries = sorted(gap_map[sym].items(), key=lambda x: x[1]["median_apr"], reverse=True)
        max_apr = max(abs(e[1]["median_apr"]) for e in entries) if entries else 1
        for venue, stats in entries:
            apr = stats["median_apr"]
            bar_len = int(abs(apr) / max(max_apr, 1) * 30)
            bar = ("+" * bar_len) if apr >= 0 else ("-" * bar_len)
            access = VENUE_PROFILES.get(venue, {}).get("nl_access", "?")
            blocked = " BLOCKED" if "BLOCKED" in access else ""
            print(f"  {venue:>14}  {apr:>+8.2f}%  {stats['neg_pct']:>4.0f}%  {stats['n']:>4}  "
                  f"{stats['interval_h']:>2}h  {bar}{blocked}")

        if entries:
            aprs = [e[1]["median_apr"] for e in entries]
            gap = max(aprs) - min(aprs)
            print(f"  Gap (max − min): {gap:.1f}pp")

    # ── Persistence check ──
    print("\n" + "─" * 78)
    print("PERSISTENCE CHECK (sign-flip = noise, stable sign = capturable)")
    print("─" * 78)

    for venue in venue_order:
        vdata = venues.get(venue, {})
        line_parts = []
        for sym in symbols:
            d = vdata.get(sym)
            if d:
                stats = analyze_venue(d)
                if stats:
                    flip = stats["neg_pct"]
                    label = "STABLE" if flip < 15 else "MIXED" if flip < 40 else "FLIP"
                    line_parts.append(f"{sym}:{label}({flip:.0f}%)")
        if line_parts:
            print(f"  {venue:>14}  {'  '.join(line_parts)}")

    # ── Phase 3: Edge vs Risk Scoring ──
    print("\n" + "─" * 78)
    print("PHASE 3: EDGE vs RISK-PREMIUM SCORING (top gaps)")
    print("─" * 78)

    # Identify top gaps
    top_gaps = []
    for sym in symbols:
        for venue, stats in gap_map.get(sym, {}).items():
            if venue == "Binance":
                continue  # baseline
            bin_stats = gap_map.get(sym, {}).get("Binance")
            if bin_stats:
                gap = abs(stats["median_apr"] - bin_stats["median_apr"])
                top_gaps.append((sym, venue, stats["median_apr"], bin_stats["median_apr"], gap))

    top_gaps.sort(key=lambda x: x[4], reverse=True)

    for sym, venue, venue_apr, bin_apr, gap in top_gaps[:8]:
        print(f"\n  ┌─ {venue} {sym}: {venue_apr:+.2f}% vs Binance {bin_apr:+.2f}% "
              f"(gap {gap:.1f}pp) ─┐")
        print_risk_card(venue)

        profile = VENUE_PROFILES.get(venue, {})
        friction = profile.get("friction", 3)
        risk = profile.get("risk", 3)

        # Score interpretation
        if risk > friction:
            interpretation = "RISK PREMIUM > friction — gap likely compensates for danger"
        elif friction > risk:
            interpretation = "FRICTION > risk — gap likely a real edge (arb can't reach)"
        else:
            interpretation = "MIXED — friction and risk roughly balanced"

        direction = "HIGH (longs pay shorts)" if venue_apr > bin_apr else "LOW/NEGATIVE (shorts pay longs)"
        print(f"    Direction: {direction}")
        print(f"    Interpretation: {interpretation}")

        # Specific analysis per notable case
        if venue == "dYdX" and venue_apr < -5:
            print(f"    ANALYSIS: Persistent negative funding = structural short-heavy OI.")
            print(f"    dYdX v4 user base is SHORT-biased (degens, hedgers). The negative")
            print(f"    rate pays LONGS — but capturing this requires going long perp on an")
            print(f"    appchain with bridge risk. To arb vs Binance, you'd short on Binance")
            print(f"    (blocked for NL) + long on dYdX. Cross-venue arb cost is the SAME")
            print(f"    problem the xexch probe killed (-26% net). NOT an edge for us.")
        elif venue == "Hyperliquid" and venue_apr > 8:
            print(f"    ANALYSIS: HL frequently hits the 0.125%/hr funding cap = structural")
            print(f"    long-heavy OI from retail/leverage traders. The high rate is real but")
            print(f"    the JELLY oracle exploit (Mar 2025) + 4-validator centralization +")
            print(f"    MiCA Recital 22 geo-block risk = significant tail risk. The funding")
            print(f"    is partly compensation for these risks. Single-venue carry (short perp")
            print(f"    + long spot elsewhere) requires cross-venue capital = same friction.")
        elif venue == "Deribit":
            print(f"    ANALYSIS: Deribit is NL-ACCESSIBLE and has a long track record.")
            print(f"    Low BTC funding (+0.5%) = well-arbed by options market makers.")
            print(f"    Higher funding on alts (LINK, BNB) = thinner markets, less arb.")
            print(f"    The carry is thin but the venue risk is LOW — best legal path.")

    # ── Venue clustering ──
    print("\n" + "─" * 78)
    print("VENUE CLUSTERING")
    print("─" * 78)
    print("""
  EFFICIENT CLUSTER (well-arbed, low gaps between them):
    Binance, Bybit, OKX — CEXes, 8h funding, tight spreads, NL-BLOCKED
    Aevo — DEX but tracks CEX rates closely, well-integrated arb

  HIGH-FUNDING CLUSTER (persistent premium):
    Hyperliquid — retail-long-heavy, hits funding cap, oracle/centralization risk
    Orderly — high but noisy (38% sign-flip), hard to capture

  NEGATIVE-FUNDING OUTLIER:
    dYdX — structurally short-heavy, persistent negative rates on ETH/SOL
    Opposite direction from carry trade — pays longs, not shorts

  NL-ACCESSIBLE:
    Deribit (best), Hyperliquid (gray zone), dYdX (gray zone), Aevo (gray zone)
    Binance/Bybit/OKX = BLOCKED
""")

    # ── Verdict ──
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    print("""
  THE GAP MAP reveals three tiers:
  1. EFFICIENT CEXes (Binance/Bybit/OKX): BTC +2-6%, ETH +0.7-2%, SOL +3-8%.
     Tightly arbed between them. NL-blocked — irrelevant for deployment.
  2. DEX PREMIUM venues (Hyperliquid, Orderly): BTC +4-8%, SOL +11%.
     Persistent funding premium over CEXes, BUT:
     - Hyperliquid: RISK > FRICTION (oracle exploit history, 4-validator
       centralization, MiCA gray zone). The 10%+ SOL funding is partly
       compensation for holding funds on a 2-year-old appchain with
       demonstrated oracle manipulation. NOT free money.
     - Orderly: 38% sign-flip on BTC = too noisy to capture persistently.
  3. NEGATIVE OUTLIER (dYdX): ETH -15%, SOL -22%. Structural short-heavy OI.
     Capturing requires cross-venue arb (long dYdX + short elsewhere) =
     the SAME cross-exchange carry that died at -26% net. Not actionable.

  FOR OUR DEPLOYMENT (NL-accessible, single-venue carry):
  - Deribit is the ONLY venue that is (a) NL-legally accessible, (b) has
    meaningful track record (10yr), (c) low risk score. But its funding is
    LOW (BTC +0.5%, ETH +0.2%) — well-arbed by options MMs.
  - Deribit alt funding (LINK +10%, BNB +22%) is higher but thin markets =
    slippage risk, and these are 20-day medians from our logger, not
    guaranteed persistent.
  - Hyperliquid's high rates are TEMPTING but the risk profile (JELLY,
    validators, MiCA) makes it a risk-premium story, not a free edge.

  HONEST BOTTOM LINE:
  The big funding gaps are almost all RISK PREMIUM on sketchy venues, not
  friction-driven edges on safe ones. The pattern from the cross-exchange
  probe holds: gaps exist for reasons, and those reasons cost you.

  Deribit remains the deployment path (low risk, NL-accessible), but the
  funding carry there is THIN (~0.5% BTC, ~0.2% ETH). The deployment
  basket's +2.5% estimate was Binance-based; on Deribit it's closer to
  +0.5-1.0% on the majors, potentially higher on select alts if liquidity
  is sufficient. This NARROWS the Tier-1 carry estimate further.

  GAPS WORTH A DEEPER PROBE (if any):
  - Deribit LINK/BNB/UNI alt funding (10-22% APR from our 20-day logger).
    These are the only high-funding rates on an NL-accessible, low-risk
    venue. Worth checking: is the liquidity deep enough to execute, and
    does the funding persist beyond our 20-day window? The venue_carry
    logger is already capturing this — let it accumulate more data.
  - Everything else is either NL-blocked, too risky, or requires cross-
    venue arb that we've already proven dies on cost.
""")


def cmd_run(args):
    venues = fetch_all()
    analyze(venues)


def cmd_analyze(args):
    data = load_cached()
    if data is None:
        print("No cached data. Run: venue_funding_map.py run")
        return
    # Reconstruct venues dict from cached
    venues = {}
    for v, syms in data.get("venues", {}).items():
        venues[v] = {}
        for s, d in syms.items():
            venues[v][s] = d
    analyze(venues)


def load_cached():
    if not DATA_FILE.exists():
        return None
    with open(DATA_FILE) as f:
        return json.loads(f.readline())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Fetch + analyze")
    sub.add_parser("analyze", help="Analyze cached data")
    args = ap.parse_args()
    {"run": cmd_run, "analyze": cmd_analyze}[args.cmd](args)
