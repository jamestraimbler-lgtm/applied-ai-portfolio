"""
Empirical joint tail: measure what ACTUALLY happened to the 3 confirmed edges
during the 2021-2024 crisis windows.

Reconstructs daily return series for:
  1. Funding carry (Binance BTC funding, delta-neutral)
  2. Stable-LP (USDC/USDT pool: fees + LP value change from USDC price)
  3. FX carry (AUD/JPY + MXN/USD + NZD/JPY basket)

Then measures: per-edge tails, joint-tail co-movement, named-event analysis
(UST/LUNA May 2022, FTX Nov 2022, USDC/SVB Mar 2023), and the actual basket
max drawdown vs the deployment plan's -15% to -25% estimate.
"""

import csv
import io
import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

# ── Config ──────────────────────────────────────────────────────────────
START = "2021-01-01"
END = "2024-12-31"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "joint_tail_data.jsonl")
FEE_DAILY = 0.04 / 365  # 4% ann fee (between 3% live and 5.5% backtest)


# ── Download ────────────────────────────────────────────────────────────
def fetch_binance_funding(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    all_data = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"https://fapi.binance.com/fapi/v1/fundingRate"
            f"?symbol={symbol}&startTime={cursor}&limit=1000"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for d in data:
            if d["fundingTime"] <= end_ms:
                all_data.append({"ts": d["fundingTime"], "rate": float(d["fundingRate"])})
        cursor = data[-1]["fundingTime"] + 1
        if len(data) < 1000:
            break
        time.sleep(0.1)
    return all_data


def fetch_binance_klines(symbol: str, start: str, end: str) -> dict[str, float]:
    start_ms = int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000)
    end_ms = int(datetime.strptime(end, "%Y-%m-%d").timestamp() * 1000)
    result = {}
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=1d&startTime={cursor}&limit=1000"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for bar in data:
            dt = datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc)
            result[dt.strftime("%Y-%m-%d")] = float(bar[4])
        cursor = data[-1][0] + 86_400_000
        if len(data) < 1000:
            break
        time.sleep(0.2)
    return result


def fetch_yahoo(symbol: str, start: str, end: str) -> dict[str, float]:
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp()) + 86400
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start_ts}&period2={end_ts}&interval=1d"
    )
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if r.status_code != 200:
            return {}
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
    except Exception:
        return {}


def fetch_fred_monthly(series_id: str, start: str, end: str) -> dict[str, float]:
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


def ffill(monthly: dict, daily_dates: list) -> dict[str, float]:
    monthly_sorted = sorted(monthly.items())
    result = {}
    last = monthly_sorted[0][1] if monthly_sorted else 0
    mi = 0
    for d in daily_dates:
        while mi < len(monthly_sorted) and monthly_sorted[mi][0] <= d:
            last = monthly_sorted[mi][1]
            mi += 1
        result[d] = last
    return result


# ── LP value model ──────────────────────────────────────────────────────
def lp_daily_return(usdc_prev: float, usdc_cur: float) -> float:
    """Daily return of a USDC/USDT v2 LP (fees + value change from USDC price)."""
    if usdc_prev <= 0:
        return 0
    # LP value ∝ 2 * sqrt(p_usdc * p_usdt). USDT ≈ 1, so LP value ∝ 2*sqrt(p_usdc)
    # Return = sqrt(p_cur/p_prev) - 1 + fees
    r = usdc_cur / usdc_prev
    lp_return = math.sqrt(r) - 1 if r > 0 else -1
    return lp_return + FEE_DAILY


# ── Stats ───────────────────────────────────────────────────────────────
def max_drawdown(cum: list[float]) -> float:
    peak = cum[0]
    mdd = 0
    for v in cum:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd
    return mdd


def cum_series(rets: list[float]) -> list[float]:
    c = [1.0]
    for r in rets:
        c.append(c[-1] * (1 + r))
    return c


def worst_window(rets: list[float], w: int) -> float:
    worst = float("inf")
    for i in range(len(rets) - w + 1):
        total = 1
        for j in range(w):
            total *= (1 + rets[i + j])
        if total - 1 < worst:
            worst = total - 1
    return worst


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


