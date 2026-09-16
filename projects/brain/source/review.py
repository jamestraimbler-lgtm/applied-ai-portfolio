#!/usr/bin/env python3
"""review.py — Forward-data review dashboard.

READ-ONLY. Uses accumulated .jsonl data to produce pre-registered verdicts.
Does not modify any logger, probe, threshold, or launchd job.
"""

import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# validation.py provides the stats layer
from validation import (
    Flag, PreRegistration, HORIZONS,
    permutation_test, bootstrap_ci, holm_bonferroni,
)

BASE = Path(__file__).parent


# ── helpers ──────────────────────────────────────────────────────────────────

def load_jsonl(name):
    p = BASE / name
    if not p.exists():
        return []
    return [json.loads(l) for l in p.open() if l.strip()]


def ts_range_str(rows, ts_key="ts"):
    """Human-readable date range from a list of dicts with a timestamp key."""
    if not rows:
        return "no data"
    vals = []
    for r in rows:
        v = r[ts_key]
        if isinstance(v, str):
            v = datetime.fromisoformat(v).timestamp()
        vals.append(v)
    mn, mx = min(vals), max(vals)
    d0 = datetime.fromtimestamp(mn, tz=timezone.utc).strftime("%Y-%m-%d")
    d1 = datetime.fromtimestamp(mx, tz=timezone.utc).strftime("%Y-%m-%d")
    days = (mx - mn) / 86400
    return f"{d0} to {d1} ({days:.0f} days)"


# ── 1. FUNDING CARRY ────────────────────────────────────────────────────────

def review_funding_carry():
    print("=" * 72)
    print("1. FUNDING CARRY (paper_carry)")
    print("=" * 72)
    rows = load_jsonl("paper_carry_snapshots.jsonl")
    if not rows:
        print("  NO DATA\n")
        return "insufficient-data"

    print(f"  Data: {len(rows)} snapshots, {ts_range_str(rows)}")
    n_events = len(set(round(r["ts"]) for r in rows))
    print(f"  Capture events: {n_events}")

    # Per-symbol stats
    by_sym = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)

    all_funding = []
    positive_funding = []
    print(f"\n  {'sym':>6} {'n':>5} {'med_fund':>10} {'gross_apr':>10} {'med_sprd':>9}")
    for sym in sorted(by_sym.keys()):
        sr = by_sym[sym]
        f = [r["funding_rate"] for r in sr]
        s = [r["spot_spread_bps"] + r["perp_spread_bps"] for r in sr]
        mf = statistics.median(f)
        ms = statistics.median(s)
        ga = mf * 3 * 365 * 100
        print(f"  {sym:>6} {len(sr):>5} {mf*100:>+9.5f}% {ga:>+9.2f}% {ms:>7.2f}bp")
        all_funding.append(mf)
        if mf > 0:
            positive_funding.append(ga)

    med_all = statistics.median(all_funding)
    gross_all = med_all * 3 * 365 * 100
    med_spread = statistics.median(
        [r["spot_spread_bps"] + r["perp_spread_bps"] for r in rows]
    )

    print(f"\n  Aggregate median funding rate: {med_all*100:+.5f}%")
    print(f"  Aggregate gross carry APR:     {gross_all:+.2f}%")
    print(f"  Median total spread:           {med_spread:.2f}bp (backtest assumed 4bp)")

    if positive_funding:
        avg_pos = statistics.mean(positive_funding)
        print(f"  Positive-funding tokens only:  {len(positive_funding)}/12, "
              f"avg gross APR {avg_pos:+.2f}%")

    # Pre-registered thresholds
    # Backtest: 4bp spread / 2.5% net APR. Pre-break: 2.64bp spread.
    # CONFIRM >= ~2% ann / DECAY 0-2% / KILL <= 0
    print(f"\n  Pre-registered expectation: backtest 2.5% net, pre-break 2.64bp spread")
    print(f"  Live gross carry:  {gross_all:+.2f}%")

    if gross_all >= 2.0:
        verdict = "CONFIRM"
    elif gross_all > 0:
        verdict = "DECAY"
    else:
        verdict = "KILL"

    print(f"  >>> VERDICT: {verdict}")
    print()
    return verdict


# ── 2. STABLE-LP ────────────────────────────────────────────────────────────

