"""Deribit variance risk premium backtest.

TWO models side by side:
  (a) Var-swap proxy (CEILING): sell variance at DVOL, settle at RV.
      Clean but NOT retail-tradeable on Deribit.
  (b) Straddle-sell (REALISTIC): sell ATM straddle, delta-hedge daily,
      pay Deribit fees + hedging drag. What you can actually execute.

The GAP between them = the cost of what's reachable.

Tail-loss model: no capping, no stops, no optimization on backtest data.
Report worst rolling 12-month window, max drawdown, crash clustering.
"""

import json, math, os, statistics, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE = os.path.join(_DIR, "vol_premium_trades.jsonl")

# ── Deribit cost assumptions ────────────────────────────────────────
DERIBIT_TAKER_BPS = 3.0          # 0.03% of underlying per option trade
DERIBIT_TAKER = DERIBIT_TAKER_BPS / 10_000
HEDGE_FREQ_PER_MONTH = 30        # daily delta-hedge
HEDGE_COST_PER_TRADE = 0.0005    # 5 bps per perp hedge (Deribit perp taker)
# Monthly hedge drag: ~30 hedges × 5bps × avg_gamma_exposure
# Rough estimate: 1.5% APR drag (from literature + Deribit fee schedule)
HEDGE_DRAG_ANNUAL = 0.015        # 1.5% APR conservative estimate

SAPI = "https://api.binance.com/api/v3"


# ── Data fetchers ────────────────────────────────────────────────────

def _fetch_dvol_daily(currency, start_ms, end_ms):
    out = []
    cursor = start_ms
    while cursor < end_ms:
        chunk = min(cursor + 365 * 86400 * 1000, end_ms)
        r = requests.get("https://www.deribit.com/api/v2/public/"
                         "get_volatility_index_data", params={
            "currency": currency, "start_timestamp": cursor,
            "end_timestamp": chunk, "resolution": 86400,
        }, timeout=15)
        d = r.json().get("result", {}).get("data", [])
        if d:
            out.extend(d)
            cursor = d[-1][0] + 86400000
        else:
            cursor = chunk
    return out


def _fetch_daily_prices(pair, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        r = requests.get(f"{SAPI}/klines", params={
            "symbol": pair, "interval": "1d",
            "startTime": cur, "limit": 1000,
        }, timeout=15)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        cur = batch[-1][0] + 86400000
        if len(batch) < 1000:
            break
    return out


# ── Core computation ─────────────────────────────────────────────────

def backtest():
    now_ms = int(time.time() * 1000)
    start_ms = 1616544000000  # Mar 2021

    print("Fetching BTC DVOL daily...")
    dvol_raw = _fetch_dvol_daily("BTC", start_ms, now_ms)
    dvol_by_date = {}
    for x in dvol_raw:
        ds = datetime.fromtimestamp(x[0] / 1000, tz=timezone.utc
                                    ).strftime("%Y-%m-%d")
        dvol_by_date[ds] = x[4]  # close
    print(f"  {len(dvol_raw)} entries")

    print("Fetching BTC daily prices...")
    klines = _fetch_daily_prices("BTCUSDT", start_ms, now_ms)
    prices = []
    for k in klines:
        ds = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc
                                    ).strftime("%Y-%m-%d")
        prices.append((ds, float(k[4])))
    print(f"  {len(prices)} daily prices")

    # ── Group into calendar months ──
    months = {}
    for d, p in prices:
        m = d[:7]
        months.setdefault(m, []).append((d, p))

    # ── Also load funding carry + stable LP monthly returns for correlation ──
    fc_monthly = _load_funding_carry_monthly()
    lp_monthly = _load_lp_monthly()

    # ── Monthly simulation ──
    results = []
    all_trades = []

    for m in sorted(months):
        days = months[m]
        if len(days) < 20:
            continue

        iv = dvol_by_date.get(days[0][0])
        if not iv:
            continue

        # Realized vol from daily log returns
        log_rets = []
        for i in range(len(days) - 1):
            if days[i][1] > 0:
                log_rets.append(math.log(days[i + 1][1] / days[i][1]))
        if len(log_rets) < 15:
            continue

        rv = statistics.stdev(log_rets) * math.sqrt(365) * 100

        # ── (a) Var-swap P&L (ceiling) ──
        # P&L = (K² - RV²) / (2K) / 12
        vs_pnl = (iv ** 2 - rv ** 2) / (2 * iv) / 12

        # ── (b) Straddle-sell P&L (realistic) ──
        # A delta-hedged short straddle replicates a short variance exposure:
        # the hedging converts directional risk into variance payoff.
        # P&L ≈ var-swap P&L MINUS execution friction:
        #   - Option entry/exit fees (Deribit taker × 2 legs × 2 sides)
        #   - Delta-hedge transaction costs (~30 hedges/mo × perp taker)
        #   - Discrete hedging error (daily hedging misses intra-day gamma)
        #
        # DO NOT use endpoint |S_T - S_0| — that's the NAKED straddle payout.
        # Delta-hedging removes the endpoint payoff and replaces it with
        # continuous gamma/theta settlement ≈ the variance swap payoff.

        # Per-month costs:
        option_fees_pct = DERIBIT_TAKER * 4 * 100  # 2 legs × entry+exit
        monthly_hedge_drag = HEDGE_DRAG_ANNUAL / 12 * 100

        # Discrete hedging error: daily hedging misses intra-day variance.
        # Empirically ~20-30% of realized variance is intra-day on crypto.
        # This increases the effective RV the hedger experiences by ~10-15%.
        rv_adjustment = rv * 0.10  # 10% extra RV from discrete hedging
        discrete_error = (iv * rv_adjustment) / (iv) / 12  # simplified drag

        total_monthly_cost = option_fees_pct + monthly_hedge_drag + discrete_error
        straddle_pnl_conservative = vs_pnl - total_monthly_cost

        res = {
            "month": m, "iv": iv, "rv": rv,
            "vs_pnl": vs_pnl,
            "straddle_pnl": straddle_pnl_conservative,
            "total_cost": total_monthly_cost,
        }
        results.append(res)

        all_trades.append({
            "month": m, "iv": iv, "rv": rv,
            "vs_pnl": round(vs_pnl, 4),
            "straddle_pnl": round(straddle_pnl_conservative, 4),
        })

    # Store trades
    if all_trades:
        with open(TRADES_FILE, "w") as f:
            for t in all_trades:
                f.write(json.dumps(t) + "\n")
        print(f"Stored {len(all_trades)} monthly records.")

    _report(results, fc_monthly, lp_monthly)


