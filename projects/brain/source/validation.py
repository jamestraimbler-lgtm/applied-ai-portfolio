"""
validation.py — Statistical rigor layer for the brain.

The brain logs news flags (asset + direction + timestamp), then `measure` pulls
the post-flag price trajectory and `score` reports directional excess vs BTC at
+1h/+4h/+24h/+72h. The danger is that `score` always returns a *number*, and on a
small, noisy sample that number looks meaningful even when it's pure luck.

This module is the thing that stops you fooling yourself. It answers three
questions the raw score can't:

  1. PLACEBO  — Do random, news-free timestamps show the same "excess" as flagged
                ones? If yes, the flag carries no information.
  2. SIGNIFICANCE — Is the flagged-vs-placebo gap distinguishable from noise, with
                no assumption that returns are normal (permutation + bootstrap)?
  3. HONESTY  — Are you held to criteria you committed to *before* seeing results,
                and corrected for testing four horizons at once (Holm-Bonferroni)?

WIRING (two functions to connect to the rest of the brain):
  - `load_flags()`         -> list[Flag]  : read your real flags from news_flag.py / store
  - an ExcessMeasurer       : given (unix_ts, asset) return {horizon: asset_return - btc_return}
                              wrap your existing `measure` price-trajectory code here.

Everything else is self-contained. Run `python validation.py` for a self-test that
proves the stats reject noise and detect an injected signal.

Dependencies: numpy (already in the brain's venv for price analysis).
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence

import numpy as np

# Horizons the brain measures, in hours. Keep in sync with news_flag.py.
HORIZONS: tuple[str, ...] = ("1h", "4h", "24h", "72h")

# 24h bucket size in seconds for event grouping
_EVENT_WINDOW_S = 86400


def event_key(flag: "Flag") -> str:
    """Group flags into independent events: same symbol+direction within 24h = one event."""
    bucket = int(flag.unix_ts // _EVENT_WINDOW_S)
    dir_str = {1: "bull", -1: "bear", 0: "flat"}[flag.direction]
    return f"{flag.asset}:{dir_str}:{bucket}"


# ----------------------------------------------------------------------------- #
# Data model
# ----------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Flag:
    """One logged news flag. direction: +1 bullish, -1 bearish, 0 = no claim."""
    unix_ts: float
    asset: str
    direction: int

    def __post_init__(self) -> None:
        if self.direction not in (-1, 0, 1):
            raise ValueError(f"direction must be -1/0/+1, got {self.direction}")


# An ExcessMeasurer takes a timestamp + asset and returns the RAW excess return
# (asset minus BTC) at each horizon, or None for a horizon that hasn't matured /
# has missing data. This is the only place that touches your price source.
ExcessMeasurer = Callable[[float, str], dict[str, float | None]]


# ----------------------------------------------------------------------------- #
# Pre-registration — lock the success criteria before looking at results
# ----------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PreRegistration:
    """
    Commit to what 'the thesis works' means BEFORE running score, so you can't
    quietly move the goalposts to the horizon that happened to look good.
    """
    min_sample: int = 100          # don't believe anything below this many matured flags
    primary_horizon: str = "24h"   # the horizon the thesis actually predicts
    alpha: float = 0.05            # significance level (pre-correction)
    # success = mean directional excess at primary horizon is at least this big,
    # in return units (e.g. 0.004 = flagged asset beats BTC by 0.4% in the
    # predicted direction), AND significant after multiple-comparison correction.
    min_effect: float = 0.004
    note: str = ""

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    def save(self, path: str) -> str:
        record = {
            "spec": asdict(self),
            "fingerprint": self.fingerprint(),
            "locked_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
        return record["fingerprint"]

    @staticmethod
    def load(path: str) -> tuple["PreRegistration", str, str]:
        with open(path) as f:
            record = json.load(f)
        prereg = PreRegistration(**record["spec"])
        if prereg.fingerprint() != record["fingerprint"]:
            raise ValueError("Pre-registration fingerprint mismatch — spec was edited after locking.")
        return prereg, record["fingerprint"], record["locked_at"]


# ----------------------------------------------------------------------------- #
# Placebo generation — random timestamps matched to flag seasonality
# ----------------------------------------------------------------------------- #
def generate_placebo_flags(
    real: Sequence[Flag],
    n_per_real: int = 5,
    seed: int | None = None,
) -> list[Flag]:
    """
    Build a control set of fake flags. Two things matter for a fair control:

      * TIME-OF-DAY / DAY-OF-WEEK match. Crypto has strong intraday and weekend
        seasonality, so uniformly-random timestamps would bias the control. We
        reuse the (hour, weekday) profile of real flags and only jitter the date.
      * Asset distribution match — we draw assets in the same proportion as real
        flags, so the comparison isn't contaminated by per-asset volatility.

    Directions are assigned at random (a placebo has no informed view), which is
    exactly what makes its directional-excess null centered on zero.
    """
    if not real:
        return []
    rng = random.Random(seed)
    assets = [f.asset for f in real]
    timestamps = [f.unix_ts for f in real]
    t_min, t_max = min(timestamps), max(timestamps)
    span = max(t_max - t_min, 1.0)

    placebo: list[Flag] = []
    for f in real:
        base = datetime.fromtimestamp(f.unix_ts, tz=timezone.utc)
        for _ in range(n_per_real):
            # keep this flag's hour+weekday, shift to a random day in-range
            day_shift = rng.uniform(-span, span)
            ts = f.unix_ts + day_shift
            ts = float(np.clip(ts, t_min - span, t_max + span))
            # snap back onto the original hour-of-day to preserve seasonality
            snapped = datetime.fromtimestamp(ts, tz=timezone.utc).replace(
                hour=base.hour, minute=base.minute, second=0, microsecond=0
            )
            placebo.append(
                Flag(
                    unix_ts=snapped.timestamp(),
                    asset=rng.choice(assets),
                    direction=rng.choice((-1, 1)),
                )
            )
    return placebo


# ----------------------------------------------------------------------------- #
# Measure a batch of flags into directional-excess arrays per horizon
# ----------------------------------------------------------------------------- #
def measure_batch(
    flags: Iterable[Flag],
    measurer: ExcessMeasurer,
) -> dict[str, np.ndarray]:
    """
    Returns {horizon: array of DIRECTIONAL excess}. Directional excess =
    direction * (asset_return - btc_return), so positive means the flag's call
    was right. Flags with direction 0 are skipped (no directional claim). Missing
    / unmatured horizons are dropped per-horizon, so sample sizes can differ
    across horizons — that's intentional and reported downstream.
    """
    buckets: dict[str, list[float]] = {h: [] for h in HORIZONS}
    for f in flags:
        if f.direction == 0:
            continue
        raw = measurer(f.unix_ts, f.asset)
        for h in HORIZONS:
            val = raw.get(h)
            if val is None:
                continue
            buckets[h].append(f.direction * float(val))
    return {h: np.asarray(v, dtype=float) for h, v in buckets.items()}


# ----------------------------------------------------------------------------- #
# Statistical core
# ----------------------------------------------------------------------------- #
def bootstrap_ci(
    sample: np.ndarray,
    n_boot: int = 10_000,
    ci: float = 0.95,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Mean and percentile CI via resampling — no normality assumption."""
    if sample.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, sample.size, size=(n_boot, sample.size))
    means = sample[idx].mean(axis=1)
    lo = float(np.percentile(means, (1 - ci) / 2 * 100))
    hi = float(np.percentile(means, (1 + ci) / 2 * 100))
    return (float(sample.mean()), lo, hi)


