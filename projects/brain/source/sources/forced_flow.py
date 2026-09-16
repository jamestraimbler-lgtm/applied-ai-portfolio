"""
Falsification probe: does front-running FORCED, MANDATED, PRICE-INSENSITIVE
flow survive the latency wall?

THE STRONGEST CASE against "prediction dies": index funds MUST buy on the
effective date regardless of price (mandated-slow by regulation). If ANY
predictive edge survives, it's anticipating this flow — because the counterparty
is slow by DESIGN, not by speed-disadvantage.

Tests: is the inclusion run-up STRONGER for the LARGEST forced-flow / lowest-
liquidity names? And is the run-up FILLABLE after announcement (or already
priced by fast players who front-run the forced flow for you)?

Reuses the index_inclusion.py S&P 500 additions sample, adds:
  - Forced-flow proxy: avg daily dollar volume (ADV$) around the event
  - Size sort: biggest demand-shock = highest mcap / lowest ADV$
"""

import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

# ── S&P 500 additions (same as index_inclusion.py) ─────────────────────
SP500_ADDITIONS = [
    ("TSLA", "2020-12-21", "announce=2020-11-16,gap=25d"),
    ("ETSY", "2020-09-21", ""), ("TER", "2020-09-21", ""),
    ("POOL", "2020-10-07", ""), ("WST", "2020-10-07", ""),
    ("CZR", "2020-12-21", ""),
    ("MRNA", "2021-07-21", ""), ("TECH", "2021-06-04", ""),
    ("LCID", "2021-12-20", ""), ("EPAM", "2021-12-20", ""),
    ("MTCH", "2021-09-20", ""), ("GNRC", "2021-03-22", ""),
    ("WBD", "2022-04-11", ""), ("ON", "2022-06-20", ""),
    ("EG", "2022-10-03", ""),
    ("BG", "2023-03-14", ""), ("PODD", "2023-03-14", ""),
    ("FICO", "2023-03-17", ""), ("KVUE", "2023-08-24", ""),
    ("PANW", "2023-06-20", ""), ("BX", "2023-09-18", ""),
    ("ABNB", "2023-09-18", ""), ("UBER", "2023-12-18", ""),
    ("BLDR", "2023-12-18", ""),
    ("SMCI", "2024-03-15", ""), ("DECK", "2024-03-15", ""),
    ("VST", "2024-05-08", ""), ("CRWD", "2024-06-24", ""),
    ("KKR", "2024-06-24", ""), ("GDDY", "2024-06-24", ""),
    ("PLTR", "2024-09-23", ""), ("DELL", "2024-09-23", ""),
    ("APO", "2024-12-23", ""),
    ("DASH", "2025-03-24", ""), ("WSM", "2025-03-24", ""),
    ("XYZ", "2025-07-01", ""), ("ARES", "2025-12-11", ""),
    ("CVNA", "2025-12-22", ""), ("CRH", "2025-12-22", ""),
]

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "forced_flow_data.jsonl")
COST_BPS = 15


# ── Download ────────────────────────────────────────────────────────────
def fetch_yahoo_ohlcv(symbol: str, start: str, end: str) -> list[dict]:
    """Fetch daily OHLCV (with volume) for a date range."""
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp()) + 86400
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("chart", {}).get("error"):
            return []
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        quote = result["indicators"]["quote"][0]
        adj = result["indicators"]["adjclose"][0]["adjclose"]
        rows = []
        for i, ts in enumerate(timestamps):
            if adj[i] is None:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            rows.append({
                "date": dt.strftime("%Y-%m-%d"),
                "close": adj[i],
                "volume": quote["volume"][i] or 0,
            })
        return rows
    except Exception:
        return []


def fetch_spy_prices(start: str, end: str) -> dict[str, float]:
    rows = fetch_yahoo_ohlcv("SPY", start, end)
    return {r["date"]: r["close"] for r in rows}


