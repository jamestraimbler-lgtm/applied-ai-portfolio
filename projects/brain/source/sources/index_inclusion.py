"""
Index-inclusion effect probe: do stocks run INTO index inclusion and fade AFTER?

Measures the S&P 500 inclusion effect across ~35 additions (2020-2025):
  - PRE-ANNOUNCE drift (T-20 to T-5, before info is public)
  - ANNOUNCE→EFFECTIVE run-up (T-5 to T, the forced-buying anticipation)
  - POST-INCLUSION fade (T to T+20, after forced buying completes)
All returns are EXCESS vs SPY (strips market beta).

Announcement dates: S&P typically announces ~5 trading days before effective.
Tesla was an exception (25 trading days). We use effective-5 as the standard
proxy and flag Tesla separately. This is an approximation — stated as such.

Builds the baseline for reading the live SPCX ai_ipo_tracker data.
"""

import json
import math
import os
import random
import statistics
import time
from datetime import datetime, timezone, timedelta

import requests

# ── Config ──────────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "index_inclusion_data.jsonl")
ANNOUNCE_GAP = 5  # standard S&P announce-to-effective gap in trading days
PRE_WINDOW = 20   # days before announce to measure pre-drift
POST_WINDOW = 20  # days after effective to measure fade

# ── S&P 500 additions sample (effective dates) ─────────────────────────
# Sources: TickerLeague, S&P press releases, Wikipedia
# Format: (ticker, effective_date, note)
# Tesla has a special announce date (Nov 16, effective Dec 21 = 25 trading days)
SP500_ADDITIONS = [
    # 2020
    ("TSLA", "2020-12-21", "announce=2020-11-16,gap=25d"),
    ("ETSY", "2020-09-21", ""),
    ("TER", "2020-09-21", ""),
    ("POOL", "2020-10-07", ""),
    ("WST", "2020-10-07", ""),
    ("CZR", "2020-12-21", ""),
    # 2021
    ("MRNA", "2021-07-21", ""),
    ("TECH", "2021-06-04", ""),
    ("LCID", "2021-12-20", ""),
    ("EPAM", "2021-12-20", ""),
    ("MTCH", "2021-09-20", ""),
    ("GNRC", "2021-03-22", ""),
    ("CEG", "2021-10-04", ""),
    # 2022
    ("WBD", "2022-04-11", ""),
    ("ON", "2022-06-20", ""),
    ("GEHC", "2022-12-19", ""),
    ("EG", "2022-10-03", ""),
    # 2023
    ("BG", "2023-03-14", ""),
    ("PODD", "2023-03-14", ""),
    ("FICO", "2023-03-17", ""),
    ("KVUE", "2023-08-24", ""),
    ("PANW", "2023-06-20", ""),
    ("BX", "2023-09-18", ""),
    ("ABNB", "2023-09-18", ""),
    ("UBER", "2023-12-18", ""),
    ("BLDR", "2023-12-18", ""),
    # 2024
    ("SMCI", "2024-03-15", ""),
    ("DECK", "2024-03-15", ""),
    ("VST", "2024-05-08", ""),
    ("CRWD", "2024-06-24", ""),
    ("KKR", "2024-06-24", ""),
    ("GDDY", "2024-06-24", ""),
    ("PLTR", "2024-09-23", ""),
    ("DELL", "2024-09-23", ""),
    ("APO", "2024-12-23", ""),
    # 2025
    ("DASH", "2025-03-24", ""),
    ("WSM", "2025-03-24", ""),
    ("XYZ", "2025-07-01", ""),
    ("ARES", "2025-12-11", ""),
    ("CVNA", "2025-12-22", ""),
    ("CRH", "2025-12-22", ""),
]


