"""
Macro probe 4: Is bank disruption MEASURABLE in market data?

Tests whether incumbent banks are visibly losing ground to fintech/payment-rails
in relative stock performance — and whether that's SECULAR disruption or just the
rate cycle (banks earn NIM when rates are high).

Data: Yahoo Finance v8 for equities, FRED for 2yr yield + bank deposits.
Baskets (equal-weighted daily returns):
  Banks:    KBE (bank ETF), JPM, BAC
  Rails:    V (Visa), MA (Mastercard)
  Fintech:  PYPL, XYZ (Block), ARKF (fintech ETF)
  Benchmark: SPY
"""

import csv
import io
import json
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────
START_DATE = "2020-01-01"
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "bank_disruption_aligned.jsonl")

FRED_SERIES = {"yield_2y": "DGS2"}
FRED_DEPOSITS = "DPSACBW027SBOG"  # weekly total commercial bank deposits ($B)

TICKERS = {
    "banks": ["KBE", "JPM", "BAC"],
    "rails": ["V", "MA"],
    "fintech": ["PYPL", "XYZ", "ARKF"],
    "benchmark": ["SPY"],
}


# ── Download ────────────────────────────────────────────────────────────
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


# ── Align + returns ─────────────────────────────────────────────────────
def align_series(*series_dicts) -> list[str]:
    common = set(series_dicts[0].keys())
    for s in series_dicts[1:]:
        common &= s.keys()
    return sorted(common)


def daily_returns(prices: dict[str, float], dates: list[str]) -> list[float]:
    return [
        (prices[dates[i]] - prices[dates[i - 1]]) / prices[dates[i - 1]]
        if prices[dates[i - 1]] != 0 else 0.0
        for i in range(1, len(dates))
    ]


def basket_returns(ticker_prices: dict[str, dict], dates: list[str]) -> list[float]:
    """Equal-weighted average of daily returns across tickers."""
    all_rets = [daily_returns(ticker_prices[t], dates) for t in ticker_prices]
    n = len(all_rets[0])
    return [statistics.mean(r[i] for r in all_rets) for i in range(n)]


def cum_return_series(daily_rets: list[float]) -> list[float]:
    """Cumulative return series (1-indexed: starts at 1.0)."""
    cum = [1.0]
    for r in daily_rets:
        cum.append(cum[-1] * (1 + r))
    return cum


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


