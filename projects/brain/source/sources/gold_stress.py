"""
Macro probe 2: Is GOLD the hedge crypto wasn't?

Same structure as dollar_stress.py (probe 1). Tests gold vs the same 3 stress
measures (DXY, 2yr/10yr yields, VIX). Side-by-side comparison with BTC.

Data: FRED (free CSV) for macro, Yahoo Finance v8 for gold futures (GC=F),
Binance 1d klines for BTC (comparison only). Aligned on common trading days.
"""

import csv
import io
import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────
START_DATE = "2020-01-01"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "gold_stress_aligned.jsonl")
STRESS_PERCENTILE = 90

FRED_SERIES = {
    "dxy": "DTWEXBGS",
    "yield_2y": "DGS2",
    "yield_10y": "DGS10",
    "vix": "VIXCLS",
}
STRESS_NAMES = ["dxy", "yield_2y", "yield_10y", "vix"]
STRESS_LABELS = {
    "dxy": "DXY up ($ strengthens)",
    "yield_2y": "2yr yield up (rates rise)",
    "yield_10y": "10yr yield up (rates rise)",
    "vix": "VIX up (fear spikes)",
}


# ── Download ────────────────────────────────────────────────────────────
def fetch_fred(series_id: str, start: str) -> dict[str, float]:
    end = datetime.now().strftime("%Y-%m-%d")
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&cosd={start}&coed={end}"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    result = {}
    reader = csv.reader(io.StringIO(r.text))
    next(reader)
    for row in reader:
        if not row[1] or row[1] == ".":
            continue
        result[row[0]] = float(row[1])
    return result


def fetch_yahoo_gold(start: str) -> dict[str, float]:
    """Download gold futures (GC=F) daily closes from Yahoo Finance v8."""
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.now().timestamp())
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/GC%3DF"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    data = r.json()["chart"]["result"][0]
    timestamps = data["timestamp"]
    closes = data["indicators"]["adjclose"][0]["adjclose"]
    result = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        result[dt.strftime("%Y-%m-%d")] = close
    return result


def fetch_binance_daily(symbol: str, start: str) -> dict[str, float]:
    start_ms = int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000)
    result = {}
    while True:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=1d&startTime={start_ms}&limit=1000"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for bar in data:
            dt = datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc)
            result[dt.strftime("%Y-%m-%d")] = float(bar[4])
        start_ms = data[-1][0] + 86_400_000
        if len(data) < 1000:
            break
        time.sleep(0.2)
    return result


# ── Align + returns ─────────────────────────────────────────────────────
def align_series(*series_dicts) -> list[str]:
    common = set(series_dicts[0].keys())
    for s in series_dicts[1:]:
        common &= s.keys()
    return sorted(common)


def daily_returns(prices: dict[str, float], dates: list[str]) -> list[float]:
    ret = []
    for i in range(1, len(dates)):
        p0 = prices[dates[i - 1]]
        ret.append((prices[dates[i]] - p0) / p0 if p0 else 0.0)
    return ret


def daily_changes(levels: dict[str, float], dates: list[str]) -> list[float]:
    return [levels[dates[i]] - levels[dates[i - 1]] for i in range(1, len(dates))]


# ── Stats ───────────────────────────────────────────────────────────────
def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / (n - 1))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / (n - 1))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1) / (sx * sy)


