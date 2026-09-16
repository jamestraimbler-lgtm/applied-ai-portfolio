"""
measurer.py — ExcessMeasurer adapter for the validation/placebo layer.

Wraps binance_klines() into the ExcessMeasurer interface expected by
validation.py and placebo.py:

    (unix_ts, asset) -> {"1h": excess, "4h": excess, "24h": excess, "72h": excess}

where excess = (asset_return - btc_return), both derived from hourly klines.

Entry = kline[0] close, exit = kline[h] close.  Identical math for real flags
and placebos — no stored entry_price/btc_entry in this path.  That symmetry is
what makes the placebo control valid.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

from validation import HORIZONS, ExcessMeasurer

# Horizon label -> kline array index
HORIZON_INDEX: dict[str, int] = {"1h": 1, "4h": 4, "24h": 24, "72h": 72}


# --------------------------------------------------------------------------- #
# Binance pair mapping — single source of truth for both asset and BTC legs
# --------------------------------------------------------------------------- #
def _pair(symbol: str) -> str:
    return f"{symbol.upper()}USDT"


# --------------------------------------------------------------------------- #
# Raw kline fetch (reused from news_flag.py's logic, not imported to avoid
# pulling in argparse/feedparser at import time)
# --------------------------------------------------------------------------- #
def _fetch_klines(pair: str, start_ms: int | None = None, limit: int = 80) -> list:
    params: dict = {"symbol": pair, "interval": "1h", "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    r = requests.get(
        "https://api.binance.com/api/v3/klines",
        params=params,
        timeout=15,
    )
    if r.status_code != 200:
        return []
    return r.json()


_STALE_THRESHOLD_MS = 48 * 3_600_000  # 48 hours


def is_measurable(symbol: str, ref_ms: int | None = None) -> bool:
    """True if the symbol has recent klines (within 48h of ref_ms, default now).

    Uses the same _fetch_klines / _pair path as make_measurer so the entry gate
    and the measurement gate can never disagree on pair naming or API behaviour.
    """
    if ref_ms is None:
        ref_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    klines = _fetch_klines(_pair(symbol), start_ms=None, limit=2)
    if not klines:
        return False
    last_open_ms = klines[-1][0]
    return (ref_ms - last_open_ms) < _STALE_THRESHOLD_MS


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def make_measurer() -> ExcessMeasurer:
    """
    Return a measurer that computes raw excess return (asset minus BTC) at
    each horizon from Binance hourly klines.

    Klines are cached per (pair, start_ms) within one measurer instance so
    overlapping placebo/real calls don't hammer the API.
    """
    cache: dict[tuple[str, int], list] = {}

    def _klines(pair: str, start_ms: int) -> list:
        key = (pair, start_ms)
        if key not in cache:
            cache[key] = _fetch_klines(pair, start_ms)
        return cache[key]

    def measure(unix_ts: float, asset: str) -> dict[str, float | None]:
        # Floor to hour boundary so kline[0] is the candle CONTAINING the
        # flag, not the next one.  Differs from cmd_measure's spot-snapshot
        # entry by design — see CHECK 3 in commit history.
        start_ms = int(unix_ts * 1000)
        start_ms = start_ms - (start_ms % 3_600_000)
        asset_pair = _pair(asset)
        btc_pair = _pair("BTC")

        asset_kl = _klines(asset_pair, start_ms)
        btc_kl = _klines(btc_pair, start_ms)

        out: dict[str, float | None] = {}
        for h_label, h_idx in HORIZON_INDEX.items():
            # Not enough candles yet → horizon unmatured
            if len(asset_kl) <= h_idx or len(btc_kl) <= h_idx:
                out[h_label] = None
                continue

            asset_entry = float(asset_kl[0][4])   # close of flag-hour candle
            asset_exit = float(asset_kl[h_idx][4])
            btc_entry = float(btc_kl[0][4])
            btc_exit = float(btc_kl[h_idx][4])

            if asset_entry == 0 or btc_entry == 0:
                out[h_label] = None
                continue

            asset_ret = asset_exit / asset_entry - 1
            btc_ret = btc_exit / btc_entry - 1
            out[h_label] = asset_ret - btc_ret

        return out

    return measure


# --------------------------------------------------------------------------- #
# Sanity check: compare kline-derived excess to stored forward excess
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    FLAGS_LOG = "news_flags.jsonl"
    if not os.path.exists(FLAGS_LOG):
        print("No flags file found.")
        raise SystemExit(1)

    flags = [json.loads(l) for l in open(FLAGS_LOG) if l.strip()]
    if not flags:
        print("Flags file is empty.")
        raise SystemExit(1)

    # Pick the first flag
    fl = flags[0]
    print(f"Flag: {fl['symbol']} {fl['direction']}  @ {fl['flagged_at']}")
    print(f"  stored entry_price={fl['entry_price']}  btc_entry={fl.get('btc_entry')}")
    print()

    measurer = make_measurer()
    ts = fl["flagged_at_ms"] / 1000.0  # convert millis -> seconds
    result = measurer(ts, fl["symbol"])

    stored_fwd = fl.get("forward") or {}

    print(f"  {'horizon':<8} {'kline excess':>14} {'stored excess':>14}  note")
    print(f"  {'------':<8} {'------------':>14} {'------------':>14}  ----")
    for h in HORIZONS:
        kline_val = result.get(h)
        stored_val = stored_fwd.get(h, {}).get("excess_pct")

        k_str = f"{kline_val * 100:+.2f}%" if kline_val is not None else "None"
        if stored_val is not None:
            s_str = f"{stored_val:+.2f}%"
            # Flag large divergence (>1pp) if both exist
            if kline_val is not None:
                diff = abs(kline_val * 100 - stored_val)
                note = "DIVERGE" if diff > 1.0 else "ok"
            else:
                note = "kline missing"
        else:
            s_str = "(not measured)"
            note = ""

        print(f"  {h:<8} {k_str:>14} {s_str:>14}  {note}")

    print()
    print("Expected: kline-derived and stored values are same ballpark / same sign.")
    print("Small differences are normal — stored uses spot snapshot, klines use")
    print("hourly close. Large divergence would indicate a bug.")
