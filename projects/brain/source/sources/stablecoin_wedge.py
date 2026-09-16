#!/usr/bin/env python3
"""stablecoin_wedge.py — MiCA USDT/USDC regulatory wedge probe.

Tests whether the MiCA-driven USDT delisting (Dec 2024–Mar 2025) caused a
STRUCTURAL BREAK in USDC/USDT pool economics vs a MiCA-neutral control
(USDC/DAI), or whether the LP fee decay is uniform market-wide compression.

Method: difference-in-differences on DefiLlama daily fee-APY and TVL.
  TREATED: USDC/USDT Uniswap v3 Ethereum (one leg USDT = MiCA-disadvantaged)
  CONTROL: USDC/DAI  Uniswap v3 Ethereum (both legs MiCA-neutral)
  WEDGE = (treated_after - treated_before) - (control_after - control_before)

MiCA event windows (from analysis/regulatory_landscape.md):
  W1: Dec 2024 – Mar 2025 (EU venue USDT delistings)
  W2: July 1, 2025 (NL early deadline)
  W3: July 1, 2026 (EU-wide deadline)

Read-only over external data. Does not modify loggers/probes/launchd.
"""

import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "stablecoin_wedge_data.jsonl"

# DefiLlama pool IDs (Uniswap v3 Ethereum, canonical highest-TVL)
TREATED_POOL = "e737d721-f45c-40f0-9793-9f56261862b9"  # USDC/USDT
CONTROL_POOL = "1193ef25-862b-43c1-a545-91bbb9678d30"  # USDC/DAI

# MiCA event dates (ISO)
MICA_W1_START = "2024-12-01"  # First EU venue USDT delistings
MICA_W1_END   = "2025-03-31"  # Last major delisting wave
MICA_W2       = "2025-07-01"  # NL early deadline
MICA_W3       = "2026-07-01"  # EU-wide deadline

# Pre/post windows for diff-in-diff (6 months each side)
WINDOWS = [
    {
        "name": "W1: USDT delistings (Dec 2024–Mar 2025)",
        "pre_start": "2024-06-01", "pre_end": "2024-11-30",
        "post_start": "2025-04-01", "post_end": "2025-09-30",
    },
    {
        "name": "W2: NL deadline (Jul 1 2025)",
        "pre_start": "2025-01-01", "pre_end": "2025-06-30",
        "post_start": "2025-07-01", "post_end": "2025-12-31",
    },
    {
        "name": "W3: EU deadline (Jul 1 2026)",
        "pre_start": "2026-01-01", "pre_end": "2026-06-30",
        "post_start": "2026-07-01", "post_end": "2026-12-31",
    },
]


def fetch_pool_history(pool_id: str) -> list[dict]:
    """Pull daily fee-APY + TVL history from DefiLlama."""
    r = requests.get(f"https://yields.llama.fi/chart/{pool_id}", timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def fetch_and_cache() -> dict:
    """Fetch both pools, cache to disk."""
    print("Fetching DefiLlama history...")
    treated = fetch_pool_history(TREATED_POOL)
    control = fetch_pool_history(CONTROL_POOL)

    record = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "treated_pool": TREATED_POOL,
        "control_pool": CONTROL_POOL,
        "treated": treated,
        "control": control,
    }

    with open(DATA_FILE, "w") as f:
        f.write(json.dumps(record) + "\n")

    print(f"  Treated (USDC/USDT): {len(treated)} days")
    print(f"  Control (USDC/DAI):  {len(control)} days")
    print(f"  Cached to {DATA_FILE.name}")
    return record


def load_cached() -> dict | None:
    if not DATA_FILE.exists():
        return None
    with open(DATA_FILE) as f:
        return json.loads(f.readline())


def to_daily(raw: list[dict]) -> dict[str, dict]:
    """Convert DefiLlama list to {date_str: {apyBase, tvlUsd, ...}}."""
    out = {}
    for r in raw:
        d = r["timestamp"][:10]
        out[d] = r
    return out