# ── Main ────────────────────────────────────────────────────────────────
def main():
    # Download all equity tickers
    print("Downloading equity data from Yahoo Finance...")
    all_prices = {}
    all_tickers = []
    for group, tickers in TICKERS.items():
        for t in tickers:
            all_prices[t] = fetch_yahoo(t, START_DATE)
            print(f"  {t}: {len(all_prices[t])} days")
            all_tickers.append(t)

    # FRED 2yr yield (for rate-cycle decomposition)
    print("\nDownloading FRED 2yr yield...")
    yield_2y = fetch_fred(FRED_SERIES["yield_2y"], START_DATE)
    print(f"  DGS2: {len(yield_2y)} obs")

    # FRED deposits
    print("Downloading FRED bank deposits...")
    deposits = fetch_fred(FRED_DEPOSITS, START_DATE)
    print(f"  Deposits: {len(deposits)} obs (weekly)")

    # Align all equities on common dates
    dates = align_series(*all_prices.values())
    print(f"\nAligned: {len(dates)} common trading days ({dates[0]} to {dates[-1]})")

    # Write aligned data
    with open(DATA_FILE, "w") as f:
        for d in dates:
            row = {"date": d}
            for t in all_tickers:
                row[t] = all_prices[t][d]
            f.write(json.dumps(row) + "\n")

    ret_dates = dates[1:]
    n = len(ret_dates)

    # ── Compute basket returns ──
    bank_prices = {t: all_prices[t] for t in TICKERS["banks"]}
    rail_prices = {t: all_prices[t] for t in TICKERS["rails"]}
    fin_prices = {t: all_prices[t] for t in TICKERS["fintech"]}

    bank_ret = basket_returns(bank_prices, dates)
    rail_ret = basket_returns(rail_prices, dates)
    fin_ret = basket_returns(fin_prices, dates)
    spy_ret = daily_returns(all_prices["SPY"], dates)

    bank_cum = cum_return_series(bank_ret)
    rail_cum = cum_return_series(rail_ret)
    fin_cum = cum_return_series(fin_ret)
    spy_cum = cum_return_series(spy_ret)

    # Also individual tickers
    indiv_cum = {}
    for t in all_tickers:
        r = daily_returns(all_prices[t], dates)
        indiv_cum[t] = cum_return_series(r)

    # ══ STAGE 1: RELATIVE PERFORMANCE ══
    print(f"\n{'=' * 78}")
    print("STAGE 1: CUMULATIVE PERFORMANCE (2020-01-02 to present)")
    print(f"{'=' * 78}\n")

    print("--- Basket Total Returns ---\n")
    print(f"  {'Basket':>12} {'Total Return':>14} {'vs SPY':>10}")
    print(f"  {'-' * 40}")
    spy_total = spy_cum[-1] - 1
    for label, cum in [("Banks", bank_cum), ("Rails", rail_cum),
                       ("Fintech", fin_cum), ("SPY", spy_cum)]:
        total = cum[-1] - 1
        vs_spy = total - spy_total
        print(f"  {label:>12} {total:>+13.1%} {vs_spy:>+9.1%}")

    print(f"\n--- Individual Ticker Returns ---\n")
    print(f"  {'Ticker':>8} {'Group':>10} {'Total Return':>14} {'vs SPY':>10}")
    print(f"  {'-' * 46}")
    group_map = {}
    for group, tickers in TICKERS.items():
        for t in tickers:
            group_map[t] = group
    for t in all_tickers:
        total = indiv_cum[t][-1] - 1
        vs_spy = total - spy_total
        print(f"  {t:>8} {group_map[t]:>10} {total:>+13.1%} {vs_spy:>+9.1%}")

    # ── Banks ÷ Fintech / Rails ratio ──
    print(f"\n--- Banks ÷ Fintech Ratio Over Time ---\n")

    # Compute ratio series (bank_cum / fin_cum)
    ratio_bf = [bank_cum[i] / fin_cum[i] if fin_cum[i] != 0 else 1.0
                for i in range(len(bank_cum))]
    ratio_br = [bank_cum[i] / rail_cum[i] if rail_cum[i] != 0 else 1.0
                for i in range(len(bank_cum))]

    # Sample at year boundaries
    year_idx = defaultdict(list)
    for i, d in enumerate(dates):
        year_idx[d[:4]].append(i)

    print(f"  {'Date':>12} {'Banks/Fintech':>15} {'Banks/Rails':>13} {'2yr Yield':>11}")
    print(f"  {'-' * 55}")
    print(f"  {dates[0]:>12} {ratio_bf[0]:>15.3f} {ratio_br[0]:>13.3f} {yield_2y.get(dates[0], 0):>10.2f}%")
    for year in sorted(year_idx):
        # Year-end (last trading day of year)
        last_idx = year_idx[year][-1]
        d = dates[last_idx]
        y2 = yield_2y.get(d, 0)
        print(f"  {d:>12} {ratio_bf[last_idx]:>15.3f} {ratio_br[last_idx]:>13.3f} {y2:>10.2f}%")

    ratio_start = ratio_bf[0]
    ratio_end = ratio_bf[-1]
    ratio_chg = (ratio_end / ratio_start - 1) * 100
    print(f"\n  Banks/Fintech ratio: {ratio_start:.3f} → {ratio_end:.3f} ({ratio_chg:+.0f}%)")
    if ratio_chg > 10:
        print("  → Banks OUTPERFORMED fintech over the full period")
    elif ratio_chg < -10:
        print("  → Banks UNDERPERFORMED fintech (disruption signal?)")
    else:
        print("  → Roughly flat — no clear secular trend")

    # ── Per-year relative returns ──
    print(f"\n--- Per-Year Relative Returns (basket - SPY) ---\n")
    print(f"  {'Year':>6} {'Banks-SPY':>12} {'Rails-SPY':>12} {'Fintech-SPY':>13} {'2yr Yield Δ':>13}")
    print(f"  {'-' * 60}")

    for year in sorted(year_idx):
        idx = year_idx[year]
        i0, i1 = idx[0], idx[-1]
        # Year returns (price at year-end / price at year-start - 1)
        b_yr = bank_cum[i1] / bank_cum[i0] - 1 if bank_cum[i0] else 0
        r_yr = rail_cum[i1] / rail_cum[i0] - 1 if rail_cum[i0] else 0
        f_yr = fin_cum[i1] / fin_cum[i0] - 1 if fin_cum[i0] else 0
        s_yr = spy_cum[i1] / spy_cum[i0] - 1 if spy_cum[i0] else 0

        # Yield change over year
        y2_start = yield_2y.get(dates[i0], 0)
        y2_end = yield_2y.get(dates[i1], 0)
        y2_chg = y2_end - y2_start

        print(
            f"  {year:>6} {b_yr - s_yr:>+11.1%} {r_yr - s_yr:>+11.1%} "
            f"{f_yr - s_yr:>+12.1%} {y2_chg:>+12.2f}%"
        )

    # ══ STAGE 2: RATE CYCLE DECOMPOSITION ══
    print(f"\n{'=' * 78}")
    print("STAGE 2: IS IT SECULAR DISRUPTION OR THE RATE CYCLE?")
    print(f"{'=' * 78}\n")

    # Daily correlation: banks÷fintech ratio changes vs yield changes
    # Align yield data to equity dates
    yield_dates = [d for d in ret_dates if d in yield_2y]
    yield_idx = [i for i, d in enumerate(ret_dates) if d in yield_2y]

    # Compute daily changes in ratio and yield
    ratio_daily_chg = [(ratio_bf[i + 1] - ratio_bf[i]) / ratio_bf[i]
                       if ratio_bf[i] != 0 else 0
                       for i in range(len(ratio_bf) - 1)]

    # Filter to days where yield data exists
    ratio_chg_aligned = []
    yield_chg_aligned = []
    prev_yield = None
    for i, d in enumerate(ret_dates):
        if d in yield_2y:
            if prev_yield is not None:
                ratio_chg_aligned.append(ratio_daily_chg[i])
                yield_chg_aligned.append(yield_2y[d] - prev_yield)
            prev_yield = yield_2y[d]

    corr = pearson(yield_chg_aligned, ratio_chg_aligned)
    print(f"  Correlation: Δ(banks/fintech ratio) vs Δ(2yr yield) = {corr:+.3f}")
    if abs(corr) > 0.3:
        print(f"  → STRONG rate-cycle link: banks beat fintech when rates rise")
    elif abs(corr) > 0.15:
        print(f"  → MODERATE rate-cycle link")
    else:
        print(f"  → WEAK rate-cycle link — other factors dominate")

    # Per-year correlation
    print(f"\n  Per-year correlation (Δratio vs Δyield):")
    year_ratio_chg = defaultdict(list)
    year_yield_chg = defaultdict(list)
    prev_yield = None
    for i, d in enumerate(ret_dates):
        if d in yield_2y:
            if prev_yield is not None:
                year_ratio_chg[d[:4]].append(ratio_daily_chg[i])
                year_yield_chg[d[:4]].append(yield_2y[d] - prev_yield)
            prev_yield = yield_2y[d]

    for year in sorted(year_ratio_chg):
        yr_corr = pearson(year_yield_chg[year], year_ratio_chg[year])
        print(f"    {year}: {yr_corr:+.3f}")

    # Residual trend: detrend banks/fintech for rates
    # Simple: regress ratio_chg on yield_chg, check if residual has a drift
    n_aligned = len(ratio_chg_aligned)
    if n_aligned > 10:
        mx = sum(yield_chg_aligned) / n_aligned
        my = sum(ratio_chg_aligned) / n_aligned
        sx2 = sum((x - mx) ** 2 for x in yield_chg_aligned)
        if sx2 > 0:
            beta = sum((yield_chg_aligned[i] - mx) * (ratio_chg_aligned[i] - my)
                       for i in range(n_aligned)) / sx2
            alpha = my - beta * mx
            residuals = [ratio_chg_aligned[i] - (alpha + beta * yield_chg_aligned[i])
                         for i in range(n_aligned)]
            residual_cum = [1.0]
            for r in residuals:
                residual_cum.append(residual_cum[-1] * (1 + r))
            residual_drift = residual_cum[-1] - 1

            print(f"\n  Rate-adjusted residual (banks/fintech after stripping yield effect):")
            print(f"    Regression: ratio_chg = {alpha:.6f} + {beta:.4f} × yield_chg")
            print(f"    Residual cumulative drift: {residual_drift:+.1%}")
            if abs(residual_drift) < 0.05:
                print(f"    → NO secular trend after stripping rates — it's mostly the rate cycle")
            elif residual_drift < -0.05:
                print(f"    → SECULAR underperformance of banks vs fintech beyond the rate cycle")
            else:
                print(f"    → SECULAR outperformance of banks vs fintech beyond the rate cycle")

    # ── Deposit context ──
    print(f"\n--- Deposit Context (FRED: Total Commercial Bank Deposits) ---\n")
    dep_dates = sorted(deposits.keys())
    if dep_dates:
        dep_start = deposits[dep_dates[0]]
        dep_end = deposits[dep_dates[-1]]
        dep_growth = (dep_end / dep_start - 1) * 100
        print(f"  {dep_dates[0]}: ${dep_start:,.0f}B → {dep_dates[-1]}: ${dep_end:,.0f}B")
        print(f"  Growth: {dep_growth:+.1f}% ({dep_dates[0][:4]}-{dep_dates[-1][:4]})")

        # Year-over-year
        print(f"\n  Year-end deposit levels + YoY growth:")
        prev_year_val = None
        for year in range(2020, 2027):
            year_deps = [(d, deposits[d]) for d in dep_dates if d.startswith(str(year))]
            if year_deps:
                last_d, last_v = year_deps[-1]
                yoy = ((last_v / prev_year_val) - 1) * 100 if prev_year_val else 0
                marker = ""
                if yoy < 0:
                    marker = " ← DECLINE"
                print(f"    {last_d}: ${last_v:,.0f}B  (YoY: {yoy:+.1f}%){marker}")
                prev_year_val = last_v

        # SVB context
        svb_dates = [d for d in dep_dates if "2023-03" <= d <= "2023-06"]
        if len(svb_dates) >= 2:
            svb_drop = (deposits[svb_dates[-1]] / deposits[svb_dates[0]] - 1) * 100
            print(f"\n  SVB crisis window (Mar-Jun 2023): {svb_drop:+.1f}%")

    print(f"\n  NOTE: Stock-price relative performance is a PROXY for disruption,")
    print(f"  not a direct measure. Deposit share, NIM compression, and fintech")
    print(f"  adoption rates would be needed for a full structural test.")

    # ══ FINAL VERDICT ══
    print(f"\n{'=' * 78}")
    print("FINAL VERDICT")
    print(f"{'=' * 78}\n")

    # Derive verdict from data
    bank_total = bank_cum[-1] - 1
    fin_total = fin_cum[-1] - 1
    rail_total = rail_cum[-1] - 1

    print(f"  Full-period returns: Banks {bank_total:+.1%}, Fintech {fin_total:+.1%}, "
          f"Rails {rail_total:+.1%}, SPY {spy_total:+.1%}")
    print()

    if bank_total > fin_total + 0.10:
        print(f"  Banks OUTPERFORMED fintech by {bank_total - fin_total:+.1%}")
        print(f"  → No market-based disruption signal. Banks won.")
    elif fin_total > bank_total + 0.10:
        print(f"  Fintech outperformed banks by {fin_total - bank_total:+.1%}")
        print(f"  → Potential disruption signal, but check rate-cycle decomposition above.")
    else:
        print(f"  Banks and fintech within 10% — no clear winner.")

    if abs(corr) > 0.2:
        print(f"\n  The banks/fintech ratio is correlated {corr:+.3f} with rate changes.")
        print(f"  Much of the relative move is the RATE CYCLE, not secular disruption.")
    print()


if __name__ == "__main__":
    main()