# ── Download ────────────────────────────────────────────────────────────
def fetch_yahoo(symbol: str, start: str, end: str) -> dict[str, float]:
    """Download daily adj-close for a date range."""
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp()) + 86400
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.status_code != 200:
            return {}
        data = r.json()
    except Exception:
        return {}
    err = data.get("chart", {}).get("error")
    if err:
        return {}
    result_data = data["chart"]["result"][0]
    timestamps = result_data.get("timestamp", [])
    closes = result_data["indicators"]["adjclose"][0]["adjclose"]
    result = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        result[dt.strftime("%Y-%m-%d")] = close
    return result


# ── Measurement ─────────────────────────────────────────────────────────
def measure_event(ticker: str, effective_date: str, note: str, spy_prices: dict):
    """Measure inclusion effect for one event."""
    eff = datetime.strptime(effective_date, "%Y-%m-%d")

    # Determine announce date
    if "announce=" in note:
        ann_str = note.split("announce=")[1].split(",")[0]
        ann = datetime.strptime(ann_str, "%Y-%m-%d")
    else:
        ann = eff - timedelta(days=10)  # ~5 trading days ≈ 7-10 calendar days

    # Fetch window: 40 days before announce to 30 days after effective
    win_start = (ann - timedelta(days=50)).strftime("%Y-%m-%d")
    win_end = (eff + timedelta(days=40)).strftime("%Y-%m-%d")

    prices = fetch_yahoo(ticker, win_start, win_end)
    if not prices:
        return None

    # Get sorted dates
    all_dates = sorted(set(prices.keys()) & set(spy_prices.keys()))
    if len(all_dates) < 20:
        return None

    # Find effective date index (nearest trading day)
    eff_str = effective_date
    eff_idx = None
    for i, d in enumerate(all_dates):
        if d >= eff_str:
            eff_idx = i
            break
    if eff_idx is None or eff_idx < 25 or eff_idx + POST_WINDOW >= len(all_dates):
        return None

    # Find announce date index
    ann_str_approx = ann.strftime("%Y-%m-%d")
    ann_idx = None
    for i, d in enumerate(all_dates):
        if d >= ann_str_approx:
            ann_idx = i
            break
    if ann_idx is None or ann_idx < PRE_WINDOW:
        return None

    # Compute excess returns for each leg
    def excess_return(start_idx, end_idx):
        d0, d1 = all_dates[start_idx], all_dates[end_idx]
        stock_ret = (prices[d1] - prices[d0]) / prices[d0]
        spy_ret = (spy_prices[d1] - spy_prices[d0]) / spy_prices[d0] if d0 in spy_prices and d1 in spy_prices else 0
        return stock_ret - spy_ret

    try:
        pre_drift = excess_return(ann_idx - PRE_WINDOW, ann_idx)
        announce_pop = excess_return(ann_idx - 1, ann_idx) if ann_idx > 0 else 0
        run_up = excess_return(ann_idx, eff_idx)
        post_fade = excess_return(eff_idx, min(eff_idx + POST_WINDOW, len(all_dates) - 1))

        return {
            "ticker": ticker,
            "effective": effective_date,
            "announce_approx": all_dates[ann_idx],
            "pre_drift_20d": pre_drift,
            "announce_pop_1d": announce_pop,
            "run_up_ann_eff": run_up,
            "post_fade_20d": post_fade,
            "note": note,
        }
    except (IndexError, ZeroDivisionError):
        return None


# ── Stats ───────────────────────────────────────────────────────────────
def pearson(x, y):
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / (n - 1))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / (n - 1))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1) / (sx * sy)


