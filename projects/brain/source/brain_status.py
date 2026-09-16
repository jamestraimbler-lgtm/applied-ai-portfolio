"""
brain_status.py — honest inventory of where the brain actually stands.

Answers the one question that matters during the patient phase, in numbers
instead of vibes: how far am I from a verdict the stats will actually believe?

Reports:
  - flags logged (total)
  - flags MATURED at each horizon — enough wall-clock time has passed since the
    flag for its +Nh price to exist. A flag only counts toward a 24h verdict once
    it's been 24h since it fired.
  - predictions: resolved vs still open
  - distance to the pre-registered sample threshold at the primary horizon
  - a rate-based ETA: at your recent logging pace, when do you cross the line?

This is deliberately read-only. It never writes, never measures prices, and
never produces a score — it just counts, so you can't fool yourself into
thinking the project moved when it didn't.

WIRING: implement load_flags() and load_predictions() to read your real store.
The defaults read JSONL (one JSON object per line) and parse common field names;
point them at your news_flag.py store and adjust the field map if needed.

Depends on validation.py (Flag, HORIZONS, PreRegistration) — keep it alongside.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from validation import Flag, HORIZONS, PreRegistration

# Horizon labels -> seconds, so we can ask "has enough time passed to measure?"
HORIZON_SECONDS: dict[str, float] = {
    "1h": 3_600.0,
    "4h": 14_400.0,
    "24h": 86_400.0,
    "72h": 259_200.0,
}

# Default store locations — override via the loaders or env vars to match your brain.
FLAG_STORE = os.environ.get("BRAIN_FLAG_STORE", "news_flags.jsonl")
PREDICTION_STORE = os.environ.get("BRAIN_PREDICTION_STORE", "predictions.jsonl")


# ----------------------------------------------------------------------------- #
# Loaders — the two seams you wire to your real data
# ----------------------------------------------------------------------------- #
def _parse_ts(value) -> float | None:
    """Accept unix seconds, unix millis, or ISO-8601 and return unix seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # treat very large numbers as milliseconds
        return float(value) / 1000.0 if value > 1e11 else float(value)
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip malformed lines rather than crash the inventory
    return rows


def load_flags(path: str = FLAG_STORE) -> list[Flag]:
    """
    Read real flags from the store. Tolerant of common field names:
      timestamp: ts / timestamp / time / created / created_at
      asset:     asset / ticker / symbol / market
      direction: direction / dir / side  (+1/-1, or 'long'/'short', 'up'/'down')
    Adjust here if news_flag.py uses different names.
    """
    rows = _read_jsonl(path)
    out: list[Flag] = []
    for r in rows:
        ts = _parse_ts(_first(r, "flagged_at_ms", "ts", "timestamp", "time", "created", "created_at", "flagged_at"))
        asset = _first(r, "asset", "ticker", "symbol", "market")
        direction = _coerce_direction(_first(r, "direction", "dir", "side"))
        if ts is None or asset is None or direction is None:
            continue
        out.append(Flag(unix_ts=ts, asset=str(asset), direction=direction))
    return out


def load_predictions(path: str = PREDICTION_STORE) -> list[dict]:
    """Read predictions (e.g. Manifold). Only needs a 'resolved' signal per row."""
    return _read_jsonl(path)