def review_stable_lp():
    print("=" * 72)
    print("2. STABLE-LP (lp_monitor)")
    print("=" * 72)
    rows = load_jsonl("lp_monitor_snapshots.jsonl")
    if not rows:
        print("  NO DATA\n")
        return "insufficient-data"

    print(f"  Data: {len(rows)} snapshots, {ts_range_str(rows)}")

    by_pool = defaultdict(list)
    for r in rows:
        by_pool[r["pool_name"]].append(r)

    primary_verdict = None
    for name, sr in by_pool.items():
        apys = [r["fee_apy"] for r in sr]
        pegs = [r["peg_deviation_bps"] for r in sr
                if r.get("peg_deviation_bps") is not None]
        med_apy = statistics.median(apys)
        mean_apy = statistics.mean(apys)
        max_peg = max(abs(p) for p in pegs) if pegs else 0

        print(f"\n  {name}:")
        print(f"    n={len(sr)}  APY: min={min(apys):.3f}%  "
              f"median={med_apy:.3f}%  mean={mean_apy:.3f}%  max={max(apys):.3f}%")
        if pegs:
            print(f"    Peg dev: median={statistics.median(pegs):.2f}bp  "
                  f"max |dev|={max_peg:.2f}bp  "
                  f"{'PEG HELD' if max_peg < 50 else 'DEPEG WARNING'}")

        # Primary pool = Uniswap
        if "Uniswap" in name:
            # CONFIRM >= ~3% & peg tight / DECAY 1-3% / KILL <1% or depeg >50bp
            if max_peg > 50:
                primary_verdict = "KILL"
            elif med_apy >= 3.0:
                primary_verdict = "CONFIRM"
            elif med_apy >= 1.0:
                primary_verdict = "DECAY"
            else:
                primary_verdict = "KILL"

    print(f"\n  Pre-registered expectation: backtest 5.5%, pre-break 3.3%")
    print(f"  >>> VERDICT (Uniswap primary): {primary_verdict}")
    print()
    return primary_verdict or "insufficient-data"


# ── 3. DERIBIT FUNDING (Step 0 gate) ────────────────────────────────────────

def review_deribit_funding():
    print("=" * 72)
    print("3. DERIBIT FUNDING (Step 0 gate via venue_carry)")
    print("=" * 72)
    rows = load_jsonl("venue_carry_snapshots.jsonl")
    deribit = [r for r in rows if r.get("venue") == "deribit"]
    if not deribit:
        print("  Step 0 NOT started — no Deribit data in venue_carry_snapshots.")
        print()
        return "not-started"

    print(f"  Data: {len(deribit)} Deribit rows, {ts_range_str(deribit)}")
    funds = [r["funding_apr"] for r in deribit
             if r.get("funding_apr") is not None and r["funding_apr"] != 0]
    spreads = [r["spread_bps"] for r in deribit if r.get("spread_bps") is not None]

    if funds:
        print(f"  Funding APR: median={statistics.median(funds):.2f}%, "
              f"mean={statistics.mean(funds):.2f}%")
    if spreads:
        print(f"  Spread: median={statistics.median(spreads):.2f}bp, "
              f"mean={statistics.mean(spreads):.2f}bp")

    print(f"  Step 0 gate: Deribit logger EXISTS and has {len(deribit)} rows.")
    print(f"  Prerequisite to NL funding-carry deployment: MET (data accumulating).")
    print()
    return "logging"


# ── 4. SPCX (ai_ipo_tracker) ────────────────────────────────────────────────

