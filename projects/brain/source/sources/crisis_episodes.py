"""
Macro probe 3b: Stress-test the hedge map against REAL crisis episodes.

Extends dollar_hedge.py: instead of daily top-decile stress days, measures
cumulative asset returns across SUSTAINED crisis episodes (multi-week drawdowns).
Same 5 assets: Short Tsy (SHY), Long Tsy (TLT), Cash, Gold (GC=F), BTC.

Two approaches:
  1. DATA-DRIVEN scan: rolling 20-day stress thresholds → cluster into episodes.
  2. Cross-check: do the episodes match known crises? Characterize each.

No forward-timing, no regime-switching — purely retrospective validation
of the daily-decile hedge map on actual crisis windows.
"""

import csv
import io
import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────
START_DATE = "2020-01-01"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "crisis_episodes_aligned.jsonl")

FRED_SERIES = {
    "dxy": "DTWEXBGS",
    "yield_2y": "DGS2",
    "yield_10y": "DGS10",
    "vix": "VIXCLS",
}

# Episode detection thresholds (rolling 20 trading days)
WINDOW = 20
DXY_THRESH = 0.02       # DXY up >2% in 20 days
YIELD10_THRESH = 0.40    # 10yr up >40bps in 20 days
VIX_AVG_THRESH = 25      # VIX avg >25 over 20 days
MERGE_GAP = 5            # merge episodes separated by <5 trading days
MIN_EPISODE_LEN = 10     # drop episodes <10 trading days


# ── Download (same as other probes) ─────────────────────────────────────
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


def align_series(*series_dicts) -> list[str]:
    common = set(series_dicts[0].keys())
    for s in series_dicts[1:]:
        common &= s.keys()
    return sorted(common)


# ── Episode detection ───────────────────────────────────────────────────
def detect_episodes(dates, macro):
    """Scan for sustained stress episodes using rolling windows."""
    n = len(dates)
    flagged = set()
    stressor_flags = defaultdict(set)  # date -> set of active stressors

    for i in range(WINDOW, n):
        window_dates = dates[i - WINDOW : i + 1]
        d = dates[i]

        # DXY rolling return
        dxy_start = macro["dxy"].get(window_dates[0], 0)
        dxy_end = macro["dxy"].get(d, 0)
        if dxy_start > 0:
            dxy_ret = (dxy_end - dxy_start) / dxy_start
            if dxy_ret > DXY_THRESH:
                flagged.add(i)
                stressor_flags[i].add("dxy")

        # 10yr yield rolling change
        y10_start = macro["yield_10y"].get(window_dates[0], 0)
        y10_end = macro["yield_10y"].get(d, 0)
        if y10_end - y10_start > YIELD10_THRESH:
            flagged.add(i)
            stressor_flags[i].add("rate")

        # VIX rolling average
        vix_vals = [macro["vix"][dd] for dd in window_dates if dd in macro["vix"]]
        if vix_vals and statistics.mean(vix_vals) > VIX_AVG_THRESH:
            flagged.add(i)
            stressor_flags[i].add("fear")

    if not flagged:
        return []

    # Cluster consecutive flagged indices into episodes
    sorted_idx = sorted(flagged)
    episodes = []
    ep_start = sorted_idx[0]
    ep_end = sorted_idx[0]
    ep_stressors = set(stressor_flags[sorted_idx[0]])

    for idx in sorted_idx[1:]:
        if idx - ep_end <= MERGE_GAP:
            ep_end = idx
            ep_stressors |= stressor_flags[idx]
        else:
            if ep_end - ep_start + 1 >= MIN_EPISODE_LEN:
                episodes.append((ep_start, ep_end, ep_stressors))
            ep_start = idx
            ep_end = idx
            ep_stressors = set(stressor_flags[idx])

    if ep_end - ep_start + 1 >= MIN_EPISODE_LEN:
        episodes.append((ep_start, ep_end, ep_stressors))

    return episodes