# ── Load existing edge returns for correlation ───────────────────────

def _load_funding_carry_monthly():
    path = os.path.join(_DIR, "funding_carry_trades.jsonl")
    if not os.path.exists(path):
        return {}
    trades = [json.loads(l) for l in open(path) if l.strip()]
    monthly = {}
    for t in trades:
        if t["symbol"] != "BTC":
            continue
        ds = datetime.fromtimestamp(t["funding_time"], tz=timezone.utc
                                    ).strftime("%Y-%m")
        rate = t["funding_rate"]
        sp_ret = t["spot_next"] / t["spot_open"] - 1
        pp_ret = t["perp_next"] / t["perp_open"] - 1
        carry = rate + sp_ret - pp_ret
        monthly[ds] = monthly.get(ds, 0) + carry
    return monthly


def _load_lp_monthly():
    path = os.path.join(_DIR, "lp_carry_trades.jsonl")
    if not os.path.exists(path):
        return {}
    trades = [json.loads(l) for l in open(path) if l.strip()]
    monthly = {}
    for t in trades:
        if t["pool"] != "USDC/USDT (v2 stable)":
            continue
        m = t["date"][:7]
        monthly[m] = monthly.get(m, 0) + t["lp_ret"]
    return monthly


def _pearson(xs, ys):
    if len(xs) < 6:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / (n - 1))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / (n - 1))
    return cov / (sx * sy) if sx > 0 and sy > 0 else None


# ── Report ───────────────────────────────────────────────────────────

