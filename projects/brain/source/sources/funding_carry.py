"""Delta-neutral funding carry backtest.

Position: SHORT perp (collect funding when rate>0) + LONG spot (hedge).
Equal notional, simultaneously. Net exposure ≈ 0.
Edge = funding_collected − all_fees − basis_drift.

Models EVERY leg:
  - perp taker fees (open + close)
  - spot taker fees (open + close)
  - slippage (both legs, both directions)
  - basis drift PnL (perp vs spot price divergence while held)

Two models:
  (i) always-on: hold continuously, single entry/exit fee
  (ii) selective: hold only when funding > 0, re-entry fees per cycle
"""

import json, math, os, statistics, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE = os.path.join(_DIR, "funding_carry_trades.jsonl")

# ── Cost assumptions (top-of-file, easily auditable) ────────────────
PERP_TAKER  = 0.00045   # 4.5 bps/side  (Binance VIP0 futures taker)
SPOT_TAKER  = 0.001     # 10  bps/side  (Binance VIP0 spot taker)
SLIPPAGE    = 0.0001    # 1   bp per leg per side (assumption)
# Round-trip = enter (perp+spot+2×slip) + exit (perp+spot+2×slip)
ROUND_TRIP  = 2 * (PERP_TAKER + SPOT_TAKER + 2 * SLIPPAGE)  # = 0.0033

UNIVERSE = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX",
    "DOT", "LINK", "UNI", "LTC", "NEAR", "APT", "SUI",
    "ONDO", "PEPE", "ARB", "OP", "FIL",
]

FAPI = "https://fapi.binance.com/fapi/v1"
SAPI = "https://api.binance.com/api/v3"


# ── Data fetchers ────────────────────────────────────────────────────

def _fetch_funding(symbol, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        r = requests.get(f"{FAPI}/fundingRate", params={
            "symbol": f"{symbol}USDT", "startTime": cur, "limit": 1000,
        }, timeout=15)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        cur = batch[-1]["fundingTime"] + 1
        if len(batch) < 1000:
            break
    return out


def _fetch_8h(pair, start_ms, end_ms, base):
    out, cur = [], start_ms
    while cur < end_ms:
        r = requests.get(f"{base}/klines", params={
            "symbol": pair, "interval": "8h",
            "startTime": cur, "limit": 1000,
        }, timeout=15)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        cur = batch[-1][0] + 8 * 3_600_000
        if len(batch) < 1000:
            break
    return out


def _round_8h(ms):
    return ms // (8 * 3_600_000) * (8 * 3_600_000)


# ── Correlation helper ───────────────────────────────────────────────

def _pearson(xs, ys):
    if len(xs) < 10:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / (n - 1))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / (n - 1))
    return cov / (sx * sy) if sx > 0 and sy > 0 else None


# ── Main backtest ────────────────────────────────────────────────────