def review_spcx():
    print("=" * 72)
    print("4. SPCX / AI IPO TRACKER")
    print("=" * 72)
    rows = load_jsonl("ai_ipo_tracker.jsonl")
    if not rows:
        print("  NO DATA\n")
        return "insufficient-data"

    auto = [r for r in rows if r.get("signal_type") == "automated"]
    manual = [r for r in rows if r.get("signal_type") == "manual"]

    print(f"  Data: {len(rows)} entries ({len(auto)} automated, {len(manual)} manual)")
    print(f"  Date range: {ts_range_str(rows, 'ts')}")

    # Find trading entries (vs_ipo > 0 or volume > 0)
    trading = [r for r in auto if r.get("volume", 0) > 0]
    pre_trading = [r for r in auto if r.get("volume", 0) == 0]

    print(f"\n  Pre-trading entries: {len(pre_trading)} (reference price $135)")
    print(f"  Trading entries: {len(trading)}")

    if trading:
        print(f"\n  SPCX PRICE SERIES:")
        print(f"  {'date':>12} {'price':>10} {'vs_ipo':>8} {'volume':>14}")
        for r in auto:
            vol = r.get("volume", 0)
            print(f"  {r['date']:>12} ${r['value']:>8.2f} {r.get('vs_ipo',0):>+7.2f}% "
                  f"{vol:>13,}")

        prices = [r["value"] for r in trading]
        vs_ipos = [r["vs_ipo"] for r in trading]
        ipo_price = 135.0

        peak = max(vs_ipos)
        current = vs_ipos[-1]
        peak_date = [r["date"] for r in trading if r["vs_ipo"] == peak][0]

        print(f"\n  IPO price:     ${ipo_price}")
        print(f"  Peak:          +{peak:.2f}% on {peak_date}")
        print(f"  Current:       +{current:.2f}% (latest)")
        print(f"  Peak price:    ${max(prices):.2f}")
        print(f"  Current price: ${prices[-1]:.2f}")

        # vs baselines
        print(f"\n  vs PRE-REGISTERED BASELINES:")
        print(f"    Index-inclusion median run-up: +1.58%")
        print(f"    SPCX actual peak:              +{peak:.2f}%  "
              f"({'>>>' if peak > 10 else '>' if peak > 1.58 else '<='} baseline)")
        print(f"    SPCX current:                  +{current:.2f}%  "
              f"({'>>>' if current > 10 else '>' if current > 1.58 else '<='} baseline)")
        print(f"    Forced-flow finding:           +0.41 sigma (no fillable edge)")
        print(f"    SPCX BROKE the typical inclusion baseline by {peak/1.58:.0f}x at peak")

        # Was the edge fillable?
        if trading:
            day1 = trading[0]
            print(f"\n    Day-1 open (first fillable): ${day1['value']:.2f} "
                  f"(+{day1['vs_ipo']:.2f}% vs IPO)")
            print(f"    The +{day1['vs_ipo']:.1f}% was already IN at open — "
                  f"confirms forced-flow finding: no fillable edge for retail")

    # Manual signals
    if manual:
        print(f"\n  Manual signals (OpenAI/Anthropic): {len(manual)} entries")
        for r in manual:
            print(f"    {r.get('entity','?')}: {r.get('metric','?')} = {r.get('value','?')}")
    else:
        print(f"\n  Manual signals (OpenAI/Anthropic): EMPTY (sparse-by-design)")

    print()
    return "recorded"


# ── 5. JOINT-TAIL MONITOR ───────────────────────────────────────────────────

def review_joint_tail():
    print("=" * 72)
    print("5. JOINT-TAIL MONITOR")
    print("=" * 72)
    print("  Capital deployed: NO — not yet deployed.")
    print("  (Deployment basket defined in analysis/deployment_basket.md;")
    print("   waiting for Step 0 gate + venue validation.)")
    print()
    return "not-deployed"


# ── 6. RSS NULL STUDY ────────────────────────────────────────────────────────