def _report(results, fc_monthly, lp_monthly):
    if not results:
        print("No results.")
        return

    _sep = "=" * 80

    vs_pnls = [r["vs_pnl"] for r in results]
    st_pnls = [r["straddle_pnl"] for r in results]
    n = len(results)

    # ── Side-by-side comparison ──
    print(f"\n{_sep}")
    print("VAR-SWAP (ceiling) vs STRADDLE-SELL (realistic)  |  {n} months")
    print(_sep)

    for label, pnls in [("Var-swap (ceiling)", vs_pnls),
                         ("Straddle (realistic)", st_pnls)]:
        ann_mean = statistics.mean(pnls) * 12
        ann_std = statistics.stdev(pnls) * math.sqrt(12) if len(pnls) > 1 else 1
        sharpe = ann_mean / ann_std if ann_std > 0 else 0
        wins = sum(1 for p in pnls if p > 0)
        print(f"\n  {label}:")
        print(f"    Mean P&L:    {statistics.mean(pnls):+.3f}%/mo "
              f"({ann_mean:+.1f}% APR)")
        print(f"    Median P&L:  {statistics.median(pnls):+.3f}%/mo")
        print(f"    Win rate:    {wins}/{n} ({wins / n * 100:.0f}%)")
        print(f"    Sharpe:      {sharpe:.2f}")

    gap = statistics.mean(vs_pnls) * 12 - statistics.mean(st_pnls) * 12
    print(f"\n  GAP (ceiling − realistic): {gap:+.1f}% APR")
    print(f"  This is the cost of what's actually executable on Deribit.")

    # ── Worst months ──
    print(f"\n{_sep}")
    print("WORST MONTHS — the steamroller")
    print(_sep)

    for label, pnls_list in [("Var-swap", results)]:
        pass

    sorted_vs = sorted(results, key=lambda x: x["vs_pnl"])
    sorted_st = sorted(results, key=lambda x: x["straddle_pnl"])

    print(f"\n  {'month':>8}  {'IV':>5}  {'RV':>5}  {'var-swap':>9}  {'straddle':>9}")
    worst_5 = sorted(results, key=lambda x: x["straddle_pnl"])[:5]
    for r in worst_5:
        print(f"  {r['month']:>8}  {r['iv']:>4.0f}%  {r['rv']:>4.0f}%  "
              f"{r['vs_pnl']:>+8.2f}%  {r['straddle_pnl']:>+8.2f}%")

    avg_win_st = statistics.mean([p for p in st_pnls if p > 0]) if any(
        p > 0 for p in st_pnls) else 0.01
    worst_st = min(st_pnls)
    print(f"\n  Steamroller (straddle): |worst| / avg_win = "
          f"|{worst_st:.2f}| / {avg_win_st:.2f} = "
          f"{abs(worst_st / avg_win_st):.1f} months wiped")

    # ── Worst rolling 12-month window ──
    print(f"\n{_sep}")
    print("WORST ROLLING 12-MONTH WINDOW")
    print(_sep)

    for label, pnls in [("Var-swap", vs_pnls), ("Straddle", st_pnls)]:
        if len(pnls) < 12:
            continue
        worst_12 = float("inf")
        worst_start = 0
        for i in range(len(pnls) - 11):
            window = sum(pnls[i:i + 12])
            if window < worst_12:
                worst_12 = window
                worst_start = i
        ws = results[worst_start]["month"]
        we = results[min(worst_start + 11, len(results) - 1)]["month"]
        print(f"  {label:>12}: {worst_12:+.2f}% ({ws} to {we})")

    # ── Max drawdown ──
    print(f"\n{_sep}")
    print("MAX DRAWDOWN (cumulative equity)")
    print(_sep)

    for label, pnls in [("Var-swap", vs_pnls), ("Straddle", st_pnls)]:
        eq = [1.0]
        for p in pnls:
            eq.append(eq[-1] * (1 + p / 100))
        peak = eq[0]
        dd = 0
        for e in eq:
            peak = max(peak, e)
            dd = max(dd, (peak - e) / peak)
        print(f"  {label:>12}: {dd * 100:.1f}%")

    # ── Crash spacing ──
    print(f"\n{_sep}")
    print("CRASH CLUSTERING")
    print(_sep)

    crash_months = [r["month"] for r in results if r["straddle_pnl"] < -2]
    print(f"  Months with >2% loss (straddle): {len(crash_months)}")
    if len(crash_months) > 1:
        # Compute spacing
        for i in range(1, len(crash_months)):
            m0 = crash_months[i - 1]
            m1 = crash_months[i]
            # Rough month difference
            y0, mo0 = int(m0[:4]), int(m0[5:7])
            y1, mo1 = int(m1[:4]), int(m1[5:7])
            gap_mo = (y1 - y0) * 12 + (mo1 - mo0)
            print(f"    {m0} → {m1}: {gap_mo} months apart"
                  f"{'  ← CLUSTER' if gap_mo <= 3 else ''}")

    # Hypothetical 2-crashes-in-6-months
    worst_2 = sorted(st_pnls)[:2]
    print(f"\n  Hypothetical 2 worst months in 6: "
          f"{sum(worst_2):+.2f}% + 4 avg months "
          f"({4 * avg_win_st:+.2f}%) = "
          f"{sum(worst_2) + 4 * avg_win_st:+.2f}% net")

    # ── Correlation to existing edges ──
    print(f"\n{_sep}")
    print("CORRELATION TO EXISTING EDGES")
    print(_sep)

    vol_months = {r["month"]: r["straddle_pnl"] for r in results}

    for edge_name, edge_monthly in [("Funding carry (BTC)", fc_monthly),
                                     ("Stable LP (USDC/USDT)", lp_monthly)]:
        common = sorted(set(vol_months) & set(edge_monthly))
        if len(common) < 6:
            print(f"  vs {edge_name}: insufficient overlap ({len(common)} months)")
            continue

        vx = [vol_months[m] for m in common]
        ey = [edge_monthly[m] * 100 for m in common]  # convert to %
        corr = _pearson(vx, ey)
        print(f"  vs {edge_name}: corr = "
              f"{corr:+.3f} ({len(common)} months)"
              f"{'  ← UNCORRELATED' if corr is not None and abs(corr) < 0.3 else ''}"
              if corr is not None else
              f"  vs {edge_name}: N/A")

    # ── Portfolio Sharpe test (the stETH test) ──
    print(f"\n{_sep}")
    print("PORTFOLIO SHARPE — does adding vol IMPROVE the portfolio?")
    print(_sep)

    # Build monthly return series for all three edges
    all_months = sorted(set(vol_months) & set(fc_monthly) & set(lp_monthly))
    if len(all_months) < 12:
        print(f"  Insufficient overlap ({len(all_months)} months) — "
              f"need ≥12 for portfolio test")
    else:
        fc_rets = [fc_monthly[m] * 100 for m in all_months]
        lp_rets = [lp_monthly[m] * 100 for m in all_months]
        vol_rets = [vol_months[m] for m in all_months]

        # 2-edge portfolio (equal-weight funding + stable LP)
        port2 = [(f + l) / 2 for f, l in zip(fc_rets, lp_rets)]
        mu2 = statistics.mean(port2) * 12
        sd2 = statistics.stdev(port2) * math.sqrt(12)
        sh2 = mu2 / sd2 if sd2 > 0 else 0

        # 3-edge portfolio (equal-weight all three)
        port3 = [(f + l + v) / 3 for f, l, v in
                 zip(fc_rets, lp_rets, vol_rets)]
        mu3 = statistics.mean(port3) * 12
        sd3 = statistics.stdev(port3) * math.sqrt(12)
        sh3 = mu3 / sd3 if sd3 > 0 else 0

        print(f"  2-edge (funding + stable LP):    "
              f"APR={mu2:+.1f}%  vol={sd2:.1f}%  Sharpe={sh2:.2f}")
        print(f"  3-edge (+ vol premium):          "
              f"APR={mu3:+.1f}%  vol={sd3:.1f}%  Sharpe={sh3:.2f}")
        delta = sh3 - sh2
        print(f"  Sharpe change:                   {delta:+.2f}")
        if delta > 0.1:
            print(f"  → IMPROVES portfolio (Sharpe +{delta:.2f})")
        elif delta > -0.1:
            print(f"  → NEUTRAL (Sharpe ~unchanged)")
        else:
            print(f"  → DEGRADES portfolio (Sharpe {delta:+.2f})")

    # ── Verdict ──
    print(f"\n{_sep}")
    print("VERDICT")
    print(_sep)

    st_sharpe = (statistics.mean(st_pnls) * 12 /
                 (statistics.stdev(st_pnls) * math.sqrt(12))
                 if len(st_pnls) > 1 else 0)

    worst_12_st = min(sum(st_pnls[i:i + 12])
                      for i in range(len(st_pnls) - 11)) if len(st_pnls) >= 12 else 0

    if st_sharpe > 0.5 and worst_12_st > -5:
        print(f"  Straddle Sharpe {st_sharpe:.2f}, "
              f"worst 12mo {worst_12_st:+.1f}%")
        if len(all_months) >= 12 and delta > 0:
            print(f"  Portfolio Sharpe improves by {delta:+.2f}")
            print(f"  → REAL 3rd edge — improves portfolio, tail survivable")
        elif len(all_months) >= 12:
            print(f"  Portfolio Sharpe change: {delta:+.2f}")
            print(f"  → REJECTED — doesn't improve portfolio despite "
                  f"positive standalone Sharpe")
        else:
            print(f"  → TENTATIVE — positive Sharpe but insufficient "
                  f"overlap for portfolio test")
    elif st_sharpe > 0:
        print(f"  Straddle Sharpe {st_sharpe:.2f} (weak), "
              f"worst 12mo {worst_12_st:+.1f}%")
        print(f"  → MARGINAL — positive but thin, tail risk concerning")
    else:
        print(f"  Straddle Sharpe {st_sharpe:.2f} (negative)")
        print(f"  → REJECTED — doesn't earn the premium after costs")


if __name__ == "__main__":
    backtest()
