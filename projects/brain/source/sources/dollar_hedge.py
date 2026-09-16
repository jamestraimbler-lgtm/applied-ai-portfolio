"""
Macro probe 3: Do DOLLAR ASSETS hedge the squeeze?

Probes 1-2 showed anti-fiat assets (crypto, gold) fail vs dollar strength.
Tests the inverse: in DXY/VIX/rate stress, do dollar assets actually hold?

Three holdable instruments:
  1. Short Treasuries (SHY — 1-3yr total return ETF)
  2. Long Treasuries (TLT — 20+yr total return ETF)
  3. Dollar cash (0% nominal — relative outperformance baseline)
Plus gold (GC=F) and BTC for the full 5-asset side-by-side map.

Data: FRED for stress measures, Yahoo Finance v8 for SHY/TLT/GC=F,
Binance for BTC. Aligned on common trading days.
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
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "dollar_hedge_aligned.jsonl")
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

# Assets to test (label, source_key)
ASSETS = [
    ("Short Tsy", "shy"),
    ("Long Tsy", "tlt"),
    ("Cash", "cash"),
    ("Gold", "gold"),
    ("BTC", "btc"),
]


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


def fetch_yahoo(symbol: str, start: str) -> dict[str, float]:
    """Download daily adj-close from Yahoo Finance v8."""
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.now().timestamp())
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
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
def stage1(dates, macro, asset_prices):
    ret_dates = dates[1:]
    n = len(ret_dates)

    # Compute returns for all assets
    asset_ret = {}
    for label, key in ASSETS:
        if key == "cash":
            asset_ret[key] = [0.0] * n  # 0% nominal daily
        else:
            asset_ret[key] = daily_returns(asset_prices[key], dates)

    macro_chg = {
        "dxy": daily_returns(macro["dxy"], dates),
        "yield_2y": daily_changes(macro["yield_2y"], dates),
        "yield_10y": daily_changes(macro["yield_10y"], dates),
        "vix": daily_changes(macro["vix"], dates),
    }

    print(f"\n{'=' * 78}")
    print("STAGE 1: DO DOLLAR ASSETS HEDGE THE SQUEEZE?")
    print(f"{'=' * 78}")
    print(f"Period: {dates[0]} to {dates[-1]}  |  n = {n} trading days")
    print(f"SHY = iShares 1-3yr Tsy (adj close, total return incl. coupons)")
    print(f"TLT = iShares 20+yr Tsy (adj close, total return incl. coupons)")
    print(f"Cash = 0% nominal (benchmark: how much do others LOSE vs holding $?)\n")

    # ── Overall correlations ──
    print("--- Overall Correlations (contemporaneous daily) ---\n")
    header = f"{'':>12}" + "".join(f"{s:>12}" for s in STRESS_NAMES)
    print(header)
    for label, key in ASSETS:
        if key == "cash":
            print(f"{label:>12}{'0.000':>12}{'0.000':>12}{'0.000':>12}{'0.000':>12}  (by defn)")
            continue
        row = f"{label:>12}"
        for sn in STRESS_NAMES:
            row += f"{pearson(macro_chg[sn], asset_ret[key]):>+12.3f}"
        print(row)

    # ── Per-asset conditional returns ──
    print(f"\n--- Returns on STRESS Days (top {100 - STRESS_PERCENTILE}%) ---\n")
    for sn in STRESS_NAMES:
        print(f"  {STRESS_LABELS[sn]}:")
        for label, key in ASSETS:
            cs = cond_stats(macro_chg[sn], asset_ret[key])
            if key == "cash":
                print(
                    f"    {label:>12}: stress  0.00% "
                    f"(by defn — others' loss = cash's relative gain)"
                )
            else:
                print(
                    f"    {label:>12}: stress {cs['s_mean']:+.2%} med {cs['s_med']:+.2%} "
                    f"hit {cs['s_hit']:.0%} (n={cs['s_n']})  |  "
                    f"normal {cs['n_mean']:+.2%} hit {cs['n_hit']:.0%}"
                )
        print()

    # ══ THE BIG TABLE: 5 assets × 4 stressors ══
    print("=" * 78)
    print("THE MAP: stress-day mean return by asset × stressor")
    print("  (Positive/flat = hedge. Negative = beta. Cash = 0% baseline.)")
    print("=" * 78)
    print()
    header = f"{'Asset':>12}" + "".join(f"{sn:>14}" for sn in STRESS_NAMES)
    print(header)
    print("-" * (12 + 14 * len(STRESS_NAMES)))
    for label, key in ASSETS:
        row = f"{label:>12}"
        for sn in STRESS_NAMES:
            cs = cond_stats(macro_chg[sn], asset_ret[key])
            row += f"{cs['s_mean']:>+13.2%} "
        print(row)
    print()

    # Hit rates on stress days
    print(f"{'Asset':>12}" + "".join(f"{'hit ' + sn:>14}" for sn in STRESS_NAMES))
    print("-" * (12 + 14 * len(STRESS_NAMES)))
    for label, key in ASSETS:
        row = f"{label:>12}"
        for sn in STRESS_NAMES:
            cs = cond_stats(macro_chg[sn], asset_ret[key])
            row += f"{cs['s_hit']:>13.0%} "
        print(row)

    # ── Stability by year (Short Tsy and Long Tsy only — the new assets) ──
    print(f"\n--- Stability by Year ---\n")
    year_idx = defaultdict(list)
    for i, d in enumerate(ret_dates):
        year_idx[d[:4]].append(i)

    for label, key in [("Short Tsy", "shy"), ("Long Tsy", "tlt")]:
        print(f"  {label}:")
        header = f"  {'Year':>6} {'n':>4}"
        for sn in STRESS_NAMES:
            header += f"  {sn:>10} sign"
        print(header)
        print("  " + "-" * (14 + 16 * len(STRESS_NAMES)))

        signs = {sn: [] for sn in STRESS_NAMES}
        for year in sorted(year_idx):
            idx = year_idx[year]
            row = f"  {year:>6} {len(idx):>4}"
            for sn in STRESS_NAMES:
                ys = [macro_chg[sn][i] for i in idx]
                ya = [asset_ret[key][i] for i in idx]
                cs = cond_stats(ys, ya)
                sign = "+" if cs["s_mean"] > 0 else "-"
                signs[sn].append(sign)
                row += f"  {cs['s_mean']:>+9.2%}    {sign}"
            print(row)

        # Verdict per stressor
        for sn in STRESS_NAMES:
            s = signs[sn]
            neg, pos = s.count("-"), s.count("+")
            total = len(s)
            dom = max(neg, pos)
            dom_sign = "-" if neg >= pos else "+"
            if dom >= total * 0.7:
                char = "BETA" if dom_sign == "-" else "HEDGE"
                v = f"STABLE {dom_sign} in {dom}/{total}yr → {char}"
            else:
                v = f"UNSTABLE ({pos}+/{neg}-)"
            print(f"    {sn:>12}: {v}")
        print()

    return macro_chg, asset_ret, ret_dates


# ── Stage 2 ─────────────────────────────────────────────────────────────
def stage2(macro_chg, asset_ret, ret_dates):
    random.seed(42)

    print(f"\n{'=' * 78}")
    print("STAGE 2: LEAD-LAG (for hedge assets, coincident is the valuable property)")
    print(f"{'=' * 78}")

    for label, key in [("Short Tsy", "shy"), ("Long Tsy", "tlt")]:
        ret = asset_ret[key]
        print(f"\n  {label}:")
        print(f"  {'Measure':>12} {'contemp':>10} {'lag-1d':>10} {'null sep':>10} {'verdict':>24}")
        print("  " + "-" * 70)
        for sn in STRESS_NAMES:
            stress = macro_chg[sn]
            rc = pearson(stress, ret)
            rl = pearson(stress[:-1], ret[1:])

            # Null test
            nulls = []
            for _ in range(1000):
                shuf = ret[1:][:]
                random.shuffle(shuf)
                nulls.append(pearson(stress[:-1], shuf))
            nm = statistics.mean(nulls)
            ns = statistics.stdev(nulls)
            sep = (rl - nm) / ns if ns > 0 else 0

            if abs(rl) > abs(rc) * 0.5 and abs(rl) > 0.03:
                v = "POSSIBLE LEAD"
            elif abs(rc) > 0.05:
                v = "COINCIDENT (same-day)"
            else:
                v = "NO SIGNAL"
            print(f"  {sn:>12} {rc:>+10.4f} {rl:>+10.4f} {sep:>+10.2f}σ {v:>24}")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print("Downloading FRED macro series...")
    macro = {}
    for name, sid in FRED_SERIES.items():
        macro[name] = fetch_fred(sid, START_DATE)
        print(f"  {name} ({sid}): {len(macro[name])} obs")

    print("\nDownloading Yahoo Finance (SHY, TLT, GC=F)...")
    shy = fetch_yahoo("SHY", START_DATE)
    print(f"  SHY: {len(shy)} days")
    tlt = fetch_yahoo("TLT", START_DATE)
    print(f"  TLT: {len(tlt)} days")
    gold = fetch_yahoo("GC%3DF", START_DATE)
    print(f"  GC=F: {len(gold)} days")

    print("\nDownloading BTC...")
    btc = fetch_binance_daily("BTCUSDT", START_DATE)
    print(f"  BTCUSDT: {len(btc)} days")

    asset_prices = {"shy": shy, "tlt": tlt, "gold": gold, "btc": btc}

    # Align on common dates (all macro + all assets)
    dates = align_series(*macro.values(), *asset_prices.values())
    print(f"\nAligned: {len(dates)} common trading days ({dates[0]} to {dates[-1]})")

    # Write aligned data
    with open(DATA_FILE, "w") as f:
        for d in dates:
            row = {"date": d}
            for name in macro:
                row[name] = macro[name][d]
            for key in asset_prices:
                row[key] = asset_prices[key][d]
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(dates)} rows to {os.path.basename(DATA_FILE)}")

    # Stage 1
    macro_chg, asset_ret, ret_dates = stage1(dates, macro, asset_prices)

    # Stage 2
    stage2(macro_chg, asset_ret, ret_dates)

    # Final verdict
    print(f"\n{'=' * 78}")
    print("FINAL VERDICT")
    print(f"{'=' * 78}\n")

    for label, key in ASSETS:
        if key == "cash":
            print(f"  {'Cash':>12}: 0% nominal. The benchmark everything else is measured against.")
            print(f"               On stress days, cash 'wins' by not losing. Boring = safe.\n")
            continue
        ret = asset_ret[key]
        verdicts = []
        for sn in STRESS_NAMES:
            cs = cond_stats(macro_chg[sn], ret)
            if cs["s_mean"] > 0.001 and cs["s_hit"] >= 0.50:
                verdicts.append(f"{sn}=HEDGE")
            elif cs["s_mean"] > -0.002:
                verdicts.append(f"{sn}=neutral")
            else:
                verdicts.append(f"{sn}=BETA")
        print(f"  {label:>12}: {', '.join(verdicts)}")

    print()


if __name__ == "__main__":
    main()
