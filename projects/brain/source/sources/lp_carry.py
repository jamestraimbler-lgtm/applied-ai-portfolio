"""Uniswap v2 LP carry backtest.

Tests: do LP fees exceed impermanent loss for v2 50-50 pools?
Fee income from DefiLlama daily apyBase. Price path from Binance daily klines.
The EDGE per period = fee_income − IL_change − gas, vs the HODL benchmark.
Fee income and IL reported SEPARATELY — the ratio is the whole story.

IMPORTANT — IL LIMITATION (path-independent, understates real IL ~3x):
The v2 LP daily return sqrt(P_t/P_{t-1}) TELESCOPES: the product over N days
equals sqrt(P_final/P_0) regardless of path. This means the computed IL is
endpoint-only — it misses intra-day volatility, LVR (loss-vs-rebalancing), and
arbitrageur extractions that real LPs suffer on every price swing.
DefiLlama's il7d (on-chain realized IL) gives ~-4.1%/yr for ETH pools vs the
~-1.3% this code computes. The report shows BOTH and uses il7d for honest
net-vs-HODL. Stable pools are unaffected (IL ≈ 0 either way).
"""

import json, math, os, statistics, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE = os.path.join(_DIR, "lp_carry_trades.jsonl")

# Gas assumption (L1 Ethereum, round-trip add+remove liquidity)
GAS_USD_RT = 50       # $50 round-trip (L1); L2 would be ~$0.50
POSITION_USD = 10_000  # default position size for gas % computation
GAS_PCT = GAS_USD_RT / POSITION_USD * 100  # 0.5% for $10k position

POOLS = [
    {"name": "ETH/USDC (v2)",
     "id": "702fff16-4bfa-4c1f-8c02-e0ea0f5ecde6",
     "binance_pair": "ETHUSDT", "is_stable": False},
    {"name": "ETH/USDT (v2)",
     "id": "196aa543-1881-4515-9928-577693d4fa72",
     "binance_pair": "ETHUSDT", "is_stable": False},
    {"name": "USDC/USDT (v2 stable)",
     "id": "e737d721-f45c-40f0-9793-9f56261862b9",
     "binance_pair": None, "is_stable": True},
]


# ── Data fetchers ────────────────────────────────────────────────────

def _fetch_chart(pool_id):
    r = requests.get(f"https://yields.llama.fi/chart/{pool_id}", timeout=15)
    if r.status_code != 200:
        return []
    return r.json().get("data", [])