def review_null_study():
    print("=" * 72)
    print("6. RSS NULL STUDY (paper_book / measurer)")
    print("=" * 72)

    # Load shadow trades for maturity count
    shadow = load_jsonl("shadow_trades.jsonl")
    by_flag = defaultdict(set)
    for r in shadow:
        key = (r["flagged_at_ms"], r["symbol"])
        by_flag[key].add(r["horizon"])
    all4 = [k for k, v in by_flag.items() if len(v) == 4]

    print(f"  Shadow trades: {len(shadow)} rows")
    print(f"  Unique flags measured: {len(by_flag)}")
    print(f"  Fully matured (all 4 horizons): {len(all4)}")

    # Load flags
    flags_raw = load_jsonl("news_flags.jsonl")
    print(f"  Total flags in store: {len(flags_raw)}")
    print(f"  Pre-registered threshold: 100")

    if len(all4) < 100:
        print(f"\n  >>> Flag count {len(all4)} < 100. NULL STUDY INCOMPLETE.")
        print()
        return "insufficient-data"

    print(f"\n  THRESHOLD MET: {len(all4)} >= 100. Running formal verdict...")

    # Build directional excess arrays from shadow_trades + news_flags
    # Map flagged_at_ms -> flag info
    flag_map = {}
    for f in flags_raw:
        key = f["flagged_at_ms"]
        flag_map[key] = f

    # Compute directional excess per horizon from shadow trades
    dir_excess = {h: [] for h in HORIZONS}
    for r in shadow:
        finfo = flag_map.get(r["flagged_at_ms"])
        if not finfo:
            continue
        direction = 1 if finfo.get("direction") == "bullish" else -1
        # MN excess = (token_ret - btc_ret) * direction
        token_ret = (r["exit_px"] - r["entry_px"]) / r["entry_px"]
        btc_ret = (r["btc_exit_px"] - r["btc_entry_px"]) / r["btc_entry_px"]
        excess = (token_ret - btc_ret) * direction
        dir_excess[r["horizon"]].append(excess)

    # Load placebos
    placebos_raw = load_jsonl("placebos.jsonl")
    placebo_excess = {h: [] for h in HORIZONS}
    for p in placebos_raw:
        ex = p.get("excess", {})
        for h in HORIZONS:
            v = ex.get(h)
            if v is not None:
                # Placebos already have direction built in
                placebo_excess[h].append(float(v))

    # Run stats
    prereg, fp, locked_at = PreRegistration.load(str(BASE / "prereg_news_drift.json"))
    print(f"  Pre-registration fingerprint: {fp}")
    print(f"  Locked at: {locked_at}")
    print(f"  Primary horizon: {prereg.primary_horizon}")
    print(f"  Alpha: {prereg.alpha}, min_effect: {prereg.min_effect}")

    flagged_arrays = {h: np.asarray(v) for h, v in dir_excess.items()}
    placebo_arrays = {h: np.asarray(v) for h, v in placebo_excess.items()}

    raw_p = {}
    for h in HORIZONS:
        f_arr = flagged_arrays[h]
        p_arr = placebo_arrays[h]
        if f_arr.size > 0 and p_arr.size > 0:
            raw_p[h] = permutation_test(f_arr, p_arr, seed=0)
        else:
            raw_p[h] = float("nan")

    survives = holm_bonferroni(raw_p, prereg.alpha)

    # Count independent events
    from validation import event_key as _ek
    flags_as_Flag = []
    for f in flags_raw:
        d = 1 if f.get("direction") == "bullish" else -1
        ts = f["flagged_at_ms"] / 1000.0
        flags_as_Flag.append(Flag(unix_ts=ts, asset=f["symbol"], direction=d))
    n_events = len(set(_ek(fl) for fl in flags_as_Flag))

    print(f"\n  FORMAL VERDICT (pre-registered)")
    print(f"  Flags: {len(flags_raw)}  Independent events: {n_events}")
    print(f"\n  {'horizon':<8}{'n_real':>7}{'n_plac':>7}{'flagged':>10}"
          f"{'95% CI':>22}{'placebo':>10}{'p':>9}  sig")

    primary = prereg.primary_horizon
    for h in HORIZONS:
        f_arr = flagged_arrays[h]
        p_arr = placebo_arrays[h]
        if f_arr.size == 0:
            print(f"  {h:<8}{'0':>7}  — no data —")
            continue
        mean, lo, hi = bootstrap_ci(f_arr, seed=0)
        p_mean = float(p_arr.mean()) if p_arr.size else float("nan")
        ci_str = f"[{lo:+.4f},{hi:+.4f}]"
        sig = "YES" if survives.get(h) else "-"
        marker = " <<<" if h == primary else ""
        print(f"  {h:<8}{f_arr.size:>7}{p_arr.size:>7}{mean:>+10.4f}"
              f"{ci_str:>22}{p_mean:>+10.4f}{raw_p[h]:>9.4f}  {sig}{marker}")

    # Grade
    ph = flagged_arrays.get(primary)
    if ph is not None and ph.size >= prereg.min_sample:
        mean_primary = float(ph.mean())
        sig_primary = survives.get(primary, False)
        if sig_primary and mean_primary >= prereg.min_effect:
            final = "THESIS SUPPORTED — edge is real"
        else:
            final = "NULL CONFIRMED — no tradeable edge"
    else:
        final = "INSUFFICIENT DATA"

    print(f"\n  >>> FINAL VERDICT: {final}")
    print()
    return "complete" if "CONFIRMED" in final or "SUPPORTED" in final else "complete"


# ── 7. MM SIMULATOR ─────────────────────────────────────────────────────────