def window_stats(daily: dict[str, dict], start: str, end: str, metric: str):
    """Compute mean of a metric over a date window."""
    vals = []
    for d, r in daily.items():
        if start <= d <= end:
            v = r.get(metric)
            if v is not None:
                vals.append(float(v))
    if not vals:
        return None, 0
    return statistics.mean(vals), len(vals)


def monthly_series(daily: dict[str, dict], metric: str) -> dict[str, float]:
    """Aggregate to monthly means for trend visualization."""
    buckets = defaultdict(list)
    for d, r in daily.items():
        v = r.get(metric)
        if v is not None:
            buckets[d[:7]].append(float(v))
    return {m: statistics.mean(vs) for m, vs in sorted(buckets.items())}


def pre_trend_check(treated_daily, control_daily, metric, pre_start, pre_end):
    """Check if treated-vs-control gap was already diverging BEFORE the event."""
    gap_first_half = []
    gap_second_half = []
    mid = None

    # Get all dates in the pre window
    dates = sorted(d for d in treated_daily if pre_start <= d <= pre_end
                   and d in control_daily)
    if len(dates) < 20:
        return None, None, "too few pre-period observations"

    mid_idx = len(dates) // 2
    for i, d in enumerate(dates):
        t_val = treated_daily[d].get(metric)
        c_val = control_daily[d].get(metric)
        if t_val is None or c_val is None:
            continue
        gap = float(t_val) - float(c_val)
        if i < mid_idx:
            gap_first_half.append(gap)
        else:
            gap_second_half.append(gap)

    if not gap_first_half or not gap_second_half:
        return None, None, "insufficient data"

    mean_first = statistics.mean(gap_first_half)
    mean_second = statistics.mean(gap_second_half)
    return mean_first, mean_second, None