def _fetch_daily_klines(pair, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        r = requests.get("https://api.binance.com/api/v3/klines", params={
            "symbol": pair, "interval": "1d",
            "startTime": cur, "limit": 1000,
        }, timeout=15)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        cur = batch[-1][0] + 86_400_000
        if len(batch) < 1000:
            break
    return out


# ── Backtest ─────────────────────────────────────────────────────────

def backtest():
    now_ms = int(time.time() * 1000)
    results = []
    all_trades = []

    for pool in POOLS:
        print(f"\n  {pool['name']}...", flush=True)

        chart = _fetch_chart(pool["id"])
        if len(chart) < 30:
            print(f"    only {len(chart)} entries, skip")
            continue

        # Parse DefiLlama dates → {date_str: apyBase}
        fee_by_date = {}
        il7d_by_date = {}
        for entry in chart:
            ds = entry["timestamp"][:10]
            fee_by_date[ds] = entry.get("apyBase") or 0
            il7d_by_date[ds] = entry.get("il7d")

        # Fetch Binance price if volatile pair
        prices_by_date = {}
        if pool["binance_pair"]:
            start_date = chart[0]["timestamp"][:10]
            start_ms = int(datetime.strptime(start_date, "%Y-%m-%d"
                           ).replace(tzinfo=timezone.utc).timestamp() * 1000)
            klines = _fetch_daily_klines(pool["binance_pair"], start_ms, now_ms)
            for k in klines:
                ds = datetime.fromtimestamp(
                    k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                prices_by_date[ds] = float(k[4])  # close price
            print(f"    {len(klines)} daily klines from Binance")

        # Align dates (only use dates present in both)
        dates = sorted(fee_by_date.keys())
        if pool["binance_pair"]:
            dates = [d for d in dates if d in prices_by_date]
        if len(dates) < 30:
            print(f"    only {len(dates)} aligned dates, skip")
            continue

        print(f"    {len(dates)} aligned days: {dates[0]} to {dates[-1]}")

        # ── Day-by-day simulation ──
        p0 = prices_by_date.get(dates[0], 1.0)
        lp_equity = 1.0   # $1 LP position
        hodl = 1.0         # $1 50-50 HODL
        cum_fee = 0.0
        cum_il = 0.0

        daily_lp_rets = []
        daily_hodl_rets = []
        monthly = {}  # month → {lp_ret, hodl_ret, fee, il}

        for i in range(1, len(dates)):
            d = dates[i]
            fee_apy = fee_by_date.get(d, 0)
            daily_fee_pct = fee_apy / 365 / 100  # de-annualize

            if pool["is_stable"]:
                # Stable pair: no IL, LP value ≈ constant
                lp_ret = daily_fee_pct
                hodl_ret = 0.0
                daily_il = 0.0
            else:
                p_prev = prices_by_date.get(dates[i - 1], p0)
                p_now = prices_by_date.get(d, p0)
                if p_prev <= 0:
                    continue

                # LP price return: sqrt(P_t / P_{t-1}) - 1
                sqrt_ratio = math.sqrt(p_now / p_prev)
                lp_price_ret = sqrt_ratio - 1

                # LP return = price change + fee
                lp_ret = (1 + lp_price_ret) * (1 + daily_fee_pct) - 1

                # HODL return: 0.5 × (P_t/P_{t-1}) + 0.5 - 1
                hodl_ret = 0.5 * (p_now / p_prev) + 0.5 - 1

                # Daily IL = LP_price_ret - hodl_ret (negative = LP underperforms)
                daily_il = lp_price_ret - hodl_ret

            lp_equity *= (1 + lp_ret)
            hodl *= (1 + hodl_ret)
            cum_fee += daily_fee_pct * lp_equity  # fee in $ terms
            cum_il += daily_il

            daily_lp_rets.append(lp_ret)
            daily_hodl_rets.append(hodl_ret)

            # Monthly aggregation
            month = d[:7]
            if month not in monthly:
                monthly[month] = {"lp": 0, "hodl": 0, "fee": 0, "il": 0,
                                  "n": 0}
            monthly[month]["lp"] += lp_ret
            monthly[month]["hodl"] += hodl_ret
            monthly[month]["fee"] += daily_fee_pct
            monthly[month]["il"] += daily_il
            monthly[month]["n"] += 1

            all_trades.append({
                "pool": pool["name"], "date": d,
                "fee_apy": fee_apy, "daily_fee": daily_fee_pct,
                "lp_ret": lp_ret, "hodl_ret": hodl_ret,
                "lp_equity": lp_equity, "hodl_equity": hodl,
            })

        # ── Compute metrics ──
        days = len(dates) - 1
        years = days / 365

        # Final values
        total_lp_ret = lp_equity - 1
        total_hodl_ret = hodl - 1

        # IL: compare LP-no-fees to HODL
        if not pool["is_stable"] and p0 > 0:
            r_final = prices_by_date.get(dates[-1], p0) / p0
            lp_no_fees = math.sqrt(r_final)
            hodl_final = 0.5 * (1 + r_final)
            total_il_pct = (lp_no_fees / hodl_final - 1) * 100
        else:
            total_il_pct = 0

        # Fee APR
        # Cumulative fee yield from daily apyBase
        cum_fee_pct = 0
        for d in dates[1:]:
            cum_fee_pct += fee_by_date.get(d, 0) / 365 / 100
        fee_apr = cum_fee_pct / years * 100 if years > 0 else 0

        # IL drag APR
        il_drag_apr = total_il_pct / years if years > 0 else 0

        # Net APR vs HODL
        net_vs_hodl = (total_lp_ret - total_hodl_ret) / years * 100

        # Sharpe of daily (LP - HODL) excess returns
        excess = [l - h for l, h in zip(daily_lp_rets, daily_hodl_rets)]
        if len(excess) > 1:
            mu = statistics.mean(excess)
            sd = statistics.stdev(excess)
            sharpe = (mu * 365) / (sd * math.sqrt(365)) if sd > 0 else 0
        else:
            sharpe = 0

        # Worst monthly excess
        month_excess = {m: v["lp"] - v["hodl"]
                        for m, v in monthly.items()}
        worst_month = min(month_excess.items(), key=lambda x: x[1])
        best_month = max(month_excess.items(), key=lambda x: x[1])

        # Fee-to-IL ratio (absolute values)
        fee_to_il = abs(fee_apr / il_drag_apr) if il_drag_apr != 0 else float("inf")

        # Cross-check: DefiLlama il7d where available
        il7d_vals = [v for v in il7d_by_date.values() if v is not None]
        il7d_mean = statistics.mean(il7d_vals) if il7d_vals else None

        res = {
            "pool": pool["name"], "days": days, "years": years,
            "fee_apr": fee_apr, "il_drag_apr": il_drag_apr,
            "net_vs_hodl_apr": net_vs_hodl, "gas_drag": GAS_PCT,
            "net_after_gas": net_vs_hodl - GAS_PCT / years if years > 0 else 0,
            "sharpe": sharpe,
            "fee_to_il": fee_to_il,
            "total_lp": total_lp_ret * 100,
            "total_hodl": total_hodl_ret * 100,
            "worst_month": worst_month,
            "best_month": best_month,
            "il7d_mean": il7d_mean,
            "is_stable": pool["is_stable"],
        }
        results.append(res)

        print(f"    fee APR: {fee_apr:+.1f}%  IL drag: {il_drag_apr:+.1f}%  "
              f"net vs HODL: {net_vs_hodl:+.1f}%/yr")

    # Store trades
    if all_trades:
        with open(TRADES_FILE, "w") as f:
            for t in all_trades:
                f.write(json.dumps(t) + "\n")
        print(f"\nStored {len(all_trades)} daily records.")

    _report(results)


# ── Report ───────────────────────────────────────────────────────────

def _report(results):
    if not results:
        print("No results.")
        return

    _sep = "=" * 85

    print(f"\n{_sep}")
    print("UNISWAP v2 LP: FEES vs IMPERMANENT LOSS vs HODL")
    print(f"  Gas assumption: ${GAS_USD_RT} round-trip on L1, "
          f"${POSITION_USD:,} position = {GAS_PCT:.1f}% drag")
    print(_sep)

    # ── Per-pool breakdown ──
    print(f"\n  {'pool':>22}  {'days':>5}  {'fee APR':>8}  {'IL drag':>8}  "
          f"{'net/HODL':>9}  {'−gas':>8}  {'Sharpe':>7}  {'fee/IL':>7}")

    for r in results:
        gas_adj = r["net_vs_hodl_apr"] - GAS_PCT / r["years"]
        print(f"  {r['pool']:>22}  {r['days']:>5}  "
              f"{r['fee_apr']:>+7.1f}%  {r['il_drag_apr']:>+7.1f}%  "
              f"{r['net_vs_hodl_apr']:>+8.1f}%  {gas_adj:>+7.1f}%  "
              f"{r['sharpe']:>+6.2f}  "
              f"{('inf' if r['fee_to_il'] > 100 else str(round(r['fee_to_il'],1))+'x'):>6}")

    # ── Fee vs IL separation (the key table) ──
    print(f"\n{_sep}")
    print("FEE vs IL SEPARATION — the ratio that decides everything")
    print(_sep)

    for r in results:
        print(f"\n  {r['pool']}:")
        print(f"    Gross fee APR:            {r['fee_apr']:>+8.1f}%  "
              f"← what a naive backtest shows")
        print(f"    IL (endpoint, code):      {r['il_drag_apr']:>+8.1f}%  "
              f"← path-INDEPENDENT, understates real IL")

        # il7d realistic IL
        il7d_apr = None
        if r["il7d_mean"] is not None:
            il7d_apr = r["il7d_mean"] * 52
            print(f"    IL (il7d, realistic):     {il7d_apr:>+8.1f}%  "
                  f"← path-DEPENDENT, on-chain realized")

        gas_adj = r["net_vs_hodl_apr"] - GAS_PCT / r["years"]
        print(f"    Net vs HODL (endpoint IL): {r['net_vs_hodl_apr']:>+7.1f}%  "
              f"← OPTIMISTIC (uses endpoint IL)")

        # Honest net using il7d IL
        if il7d_apr is not None and not r["is_stable"]:
            extra_il = abs(il7d_apr) - abs(r["il_drag_apr"])
            honest_net = r["net_vs_hodl_apr"] - extra_il
            honest_gas = honest_net - GAS_PCT / r["years"]
            print(f"    Net vs HODL (il7d IL):     {honest_net:>+7.1f}%  "
                  f"← HONEST (uses realistic IL)")
            print(f"    Net after gas (honest):    {honest_gas:>+7.1f}%  "
                  f"← THE REAL NUMBER")
        else:
            print(f"    Net vs HODL (post-gas):    {gas_adj:>+7.1f}%  "
                  f"← THE REAL NUMBER (IL=0 for stable)")

    # ── Worst/best months ──
    print(f"\n{_sep}")
    print("REGIME DEPENDENCE — worst and best months")
    print(_sep)
    for r in results:
        wm, wv = r["worst_month"]
        bm, bv = r["best_month"]
        print(f"  {r['pool']:>22}: worst={wm} ({wv*100:+.2f}%)  "
              f"best={bm} ({bv*100:+.2f}%)")

    # ── Verdict (uses il7d IL for volatile pools) ──
    print(f"\n{_sep}")
    print("VERDICT (honest — volatile pools use il7d realistic IL)")
    print(_sep)
    print("  NOTE: endpoint IL understates real IL ~3x for volatile pairs")
    print("  (daily sqrt telescopes — misses intra-day LVR). Using il7d.")
    print()
    for r in results:
        if r["is_stable"]:
            gas_adj = r["net_vs_hodl_apr"] - GAS_PCT / r["years"]
            if gas_adj > 0:
                v = "CONFIRMED — pure yield, zero IL, market-neutral"
            else:
                v = "gas eats it — only viable on L2 or large positions"
        else:
            # Use il7d-adjusted net
            il7d_apr = (r["il7d_mean"] * 52) if r["il7d_mean"] else r["il_drag_apr"]
            extra_il = abs(il7d_apr) - abs(r["il_drag_apr"])
            honest_net = r["net_vs_hodl_apr"] - extra_il - GAS_PCT / r["years"]
            if honest_net > 1:
                v = f"REAL — survives realistic IL ({honest_net:+.1f}%/yr)"
            elif honest_net > 0:
                v = f"MARGINAL — barely positive under realistic IL ({honest_net:+.1f}%/yr), directional"
            else:
                v = f"IL EATS IT — negative under realistic IL ({honest_net:+.1f}%/yr)"
        print(f"  {r['pool']:>22}: {v}")


if __name__ == "__main__":
    backtest()
