"""
placebo.py — capture the control set on the same cadence as real flags.

Why capture now instead of generating placebos later: the verdict is only
meaningful if placebo timestamps run through the IDENTICAL price path as real
flags — same source, same return windows, same BTC benchmark. Generating the
control retroactively risks pulling from a different data window (source gaps,
retention limits, an API that changed). Capturing as flags are logged locks in
identical provenance and builds the control's history in parallel, so when real
flags mature you already have a matched control instead of a scramble.

A placebo answers: "if I'd flagged this same asset at a random NON-news time,
would I have seen the same excess?" So each placebo is matched to its real flag
on asset and hour-of-day (to control crypto's intraday/weekend seasonality),
placed on a random earlier day, with a random direction (no informed view — that
is what makes the control's directional-excess null sit at zero).

Two entry points:
  - on_flag_logged(flag): call right after a real flag is persisted. Writes K
    matched placebos to the placebo store, unmeasured.
  - measure_due_placebos(measurer): like your real measure loop — finds placebos
    whose horizons have matured and records directional excess via the SAME
    measurer you use for real flags. Idempotent: only fills gaps.

Then load_placebo_excess() returns arrays in the exact shape validation.py's
stats consume, so the captured control plugs straight into the verdict.

Depends on validation.py (Flag, HORIZONS) and brain_status.py (HORIZON_SECONDS).
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone

import numpy as np

from validation import Flag, HORIZONS, ExcessMeasurer
from brain_status import HORIZON_SECONDS

PLACEBO_STORE = os.environ.get("BRAIN_PLACEBO_STORE", "placebos.jsonl")
PLACEBOS_PER_FLAG = 5

# Longest measured horizon (72h) + 1h buffer. A placebo candidate within
# this distance of ANY same-asset real flag is rejected, so the control
# window can neither contain a news moment nor sit inside another flag's
# drift window.
DRIFT_WINDOW_S = 73 * 3_600.0


# ----------------------------------------------------------------------------- #
# Capture
# ----------------------------------------------------------------------------- #
def matched_placebos(
    flag: Flag,
    k: int = PLACEBOS_PER_FLAG,
    lookback_days: float = 30.0,
    min_gap_hours: float = 6.0,
    seed: int | None = None,
    avoid_ts: tuple[float, ...] = (),
) -> list[Flag]:
    """
    Generate k control timestamps for one real flag: same asset, same hour-of-day,
    a random earlier day within lookback_days, random direction. Earlier (not
    later) so the control has price data immediately and matures fast — the
    bottleneck is sample size, and past non-news points are a valid matched
    control for a forward +Nh return.
    """
    base = datetime.fromtimestamp(flag.unix_ts, tz=timezone.utc)
    rng = random.Random(seed if seed is not None else int(flag.unix_ts))
    out: list[Flag] = []
    attempts = 0
    while len(out) < k and attempts < k * 60:
        attempts += 1
        day_offset = rng.uniform(1.0, lookback_days)
        cand = flag.unix_ts - day_offset * 86_400.0
        snapped = datetime.fromtimestamp(cand, tz=timezone.utc).replace(
            hour=base.hour, minute=base.minute, second=0, microsecond=0
        )
        cand_ts = snapped.timestamp()
        # keep the control clear of the news moment itself
        if abs(cand_ts - flag.unix_ts) < min_gap_hours * 3_600.0:
            continue
        # keep the control clear of EVERY same-asset news event's drift window
        if any(abs(cand_ts - t) < DRIFT_WINDOW_S for t in avoid_ts):
            continue
        out.append(Flag(unix_ts=cand_ts, asset=flag.asset, direction=rng.choice((-1, 1))))
    return out


def on_flag_logged(flag: Flag, store_path: str = PLACEBO_STORE,
                   k: int = PLACEBOS_PER_FLAG,
                   avoid_ts: tuple[float, ...] = ()) -> int:
    """Call right after persisting a real flag. Appends k matched placebos. Returns count written."""
    placebos = matched_placebos(flag, k=k, avoid_ts=avoid_ts)
    with open(store_path, "a") as f:
        for p in placebos:
            f.write(json.dumps({
                "real_flag_ts": flag.unix_ts,
                "ts": p.unix_ts,
                "asset": p.asset,
                "direction": p.direction,
                "excess": {h: None for h in HORIZONS},  # filled by measure_due_placebos
            }) + "\n")
    return len(placebos)


# ----------------------------------------------------------------------------- #
# Measure (same pipeline as real flags)
# ----------------------------------------------------------------------------- #
def _read_rows(store_path: str) -> list[dict]:
    if not os.path.exists(store_path):
        return []
    rows = []
    with open(store_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_rows(store_path: str, rows: list[dict]) -> None:
    tmp = store_path + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, store_path)  # atomic swap so a crash can't truncate the store


def measure_due_placebos(
    measurer: ExcessMeasurer,
    store_path: str = PLACEBO_STORE,
    now: float | None = None,
) -> int:
    """
    Fill in directional excess for every placebo/horizon that has matured and
    isn't measured yet, using the SAME measurer as real flags. Idempotent.
    Returns the number of (placebo, horizon) cells newly filled.
    """
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    rows = _read_rows(store_path)
    filled = 0
    for r in rows:
        excess = r.get("excess") or {h: None for h in HORIZONS}
        # only call the price source if this row still has a matured, unfilled horizon
        due = [h for h in HORIZONS
               if excess.get(h) is None and (now - r["ts"]) >= HORIZON_SECONDS[h]]
        if not due:
            r["excess"] = excess
            continue
        raw = measurer(r["ts"], r["asset"])
        for h in due:
            val = raw.get(h)
            if val is None:
                continue
            excess[h] = r["direction"] * float(val)  # directional excess
            filled += 1
        r["excess"] = excess
    _write_rows(store_path, rows)
    return filled


def load_placebo_excess(store_path: str = PLACEBO_STORE) -> dict[str, np.ndarray]:
    """
    Return {horizon: array of measured directional excess}, matching the shape of
    validation.measure_batch() so the control plugs straight into the verdict.
    """
    rows = _read_rows(store_path)
    buckets: dict[str, list[float]] = {h: [] for h in HORIZONS}
    for r in rows:
        excess = r.get("excess") or {}
        for h in HORIZONS:
            v = excess.get(h)
            if v is not None:
                buckets[h].append(float(v))
    return {h: np.asarray(v, dtype=float) for h, v in buckets.items()}


# ----------------------------------------------------------------------------- #
# Self-test: capture placebos, measure them, prove they feed the verdict stats
# ----------------------------------------------------------------------------- #
def _self_test() -> None:
    import tempfile
    from validation import measure_batch, permutation_test, _make_flags

    # A measurer that injects a real 24h edge ONLY at real-flag timestamps.
    # Placebos sit at other (earlier, hour-matched) times, so they should see noise.
    real_flags = _make_flags(120, seed=7)
    real_dirs = {f.unix_ts: f.direction for f in real_flags}
    rng = np.random.default_rng(7)

    def measurer(ts: float, asset: str) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for h in HORIZONS:
            noise = float(rng.normal(0, 0.03))
            if h == "24h" and ts in real_dirs:
                out[h] = real_dirs[ts] * 0.012 + noise
            else:
                out[h] = noise
        return out

    store = os.path.join(tempfile.mkdtemp(), "placebos.jsonl")

    print("=" * 70)
    print("SELF-TEST — capture control on flag-log, measure via identical pipeline")
    print("=" * 70)

    # 1) capture: every real flag spawns matched placebos
    total = sum(on_flag_logged(f, store_path=store, k=5) for f in real_flags)
    print(f"captured {total} placebos for {len(real_flags)} real flags")

    # 2) measure: placebos are in the past, so all horizons are already due
    far_future = max(f.unix_ts for f in real_flags) + 10 * 86_400.0
    filled = measure_due_placebos(measurer, store_path=store, now=far_future)
    print(f"measured {filled} placebo cells")

    # idempotency: a second pass should fill nothing
    again = measure_due_placebos(measurer, store_path=store, now=far_future)
    print(f"second pass filled {again} cells (should be 0)")

    # 3) plug captured control into the verdict stats vs measured real flags
    real_excess = measure_batch(real_flags, measurer)
    placebo_excess = load_placebo_excess(store)
    p_24 = permutation_test(real_excess["24h"], placebo_excess["24h"], seed=7)
    p_1 = permutation_test(real_excess["1h"], placebo_excess["1h"], seed=7)

    print()
    print(f"  placebo 24h mean: {placebo_excess['24h'].mean():+.4f} (should sit near zero)")
    print(f"  real    24h mean: {real_excess['24h'].mean():+.4f} (planted +1.2% edge)")
    print(f"  permutation p @24h (real vs captured control): {p_24:.4f}  -> edge detected")
    print(f"  permutation p @1h  (no planted edge):           {p_1:.4f}  -> correctly null")

    assert again == 0, "measurement must be idempotent"
    assert abs(placebo_excess["24h"].mean()) < 0.01, "captured control should be ~0"
    assert p_24 < 0.01, "real-vs-control gap should be significant at 24h"
    assert p_1 > 0.05, "no edge at 1h -> should not be significant"
    print("\nchecks passed: captured placebos are clean and plug straight into the verdict.")


def cmd_shuffle(n: int = 200, seed: int = 42) -> None:
    """Null-baseline comparison: real flags vs random-timestamp flags, same measurer."""
    import statistics
    import time as _time
    from measurer import make_measurer
    from brain_status import load_flags, FLAG_STORE

    flags_raw = []
    with open(FLAG_STORE) as f:
        for line in f:
            line = line.strip()
            if line:
                flags_raw.append(json.loads(line))
    if not flags_raw:
        print("No flags to shuffle against.")
        return

    # Real flag metadata for generating matched nulls
    symbols = list({f["symbol"] for f in flags_raw})
    ts_list = [f["flagged_at_ms"] / 1000.0 for f in flags_raw]
    ts_min, ts_max = min(ts_list), max(ts_list)

    # Generate N null flags: uniform timestamp, random symbol, random direction
    rng = random.Random(seed)
    null_flags = []
    for _ in range(n):
        ts = rng.uniform(ts_min, ts_max)
        null_flags.append({
            "flagged_at_ms": ts * 1000.0,
            "symbol": rng.choice(symbols),
            "direction": rng.choice(["bullish", "bearish"]),
        })

    measurer = make_measurer()
    horizons = ["1h", "4h", "24h", "72h"]

    def score_set(flag_list):
        buckets = {h: [] for h in horizons}
        for f in flag_list:
            sign = 1 if f["direction"] == "bullish" else -1
            ts = f["flagged_at_ms"] / 1000.0
            raw = measurer(ts, f["symbol"])
            for h in horizons:
                val = raw.get(h)
                if val is not None:
                    buckets[h].append(sign * val * 100)
            _time.sleep(0.05)  # respect Binance rate limits on cache misses
        return buckets

    print(f"Scoring {len(flags_raw)} real flags vs {n} null flags (seed={seed})...")
    print(f"  symbols: {symbols}   window: {ts_max - ts_min:.0f}s")
    print()

    real_buckets = score_set(flags_raw)
    null_buckets = score_set(null_flags)

    print(f"  {'horizon':<8} {'real mean':>10} {'real med':>10} {'null mean':>10} "
          f"{'null med':>10} {'null std':>10} {'real n':>7} {'null n':>7}")
    print(f"  {'------':<8} {'--------':>10} {'--------':>10} {'--------':>10} "
          f"{'--------':>10} {'--------':>10} {'------':>7} {'------':>7}")
    for h in horizons:
        r = real_buckets[h]
        nl = null_buckets[h]
        if not r:
            print(f"  {h:<8} {'--':>10} {'--':>10} {'--':>10} {'--':>10} {'--':>10} {0:>7} {len(nl):>7}")
            continue
        r_mean = statistics.mean(r)
        r_med = statistics.median(r)
        if nl:
            n_mean = statistics.mean(nl)
            n_med = statistics.median(nl)
            n_std = statistics.stdev(nl) if len(nl) > 1 else 0.0
        else:
            n_mean = n_med = n_std = float("nan")
        print(f"  {h:<8} {r_mean:>+10.2f}% {r_med:>+10.2f}% {n_mean:>+10.2f}% "
              f"{n_med:>+10.2f}% {n_std:>10.2f}% {len(r):>7} {len(nl):>7}")

    print()
    print("  If real mean/median sit well outside null's std band, the flags carry signal.")
    print("  If they overlap, the 'edge' is indistinguishable from random timestamps.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "shuffle":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
        seed = 42
        for i, arg in enumerate(sys.argv):
            if arg == "--seed" and i + 1 < len(sys.argv):
                seed = int(sys.argv[i + 1])
        cmd_shuffle(n=n, seed=seed)
    else:
        _self_test()