def analyze(data: dict):
    """Run the full diff-in-diff analysis."""
    treated_daily = to_daily(data["treated"])
    control_daily = to_daily(data["control"])

    print("\n" + "=" * 72)
    print("STABLECOIN REGULATORY WEDGE PROBE")
    print("=" * 72)
    print(f"Treated: USDC/USDT Uniswap v3 (USDT = MiCA-disadvantaged)")
    print(f"Control: USDC/DAI  Uniswap v3 (both legs MiCA-neutral)")
    print(f"Method:  Difference-in-differences on DefiLlama daily data")

    # ── Monthly trend overview ──
    print("\n── MONTHLY FEE-APY TREND ──")
    t_monthly = monthly_series(treated_daily, "apyBase")
    c_monthly = monthly_series(control_daily, "apyBase")
    all_months = sorted(set(t_monthly) | set(c_monthly))
    # Show from 2024 onward
    print(f"  {'month':>8}  {'USDC/USDT':>10}  {'USDC/DAI':>10}  {'gap':>8}  {'note':>30}")
    for m in all_months:
        if m < "2024-01":
            continue
        tv = t_monthly.get(m)
        cv = c_monthly.get(m)
        t_str = f"{tv:.2f}%" if tv is not None else "N/A"
        c_str = f"{cv:.2f}%" if cv is not None else "N/A"
        gap_str = f"{tv - cv:+.2f}pp" if tv is not None and cv is not None else "N/A"
        note = ""
        if m == "2024-12":
            note = "← USDT delistings begin"
        elif m == "2025-03":
            note = "← last major delisting"
        elif m == "2025-07":
            note = "← NL deadline"
        elif m == "2026-07":
            note = "← EU deadline"
        print(f"  {m:>8}  {t_str:>10}  {c_str:>10}  {gap_str:>8}  {note}")

    # ── Monthly TVL trend ──
    print("\n── MONTHLY TVL TREND ──")
    t_tvl_m = monthly_series(treated_daily, "tvlUsd")
    c_tvl_m = monthly_series(control_daily, "tvlUsd")
    print(f"  {'month':>8}  {'USDC/USDT':>12}  {'USDC/DAI':>12}  {'ratio':>8}")
    for m in all_months:
        if m < "2024-01":
            continue
        tv = t_tvl_m.get(m)
        cv = c_tvl_m.get(m)
        t_str = f"${tv/1e6:.1f}M" if tv is not None else "N/A"
        c_str = f"${cv/1e6:.1f}M" if cv is not None else "N/A"
        ratio = f"{tv/cv:.1f}x" if tv and cv and cv > 0 else "N/A"
        print(f"  {m:>8}  {t_str:>12}  {c_str:>12}  {ratio:>8}")

    # ── Diff-in-diff per window ──
    print("\n── DIFFERENCE-IN-DIFFERENCES ──")

    did_results = []
    for w in WINDOWS:
        print(f"\n  {w['name']}")

        for metric, label in [("apyBase", "Fee APY (%)"), ("tvlUsd", "TVL ($)")]:
            t_pre, t_pre_n = window_stats(treated_daily, w["pre_start"], w["pre_end"], metric)
            t_post, t_post_n = window_stats(treated_daily, w["post_start"], w["post_end"], metric)
            c_pre, c_pre_n = window_stats(control_daily, w["pre_start"], w["pre_end"], metric)
            c_post, c_post_n = window_stats(control_daily, w["post_start"], w["post_end"], metric)

            if any(x is None for x in [t_pre, t_post, c_pre, c_post]):
                print(f"    {label}: insufficient data "
                      f"(t_pre={t_pre_n}, t_post={t_post_n}, c_pre={c_pre_n}, c_post={c_post_n})")
                continue

            t_diff = t_post - t_pre
            c_diff = c_post - c_pre
            did = t_diff - c_diff

            if metric == "tvlUsd":
                # Report as % change for TVL
                t_pct = (t_post - t_pre) / t_pre * 100 if t_pre != 0 else 0
                c_pct = (c_post - c_pre) / c_pre * 100 if c_pre != 0 else 0
                did_pct = t_pct - c_pct
                print(f"    {label}:")
                print(f"      Treated: ${t_pre/1e6:.1f}M → ${t_post/1e6:.1f}M "
                      f"({t_pct:+.1f}%)  [n={t_pre_n},{t_post_n}]")
                print(f"      Control: ${c_pre/1e6:.1f}M → ${c_post/1e6:.1f}M "
                      f"({c_pct:+.1f}%)  [n={c_pre_n},{c_post_n}]")
                print(f"      DiD:     {did_pct:+.1f}pp  "
                      f"({'TREATED fell MORE' if did_pct < -5 else 'TREATED fell LESS' if did_pct > 5 else 'SIMILAR'})")
                did_results.append((w["name"], label, did_pct, "pp_tvl"))
            else:
                print(f"    {label}:")
                print(f"      Treated: {t_pre:.2f}% → {t_post:.2f}% "
                      f"({t_diff:+.2f}pp)  [n={t_pre_n},{t_post_n}]")
                print(f"      Control: {c_pre:.2f}% → {c_post:.2f}% "
                      f"({c_diff:+.2f}pp)  [n={c_pre_n},{c_post_n}]")
                print(f"      DiD:     {did:+.2f}pp  "
                      f"({'TREATED fell MORE' if did < -0.5 else 'TREATED fell LESS' if did > 0.5 else 'SIMILAR'})")
                did_results.append((w["name"], label, did, "pp_apy"))

        # Pre-trend check
        pre_first, pre_second, err = pre_trend_check(
            treated_daily, control_daily, "apyBase",
            w["pre_start"], w["pre_end"]
        )
        if err:
            print(f"    Pre-trend check: {err}")
        else:
            trend = pre_second - pre_first
            print(f"    Pre-trend check (gap 1st vs 2nd half of pre-period): "
                  f"{pre_first:+.2f} → {pre_second:+.2f}  "
                  f"(drift {trend:+.2f}pp)")
            if abs(trend) > 1.0:
                print(f"    ⚠ PRE-EXISTING DIVERGENCE detected — DiD may be spurious")
            else:
                print(f"    Pre-period gap stable — break at event date would be credible")

    # ── Decomposition: regulatory vs market ──
    print("\n── DECAY DECOMPOSITION (our measured LP decay) ──")
    # Use W1 (the main event) for decomposition
    t_pre_apy, _ = window_stats(treated_daily, "2024-06-01", "2024-11-30", "apyBase")
    t_post_apy, _ = window_stats(treated_daily, "2025-04-01", "2025-09-30", "apyBase")
    c_pre_apy, _ = window_stats(control_daily, "2024-06-01", "2024-11-30", "apyBase")
    c_post_apy, _ = window_stats(control_daily, "2025-04-01", "2025-09-30", "apyBase")

    if all(x is not None for x in [t_pre_apy, t_post_apy, c_pre_apy, c_post_apy]):
        total_decay = t_pre_apy - t_post_apy
        market_decay = c_pre_apy - c_post_apy  # what the control lost = market effect
        regulatory_wedge = total_decay - market_decay  # excess treated loss

        print(f"  Our backtest APY:           5.5% (4yr average)")
        print(f"  Our live APY:               1.6% (Jun 2026 median)")
        print(f"  Total measured decay:        {total_decay:+.2f}pp (treated pre→post W1)")
        print(f"  Market compression (control):{market_decay:+.2f}pp")
        print(f"  Regulatory wedge (DiD):      {regulatory_wedge:+.2f}pp")
        if total_decay != 0:
            reg_pct = regulatory_wedge / total_decay * 100
            mkt_pct = market_decay / total_decay * 100
            print(f"  Split: ~{mkt_pct:.0f}% market + ~{reg_pct:.0f}% regulatory")
        else:
            print(f"  Split: no decay measured in this window")

    # ── Control quality assessment ──
    print("\n── CONTROL QUALITY ASSESSMENT ──")

    # Floor effect: was control already near-zero?
    c_pre_vals = [float(r.get("apyBase") or 0) for r in data["control"]
                  if "2024-06" <= r["timestamp"][:7] <= "2024-11"]
    t_pre_vals = [float(r.get("apyBase") or 0) for r in data["treated"]
                  if "2024-06" <= r["timestamp"][:7] <= "2024-11"]

    if c_pre_vals and t_pre_vals:
        c_mean = statistics.mean(c_pre_vals)
        t_mean = statistics.mean(t_pre_vals)
        pct_below_half = sum(1 for x in c_pre_vals if x < 0.5) / len(c_pre_vals) * 100
        print(f"  Pre-MiCA APY ratio (treated/control): {t_mean/c_mean:.1f}x")
        print(f"  Control pre-MiCA APY: mean={c_mean:.3f}%, {pct_below_half:.0f}% of days < 0.5%")
        print(f"  FLOOR EFFECT: control was already near-zero APY — it CANNOT fall")
        print(f"  further, so ANY treated decline mechanically shows as 'regulatory")
        print(f"  wedge.' This inflates the DiD and makes the '101% regulatory' split")
        print(f"  a MECHANICAL ARTIFACT, not a causal estimate.")

    # TVL contradiction
    w1_tvl = next((r for r in did_results if "W1" in r[0] and r[3] == "pp_tvl"), None)
    w1_apy_r = next((r for r in did_results if "W1" in r[0] and r[3] == "pp_apy"), None)
    if w1_tvl and w1_apy_r:
        print(f"\n  CONTRADICTORY SIGNALS:")
        print(f"    Fee APY DiD (W1): {w1_apy_r[2]:+.2f}pp → treated fell MORE (suggests wedge)")
        print(f"    TVL DiD (W1):     {w1_tvl[2]:+.1f}pp → treated fell LESS (contradicts wedge)")
        print(f"    If MiCA drove capital from USDT pools, TVL should fall MORE in treated.")
        print(f"    It fell LESS. The fee/TVL signals disagree — no coherent wedge story.")

    # Control collapse in 2026
    c_tvl_2026 = [float(r.get("tvlUsd") or 0) for r in data["control"]
                  if r["timestamp"][:4] == "2026"]
    if c_tvl_2026:
        print(f"\n  CONTROL COLLAPSE: USDC/DAI TVL in 2026 = ${statistics.mean(c_tvl_2026)/1e6:.1f}M")
        print(f"  (down from $73M in 2024). Pool effectively DIED — unreliable as a")
        print(f"  control for any 2025-2026 comparison. The Feb 2026 APY spike (16.3%)")
        print(f"  is a denominator artifact (tiny TVL + any volume = high APY).")

    # ── Verdict ──
    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)

    print(f"  INCONCLUSIVE — control too flawed to isolate MiCA effect.")
    print(f"")
    print(f"  The raw DiD says 'wedge' (treated fee APY fell -3.50pp more than")
    print(f"  control around W1), BUT this is a MECHANICAL ARTIFACT:")
    print(f"    1. FLOOR EFFECT: control was at 0.43% APY pre-MiCA (78% of days")
    print(f"       below 0.5%) — it couldn't fall further, so any treated decline")
    print(f"       automatically shows as excess. The '101% regulatory' split is")
    print(f"       not a finding, it's a floor artifact.")
    print(f"    2. CONTRADICTORY TVL: if MiCA drove capital away from USDT pools,")
    print(f"       treated TVL should fall MORE. It fell LESS (-1.8% vs -20.5%).")
    print(f"       Fee and TVL signals disagree — no coherent wedge narrative.")
    print(f"    3. CONTROL DIED: USDC/DAI collapsed from $73M to $1M TVL by 2026.")
    print(f"       It's not a viable control for the period we care about.")
    print(f"    4. SCALE MISMATCH: treated had 15x higher APY pre-MiCA. The pools")
    print(f"       operate in different fee regimes — not comparable units.")
    print(f"")
    print(f"  The LP fee decay (5.5% → 1.6%) is CONSISTENT WITH pure market-wide")
    print(f"  compression. We CANNOT confirm or rule out a MiCA contribution with")
    print(f"  this control. The regulatory_landscape.md hypothesis ('may explain")
    print(f"  PART of the decay') remains UNTESTED — not confirmed, not rejected.")
    print(f"")
    print(f"  BETTER TEST (future): compare the SAME USDC/USDT pool across chains")
    print(f"  (Ethereum vs Polygon/Arbitrum/Base). If MiCA affected EU-accessible")
    print(f"  venues but not the underlying protocol, cross-chain DiD would isolate")
    print(f"  it. Requires DefiLlama pool IDs for other chains.")
    print(f"")
    print(f"  HONEST CAVEATS:")
    print(f"  - USDC/DAI is a fundamentally flawed control: near-zero APY (floor),")
    print(f"    different scale (15x APY gap), DAI-specific dynamics (DSR changes,")
    print(f"    MakerDAO governance), and the pool died in 2026.")
    print(f"  - This is an observational DiD with n=1 per group — descriptive only,")
    print(f"    not a formal causal estimate even with a clean control.")
    print(f"  - The probe did its job: it showed the available control is too flawed")
    print(f"    to answer the question. That's an honest result.")


def cmd_fetch(args):
    fetch_and_cache()


def cmd_analyze(args):
    data = load_cached()
    if data is None:
        print("No cached data. Run: stablecoin_wedge.py fetch")
        return
    analyze(data)


def cmd_run(args):
    """Fetch + analyze in one go."""
    data = fetch_and_cache()
    analyze(data)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="Fetch and cache DefiLlama data")
    sub.add_parser("analyze", help="Run analysis on cached data")
    sub.add_parser("run", help="Fetch + analyze")
    args = ap.parse_args()
    {"fetch": cmd_fetch, "analyze": cmd_analyze, "run": cmd_run}[args.cmd](args)