def backtest(months=12):
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - months * 30 * 86_400_000

    # Pre-fetch BTC spot for correlation
    print("Fetching BTC spot 8h klines (correlation reference)...")
    btc_spot_kl = _fetch_8h("BTCUSDT", start_ms, now_ms, SAPI)
    btc_by_ts = {_round_8h(k[0]): float(k[1]) for k in btc_spot_kl}

    results = []
    all_trades = []

    for sym in UNIVERSE:
        pair = f"{sym}USDT"
        print(f"  {sym}...", end=" ", flush=True)

        funding = _fetch_funding(sym, start_ms, now_ms)
        spot_kl = _fetch_8h(pair, start_ms, now_ms, SAPI)
        perp_kl = _fetch_8h(pair, start_ms, now_ms, FAPI)

        if not funding or not spot_kl or not perp_kl:
            print("no data, skip")
            continue

        spot_ts = {_round_8h(k[0]): float(k[1]) for k in spot_kl}
        perp_ts = {_round_8h(k[0]): float(k[1]) for k in perp_kl}

        # Build aligned timeline
        tl = []
        for f in funding:
            ft = _round_8h(f["fundingTime"])
            rate = float(f["fundingRate"])
            sp = spot_ts.get(ft)
            pp = perp_ts.get(ft)
            if sp and pp and sp > 0 and pp > 0:
                tl.append((ft, rate, sp, pp))

        if len(tl) < 30:
            print(f"only {len(tl)} periods, skip")
            continue

        hold_days = (tl[-1][0] - tl[0][0]) / 86_400_000

        # ── Per-period returns ──
        period_rets = []
        for i in range(len(tl) - 1):
            _, rate, sp, pp = tl[i]
            _, _, sp1, pp1 = tl[i + 1]
            # SHORT perp + LONG spot: collect funding, hedge price
            pr = rate + (sp1 / sp - 1) - (pp1 / pp - 1)
            period_rets.append(pr)

        # ── ALWAYS-ON ──
        gross_funding = sum(r for _, r, _, _ in tl[:-1])
        price_pnl = (tl[-1][2] / tl[0][2]) - (tl[-1][3] / tl[0][3])
        net_ret = gross_funding + price_pnl - ROUND_TRIP
        net_ret_2x = gross_funding + price_pnl - ROUND_TRIP * 2

        gross_apr = gross_funding / hold_days * 365 * 100
        net_apr = net_ret / hold_days * 365 * 100
        net_apr_2x = net_ret_2x / hold_days * 365 * 100

        # Sharpe (8h periods, 1095/yr)
        ppy = 365 * 3
        fee_pp = ROUND_TRIP / len(period_rets)
        net_prs = [pr - fee_pp for pr in period_rets]
        if len(net_prs) > 1:
            mu = statistics.mean(net_prs)
            sd = statistics.stdev(net_prs)
            sharpe = (mu * ppy) / (sd * math.sqrt(ppy)) if sd > 0 else 0
        else:
            sharpe = 0

        # % time funding positive
        pct_pos = sum(1 for _, r, _, _ in tl if r > 0) / len(tl) * 100

        # Max drawdown of equity curve (multiplicative)
        equity = [1.0]
        for pr in net_prs:
            equity.append(equity[-1] * (1 + pr))
        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            peak = max(peak, e)
            dd = (peak - e) / peak
            max_dd = max(max_dd, dd)
        max_dd *= 100

        # BTC correlation
        carry_r, btc_r = [], []
        for i in range(len(tl) - 1):
            ft = tl[i][0]
            ft1 = tl[i + 1][0]
            b0 = btc_by_ts.get(ft)
            b1 = btc_by_ts.get(ft1)
            if b0 and b1 and b0 > 0:
                carry_r.append(period_rets[i])
                btc_r.append(b1 / b0 - 1)
        btc_corr = _pearson(carry_r, btc_r)

        # Basis
        basis_entry = (tl[0][3] / tl[0][2] - 1) * 100
        basis_exit = (tl[-1][3] / tl[-1][2] - 1) * 100

        # ── SELECTIVE (hold only when funding > 0) ──
        in_pos = False
        sel_cum = [0.0]
        sel_cycles = 0
        sel_in = 0
        e_sp = e_pp = c_fund = 0.0

        for i in range(len(tl) - 1):
            _, rate, sp, pp = tl[i]
            _, _, sp1, pp1 = tl[i + 1]

            if in_pos:
                c_fund += rate
                sel_in += 1
                pr = rate + (sp1 / sp - 1) - (pp1 / pp - 1)

                if rate <= 0:
                    # Exit: price PnL from entry to now
                    ppnl = (sp / e_sp) - (pp / e_pp)
                    sel_cum.append(sel_cum[-1] + c_fund + ppnl - ROUND_TRIP
                                   - sel_cum[-1] + sel_cum[-1])
                    # Simpler: just track via period returns
                    sel_cum[-1] = sel_cum[-2] + pr
                    sel_cum[-1] -= ROUND_TRIP
                    in_pos = False
                    sel_cycles += 1
                    c_fund = 0
                else:
                    sel_cum.append(sel_cum[-1] + pr)
            else:
                sel_cum.append(sel_cum[-1])
                if rate > 0:
                    e_sp, e_pp = sp, pp
                    c_fund = 0
                    in_pos = True

        if in_pos:
            sel_cum[-1] -= ROUND_TRIP
            sel_cycles += 1

        sel_total = sel_cum[-1]
        sel_apr = sel_total / hold_days * 365 * 100 if hold_days > 0 else 0
        sel_pct = sel_in / len(period_rets) * 100 if period_rets else 0

        sel_eq = [1.0]
        for i in range(1, len(sel_cum)):
            delta = sel_cum[i] - sel_cum[i - 1]
            sel_eq.append(sel_eq[-1] * (1 + delta))
        sel_peak = sel_eq[0]
        sel_dd = 0.0
        for e in sel_eq:
            sel_peak = max(sel_peak, e)
            sel_dd = max(sel_dd, (sel_peak - e) / sel_peak)
        sel_dd *= 100

        res = {
            "sym": sym, "periods": len(tl), "days": hold_days,
            "gross_apr": gross_apr, "net_apr": net_apr,
            "net_apr_2x": net_apr_2x, "sharpe": sharpe,
            "pct_pos": pct_pos, "max_dd": max_dd,
            "btc_corr": btc_corr,
            "basis_entry": basis_entry, "basis_exit": basis_exit,
            "sel_apr": sel_apr, "sel_pct": sel_pct,
            "sel_cycles": sel_cycles, "sel_dd": sel_dd,
        }
        results.append(res)

        # Store raw period data
        for i in range(len(tl) - 1):
            ft, rate, sp, pp = tl[i]
            _, _, sp1, pp1 = tl[i + 1]
            all_trades.append({
                "symbol": sym,
                "funding_time": ft / 1000,
                "funding_rate": rate,
                "spot_open": sp, "spot_next": sp1,
                "perp_open": pp, "perp_next": pp1,
            })

        print(f"{len(tl)} periods, gross {gross_apr:+.1f}% APR, "
              f"net {net_apr:+.1f}% APR")

    # Store trades
    if all_trades:
        with open(TRADES_FILE, "w") as f:
            for t in all_trades:
                f.write(json.dumps(t) + "\n")
        print(f"\nStored {len(all_trades)} period records.")

    _report(results)