def _first(row: dict, *keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _coerce_direction(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return 1 if value > 0 else (-1 if value < 0 else 0)
    s = str(value).strip().lower()
    if s in ("1", "+1", "long", "up", "bull", "bullish", "yes"):
        return 1
    if s in ("-1", "short", "down", "bear", "bearish", "no"):
        return -1
    if s in ("0", "flat", "neutral", "none"):
        return 0
    return None


def _is_resolved(row: dict) -> bool:
    # Predictions use outcome/resolved_at (not a boolean "resolved" field).
    # Treat as resolved when either is non-null.
    if row.get("outcome") is not None or row.get("resolved_at") is not None:
        return True
    val = _first(row, "resolved", "is_resolved", "resolution", "settled", "status")
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "resolved", "settled", "closed", "done")


# ----------------------------------------------------------------------------- #
# Inventory
# ----------------------------------------------------------------------------- #
@dataclass
class Inventory:
    now: float
    total_flags: int
    matured: dict[str, int]            # horizon -> count of flags old enough to measure
    directional_flags: int            # flags with a non-zero direction (the ones that count)
    total_predictions: int
    resolved_predictions: int
    flags_per_day: float              # recent logging rate
    primary_horizon: str
    threshold: int

    def need(self) -> int:
        return max(0, self.threshold - self.matured.get(self.primary_horizon, 0))

    def eta_days(self) -> float | None:
        """
        Rough days until `need` more flags have BOTH been logged and matured at the
        primary horizon. Approximate: assumes the recent logging rate continues.
        Returns None if nothing's been logged yet (no rate to extrapolate).
        """
        if self.need() == 0:
            return 0.0
        if self.flags_per_day <= 0:
            return None
        horizon_lag = HORIZON_SECONDS[self.primary_horizon] / 86_400.0
        return self.need() / self.flags_per_day + horizon_lag

    def report(self) -> str:
        lines = [
            "BRAIN STATUS — inventory only, no scoring",
            f"  as of: {datetime.fromtimestamp(self.now, tz=timezone.utc).isoformat()}",
            "",
            f"  flags logged (total):        {self.total_flags}",
            f"  flags with a direction:      {self.directional_flags}",
            "  matured (old enough to measure):",
        ]
        for h in HORIZONS:
            lines.append(f"      {h:<5} {self.matured.get(h, 0)}")
        lines.append("")
        lines.append(
            f"  predictions:                 {self.resolved_predictions} resolved "
            f"/ {self.total_predictions} total"
        )
        lines.append(f"  recent rate:                 {self.flags_per_day:.2f} flags/day")
        lines.append("")
        need = self.need()
        if need == 0 and self.total_flags > 0:
            lines.append(
                f"  THRESHOLD MET at {self.primary_horizon}: "
                f"{self.matured.get(self.primary_horizon, 0)} >= {self.threshold}. "
                f"You can run a verdict (it still has to clear significance)."
            )
        else:
            eta = self.eta_days()
            eta_str = f"~{eta:.0f} days at current rate" if eta is not None else "unknown (log some flags first)"
            lines.append(
                f"  DISTANCE TO VERDICT: need {need} more matured {self.primary_horizon} "
                f"flags ({self.matured.get(self.primary_horizon, 0)}/{self.threshold}). ETA {eta_str}."
            )
            lines.append(
                "  Until then: any score is noise. The number existing doesn't make it real."
            )
        return "\n".join(lines)


def _recent_rate(timestamps: list[float], now: float, window_days: float = 14.0) -> float:
    """Flags/day over the recent window; falls back to full-span rate if sparse."""
    if not timestamps:
        return 0.0
    window_start = now - window_days * 86_400.0
    recent = [t for t in timestamps if t >= window_start]
    if len(recent) >= 3:
        return len(recent) / window_days
    span_days = max((now - min(timestamps)) / 86_400.0, 1.0)
    return len(timestamps) / span_days


def take_inventory(
    flags: Iterable[Flag],
    predictions: Iterable[dict],
    prereg: PreRegistration,
    now: float | None = None,
) -> Inventory:
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    flags = list(flags)
    predictions = list(predictions)
    timestamps = [f.unix_ts for f in flags]

    matured = {h: 0 for h in HORIZONS}
    for f in flags:
        if f.direction == 0:
            continue  # no directional claim -> never counts toward a directional verdict
        age = now - f.unix_ts
        for h in HORIZONS:
            if age >= HORIZON_SECONDS[h]:
                matured[h] += 1

    return Inventory(
        now=now,
        total_flags=len(flags),
        matured=matured,
        directional_flags=sum(1 for f in flags if f.direction != 0),
        total_predictions=len(predictions),
        resolved_predictions=sum(1 for p in predictions if _is_resolved(p)),
        flags_per_day=_recent_rate(timestamps, now),
        primary_horizon=prereg.primary_horizon,
        threshold=prereg.min_sample,
    )


PREREG_FILE = "prereg_news_drift.json"

def main() -> None:
    if os.path.exists(PREREG_FILE):
        prereg, fp, locked_at = PreRegistration.load(PREREG_FILE)
        print(f"pre-registration: {fp} (locked {locked_at[:10]})")
    else:
        prereg = PreRegistration()  # defaults: 100 matured at 24h
        print("WARNING: no prereg file on disk — using code defaults")
    flags = load_flags()
    predictions = load_predictions()
    print(take_inventory(flags, predictions, prereg).report())


# ----------------------------------------------------------------------------- #
# Self-test: synthetic store that mirrors the brain's real situation (~10 flags)
# ----------------------------------------------------------------------------- #
def _self_test() -> None:
    import random

    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc).timestamp()
    prereg = PreRegistration(min_sample=100, primary_horizon="24h")
    rng = random.Random(0)
    assets = ["ONDO", "SOL", "ETH"]

    # 10 flags spread over the last 6 days — like the real patient-phase state.
    flags = []
    for i in range(10):
        age_days = rng.uniform(0.2, 6.0)  # some <1h old, some >72h old
        flags.append(
            Flag(
                unix_ts=now - age_days * 86_400.0,
                asset=rng.choice(assets),
                direction=rng.choice((-1, 1)),
            )
        )
    predictions = [{"resolved": i < 12} for i in range(35)]  # 12 of 35 resolved

    print("=" * 70)
    print("SELF-TEST — synthetic ~10-flag store (mirrors the real patient phase)")
    print("=" * 70)
    inv = take_inventory(flags, predictions, prereg, now=now)
    print(inv.report())
    print()
    assert inv.total_flags == 10
    assert inv.matured["1h"] >= inv.matured["72h"]  # more flags clear the short horizon
    assert inv.need() == 100 - inv.matured["24h"]
    assert inv.resolved_predictions == 12
    print("checks passed: counts and distance-to-threshold are internally consistent.")


if __name__ == "__main__":
    # If a real store exists, show it; otherwise run the self-test.
    if os.path.exists(FLAG_STORE):
        main()
    else:
        _self_test()