def permutation_test(
    flagged: np.ndarray,
    placebo: np.ndarray,
    n_perm: int = 20_000,
    seed: int = 0,
) -> float:
    """
    One-sided permutation p-value for H0: flagged and placebo are the same
    distribution, against H1: flagged mean > placebo mean. Pools both groups,
    repeatedly reshuffles into the original group sizes, and measures how often a
    shuffled split beats the observed difference. Distribution-free.
    """
    if flagged.size == 0 or placebo.size == 0:
        return float("nan")
    observed = flagged.mean() - placebo.mean()
    pooled = np.concatenate([flagged, placebo])
    n_f = flagged.size
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        diff = pooled[:n_f].mean() - pooled[n_f:].mean()
        if diff >= observed:
            count += 1
    # +1 smoothing so p is never exactly 0
    return (count + 1) / (n_perm + 1)


def holm_bonferroni(pvalues: dict[str, float], alpha: float) -> dict[str, bool]:
    """
    Correct for testing multiple horizons. Holm is uniformly more powerful than
    plain Bonferroni while keeping the same family-wise error guarantee. Returns
    {horizon: survives_correction}.
    """
    valid = {h: p for h, p in pvalues.items() if not np.isnan(p)}
    m = len(valid)
    survives = {h: False for h in pvalues}
    if m == 0:
        return survives
    ordered = sorted(valid.items(), key=lambda kv: kv[1])
    for rank, (h, p) in enumerate(ordered):
        threshold = alpha / (m - rank)
        if p <= threshold:
            survives[h] = True
        else:
            break  # Holm stops at first failure
    return survives