# ── Main ────────────────────────────────────────────────────────────────
def main():
    start_ms = int(datetime.strptime(START, "%Y-%m-%d").timestamp() * 1000)
    end_ms = int(datetime.strptime(END, "%Y-%m-%d").timestamp() * 1000)

    # ── Edge 1: Funding carry ──
    print("Downloading BTC funding rates (Binance, 2021-2024)...")
    funding = fetch_binance_funding("BTCUSDT", start_ms, end_ms)
    print(f"  {len(funding)} funding events")

    # Aggregate to daily carry return (sum of 3 payments per day)
    daily_funding = defaultdict(float)
    for f in funding:
        dt = datetime.fromtimestamp(f["ts"] / 1000, tz=timezone.utc)
        daily_funding[dt.strftime("%Y-%m-%d")] += f["rate"]

    # ── Edge 2: Stable-LP ──
    print("Downloading USDC price (Binance USDCUSDT, 2021-2024)...")
    usdc = fetch_binance_klines("USDCUSDT", START, END)
    print(f"  {len(usdc)} days")

    # ── Edge 3: FX carry ──
    print("Downloading FX data (Yahoo + FRED)...")
    fx_tickers = {"AUDUSD=X": None, "USDJPY=X": None, "NZDUSD=X": None, "USDMXN=X": None}
    for t in fx_tickers:
        fx_tickers[t] = fetch_yahoo(t, START, END)
        print(f"  {t}: {len(fx_tickers[t])} days")

    rate_ids = {
        "AU": "IR3TIB01AUM156N", "JP": "IR3TIB01JPM156N",
        "US": "IR3TIB01USM156N", "MX": "IR3TIB01MXM156N",
        "NZ": "IR3TIB01NZM156N",
    }
    rates_raw = {}
    for k, sid in rate_ids.items():
        rates_raw[k] = fetch_fred_monthly(sid, START, END)
        print(f"  {k} rate: {len(rates_raw[k])} obs")

    # ── Align all on common dates ──
    fx_dates = sorted(set.intersection(*[set(v.keys()) for v in fx_tickers.values()]))
    all_dates = sorted(
        set(daily_funding.keys()) & set(usdc.keys()) & set(fx_dates)
    )
    print(f"\nAligned: {len(all_dates)} common days ({all_dates[0]} to {all_dates[-1]})")

    # Forward-fill rates
    rates = {k: ffill(v, all_dates) for k, v in rates_raw.items()}

    # ── Build daily return series ──
    ret_dates = all_dates[1:]
    n = len(ret_dates)

    # 1. Funding carry: daily funding payment (positive = carry earned as short-perp)
    funding_ret = [daily_funding.get(d, 0) for d in ret_dates]

    # 2. Stable-LP: LP value change + fees
    lp_ret = [
        lp_daily_return(usdc[all_dates[i]], usdc[all_dates[i + 1]])
        for i in range(n)
    ]

    # 3. FX carry basket (equal-weight AUD/JPY, MXN/USD, NZD/JPY)
    fx_ret = []
    for i in range(n):
        d0, d1 = all_dates[i], all_dates[i + 1]
        # AUD/JPY
        audjpy0 = fx_tickers["AUDUSD=X"][d0] * fx_tickers["USDJPY=X"][d0]
        audjpy1 = fx_tickers["AUDUSD=X"][d1] * fx_tickers["USDJPY=X"][d1]
        auj_spot = (audjpy1 - audjpy0) / audjpy0 if audjpy0 else 0
        auj_carry = (rates["AU"].get(d1, 0) - rates["JP"].get(d1, 0)) / 100 / 252

        # MXN/USD (long MXN = short USDMXN)
        mxn0 = 1 / fx_tickers["USDMXN=X"][d0] if fx_tickers["USDMXN=X"][d0] else 0
        mxn1 = 1 / fx_tickers["USDMXN=X"][d1] if fx_tickers["USDMXN=X"][d1] else 0
        mxn_spot = (mxn1 - mxn0) / mxn0 if mxn0 else 0
        mxn_carry = (rates["MX"].get(d1, 0) - rates["US"].get(d1, 0)) / 100 / 252

        # NZD/JPY
        nzdjpy0 = fx_tickers["NZDUSD=X"][d0] * fx_tickers["USDJPY=X"][d0]
        nzdjpy1 = fx_tickers["NZDUSD=X"][d1] * fx_tickers["USDJPY=X"][d1]
        nzj_spot = (nzdjpy1 - nzdjpy0) / nzdjpy0 if nzdjpy0 else 0
        nzj_carry = (rates["NZ"].get(d1, 0) - rates["JP"].get(d1, 0)) / 100 / 252

        basket = ((auj_spot + auj_carry) + (mxn_spot + mxn_carry) + (nzj_spot + nzj_carry)) / 3
        fx_ret.append(basket)

    # Equal-weight basket
    basket_ret = [(funding_ret[i] + lp_ret[i] + fx_ret[i]) / 3 for i in range(n)]

    # Write data
    with open(DATA_FILE, "w") as f:
        for i, d in enumerate(ret_dates):
            f.write(json.dumps({
                "date": d, "funding": funding_ret[i],
                "lp": lp_ret[i], "fx": fx_ret[i], "basket": basket_ret[i],
            }) + "\n")

    # ══ PER-EDGE TAIL STATISTICS ══
    print(f"\n{'=' * 74}")
    print(f"PER-EDGE TAIL STATISTICS (2021-2024, {n} trading days)")
    print(f"{'=' * 74}\n")

    edges = [
        ("Funding carry", funding_ret),
        ("Stable-LP", lp_ret),
        ("FX carry", fx_ret),
        ("EQ-WT BASKET", basket_ret),
    ]

    print(f"  {'Edge':>16} {'Total':>8} {'Ann':>8} {'MDD':>7} {'Worst day':>11} {'Worst wk':>10} {'Worst mo':>10}")
    print(f"  {'-' * 78}")
    for name, rets in edges:
        total = cum_series(rets)[-1] - 1
        ann = total / (n / 252)
        mdd = max_drawdown(cum_series(rets))
        wd = min(rets)
        ww = worst_window(rets, 5) if n > 5 else 0
        wm = worst_window(rets, 21) if n > 21 else 0
        print(f"  {name:>16} {total:>+7.1%} {ann:>+7.1%} {mdd:>6.1%} {wd:>+10.2%} {ww:>+9.2%} {wm:>+9.2%}")

    # ══ THE 3×3 TAIL CO-MOVEMENT ══
    print(f"\n{'=' * 74}")
    print("TAIL CO-MOVEMENT: when one edge is in its worst decile, what are the others doing?")
    print(f"{'=' * 74}\n")

    edge_series = {"Funding": funding_ret, "LP": lp_ret, "FX": fx_ret}
    decile_n = n // 10

    for trigger_name, trigger_rets in edge_series.items():
        sorted_idx = sorted(range(n), key=lambda i: trigger_rets[i])
        worst_decile = set(sorted_idx[:decile_n])

        print(f"  When {trigger_name} is in its WORST 10% ({decile_n} days):")
        for other_name, other_rets in edge_series.items():
            stress_mean = statistics.mean(other_rets[i] for i in worst_decile)
            normal_mean = statistics.mean(other_rets[i] for i in range(n) if i not in worst_decile)
            print(f"    {other_name:>10}: stress {stress_mean:+.3%}  normal {normal_mean:+.3%}  ratio {stress_mean/normal_mean:.1f}x" if normal_mean != 0 else f"    {other_name:>10}: stress {stress_mean:+.3%}  normal {normal_mean:+.3%}")
        print()

    # ══ TAIL vs NORMAL CORRELATION ══
    print(f"{'=' * 74}")
    print("CORRELATION: normal periods vs stress decile")
    print(f"{'=' * 74}\n")

    # Overall
    print(f"  Overall (all {n} days):")
    for a_name, a_rets in edge_series.items():
        for b_name, b_rets in edge_series.items():
            if a_name >= b_name:
                continue
            print(f"    {a_name} × {b_name}: ρ = {pearson(a_rets, b_rets):+.3f}")

    # Stress decile (joint worst 10% of basket)
    basket_sorted = sorted(range(n), key=lambda i: basket_ret[i])
    stress_idx = set(basket_sorted[:decile_n])
    normal_idx = [i for i in range(n) if i not in stress_idx]

    print(f"\n  Stress days (basket worst 10%, n={decile_n}):")
    for a_name, a_rets in edge_series.items():
        for b_name, b_rets in edge_series.items():
            if a_name >= b_name:
                continue
            sx = [a_rets[i] for i in stress_idx]
            sy = [b_rets[i] for i in stress_idx]
            print(f"    {a_name} × {b_name}: ρ = {pearson(sx, sy):+.3f}")

    print(f"\n  Normal days (n={len(normal_idx)}):")
    for a_name, a_rets in edge_series.items():
        for b_name, b_rets in edge_series.items():
            if a_name >= b_name:
                continue
            sx = [a_rets[i] for i in normal_idx]
            sy = [b_rets[i] for i in normal_idx]
            print(f"    {a_name} × {b_name}: ρ = {pearson(sx, sy):+.3f}")

    # ══ NAMED CRISIS EVENTS ══
    print(f"\n{'=' * 74}")
    print("NAMED CRISIS EVENTS: all 3 edges during specific windows")
    print(f"{'=' * 74}\n")

    events = [
        ("UST/LUNA collapse", "2022-05-06", "2022-05-13"),
        ("FTX collapse", "2022-11-07", "2022-11-14"),
        ("USDC/SVB depeg", "2023-03-10", "2023-03-17"),
        ("2022 rate-hike peak", "2022-09-15", "2022-09-30"),
    ]

    for event_name, ev_start, ev_end in events:
        ev_idx = [i for i, d in enumerate(ret_dates) if ev_start <= d <= ev_end]
        if not ev_idx:
            print(f"  {event_name}: no data in window")
            continue

        print(f"  {event_name} ({ev_start} to {ev_end}, {len(ev_idx)} days):")
        for name, rets in [("Funding", funding_ret), ("LP", lp_ret), ("FX", fx_ret), ("BASKET", basket_ret)]:
            total = 1
            for i in ev_idx:
                total *= (1 + rets[i])
            print(f"    {name:>10}: {total - 1:+.2%}")
        print()

    # ══ MEASURED JOINT DRAWDOWN vs ESTIMATE ══
    print(f"{'=' * 74}")
    print("MEASURED BASKET MAX DRAWDOWN vs DEPLOYMENT PLAN ESTIMATE")
    print(f"{'=' * 74}\n")

    basket_cum = cum_series(basket_ret)
    basket_mdd = max_drawdown(basket_cum)
    basket_worst_mo = worst_window(basket_ret, 21) if n > 21 else 0

    print(f"  Measured basket MDD (2021-2024): {basket_mdd:.1%}")
    print(f"  Measured basket worst month:     {basket_worst_mo:+.1%}")
    print(f"  Plan estimate:                   -15% to -25%")
    print(f"  Comparison:                      {'WORSE than estimate' if basket_mdd > 0.25 else 'WITHIN estimate' if basket_mdd > 0.10 else 'BETTER than estimate'}")

    # Per-edge MDD for context
    print(f"\n  Per-edge MDD for context:")
    for name, rets in edges[:3]:
        mdd = max_drawdown(cum_series(rets))
        print(f"    {name:>16}: {mdd:.1%}")

    # ══ VERDICT ══
    print(f"\n{'=' * 74}")
    print("VERDICT")
    print(f"{'=' * 74}\n")

    print(f"  MEASURED joint-tail MDD:        {basket_mdd:.1%}")
    print(f"  MEASURED worst month:           {basket_worst_mo:+.1%}")
    print(f"  PLAN ESTIMATE:                  -15% to -25%")
    print()
    print(f"  CAVEAT: 2021-2024 contains UST/FTX/SVB but NOT a 2008-style global")
    print(f"  meltdown. The measured joint tail is a FLOOR, not a ceiling.")


if __name__ == "__main__":
    main()