def _report(results):
    if not results:
        print("No results.")
        return

    _sep = "=" * 90

    # ── Sign check ──
    print(f"\n{_sep}")
    print("SIGN CHECK: SHORT perp (collect funding when rate>0) + LONG spot")
    print("  Positive funding rate → SHORT receives payment")
    print("  Position = delta-neutral; edge is the thin spread after all costs")
    print(_sep)

    # ── ALWAYS-ON per-token ──
    print(f"\n{_sep}")
    print(f"ALWAYS-ON MODEL — hold continuously, single entry/exit")
    print(f"  Fees: perp {PERP_TAKER*100:.3f}%/side, "
          f"spot {SPOT_TAKER*100:.2f}%/side, "
          f"slip {SLIPPAGE*100:.2f}%/leg/side  |  "
          f"round-trip = {ROUND_TRIP*100:.2f}%")
    print(_sep)
    print(f"  {'sym':>6}  {'days':>5}  {'gross':>8}  {'net':>8}  "
          f"{'net 2×':>8}  {'Sharpe':>7}  {'%pos':>5}  "
          f"{'maxDD':>6}  {'BTC ρ':>6}  {'basis Δ':>8}")

    for r in sorted(results, key=lambda x: -x["net_apr"]):
        bd = r["basis_exit"] - r["basis_entry"]
        corr_s = f"{r['btc_corr']:+.3f}" if r["btc_corr"] is not None else "  N/A"
        print(f"  {r['sym']:>6}  {r['days']:>5.0f}  "
              f"{r['gross_apr']:>+7.1f}%  {r['net_apr']:>+7.1f}%  "
              f"{r['net_apr_2x']:>+7.1f}%  {r['sharpe']:>+6.2f}  "
              f"{r['pct_pos']:>4.0f}%  {r['max_dd']:>5.1f}%  "
              f"{corr_s}  {bd:>+7.2f}%")

    # ── Aggregate ──
    avg = lambda k: statistics.mean([r[k] for r in results])
    med = lambda k: statistics.median([r[k] for r in results])
    corrs = [r["btc_corr"] for r in results if r["btc_corr"] is not None]

    print(f"\n  {'MEAN':>6}  {'':>5}  {avg('gross_apr'):>+7.1f}%  "
          f"{avg('net_apr'):>+7.1f}%  {avg('net_apr_2x'):>+7.1f}%  "
          f"{avg('sharpe'):>+6.2f}  {avg('pct_pos'):>4.0f}%  "
          f"{avg('max_dd'):>5.1f}%  "
          f"{statistics.mean(corrs):>+6.3f}" if corrs else "")
    print(f"  {'MEDIAN':>6}  {'':>5}  {med('gross_apr'):>+7.1f}%  "
          f"{med('net_apr'):>+7.1f}%  {med('net_apr_2x'):>+7.1f}%  "
          f"{med('sharpe'):>+6.2f}  {med('pct_pos'):>4.0f}%  "
          f"{med('max_dd'):>5.1f}%")

    # ── SELECTIVE per-token ──
    print(f"\n{_sep}")
    print("SELECTIVE MODEL — hold only when funding > 0, flat otherwise")
    print(f"  Re-entry cost: {ROUND_TRIP*100:.2f}% per cycle")
    print(_sep)
    print(f"  {'sym':>6}  {'sel APR':>9}  {'%in':>5}  "
          f"{'cycles':>7}  {'maxDD':>6}")

    for r in sorted(results, key=lambda x: -x["sel_apr"]):
        print(f"  {r['sym']:>6}  {r['sel_apr']:>+8.1f}%  "
              f"{r['sel_pct']:>4.0f}%  {r['sel_cycles']:>6}  "
              f"{r['sel_dd']:>5.1f}%")

    sel_apr_avg = avg("sel_apr")
    sel_pct_avg = avg("sel_pct")
    print(f"\n  {'MEAN':>6}  {sel_apr_avg:>+8.1f}%  {sel_pct_avg:>4.0f}%")

    # ── BTC comparison ──
    btc = next((r for r in results if r["sym"] == "BTC"), None)
    if btc:
        # BTC buy-and-hold return from spot klines
        print(f"\n{_sep}")
        print("BENCHMARK COMPARISON")
        print(_sep)
        print(f"  USDT (hold cash):        0.0% APR")
        print(f"  BTC carry (always-on):   {btc['net_apr']:+.1f}% APR, "
              f"Sharpe {btc['sharpe']:+.2f}")
        print(f"  Aggregate carry (mean):  {avg('net_apr'):+.1f}% APR, "
              f"Sharpe {avg('sharpe'):+.2f}")
        if corrs:
            print(f"  BTC correlation (mean):  {statistics.mean(corrs):+.3f} "
                  f"({'low' if abs(statistics.mean(corrs)) < 0.3 else 'moderate-high'})")

    # ── Robustness ──
    pos_net = sum(1 for r in results if r["net_apr"] > 0)
    pos_2x = sum(1 for r in results if r["net_apr_2x"] > 0)
    n = len(results)
    print(f"\n{_sep}")
    print("ROBUSTNESS CHECK")
    print(_sep)
    print(f"  Net positive at stated fees:  {pos_net}/{n} tokens")
    print(f"  Net positive at 2× fees:      {pos_2x}/{n} tokens")
    if pos_2x >= n * 0.6:
        print(f"  → ROBUST: majority survive 2× fees")
    elif pos_2x >= n * 0.3:
        print(f"  → THIN: some survive 2× fees, fee-sensitive")
    else:
        print(f"  → FRAGILE: collapses at higher fees")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Delta-neutral funding carry")
    ap.add_argument("--months", type=int, default=12)
    args = ap.parse_args()
    backtest(months=args.months)