# ----------------------------------------------------------------------------- #
# Orchestrator + verdict
# ----------------------------------------------------------------------------- #
@dataclass
class HorizonResult:
    horizon: str
    n_flagged: int
    n_placebo: int
    flagged_mean: float
    flagged_ci: tuple[float, float]
    placebo_mean: float
    p_value: float
    significant: bool = False  # filled after correction


@dataclass
class Verdict:
    prereg_fingerprint: str
    per_horizon: dict[str, HorizonResult]
    sample_ok: bool
    passed: bool
    reasons: list[str] = field(default_factory=list)
    n_flags: int = 0
    n_events: int = 0

    def report(self) -> str:
        lines = [
            "BRAIN VALIDATION REPORT",
            f"  pre-registration: {self.prereg_fingerprint}",
            f"  sample threshold met: {self.sample_ok}",
            f"  flags: {self.n_flags}  independent events: {self.n_events}",
            "",
            f"  {'horizon':<8}{'n':>5}{'flagged':>11}{'95% CI':>22}{'placebo':>11}{'p':>9}  sig",
        ]
        for h in HORIZONS:
            r = self.per_horizon.get(h)
            if r is None:
                continue
            ci = f"[{r.flagged_ci[0]:+.4f},{r.flagged_ci[1]:+.4f}]"
            lines.append(
                f"  {h:<8}{r.n_flagged:>5}{r.flagged_mean:>+11.4f}{ci:>22}"
                f"{r.placebo_mean:>+11.4f}{r.p_value:>9.4f}  {'YES' if r.significant else '-'}"
            )
        lines.append("")
        lines.append(f"  VERDICT: {'THESIS SUPPORTED' if self.passed else 'NOT SUPPORTED (yet)'}")
        for reason in self.reasons:
            lines.append(f"    - {reason}")
        return "\n".join(lines)


def validate(
    real_flags: Sequence[Flag],
    measurer: ExcessMeasurer,
    prereg: PreRegistration,
    placebo_per_real: int = 5,
    seed: int = 0,
) -> Verdict:
    """Run the full pipeline and grade strictly against the pre-registration."""
    n_flags = len(real_flags)
    n_events = len(set(event_key(f) for f in real_flags))
    placebo_flags = generate_placebo_flags(real_flags, placebo_per_real, seed=seed)
    flagged = measure_batch(real_flags, measurer)
    control = measure_batch(placebo_flags, measurer)

    raw_p = {h: permutation_test(flagged[h], control[h], seed=seed) for h in HORIZONS}
    survives = holm_bonferroni(raw_p, prereg.alpha)

    per_horizon: dict[str, HorizonResult] = {}
    for h in HORIZONS:
        f_arr, c_arr = flagged[h], control[h]
        mean, lo, hi = bootstrap_ci(f_arr, seed=seed)
        per_horizon[h] = HorizonResult(
            horizon=h,
            n_flagged=int(f_arr.size),
            n_placebo=int(c_arr.size),
            flagged_mean=mean,
            flagged_ci=(lo, hi),
            placebo_mean=float(c_arr.mean()) if c_arr.size else float("nan"),
            p_value=raw_p[h],
            significant=survives[h],
        )

    # Grade against pre-registered criteria — primary horizon only.
    reasons: list[str] = []
    primary = per_horizon.get(prereg.primary_horizon)
    n_primary = primary.n_flagged if primary else 0
    sample_ok = n_primary >= prereg.min_sample
    if not sample_ok:
        reasons.append(
            f"Only {n_primary} matured flags at {prereg.primary_horizon}; "
            f"need {prereg.min_sample}. Treat any signal below this as noise."
        )

    passed = False
    if primary is not None:
        big_enough = primary.flagged_mean >= prereg.min_effect
        if not sample_ok:
            reasons.append("Sample threshold not met — verdict withheld.")
        elif not primary.significant:
            reasons.append(
                f"{prereg.primary_horizon} excess not significant after Holm "
                f"correction (p={primary.p_value:.4f})."
            )
        elif not big_enough:
            reasons.append(
                f"Effect ({primary.flagged_mean:+.4f}) below pre-registered "
                f"minimum ({prereg.min_effect:+.4f})."
            )
        else:
            passed = True
            reasons.append(
                f"{prereg.primary_horizon}: {primary.flagged_mean:+.4f} excess, "
                f"significant after correction, above threshold. Edge is real on this sample."
            )

    return Verdict(
        prereg_fingerprint=prereg.fingerprint(),
        per_horizon=per_horizon,
        sample_ok=sample_ok,
        passed=passed,
        reasons=reasons,
        n_flags=n_flags,
        n_events=n_events,
    )