def label_episode(dates, start_idx, end_idx, stressors):
    """Auto-label episodes by date + dominant stressor."""
    d0 = dates[start_idx]
    d1 = dates[end_idx]

    # Known episode matching
    if d0 <= "2020-04-01" and d1 >= "2020-02-15":
        name = "COVID crash"
    elif "2022" in d0[:4] and end_idx - start_idx > 100:
        name = "2022 rate-hike grind"
    elif d0[:7] == "2023-03" or d1[:7] == "2023-03":
        name = "SVB / bank stress"
    elif "2024-08" in d0[:7] or "2024-07" in d0[:7]:
        name = "Aug 2024 yen unwind"
    elif d0 >= "2025-01-01":
        name = f"2025-26 stress"
    else:
        name = f"Stress {d0[:7]}"

    stressor_str = "+".join(sorted(stressors))
    return name, stressor_str


# ── Measurement ─────────────────────────────────────────────────────────
def cumulative_return(prices, dates, start_idx, end_idx):
    """Cumulative return from start to end of episode."""
    d0 = dates[start_idx]
    d1 = dates[end_idx]
    p0 = prices.get(d0, 0)
    p1 = prices.get(d1, 0)
    if p0 > 0:
        return (p1 - p0) / p0
    return 0.0


def episode_stressor_profile(macro, dates, start_idx, end_idx):
    """Measure what each stressor did across the episode."""
    d0 = dates[start_idx]
    d1 = dates[end_idx]
    window = dates[start_idx : end_idx + 1]

    dxy0 = macro["dxy"].get(d0, 0)
    dxy1 = macro["dxy"].get(d1, 0)
    dxy_ret = (dxy1 - dxy0) / dxy0 * 100 if dxy0 else 0

    y2_chg = macro["yield_2y"].get(d1, 0) - macro["yield_2y"].get(d0, 0)
    y10_chg = macro["yield_10y"].get(d1, 0) - macro["yield_10y"].get(d0, 0)

    vix_vals = [macro["vix"][d] for d in window if d in macro["vix"]]
    vix_avg = statistics.mean(vix_vals) if vix_vals else 0
    vix_peak = max(vix_vals) if vix_vals else 0

    return {
        "dxy_pct": dxy_ret,
        "y2_bps": y2_chg * 100,
        "y10_bps": y10_chg * 100,
        "vix_avg": vix_avg,
        "vix_peak": vix_peak,
    }