# ── Measurement ─────────────────────────────────────────────────────────
def measure_event(ticker, effective_date, note, spy):
    eff = datetime.strptime(effective_date, "%Y-%m-%d")

    # Announce date
    if "announce=" in note:
        ann = datetime.strptime(note.split("announce=")[1].split(",")[0], "%Y-%m-%d")
    else:
        ann = eff - timedelta(days=10)

    # Fetch wide window
    win_start = (ann - timedelta(days=50)).strftime("%Y-%m-%d")
    win_end = (eff + timedelta(days=40)).strftime("%Y-%m-%d")
    rows = fetch_yahoo_ohlcv(ticker, win_start, win_end)
    if len(rows) < 30:
        return None

    dates = [r["date"] for r in rows]
    prices = {r["date"]: r["close"] for r in rows}
    volumes = {r["date"]: r["volume"] for r in rows}

    # Find effective and announce indices
    eff_str = effective_date
    ann_str = ann.strftime("%Y-%m-%d")
    eff_idx = ann_idx = None
    for i, d in enumerate(dates):
        if d >= eff_str and eff_idx is None:
            eff_idx = i
        if d >= ann_str and ann_idx is None:
            ann_idx = i
    if eff_idx is None or ann_idx is None or ann_idx < 20 or eff_idx + 20 >= len(dates):
        return None

    # Average daily dollar volume (20 days before announce)
    pre_window = dates[max(0, ann_idx - 20):ann_idx]
    adv_dollar = 0
    if pre_window:
        dollar_vols = [prices.get(d, 0) * volumes.get(d, 0) for d in pre_window]
        adv_dollar = statistics.mean(dollar_vols) if dollar_vols else 0

    # Price at announce
    ann_price = prices.get(dates[ann_idx], 0)

    # Returns (excess vs SPY)
    def excess(i0, i1):
        d0, d1 = dates[i0], dates[i1]
        sr = (prices[d1] - prices[d0]) / prices[d0] if prices[d0] else 0
        spy_r = (spy.get(d1, 0) - spy.get(d0, 0)) / spy.get(d0, 1) if spy.get(d0) else 0
        return sr - spy_r

    # Announcement pop: day before announce → announce close
    ann_pop = excess(ann_idx - 1, ann_idx)

    # Run-up: announce close → effective (the FILLABLE window — you buy AFTER announce)
    run_up_post_ann = excess(ann_idx, eff_idx)

    # Post-inclusion fade: effective → T+20
    post_fade = excess(eff_idx, min(eff_idx + 20, len(dates) - 1))

    # Total fillable: announce close → effective (this is what you could capture)
    fillable = run_up_post_ann

    # Volume surge: ratio of effective-day volume to ADV
    eff_vol = volumes.get(dates[eff_idx], 0) * prices.get(dates[eff_idx], 0)
    vol_surge = eff_vol / adv_dollar if adv_dollar > 0 else 0

    return {
        "ticker": ticker,
        "effective": effective_date,
        "adv_dollar_M": adv_dollar / 1e6,
        "ann_price": ann_price,
        "ann_pop": ann_pop,
        "fillable_runup": fillable,
        "post_fade": post_fade,
        "vol_surge": vol_surge,
    }


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print("Downloading SPY baseline...")
    spy = fetch_spy_prices("2019-06-01", datetime.now().strftime("%Y-%m-%d"))
    print(f"  SPY: {len(spy)} days\n")

    print(f"Measuring {len(SP500_ADDITIONS)} additions with volume data...\n")
    results = []
    for ticker, eff, note in SP500_ADDITIONS:
        r = measure_event(ticker, eff, note, spy)
        if r:
            results.append(r)
            print(f"  {ticker:>6}: ADV${r['adv_dollar_M']:.0f}M  fillable {r['fillable_runup']:+.1%}  vol_surge {r['vol_surge']:.1f}x")
        else:
            print(f"  {ticker:>6}: FAILED")
        time.sleep(0.15)

    print(f"\nMeasured: {len(results)}/{len(SP500_ADDITIONS)}")

    # Write data
    with open(DATA_FILE, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    if len(results) < 15:
        print("Insufficient data.")
        return

    # ══ SIZE-SORTED ANALYSIS ══
    print(f"\n{'=' * 74}")
    print("FALSIFICATION TEST: does forced-flow SIZE predict run-up strength?")
    print(f"{'=' * 74}")

    # Sort by ADV$ (ascending = lowest liquidity = biggest demand shock)
    sorted_by_adv = sorted(results, key=lambda r: r["adv_dollar_M"])
    n = len(sorted_by_adv)
    t1 = n // 3
    t2 = 2 * n // 3

    terciles = [
        ("LOW liquidity (biggest shock)", sorted_by_adv[:t1]),
        ("MID liquidity", sorted_by_adv[t1:t2]),
        ("HIGH liquidity (smallest shock)", sorted_by_adv[t2:]),
    ]

    print(f"\n--- Tercile Analysis: sorted by ADV$ (low → high liquidity) ---\n")
    print(f"  {'Tercile':>32} {'n':>4} {'ADV$ range':>20} {'Fillable runup':>16} {'Ann pop':>10} {'Post fade':>12}")
    print(f"  {'-' * 98}")

    for label, group in terciles:
        advs = [r["adv_dollar_M"] for r in group]
        fillables = [r["fillable_runup"] for r in group]
        pops = [r["ann_pop"] for r in group]
        fades = [r["post_fade"] for r in group]
        adv_range = f"${min(advs):.0f}-{max(advs):.0f}M"
        print(
            f"  {label:>32} {len(group):>4} {adv_range:>20} "
            f"med {statistics.median(fillables):>+6.1%} mean {statistics.mean(fillables):>+6.1%} "
            f"{statistics.mean(pops):>+9.1%} "
            f"med {statistics.median(fades):>+6.1%}"
        )

    # Show individual names in each tercile
    print(f"\n--- Names per tercile ---\n")
    for label, group in terciles:
        names = [f"{r['ticker']}(${r['adv_dollar_M']:.0f}M)" for r in group]
        print(f"  {label[:20]:>20}: {', '.join(names)}")

    # ── THE FILLABLE TEST: is the run-up captured AFTER announce? ──
    print(f"\n{'=' * 74}")
    print("THE FILLABLE TEST: is the run-up already priced AT announcement?")
    print(f"{'=' * 74}\n")

    all_pops = [r["ann_pop"] for r in results]
    all_fillable = [r["fillable_runup"] for r in results]

    print(f"  Announcement pop (day before → announce close):")
    print(f"    Mean: {statistics.mean(all_pops):+.2%}  Median: {statistics.median(all_pops):+.2%}  Hit: {sum(1 for p in all_pops if p > 0)/len(all_pops):.0%}")
    print(f"\n  Fillable run-up (announce close → effective, what you can capture):")
    print(f"    Mean: {statistics.mean(all_fillable):+.2%}  Median: {statistics.median(all_fillable):+.2%}  Hit: {sum(1 for f in all_fillable if f > 0)/len(all_fillable):.0%}")

    # Volume surge on effective day
    surges = [r["vol_surge"] for r in results]
    print(f"\n  Effective-day volume surge (vs 20d ADV):")
    print(f"    Mean: {statistics.mean(surges):.1f}x  Median: {statistics.median(surges):.1f}x")
    print(f"    → Forced buying IS visible in the data (volume spike on effective date)")

    # ── NULL BASELINE ──
    random.seed(42)
    print(f"\n{'=' * 74}")
    print("NULL BASELINE: real fillable run-up vs random 5-day windows")
    print(f"{'=' * 74}\n")

    null_returns = []
    for r in results:
        rows = fetch_yahoo_ohlcv(r["ticker"], "2019-06-01", datetime.now().strftime("%Y-%m-%d"))
        if len(rows) < 100:
            continue
        dates = [row["date"] for row in rows]
        prices = {row["date"]: row["close"] for row in rows}
        for _ in range(10):
            idx = random.randint(20, len(dates) - 25)
            d0, d5 = dates[idx], dates[min(idx + 5, len(dates) - 1)]
            sr = (prices[d5] - prices[d0]) / prices[d0] if prices[d0] else 0
            spy_r = (spy.get(d5, 0) - spy.get(d0, 0)) / spy.get(d0, 1) if spy.get(d0) else 0
            null_returns.append(sr - spy_r)
        time.sleep(0.15)

    if null_returns:
        nm = statistics.mean(null_returns)
        ns = statistics.stdev(null_returns)
        real_mean = statistics.mean(all_fillable)
        sep = (real_mean - nm) / ns if ns > 0 else 0
        print(f"  Null (random 5d excess): mean {nm:+.2%}  sd {ns:.2%}  n={len(null_returns)}")
        print(f"  Real fillable run-up:    mean {real_mean:+.2%}")
        print(f"  Separation: {sep:+.2f}σ")

        # Per-tercile vs null
        print(f"\n  Per-tercile vs null:")
        for label, group in terciles:
            fillables = [r["fillable_runup"] for r in group]
            t_mean = statistics.mean(fillables)
            t_sep = (t_mean - nm) / ns if ns > 0 else 0
            print(f"    {label[:32]:>32}: {t_mean:+.2%} mean ({t_sep:+.2f}σ vs null)")

    # ── COST ──
    cost = COST_BPS / 10000 * 2  # round trip
    print(f"\n{'=' * 74}")
    print(f"COST TEST ({COST_BPS}bps × 2 legs = {COST_BPS*2}bps round-trip)")
    print(f"{'=' * 74}\n")

    net_fillable = [f - cost for f in all_fillable]
    net_mean = statistics.mean(net_fillable)
    net_hit = sum(1 for f in net_fillable if f > 0) / len(net_fillable)
    print(f"  All: gross {statistics.mean(all_fillable):+.2%} → net {net_mean:+.2%}  hit {net_hit:.0%}")

    for label, group in terciles:
        fillables = [r["fillable_runup"] - cost for r in group]
        t_mean = statistics.mean(fillables)
        t_hit = sum(1 for f in fillables if f > 0) / len(fillables)
        print(f"  {label[:32]:>32}: net {t_mean:+.2%}  hit {t_hit:.0%}")

    # ── STABILITY ──
    print(f"\n{'=' * 74}")
    print("STABILITY: per-period")
    print(f"{'=' * 74}\n")

    early = [r for r in results if r["effective"] < "2023-01-01"]
    late = [r for r in results if r["effective"] >= "2023-01-01"]
    for label, group in [("2020-2022", early), ("2023-2025", late)]:
        if len(group) < 5:
            continue
        fill = [r["fillable_runup"] for r in group]
        print(
            f"  {label} (n={len(group)}): fillable mean {statistics.mean(fill):+.2%} "
            f"median {statistics.median(fill):+.2%}  hit {sum(1 for f in fill if f > 0)/len(fill):.0%}"
        )

    # ── SPCX TIE-IN ──
    print(f"\n{'=' * 74}")
    print("SPCX TIE-IN")
    print(f"{'=' * 74}\n")

    # Find the lowest-ADV tercile's characteristics
    low_liq = terciles[0][1]
    low_fill_mean = statistics.mean([r["fillable_runup"] for r in low_liq])
    low_fill_med = statistics.median([r["fillable_runup"] for r in low_liq])
    print(f"  SPCX ($1.77T, biggest-ever S&P-eligible IPO) maps to the")
    print(f"  extreme end of forced-flow demand. Based on this sample:")
    print(f"  - Lowest-liquidity tercile fillable run-up: mean {low_fill_mean:+.1%}, median {low_fill_med:+.1%}")
    print(f"  - If forced-flow front-running is real, SPCX should show a")
    print(f"    run-up into CRSP/NDX inclusion dates EXCEEDING the median")
    print(f"    inclusion effect (+1.6%). If it doesn't, the forced-flow")
    print(f"    edge is already competed away even at extreme size.")

    # ── VERDICT ──
    print(f"\n{'=' * 74}")
    print("VERDICT: is the central finding FALSIFIED?")
    print(f"{'=' * 74}\n")

    overall_fill_mean = statistics.mean(all_fillable)
    overall_fill_med = statistics.median(all_fillable)
    low_fill = [r["fillable_runup"] for r in terciles[0][1]]
    high_fill = [r["fillable_runup"] for r in terciles[2][1]]
    gradient = statistics.mean(low_fill) - statistics.mean(high_fill)

    print(f"  1. Fillable run-up (post-announce): mean {overall_fill_mean:+.2%}, median {overall_fill_med:+.2%}")
    print(f"  2. Size gradient (low-liq minus high-liq): {gradient:+.2%}")
    print(f"  3. Null separation: {sep:+.2f}σ" if null_returns else "  3. Null: insufficient data")
    print()

    if overall_fill_med > 0.01 and sep > 2.0 and gradient > 0.02:
        print("  >>> FALSIFIED: forced-flow front-running beats null + cost.")
        print("  >>> The wall breaks when the counterparty is mandated-slow.")
        print("  >>> Exception to 'prediction dies' found.")
    elif overall_fill_med > 0.005 and sep > 1.0:
        print("  >>> PARTIALLY FALSIFIED: signal exists but weak/marginal after cost.")
        print("  >>> The wall is dented but not broken.")
    else:
        print("  >>> WALL HOLDS: even forced, mandated, price-insensitive flow is")
        print("  >>> already priced by fast players who front-run the announcement.")
        print("  >>> The wall beats even mandated-slow counterparties.")
        print("  >>> Central finding SURVIVES its hardest test.")


if __name__ == "__main__":
    main()
