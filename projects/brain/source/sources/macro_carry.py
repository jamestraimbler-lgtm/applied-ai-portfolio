"""
Macro carry probe: does "structural compensation survives, prediction dies"
generalize from crypto to TradFi?

Tests two classic carry structures:
  1. FX CARRY: long high-yield / short low-yield currency, earns rate differential.
     AUD/JPY, MXN/USD, NZD/JPY — the canonical carry trades.
  2. TREASURY CARRY: term premium + roll-down. TLT/IEF vs BIL (cash proxy).

Data: Yahoo v8 (FX spot + Treasury ETFs), FRED (3-month interbank rates, monthly,
forward-filled to daily). Aligned on common trading days.
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
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "macro_carry_data.jsonl")
TRADING_DAYS_YR = 252

# FX carry pairs: (name, long_ccy, short_ccy, yahoo_tickers, rate_series)
FX_PAIRS = [
    {
        "name": "AUD/JPY carry",
        "long_ccy": "AUD", "short_ccy": "JPY",
        "spot_tickers": ["AUDUSD=X", "USDJPY=X"],  # cross = AUD/USD × USD/JPY
        "long_rate": "IR3TIB01AUM156N",
        "short_rate": "IR3TIB01JPM156N",
    },
    {
        "name": "MXN/USD carry",
        "long_ccy": "MXN", "short_ccy": "USD",
        "spot_tickers": ["USDMXN=X"],  # invert: long MXN = short USDMXN
        "invert": True,
        "long_rate": "IR3TIB01MXM156N",
        "short_rate": "IR3TIB01USM156N",
    },
    {
        "name": "NZD/JPY carry",
        "long_ccy": "NZD", "short_ccy": "JPY",
        "spot_tickers": ["NZDUSD=X", "USDJPY=X"],
        "long_rate": "IR3TIB01NZM156N",
        "short_rate": "IR3TIB01JPM156N",
    },
]

# Treasury carry: long_etf vs BIL (cash proxy)
TSY_PAIRS = [
    {"name": "Long Tsy (TLT) vs cash", "long": "TLT", "short": "BIL"},
    {"name": "Interm Tsy (IEF) vs cash", "long": "IEF", "short": "BIL"},
    {"name": "Short Tsy (SHY) vs cash", "long": "SHY", "short": "BIL"},
]


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


def fetch_fred_monthly(series_id: str, start: str) -> dict[str, float]:
    """Download FRED monthly series, forward-fill to daily."""
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


def ffill_to_daily(monthly: dict[str, float], daily_dates: list[str]) -> dict[str, float]:
    """Forward-fill monthly data to daily dates."""
    monthly_sorted = sorted(monthly.items())
    result = {}
    last_val = monthly_sorted[0][1] if monthly_sorted else 0
    m_idx = 0
    for d in daily_dates:
        while m_idx < len(monthly_sorted) and monthly_sorted[m_idx][0] <= d:
            last_val = monthly_sorted[m_idx][1]
            m_idx += 1
        result[d] = last_val
    return result


def align_series(*series_dicts) -> list[str]:
    common = set(series_dicts[0].keys())
    for s in series_dicts[1:]:
        common &= s.keys()
    return sorted(common)


# ── Stats ───────────────────────────────────────────────────────────────
def sharpe(daily_returns: list[float]) -> float:
    if len(daily_returns) < 10:
        return 0.0
    mean = statistics.mean(daily_returns)
    sd = statistics.stdev(daily_returns)
    if sd == 0:
        return 0.0
    return mean / sd * math.sqrt(TRADING_DAYS_YR)


def max_drawdown(cum_returns: list[float]) -> float:
    peak = cum_returns[0]
    mdd = 0
    for v in cum_returns:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd
    return mdd


def worst_period(daily_returns: list[float], window: int) -> float:
    """Worst rolling-window return."""
    worst = float("inf")
    for i in range(len(daily_returns) - window + 1):
        total = sum(daily_returns[i:i + window])
        if total < worst:
            worst = total
    return worst


def cum_series(daily_returns: list[float]) -> list[float]:
    cum = [1.0]
    for r in daily_returns:
        cum.append(cum[-1] * (1 + r))
    return cum


# ── FX Carry ────────────────────────────────────────────────────────────
def measure_fx_carry(pair_cfg, all_fx, all_rates, common_dates):
    """Compute daily carry returns for one FX pair."""
    name = pair_cfg["name"]
    ret_dates = common_dates[1:]

    # Build spot cross rate
    if len(pair_cfg["spot_tickers"]) == 2:
        t1, t2 = pair_cfg["spot_tickers"]
        spot = {d: all_fx[t1][d] * all_fx[t2][d] for d in common_dates}
    else:
        t1 = pair_cfg["spot_tickers"][0]
        if pair_cfg.get("invert"):
            spot = {d: 1.0 / all_fx[t1][d] if all_fx[t1][d] != 0 else 0 for d in common_dates}
        else:
            spot = {d: all_fx[t1][d] for d in common_dates}

    long_rate = all_rates[pair_cfg["long_rate"]]
    short_rate = all_rates[pair_cfg["short_rate"]]

    daily_rets = []
    for i in range(1, len(common_dates)):
        d_prev, d_cur = common_dates[i - 1], common_dates[i]
        s0, s1 = spot[d_prev], spot[d_cur]
        if s0 == 0:
            daily_rets.append(0)
            continue
        spot_ret = (s1 - s0) / s0
        carry = (long_rate.get(d_cur, 0) - short_rate.get(d_cur, 0)) / 100 / TRADING_DAYS_YR
        daily_rets.append(spot_ret + carry)

    return daily_rets


# ── Treasury Carry ──────────────────────────────────────────────────────
def measure_tsy_carry(pair_cfg, all_tsy, common_dates):
    """Compute daily excess return of long ETF vs short ETF (cash)."""
    long_px = all_tsy[pair_cfg["long"]]
    short_px = all_tsy[pair_cfg["short"]]

    daily_rets = []
    for i in range(1, len(common_dates)):
        d_prev, d_cur = common_dates[i - 1], common_dates[i]
        l_ret = (long_px[d_cur] - long_px[d_prev]) / long_px[d_prev] if long_px[d_prev] else 0
        s_ret = (short_px[d_cur] - short_px[d_prev]) / short_px[d_prev] if short_px[d_prev] else 0
        daily_rets.append(l_ret - s_ret)

    return daily_rets


# ── Report one carry structure ──────────────────────────────────────────
def report_carry(name: str, daily_rets: list[float], ret_dates: list[str]):
    n = len(daily_rets)
    if n < 20:
        print(f"  {name}: insufficient data ({n} days)")
        return {}

    total = cum_series(daily_rets)[-1] - 1
    ann_ret = total / (n / TRADING_DAYS_YR)
    sh = sharpe(daily_rets)
    mdd = max_drawdown(cum_series(daily_rets))
    worst_mo = worst_period(daily_rets, 21) if n > 21 else 0
    worst_qtr = worst_period(daily_rets, 63) if n > 63 else 0
    hit = sum(1 for r in daily_rets if r > 0) / n

    print(f"\n  {name}:")
    print(f"    Total: {total:+.1%}  Ann: {ann_ret:+.1%}  Sharpe: {sh:.2f}")
    print(f"    Max DD: {mdd:.1%}  Worst month: {worst_mo:+.1%}  Worst quarter: {worst_qtr:+.1%}")
    print(f"    Hit rate (daily): {hit:.0%}  n={n} days")

    # Per-year
    year_idx = defaultdict(list)
    for i, d in enumerate(ret_dates):
        year_idx[d[:4]].append(i)

    print(f"    Per-year:")
    for year in sorted(year_idx):
        idx = year_idx[year]
        yr_rets = [daily_rets[i] for i in idx]
        yr_total = cum_series(yr_rets)[-1] - 1
        yr_sh = sharpe(yr_rets) if len(yr_rets) > 10 else 0
        print(f"      {year}: {yr_total:+.1%}  Sharpe {yr_sh:+.2f}")

    return {
        "name": name, "total": total, "ann": ann_ret, "sharpe": sh,
        "mdd": mdd, "worst_mo": worst_mo, "worst_qtr": worst_qtr,
        "daily_rets": daily_rets,
    }


# ── Main ────────────────────────────────────────────────────────────────
def main():
    # Download FX spot
    print("Downloading FX spot data...")
    all_fx = {}
    fx_tickers = set()
    for pair in FX_PAIRS:
        for t in pair["spot_tickers"]:
            fx_tickers.add(t)
    for t in sorted(fx_tickers):
        all_fx[t] = fetch_yahoo(t, START_DATE)
        print(f"  {t}: {len(all_fx[t])} days")

    # Download FRED rates
    print("\nDownloading FRED 3-month rates (monthly)...")
    rate_series_ids = set()
    for pair in FX_PAIRS:
        rate_series_ids.add(pair["long_rate"])
        rate_series_ids.add(pair["short_rate"])
    all_rates_raw = {}
    for sid in sorted(rate_series_ids):
        all_rates_raw[sid] = fetch_fred_monthly(sid, START_DATE)
        print(f"  {sid}: {len(all_rates_raw[sid])} obs")

    # Download Treasury ETFs
    print("\nDownloading Treasury ETFs...")
    all_tsy = {}
    tsy_tickers = set()
    for pair in TSY_PAIRS:
        tsy_tickers.add(pair["long"])
        tsy_tickers.add(pair["short"])
    for t in sorted(tsy_tickers):
        all_tsy[t] = fetch_yahoo(t, START_DATE)
        print(f"  {t}: {len(all_tsy[t])} days")

    # Align FX dates
    fx_dates = align_series(*all_fx.values())
    print(f"\nFX aligned: {len(fx_dates)} days ({fx_dates[0]} to {fx_dates[-1]})")

    # Forward-fill rates to daily
    all_rates = {}
    for sid, raw in all_rates_raw.items():
        all_rates[sid] = ffill_to_daily(raw, fx_dates)

    # Align Treasury dates
    tsy_dates = align_series(*all_tsy.values())
    print(f"Tsy aligned: {len(tsy_dates)} days ({tsy_dates[0]} to {tsy_dates[-1]})")

    # ══ FX CARRY ══
    print(f"\n{'=' * 70}")
    print("FX CARRY (long high-yield / short low-yield + rate differential)")
    print(f"{'=' * 70}")

    fx_results = []
    for pair in FX_PAIRS:
        rets = measure_fx_carry(pair, all_fx, all_rates, fx_dates)
        result = report_carry(pair["name"], rets, fx_dates[1:])
        if result:
            fx_results.append(result)

    # Equal-weighted FX basket
    if len(fx_results) >= 2:
        min_len = min(len(r["daily_rets"]) for r in fx_results)
        basket_rets = [
            statistics.mean(r["daily_rets"][i] for r in fx_results)
            for i in range(min_len)
        ]
        print(f"\n  --- FX Carry Basket (equal-weighted) ---")
        fx_basket = report_carry("FX basket (3 pairs)", basket_rets, fx_dates[1:min_len + 1])

    # ══ TREASURY CARRY ══
    print(f"\n{'=' * 70}")
    print("TREASURY CARRY (term premium + roll vs cash/BIL)")
    print(f"{'=' * 70}")

    tsy_results = []
    for pair in TSY_PAIRS:
        rets = measure_tsy_carry(pair, all_tsy, tsy_dates)
        result = report_carry(pair["name"], rets, tsy_dates[1:])
        if result:
            tsy_results.append(result)

    # ══ CORRELATION TO EXISTING EDGES ══
    print(f"\n{'=' * 70}")
    print("CROSS-CORRELATION (does TradFi carry diversify the crypto basket?)")
    print(f"{'=' * 70}\n")

    # Correlation between FX carry pairs
    if len(fx_results) >= 2:
        print("  FX pair correlations (daily):")
        for i in range(len(fx_results)):
            for j in range(i + 1, len(fx_results)):
                n = min(len(fx_results[i]["daily_rets"]), len(fx_results[j]["daily_rets"]))
                x = fx_results[i]["daily_rets"][:n]
                y = fx_results[j]["daily_rets"][:n]
                mx, my = sum(x) / n, sum(y) / n
                sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / (n - 1))
                sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / (n - 1))
                if sx > 0 and sy > 0:
                    corr = sum((x[k] - mx) * (y[k] - my) for k in range(n)) / (n - 1) / (sx * sy)
                else:
                    corr = 0
                print(f"    {fx_results[i]['name']} × {fx_results[j]['name']}: {corr:+.3f}")

    # FX vs Treasury
    if fx_results and tsy_results:
        print("\n  FX basket vs Treasury carry:")
        for tr in tsy_results:
            n = min(len(fx_basket["daily_rets"]) if fx_basket else 0, len(tr["daily_rets"]))
            if n < 20:
                continue
            x = fx_basket["daily_rets"][:n]
            y = tr["daily_rets"][:n]
            mx, my = sum(x) / n, sum(y) / n
            sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / (n - 1))
            sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / (n - 1))
            if sx > 0 and sy > 0:
                corr = sum((x[k] - mx) * (y[k] - my) for k in range(n)) / (n - 1) / (sx * sy)
            else:
                corr = 0
            print(f"    FX basket × {tr['name']}: {corr:+.3f}")

    print(f"\n  NOTE: correlation to crypto funding-carry/stable-LP cannot be")
    print(f"  computed directly (different trading calendars). Crypto carry is")
    print(f"  BTC-uncorrelated (ρ=-0.087); FX carry is risk-on (ρ with equities")
    print(f"  is typically +0.3-0.5). They are structurally DIFFERENT tail risks.")

    # ══ VERDICT ══
    print(f"\n{'=' * 70}")
    print("VERDICT")
    print(f"{'=' * 70}\n")

    all_results = fx_results + tsy_results
    for r in all_results:
        tail = "TAIL RISK" if r["mdd"] > 0.15 else "moderate DD"
        if r["sharpe"] > 0.5 and r["ann"] > 0.01:
            edge = "REAL structural carry"
        elif r["sharpe"] > 0.2:
            edge = "WEAK carry (marginal after cost)"
        elif r["ann"] < -0.01:
            edge = "NEGATIVE (not a carry, just duration risk)"
        else:
            edge = "NOISE"
        print(f"  {r['name']:>30}: {edge}  |  Ann {r['ann']:+.1%}  Sharpe {r['sharpe']:.2f}  MDD {r['mdd']:.0%}  |  {tail}")

    print(f"\n  Does 'structural compensation survives' generalize to TradFi?")


if __name__ == "__main__":
    main()