def pctl(vals: list[float], p: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


def cond_stats(stress: list[float], ret: list[float], p=STRESS_PERCENTILE):
    thresh = pctl(stress, p)
    s_ret = [ret[i] for i in range(len(stress)) if stress[i] >= thresh]
    n_ret = [ret[i] for i in range(len(stress)) if stress[i] < thresh]
    return {
        "s_n": len(s_ret),
        "s_mean": statistics.mean(s_ret) if s_ret else 0,
        "s_med": statistics.median(s_ret) if s_ret else 0,
        "s_hit": sum(1 for r in s_ret if r > 0) / len(s_ret) if s_ret else 0,
        "n_n": len(n_ret),
        "n_mean": statistics.mean(n_ret) if n_ret else 0,
        "n_hit": sum(1 for r in n_ret if r > 0) / len(n_ret) if n_ret else 0,
    }


# ── Stage 1 ─────────────────────────────────────────────────────────────
def stage1(dates, macro, gold_prices, btc_prices):
    ret_dates = dates[1:]
    n = len(ret_dates)

    gold_ret = daily_returns(gold_prices, dates)
    btc_ret = daily_returns(btc_prices, dates)

    macro_chg = {
        "dxy": daily_returns(macro["dxy"], dates),
        "yield_2y": daily_changes(macro["yield_2y"], dates),
        "yield_10y": daily_changes(macro["yield_10y"], dates),
        "vix": daily_changes(macro["vix"], dates),
    }

    print(f"\n{'=' * 74}")
    print("STAGE 1: GOLD — HEDGE vs BETA CHARACTERIZATION")
    print(f"{'=' * 74}")
    print(f"Period: {dates[0]} to {dates[-1]}  |  n = {n} trading days\n")

    # ── Overall correlations ──
    print("--- Overall Correlations (contemporaneous daily) ---\n")
    header = f"{'':>10}" + "".join(f"{s:>12}" for s in STRESS_NAMES)
    print(header)
    for label, ret in [("Gold", gold_ret), ("BTC", btc_ret)]:
        row = f"{label:>10}"
        for sn in STRESS_NAMES:
            row += f"{pearson(macro_chg[sn], ret):>+12.3f}"
        print(row)
    print("  (BTC from probe 1 for direct comparison)\n")

    # ── Conditional returns: gold vs BTC on stress days ──
    print(f"--- Returns on STRESS Days (top {100 - STRESS_PERCENTILE}%): Gold vs BTC ---\n")
    for sn in STRESS_NAMES:
        print(f"  {STRESS_LABELS[sn]}:")
        cg = cond_stats(macro_chg[sn], gold_ret)
        cb = cond_stats(macro_chg[sn], btc_ret)
        print(
            f"    Gold: stress {cg['s_mean']:+.2%} med {cg['s_med']:+.2%} "
            f"hit {cg['s_hit']:.0%} (n={cg['s_n']})  |  "
            f"normal {cg['n_mean']:+.2%} hit {cg['n_hit']:.0%}"
        )
        print(
            f"    BTC:  stress {cb['s_mean']:+.2%} med {cb['s_med']:+.2%} "
            f"hit {cb['s_hit']:.0%} (n={cb['s_n']})  |  "
            f"normal {cb['n_mean']:+.2%} hit {cb['n_hit']:.0%}"
        )
        delta = cg["s_mean"] - cb["s_mean"]
        print(f"    >>> Gold advantage on stress days: {delta:+.2%}")
        print()

    # ── Stability by year ──
    print("--- Stability by Year (GOLD mean return on stress days) ---\n")
    year_idx = defaultdict(list)
    for i, d in enumerate(ret_dates):
        year_idx[d[:4]].append(i)

    header = f"{'Year':>6} {'n':>4}"
    for sn in STRESS_NAMES:
        header += f"  {sn:>10} sign"
    print(header)
    print("-" * (16 + 16 * len(STRESS_NAMES)))

    signs = {sn: [] for sn in STRESS_NAMES}
    for year in sorted(year_idx):
        idx = year_idx[year]
        row = f"{year:>6} {len(idx):>4}"
        for sn in STRESS_NAMES:
            ys = [macro_chg[sn][i] for i in idx]
            yg = [gold_ret[i] for i in idx]
            cs = cond_stats(ys, yg)
            sign = "+" if cs["s_mean"] > 0 else "-"
            signs[sn].append(sign)
            row += f"  {cs['s_mean']:>+9.2%}    {sign}"
        print(row)

    # ── Verdict ──
    print(f"\n--- Stage 1 Verdict ---\n")
    any_stable = False
    for sn in STRESS_NAMES:
        s = signs[sn]
        neg, pos = s.count("-"), s.count("+")
        total = len(s)
        dom = max(neg, pos)
        dom_sign = "-" if neg >= pos else "+"
        if dom >= total * 0.7:
            char = "BETA (dumps)" if dom_sign == "-" else "HEDGE (holds/rises)"
            v = f"STABLE {dom_sign} in {dom}/{total}yr → {char}"
            any_stable = True
        else:
            v = f"UNSTABLE — flips {pos}+/{neg}- across years (regime-dependent)"
        print(f"  {sn:>12}: {v}")

    print(
        f"\n  (~{n // 10} stress days/measure, "
        f"~{n // 10 // len(year_idx)} per year — per-year estimates are noisy)"
    )
    return any_stable, macro_chg, gold_ret, btc_ret, ret_dates


# ── Stage 2 ─────────────────────────────────────────────────────────────
def stage2(macro_chg, gold_ret, ret_dates, stable):
    """Lead-lag analysis. For a hedge, coincident is fine = portfolio insurance."""
    random.seed(42)

    print(f"\n{'=' * 74}")
    if not stable:
        print("STAGE 2: LEAD-LAG  *** Stage 1 unstable — academic only ***")
    else:
        print("STAGE 2: LEAD-LAG ANALYSIS")
        print("  (For a hedge, COINCIDENT protection is the valuable property —")
        print("   you hold gold for insurance, not timing. Lead-lag is a bonus.)")
    print(f"{'=' * 74}")

    print(f"\n--- Lead-Lag: stress[t] vs Gold[t] (contemp) vs Gold[t+1] (lagged) ---\n")
    print(f"{'Measure':>12} {'contemp':>10} {'lag-1d':>10} {'verdict':>24}")
    print("-" * 60)
    for sn in STRESS_NAMES:
        stress = macro_chg[sn]
        rc = pearson(stress, gold_ret)
        rl = pearson(stress[:-1], gold_ret[1:])
        if abs(rl) > abs(rc) * 0.5 and abs(rl) > 0.03:
            v = "POSSIBLE LEAD"
        elif abs(rc) > 0.05:
            v = "COINCIDENT (same-day)"
        else:
            v = "NO SIGNAL"
        print(f"{sn:>12} {rc:>+10.4f} {rl:>+10.4f} {v:>24}")

    N_SHUFFLES = 1000
    print(f"\n--- Null Test: real lagged rho vs {N_SHUFFLES} shuffled ---\n")
    print(f"{'Measure':>12} {'real lag':>10} {'null mu':>10} {'null sd':>10} {'sep sigma':>10}")
    print("-" * 56)
    for sn in STRESS_NAMES:
        stress = macro_chg[sn]
        real_lag = pearson(stress[:-1], gold_ret[1:])
        nulls = []
        for _ in range(N_SHUFFLES):
            shuf = gold_ret[1:][:]
            random.shuffle(shuf)
            nulls.append(pearson(stress[:-1], shuf))
        nm = statistics.mean(nulls)
        ns = statistics.stdev(nulls)
        sep = (real_lag - nm) / ns if ns > 0 else 0
        print(f"{sn:>12} {real_lag:>+10.4f} {nm:>+10.4f} {ns:>10.4f} {sep:>+10.2f}")


# ── Side-by-side summary ────────────────────────────────────────────────
def side_by_side(macro_chg, gold_ret, btc_ret):
    print(f"\n{'=' * 74}")
    print("SIDE-BY-SIDE: GOLD vs BTC as STRESS HEDGE")
    print(f"{'=' * 74}\n")

    print(
        f"{'Measure':>12} {'Gold stress':>14} {'BTC stress':>14} "
        f"{'Gold hit':>10} {'BTC hit':>10} {'Winner':>10}"
    )
    print("-" * 74)
    for sn in STRESS_NAMES:
        cg = cond_stats(macro_chg[sn], gold_ret)
        cb = cond_stats(macro_chg[sn], btc_ret)
        winner = "GOLD" if cg["s_mean"] > cb["s_mean"] else "BTC"
        print(
            f"{sn:>12} {cg['s_mean']:>+13.2%} {cb['s_mean']:>+13.2%} "
            f"{cg['s_hit']:>9.0%} {cb['s_hit']:>9.0%} {winner:>10}"
        )

    print(f"\n  Positive on stress → genuine hedge (insurance value)")
    print(f"  Negative on stress → beta (dumps with risk assets)")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print("Downloading FRED macro series...")
    macro = {}
    for name, sid in FRED_SERIES.items():
        macro[name] = fetch_fred(sid, START_DATE)
        print(f"  {name} ({sid}): {len(macro[name])} obs")

    print("\nDownloading gold futures (GC=F) from Yahoo Finance...")
    gold = fetch_yahoo_gold(START_DATE)
    print(f"  GC=F: {len(gold)} days")

    print("\nDownloading BTC for comparison...")
    btc = fetch_binance_daily("BTCUSDT", START_DATE)
    print(f"  BTCUSDT: {len(btc)} days")

    # Align on common dates
    dates = align_series(*macro.values(), gold, btc)
    print(f"\nAligned: {len(dates)} common trading days ({dates[0]} to {dates[-1]})")

    # Write aligned data
    with open(DATA_FILE, "w") as f:
        for d in dates:
            row = {"date": d, "gold": gold[d], "btc": btc[d]}
            for name in macro:
                row[name] = macro[name][d]
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(dates)} rows to {os.path.basename(DATA_FILE)}")

    # Stage 1
    stable, macro_chg, gold_ret, btc_ret, ret_dates = stage1(dates, macro, gold, btc)

    # Side-by-side
    side_by_side(macro_chg, gold_ret, btc_ret)

    # Stage 2
    stage2(macro_chg, gold_ret, ret_dates, stable)

    # Final verdict
    print(f"\n{'=' * 74}")
    print("FINAL VERDICT")
    print(f"{'=' * 74}\n")

    for sn in STRESS_NAMES:
        stress = macro_chg[sn]
        cg = cond_stats(stress, gold_ret)
        cb = cond_stats(stress, btc_ret)
        rc = pearson(stress, gold_ret)
        rl = pearson(stress[:-1], gold_ret[1:])

        if cg["s_mean"] > 0.001 and cg["s_hit"] >= 0.50:
            char = "HEDGE (rises on stress)"
        elif cg["s_mean"] > -0.002:
            char = "NEUTRAL (flat on stress)"
        else:
            char = "BETA (dumps on stress)"

        if abs(rc) > 0.05:
            timing = "coincident (portfolio insurance)"
        elif abs(rl) > 0.03:
            timing = "weak lead-lag"
        else:
            timing = "no clear timing"

        delta = cg["s_mean"] - cb["s_mean"]
        print(f"  {sn:>12}: Gold is {char}; {timing}")
        print(f"               vs BTC: gold {delta:+.2%} better on stress days")

    print()


if __name__ == "__main__":
    main()