def report_leg(name, values):
    """Report stats for one leg of the inclusion effect."""
    n = len(values)
    if n == 0:
        print(f"  {name}: no data")
        return
    mean = statistics.mean(values)
    med = statistics.median(values)
    hit = sum(1 for v in values if v > 0) / n
    sd = statistics.stdev(values) if n > 1 else 0
    print(
        f"  {name:>24}: mean {mean:+.2%}  median {med:+.2%}  "
        f"hit {hit:.0%}  sd {sd:.2%}  n={n}"
    )
    return {"mean": mean, "median": med, "hit": hit, "sd": sd, "n": n}


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print("Downloading SPY baseline (2019-2026)...")
    spy = fetch_yahoo("SPY", "2019-06-01", datetime.now().strftime("%Y-%m-%d"))
    print(f"  SPY: {len(spy)} days\n")

    print(f"Measuring {len(SP500_ADDITIONS)} S&P 500 additions...\n")

    results = []
    failures = []
    for ticker, eff_date, note in SP500_ADDITIONS:
        r = measure_event(ticker, eff_date, note, spy)
        if r:
            results.append(r)
            print(f"  {ticker:>6} ({eff_date}): run-up {r['run_up_ann_eff']:+.1%}  post {r['post_fade_20d']:+.1%}")
        else:
            failures.append(ticker)
        time.sleep(0.15)  # rate limit

    print(f"\nMeasured: {len(results)}/{len(SP500_ADDITIONS)}  (failed: {', '.join(failures) if failures else 'none'})")

    # Write data
    with open(DATA_FILE, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    if len(results) < 10:
        print("\nInsufficient data for analysis.")
        return

    # ══ RESULTS ══
    pre_drifts = [r["pre_drift_20d"] for r in results]
    ann_pops = [r["announce_pop_1d"] for r in results]
    run_ups = [r["run_up_ann_eff"] for r in results]
    post_fades = [r["post_fade_20d"] for r in results]

    print(f"\n{'=' * 70}")
    print(f"INDEX INCLUSION EFFECT — {len(results)} S&P 500 additions (2020-2025)")
    print(f"{'=' * 70}")
    print(f"All returns are EXCESS vs SPY (market-beta stripped)\n")

    print("--- Per-Leg Statistics ---\n")
    report_leg("Pre-announce drift (T-20→T-5)", pre_drifts)
    report_leg("Announce pop (T-6→T-5, 1d)", ann_pops)
    report_leg("Run-up (announce→effective)", run_ups)
    report_leg("Post-inclusion (T→T+20)", post_fades)

    # Tesla case study
    tsla = next((r for r in results if r["ticker"] == "TSLA"), None)
    if tsla:
        print(f"\n--- Tesla Case Study (canonical) ---")
        print(f"  Announce: {tsla['announce_approx']}  Effective: {tsla['effective']}")
        print(f"  Run-up (announce→effective): {tsla['run_up_ann_eff']:+.1%}")
        print(f"  Post-inclusion (20d): {tsla['post_fade_20d']:+.1%}")

    # ── Stability by period ──
    print(f"\n--- Stability: 2020-2022 vs 2023-2025 ---\n")
    early = [r for r in results if r["effective"] < "2023-01-01"]
    late = [r for r in results if r["effective"] >= "2023-01-01"]

    for label, subset in [("2020-2022", early), ("2023-2025", late)]:
        if len(subset) < 3:
            print(f"  {label}: too few ({len(subset)})")
            continue
        ru = [r["run_up_ann_eff"] for r in subset]
        pf = [r["post_fade_20d"] for r in subset]
        print(
            f"  {label} (n={len(subset)}): "
            f"run-up mean {statistics.mean(ru):+.2%} med {statistics.median(ru):+.2%}  |  "
            f"post-fade mean {statistics.mean(pf):+.2%} med {statistics.median(pf):+.2%}"
        )

    # ── Null baseline ──
    print(f"\n--- Null Baseline: random 20-day windows for same stocks ---\n")
    random.seed(42)
    null_returns = []
    spy_dates = sorted(spy.keys())
    for r in results:
        ticker_prices = fetch_yahoo(r["ticker"], "2019-06-01", datetime.now().strftime("%Y-%m-%d"))
        common = sorted(set(ticker_prices.keys()) & set(spy.keys()))
        if len(common) < 100:
            continue
        # 5 random non-event 20-day windows
        for _ in range(5):
            idx = random.randint(20, len(common) - 25)
            d0, d1 = common[idx], common[idx + 20]
            s_ret = (ticker_prices[d1] - ticker_prices[d0]) / ticker_prices[d0]
            spy_ret = (spy[d1] - spy[d0]) / spy[d0]
            null_returns.append(s_ret - spy_ret)
        time.sleep(0.15)

    if null_returns:
        null_mean = statistics.mean(null_returns)
        null_sd = statistics.stdev(null_returns)
        real_ru_mean = statistics.mean(run_ups)
        real_pf_mean = statistics.mean(post_fades)
        ru_sep = (real_ru_mean - null_mean) / null_sd if null_sd > 0 else 0
        pf_sep = (real_pf_mean - null_mean) / null_sd if null_sd > 0 else 0
        print(f"  Null (random 20d): mean {null_mean:+.2%}  sd {null_sd:.2%}  n={len(null_returns)}")
        print(f"  Run-up vs null: {ru_sep:+.2f}σ")
        print(f"  Post-fade vs null: {pf_sep:+.2f}σ")

    # ── Tradeability ──
    COST_BPS = 15
    cost = COST_BPS / 10000
    print(f"\n--- Tradeability (15bps round-trip) ---\n")
    fillable_ru = [r["run_up_ann_eff"] - 2 * cost for r in results]
    fillable_pf = [-r["post_fade_20d"] - 2 * cost for r in results]  # short the fade
    net_ru = statistics.mean(fillable_ru) if fillable_ru else 0
    net_pf = statistics.mean(fillable_pf) if fillable_pf else 0
    hit_ru = sum(1 for v in fillable_ru if v > 0) / len(fillable_ru) if fillable_ru else 0
    hit_pf = sum(1 for v in fillable_pf if v > 0) / len(fillable_pf) if fillable_pf else 0
    print(f"  Buy-announce/sell-effective: mean {net_ru:+.2%} net, hit {hit_ru:.0%}")
    print(f"  Short-effective/cover-T+20:  mean {net_pf:+.2%} net, hit {hit_pf:.0%}")

    # ── SPCX Application ──
    print(f"\n{'=' * 70}")
    print("SPCX APPLICATION (baseline for reading live tracker data)")
    print(f"{'=' * 70}\n")
    print(f"  Historical S&P 500 inclusion effect (median, this sample):")
    print(f"    Announce→effective run-up: {statistics.median(run_ups):+.2%}")
    print(f"    Post-inclusion 20d fade:   {statistics.median(post_fades):+.2%}")
    print(f"\n  SPCX calendar (for comparison against these baselines):")
    print(f"    IPO:  2026-06-12 at $135")
    print(f"    CRSP: ~2026-06-19  (forced-buy trigger)")
    print(f"    NDX:  ~2026-07-03  (Nasdaq-100 fast-entry)")
    print(f"    Russell: Sep + Dec reconstitution")
    print(f"\n  NOTE: SPCX is the LARGEST ever S&P-eligible IPO ($1.77T).")
    print(f"  Tesla ($304B) was the previous record and showed {tsla['run_up_ann_eff']:+.1%} run-up." if tsla else "")
    print(f"  SPCX's size may produce a larger or smaller effect — the sample")
    print(f"  provides a BASELINE, not a prediction for this specific case.")

    # ── Final verdict ──
    print(f"\n{'=' * 70}")
    print("VERDICT (per leg)")
    print(f"{'=' * 70}\n")

    for leg_name, values, direction in [
        ("Run-up (announce→effective)", run_ups, "positive"),
        ("Post-inclusion fade (T→T+20)", post_fades, "negative"),
    ]:
        mean = statistics.mean(values)
        med = statistics.median(values)
        hit = sum(1 for v in values if v > 0) / len(values)
        if abs(med) > 0.005 and (hit > 0.55 or hit < 0.45):
            strength = "REAL"
        elif abs(med) > 0.002:
            strength = "WEAK"
        else:
            strength = "NOISE"
        print(f"  {leg_name}: {strength} — mean {mean:+.2%}, median {med:+.2%}, hit {hit:.0%}")


if __name__ == "__main__":
    main()
