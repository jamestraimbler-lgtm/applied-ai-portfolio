"""Forward-only paper-trade logger for funding carry edge.

Captures ACTUAL bid/ask spreads at funding-relevant moments.
The backtest assumed fills at kline closes with 1bp slippage per leg;
this logs what the real order book looks like pre-funding.
"""

import json, os, statistics, time
from datetime import datetime, timezone

import requests

SNAPSHOTS_FILE = "paper_carry_snapshots.jsonl"

# The 12 tokens that survived 2× fees in the funding carry backtest
WINNERS = [
    "BTC", "ETH", "BNB", "XRP", "DOGE", "ADA",
    "LINK", "UNI", "LTC", "NEAR", "SUI", "ARB",
]

# Backtest cost assumptions (for comparison)
PERP_TAKER_BPS = 4.5     # per side
SPOT_TAKER_BPS = 10.0    # per side
SLIPPAGE_BPS = 1.0       # per leg per side (backtest assumption)
ROUND_TRIP_BPS = 2 * (PERP_TAKER_BPS + SPOT_TAKER_BPS + 2 * SLIPPAGE_BPS)  # 33bp


def snapshot():
    """Capture current book state for all carry-eligible tokens."""
    now = time.time()
    rows = []

    for sym in WINNERS:
        pair = f"{sym}USDT"
        try:
            sb = requests.get("https://api.binance.com/api/v3/ticker/bookTicker",
                              params={"symbol": pair}, timeout=10).json()
            pb = requests.get("https://fapi.binance.com/fapi/v1/ticker/bookTicker",
                              params={"symbol": pair}, timeout=10).json()
            pi = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex",
                              params={"symbol": pair}, timeout=10).json()
        except Exception as e:
            print(f"  {sym}: request failed ({e})")
            continue

        s_bid = float(sb["bidPrice"])
        s_ask = float(sb["askPrice"])
        p_bid = float(pb["bidPrice"])
        p_ask = float(pb["askPrice"])
        s_mid = (s_bid + s_ask) / 2
        p_mid = (p_bid + p_ask) / 2

        if s_mid == 0 or p_mid == 0:
            continue

        s_spread = (s_ask - s_bid) / s_mid * 10_000
        p_spread = (p_ask - p_bid) / p_mid * 10_000

        rows.append({
            "ts": now,
            "symbol": sym,
            "spot_bid": s_bid,
            "spot_ask": s_ask,
            "perp_bid": p_bid,
            "perp_ask": p_ask,
            "spot_spread_bps": round(s_spread, 3),
            "perp_spread_bps": round(p_spread, 3),
            "basis_mid_bps": round((p_mid - s_mid) / s_mid * 10_000, 3),
            "entry_basis_bps": round((p_bid - s_ask) / s_ask * 10_000, 3),
            "funding_rate": float(pi["lastFundingRate"]),
            "next_funding_ts": int(pi["nextFundingTime"]) / 1000,
        })

    with open(SNAPSHOTS_FILE, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    ts_str = datetime.fromtimestamp(now, tz=timezone.utc
                                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Snapshot at {ts_str}: {len(rows)} tokens")
    print(f"  {'sym':>6}  {'spot sp':>8}  {'perp sp':>8}  "
          f"{'total':>7}  {'basis':>8}  {'entry':>8}  {'funding':>10}")

    for r in rows:
        tot = r["spot_spread_bps"] + r["perp_spread_bps"]
        print(f"  {r['symbol']:>6}  {r['spot_spread_bps']:>6.2f}bp  "
              f"{r['perp_spread_bps']:>6.2f}bp  {tot:>5.2f}bp  "
              f"{r['basis_mid_bps']:>+6.1f}bp  {r['entry_basis_bps']:>+6.1f}bp  "
              f"{r['funding_rate'] * 100:>+8.4f}%")

    if rows:
        spreads = sorted(r["spot_spread_bps"] + r["perp_spread_bps"]
                         for r in rows)
        med = spreads[len(spreads) // 2]
        assumed = SLIPPAGE_BPS * 4
        print(f"\n  Median total spread:   {med:.2f}bp")
        print(f"  Backtest slip assumed: {assumed:.0f}bp (1bp × 4 legs)")
        print(f"  Gap:                   {med - assumed:+.2f}bp")


def report():
    """Analyze accumulated snapshots vs backtest assumptions."""
    if not os.path.exists(SNAPSHOTS_FILE):
        print("No snapshots yet.")
        return

    rows = [json.loads(l) for l in open(SNAPSHOTS_FILE) if l.strip()]
    n_events = len(set(round(r["ts"]) for r in rows))
    if n_events < 6:
        print(f"Only {n_events} capture events — need ≥6 (2+ days). Wait.")
        return

    by_sym = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)

    print(f"Paper carry report — {len(rows)} rows, "
          f"{n_events} capture events\n")

    print(f"  {'sym':>6}  {'n':>4}  {'med spot':>9}  {'med perp':>9}  "
          f"{'med total':>10}  {'med funding':>12}  "
          f"{'gross APR':>10}  {'spread hit':>10}")

    all_totals = []
    for sym in WINNERS:
        sr = by_sym.get(sym, [])
        if not sr:
            continue
        s_sp = [r["spot_spread_bps"] for r in sr]
        p_sp = [r["perp_spread_bps"] for r in sr]
        tots = [s + p for s, p in zip(s_sp, p_sp)]
        rates = [r["funding_rate"] for r in sr]

        med_t = statistics.median(tots)
        med_r = statistics.median(rates)
        gross = med_r * 3 * 365 * 100

        # Spread hit: actual total spread vs assumed 4bp, per round-trip
        # For always-on: this is a ONE-TIME cost difference
        extra = max(0, med_t - SLIPPAGE_BPS * 4) * 2  # × 2 for round-trip
        # Annualized: not meaningful for one-time cost, show raw bps
        all_totals.extend(tots)

        print(f"  {sym:>6}  {len(sr):>4}  "
              f"{statistics.median(s_sp):>7.2f}bp  "
              f"{statistics.median(p_sp):>7.2f}bp  "
              f"{med_t:>8.2f}bp  {med_r * 100:>+10.4f}%  "
              f"{gross:>+8.1f}%  {extra:>+8.1f}bp")

    if all_totals:
        med = statistics.median(all_totals)
        assumed = SLIPPAGE_BPS * 4
        extra_rt = max(0, med - assumed) * 2
        print(f"\n  Aggregate median spread:       {med:.2f}bp")
        print(f"  Backtest assumed (4 legs):      {assumed:.0f}bp")
        print(f"  Extra spread per round-trip:    {extra_rt:+.1f}bp")
        print(f"  Impact on always-on net APR:    "
              f"{-extra_rt / 100:.3f}% (one-time, amortized = negligible)")
        print(f"\n  Verdict: if median spread ≤ ~10bp, the +2.5% APR survives.")
        print(f"  If >> 20bp on thin alts, those specific tokens are suspect.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Paper carry logger")
    ap.add_argument("cmd", choices=["snapshot", "report"])
    args = ap.parse_args()
    {"snapshot": snapshot, "report": report}[args.cmd]()