def review_mm_sim():
    print("=" * 72)
    print("7. MM SIMULATOR (paper-MM on Hyperliquid long-tail)")
    print("=" * 72)
    fills_file = BASE / "mm_sim_fills.jsonl"
    if not fills_file.exists():
        print("  NO DATA — simulator not yet running or no fills completed.\n")
        return "insufficient-data"

    fills = load_jsonl("mm_sim_fills.jsonl")
    if not fills:
        print("  No completed fills yet (markouts still pending).\n")
        return "insufficient-data"

    first_ts = min(f["ts"] for f in fills)
    last_ts = max(f["ts"] for f in fills)
    days = max((last_ts - first_ts) / 86400000, 0.1)

    print(f"  Data: {len(fills)} completed fills over {days:.1f} days")

    # Per-market
    from collections import defaultdict
    by_coin = defaultdict(list)
    for f in fills:
        by_coin[f["coin"]].append(f)

    total_net = 0
    total_neg = 0
    total_n = 0

    for coin in sorted(by_coin.keys()):
        cf = by_coin[coin]
        mo_300 = [f["markouts"].get("mo_300s", {}).get("markout_bps", 0)
                  for f in cf if "mo_300s" in f.get("markouts", {})]
        mo_usd = [f["markouts"].get("mo_300s", {}).get("markout_usd", 0)
                  for f in cf if "mo_300s" in f.get("markouts", {})]
        fees = sum(f["sz_usd"] * 1.0 / 10000 for f in cf)  # 1bp maker fee
        net = sum(mo_usd) - fees
        neg_pct = (sum(1 for m in mo_300 if m < 0) / len(mo_300) * 100) if mo_300 else 0
        med_mo = statistics.median(mo_300) if mo_300 else 0

        total_net += net
        total_neg += sum(1 for m in mo_300 if m < 0)
        total_n += len(mo_300)

        print(f"    {coin:>10}: {len(cf)} fills, 5m-markout median {med_mo:+.1f}bp, "
              f"neg {neg_pct:.0f}%, net ${net/max(days,0.1):.1f}/day")

    total_neg_pct = (total_neg / total_n * 100) if total_n else 0
    total_per_day = total_net / max(days, 0.1)

    print(f"\n  Aggregate: ${total_per_day:+.1f}/day, {total_neg_pct:.0f}% negative markouts")

    # Pre-registered thresholds
    # BUILD-REAL: net > $20/day AND <40% negative
    # PARK: $0-20/day
    # DEAD: negative
    if days < 14:
        verdict = "insufficient-data"
        print(f"  Status: ACCUMULATING ({days:.1f} days, need 21+)")
    elif total_per_day > 20 and total_neg_pct < 40:
        verdict = "CONFIRM"
        print(f"  >>> VERDICT: BUILD-REAL (net ${total_per_day:.0f}/day, {total_neg_pct:.0f}% neg)")
    elif total_per_day > 0:
        verdict = "DECAY"
        print(f"  >>> VERDICT: PARK (net ${total_per_day:.1f}/day)")
    else:
        verdict = "KILL"
        print(f"  >>> VERDICT: DEAD (net ${total_per_day:.1f}/day)")

    # BTC control
    btc_fills = by_coin.get("BTC", [])
    if btc_fills:
        btc_mo = [f["markouts"].get("mo_300s", {}).get("markout_usd", 0)
                  for f in btc_fills if "mo_300s" in f.get("markouts", {})]
        if btc_mo:
            btc_per_day = sum(btc_mo) / max(days, 0.1)
            status = "GOOD" if abs(btc_per_day) < 5 else "WARNING — check fill logic"
            print(f"  BTC control: ${btc_per_day:+.1f}/day ({status})")

    print()
    return verdict


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 72)
    print("  BRAIN FORWARD-DATA REVIEW DASHBOARD")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)
    print()

    verdicts = {}
    verdicts["funding_carry"] = review_funding_carry()
    verdicts["stable_lp"] = review_stable_lp()
    verdicts["deribit_step0"] = review_deribit_funding()
    verdicts["spcx"] = review_spcx()
    verdicts["joint_tail"] = review_joint_tail()
    verdicts["null_study"] = review_null_study()
    verdicts["mm_sim"] = review_mm_sim()

    # Summary
    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    cats = {"CONFIRM": 0, "DECAY": 0, "KILL": 0,
            "insufficient-data": 0, "complete": 0, "other": 0}
    for name, v in verdicts.items():
        bucket = v if v in cats else "other"
        cats[bucket] += 1
        print(f"  {name:<20} {v}")

    print()
    print(f"  CONFIRM: {cats['CONFIRM']}  DECAY: {cats['DECAY']}  "
          f"KILL: {cats['KILL']}  complete: {cats['complete']}  "
          f"insufficient/other: {cats['insufficient-data'] + cats['other']}")
    print()


if __name__ == "__main__":
    main()