ASSET_KEYS = [
    ("Short Tsy", "shy"),
    ("Long Tsy", "tlt"),
    ("Cash", None),
    ("Gold", "gold"),
    ("BTC", "btc"),
]


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print("Downloading data (same sources as probes 1-3)...")
    macro = {}
    for name, sid in FRED_SERIES.items():
        macro[name] = fetch_fred(sid, START_DATE)
        print(f"  {name}: {len(macro[name])} obs")

    print("  Yahoo: SHY, TLT, GC=F...")
    shy = fetch_yahoo("SHY", START_DATE)
    tlt = fetch_yahoo("TLT", START_DATE)
    gold = fetch_yahoo("GC%3DF", START_DATE)
    print("  Binance: BTCUSDT...")
    btc = fetch_binance_daily("BTCUSDT", START_DATE)

    asset_prices = {"shy": shy, "tlt": tlt, "gold": gold, "btc": btc}

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

    # ── Detect episodes ──
    episodes = detect_episodes(dates, macro)
    print(f"\nDetected {len(episodes)} crisis episodes:\n")

    if not episodes:
        print("No episodes detected. Check thresholds.")
        return

    # ── Episode detail + asset returns ──
    print("=" * 90)
    print("CRISIS EPISODES: stressor profile + cumulative asset returns")
    print("=" * 90)

    # Collect for summary table
    table_rows = []

    for ep_start, ep_end, stressors in episodes:
        name, stype = label_episode(dates, ep_start, ep_end, stressors)
        d0 = dates[ep_start]
        d1 = dates[ep_end]
        n_days = ep_end - ep_start + 1
        profile = episode_stressor_profile(macro, dates, ep_start, ep_end)

        print(f"\n{'─' * 90}")
        print(f"  {name}")
        print(f"  {d0} → {d1}  ({n_days} trading days)  |  Stressors: {stype}")
        print(
            f"  DXY {profile['dxy_pct']:+.1f}%  |  "
            f"2yr {profile['y2_bps']:+.0f}bps  |  "
            f"10yr {profile['y10_bps']:+.0f}bps  |  "
            f"VIX avg {profile['vix_avg']:.1f} peak {profile['vix_peak']:.1f}"
        )

        # Dominant stressor
        dominant = []
        if abs(profile["dxy_pct"]) > 3:
            dominant.append(f"DXY {'↑' if profile['dxy_pct'] > 0 else '↓'}")
        if abs(profile["y10_bps"]) > 50:
            dominant.append(f"rates {'↑' if profile['y10_bps'] > 0 else '↓'}")
        if profile["vix_avg"] > 25:
            dominant.append("fear")
        if not dominant:
            dominant = ["mild"]
        dom_label = " + ".join(dominant)
        print(f"  Dominant: {dom_label}")

        # Asset returns
        print(f"\n  {'Asset':>12} {'Cumulative':>12} {'Verdict':>30}")
        print(f"  {'-' * 58}")

        row_data = {"name": name, "dates": f"{d0} → {d1}", "days": n_days,
                     "dominant": dom_label, "profile": profile, "returns": {}}

        for label, key in ASSET_KEYS:
            if key is None:
                ret = 0.0
                verdict = "0% nominal (others' loss = cash's rel. gain)"
            else:
                ret = cumulative_return(asset_prices[key], dates, ep_start, ep_end)
                if ret > 0.01:
                    verdict = "HELD / GAINED"
                elif ret > -0.02:
                    verdict = "~FLAT"
                elif ret > -0.10:
                    verdict = "mild loss"
                elif ret > -0.25:
                    verdict = "SIGNIFICANT LOSS"
                else:
                    verdict = "DEVASTATING"
            row_data["returns"][label] = ret
            print(f"  {label:>12} {ret:>+11.1%}  {verdict:>30}")

        table_rows.append(row_data)

    # ══ THE PAYOFF TABLE ══
    print(f"\n\n{'=' * 90}")
    print("THE PAYOFF TABLE: cumulative return per asset per crisis episode")
    print("=" * 90)
    print()

    # Header
    header = f"{'Episode':>28} {'Days':>5} {'Dominant':>16}"
    for label, _ in ASSET_KEYS:
        header += f" {label:>10}"
    print(header)
    print("-" * (28 + 5 + 16 + 11 * len(ASSET_KEYS)))

    for row in table_rows:
        short_name = row["name"][:28]
        line = f"{short_name:>28} {row['days']:>5} {row['dominant']:>16}"
        for label, _ in ASSET_KEYS:
            ret = row["returns"][label]
            line += f" {ret:>+9.1%} "
        print(line)

    # ── Cross-check vs daily-decile map ──
    print(f"\n\n{'=' * 90}")
    print("CROSS-CHECK: do episodes confirm the daily-decile hedge map?")
    print("=" * 90)

    # Daily map reference (from probe 3):
    # DXY stress: Cash=0, ShortTsy=-0.05%, LongTsy=-0.35%, Gold=-0.77%, BTC=-0.86%
    # Rate stress: Cash=0, ShortTsy=-0.15%, LongTsy=-1.63%, Gold=-0.43%, BTC=+0.31%
    # VIX stress: Cash=0, ShortTsy=+0.03%, LongTsy=+0.16%, Gold=-0.03%, BTC=-2.58%

    print("\n  Daily-decile map (from probe 3) predicted:")
    print("    DXY stress → everything loses except cash")
    print("    Rate stress → bonds crushed, BTC surprisingly positive")
    print("    VIX/fear → long bonds hedge, BTC crashes")
    print()

    for row in table_rows:
        name = row["name"]
        dom = row["dominant"]
        rets = row["returns"]

        print(f"  {name} ({dom}):")

        # Find best and worst
        non_cash = {k: v for k, v in rets.items() if k != "Cash"}
        best = max(non_cash, key=non_cash.get)
        worst = min(non_cash, key=non_cash.get)

        print(f"    Best:  {best} ({non_cash[best]:+.1%})")
        print(f"    Worst: {worst} ({non_cash[worst]:+.1%})")

        # Check if daily prediction held
        if "fear" in dom.lower():
            tlt_ret = rets["Long Tsy"]
            btc_ret = rets["BTC"]
            if tlt_ret > 0 and btc_ret < -0.1:
                print("    ✓ Confirms daily map: long bonds hedged, BTC crashed")
            elif tlt_ret < -0.05:
                print("    ✗ CONTRADICTS daily map: long bonds FAILED as fear hedge")
            else:
                print(f"    ~ Mixed: TLT {tlt_ret:+.1%}, BTC {btc_ret:+.1%}")

        if "rates" in dom.lower() and "↑" in dom:
            tlt_ret = rets["Long Tsy"]
            if tlt_ret < -0.1:
                print("    ✓ Confirms: long bonds crushed by rate stress (as predicted)")
            else:
                print(f"    ~ Long Tsy {tlt_ret:+.1%} — not the devastation expected")

        if "dxy" in dom.lower() and "↑" in dom:
            all_neg = all(v <= 0.01 for k, v in rets.items() if k != "Cash")
            if all_neg:
                print("    ✓ Confirms: everything negative, cash wins (as predicted)")
            else:
                winners = [k for k, v in non_cash.items() if v > 0.01]
                if winners:
                    print(f"    ~ Exception: {', '.join(winners)} positive despite DXY stress")
        print()

    # ── Honest nuances ──
    print("=" * 90)
    print("HONEST NUANCES")
    print("=" * 90)

    # Check for daily-vs-episode divergence
    print("\n  1. DAILY-FLAT BUT EPISODE-BLEED trap:")
    for row in table_rows:
        if row["days"] > 50:  # only long episodes
            for label, _ in ASSET_KEYS:
                if label == "Cash":
                    continue
                ret = row["returns"][label]
                # Gold was "flat" on daily VIX stress but might bleed in long episodes
                if label == "Gold" and abs(ret) > 0.05:
                    print(
                        f"    Gold in {row['name']}: {ret:+.1%} over {row['days']} days"
                        f" — daily-flat on VIX but episode-level tells a different story"
                    )

    # Cash inflation adjustment
    print("\n  2. CASH INFLATION EROSION:")
    print("    Cash is 0% NOMINAL. In sustained high-inflation episodes:")
    for row in table_rows:
        if row["days"] > 100:
            # Rough: 2022 CPI ~8% annualized, ~0.03% per trading day
            if "2022" in row["name"]:
                approx_inflation = row["days"] * 0.0003  # ~8% annualized
                print(
                    f"    {row['name']} ({row['days']} days): cash lost ~{approx_inflation:.0%}"
                    f" real (CPI ~8% ann). Still beat everything except possibly BTC."
                )

    # Crisis-type dependence
    print("\n  3. CRISIS-TYPE DEPENDENCE:")
    print("    The hedge that works depends on the crisis TYPE:")
    for row in table_rows:
        dom = row["dominant"]
        rets = row["returns"]
        non_cash = {k: v for k, v in rets.items() if k != "Cash"}
        best = max(non_cash, key=non_cash.get)
        print(f"    {row['name']:>30} ({dom:>16}) → best non-cash: {best}")
    print(
        "\n    You can only identify the crisis type AS IT UNFOLDS (coincident),"
        "\n    not in advance. This is the honest limitation: there is no"
        "\n    single pre-positioned hedge that works for all crisis types."
    )

    # ── Final verdict ──
    print(f"\n{'=' * 90}")
    print("FINAL VERDICT")
    print(f"{'=' * 90}\n")

    print("  Does the episode view CONFIRM or COMPLICATE the daily-decile map?\n")


if __name__ == "__main__":
    main()