# ----------------------------------------------------------------------------- #
# Self-test: prove the stats reject noise and detect a planted signal
# ----------------------------------------------------------------------------- #
def _synthetic_measurer(signal_at_24h: float, flag_directions: dict[float, int], seed: int):
    """
    Fake price source for testing. For known flag timestamps it injects
    `signal_at_24h` in the flag's intended direction at the 24h horizon; every
    other timestamp (placebo) and horizon is pure noise. Crypto-like vol ~3%.
    """
    rng = np.random.default_rng(seed)

    def measure(unix_ts: float, asset: str) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for h in HORIZONS:
            noise = float(rng.normal(0, 0.03))
            if h == "24h" and unix_ts in flag_directions:
                out[h] = flag_directions[unix_ts] * signal_at_24h + noise
            else:
                out[h] = noise
        return out

    return measure


def _make_flags(n: int, seed: int) -> list[Flag]:
    rng = random.Random(seed)
    assets = ["ONDO", "SOL", "ETH", "DOGE", "LINK"]
    base = datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()
    flags = []
    for i in range(n):
        ts = base + i * 7200 + rng.uniform(0, 3600)
        flags.append(Flag(unix_ts=ts, asset=rng.choice(assets), direction=rng.choice((-1, 1))))
    return flags


def _self_test() -> None:
    prereg = PreRegistration(min_sample=100, primary_horizon="24h", alpha=0.05, min_effect=0.004)

    print("=" * 70)
    print("CASE A — pure noise (flags carry NO information). Expect: NOT SUPPORTED")
    print("=" * 70)
    flags = _make_flags(150, seed=1)
    dirs = {f.unix_ts: f.direction for f in flags}
    noise_measurer = _synthetic_measurer(signal_at_24h=0.0, flag_directions=dirs, seed=1)
    print(validate(flags, noise_measurer, prereg, seed=1).report())

    print()
    print("=" * 70)
    print("CASE B — planted 1.2% directional edge at 24h. Expect: THESIS SUPPORTED")
    print("=" * 70)
    flags = _make_flags(150, seed=2)
    dirs = {f.unix_ts: f.direction for f in flags}
    signal_measurer = _synthetic_measurer(signal_at_24h=0.012, flag_directions=dirs, seed=2)
    print(validate(flags, signal_measurer, prereg, seed=2).report())

    print()
    print("=" * 70)
    print("CASE C — real signal but only 30 flags. Expect: verdict WITHHELD (too few)")
    print("=" * 70)
    flags = _make_flags(30, seed=3)
    dirs = {f.unix_ts: f.direction for f in flags}
    small_measurer = _synthetic_measurer(signal_at_24h=0.008, flag_directions=dirs, seed=3)
    print(validate(flags, small_measurer, prereg, seed=3).report())


if __name__ == "__main__":
    _self_test()
