"""
regime_monitor.py — Daily regime classification: "which kind of day is today,
against 2020-2026 history?"

Maps current macro/crypto indicators to percentiles of their own historical
distributions, applies pre-committed regime rules, and names the matching
playbook section in playbooks.md. DESCRIPTIVE ONLY — this module must never
output position advice, trade signals, or sizing. It answers "which playbook
page applies", nothing else.

Indicators (daily, all free/no-key sources):
  dxy   — FRED DTWEXBGS (broad dollar index)
  vix   — FRED VIXCLS
  y10   — FRED DGS10 (10Y yield, %)
  y02   — FRED DGS2  (2Y yield, %)
  btc   — Binance daily klines BTCUSDT (close)
  gold  — Yahoo v8 chart, GLD ETF
  funding — Binance fapi premiumIndex BTCUSDT (current only, accumulated)
  peg     — USDC/USDT mid deviation from 1.0 in bps (current only, accumulated)

Usage:
  regime_monitor.py snapshot   — fetch, classify today, append, alert
  regime_monitor.py report     — pretty-print last 14 snapshots
  regime_monitor.py backtest   — classify every historical day 2020-2026
"""

import bisect
import csv
import io
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────
START_DATE = "2020-01-01"
SNAPSHOTS_FILE = "regime_snapshots.jsonl"
ALERT_FILE = os.environ.get("BRAIN_ALERT_FILE", "REGIME_ALERT.txt")

FRED_SERIES = {
    "dxy": "DTWEXBGS",
    "vix": "VIXCLS",
    "y10": "DGS10",
    "y02": "DGS2",
}

PRICE_INDICATORS = {"dxy", "btc", "gold"}   # chg5d = percent change
YIELD_INDICATORS = {"y10", "y02"}            # chg5d = absolute bps
POINT_INDICATORS = {"vix"}                   # chg5d = absolute points

ACCUMULATED_MIN_N = 60  # min snapshots before percentiling funding/peg
STALE_WARN_DAYS = 5     # calendar days behind run_date before flagging a leg


# ── Regime Rules (pre-committed from crisis-episodes / dollar-stress probes) ──
REGIME_RULES = {
    "DOLLAR_SQUEEZE": {
        "severity": 1,
        "playbook": "§1 DOLLAR_SQUEEZE",
        "desc": "2022-type: DXY↑ + rates↑ + fear",
    },
    "FEAR_SPIKE": {
        "severity": 2,
        "playbook": "§2 FEAR_SPIKE",
        "desc": "Pure fear: VIX spike without dollar/rate legs",
    },
    "CRYPTO_STRESS": {
        "severity": 3,
        "playbook": "§3 CRYPTO_STRESS",
        "desc": "Exchange failure / depeg / liquidation cascade",
    },
    "RATE_SHOCK": {
        "severity": 4,
        "playbook": "§4 RATE_SHOCK",
        "desc": "Rates repricing without full squeeze",
    },
    "CALM": {
        "severity": 5,
        "playbook": "§5 CALM",
        "desc": "Normal operations",
    },
}


# ── Fetch ───────────────────────────────────────────────────────────────
def fetch_fred(series_id: str, start: str) -> dict[str, float]:
    """Download FRED daily series as {date_str: value}.
    Follows documented gotchas: explicit coed end date, filter '.' and empty."""
    end = datetime.now().strftime("%Y-%m-%d")
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&cosd={start}&coed={end}"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    result = {}
    reader = csv.reader(io.StringIO(r.text))
    next(reader)  # skip header
    for row in reader:
        if not row[1] or row[1] == ".":
            continue
        result[row[0]] = float(row[1])
    return result


def fetch_binance_daily(symbol: str, start: str) -> dict[str, float]:
    """Download Binance 1d klines as {date_str: close}. Paginates by startTime."""
    start_ms = int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000)
    result = {}
    while True:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1d",
                    "startTime": start_ms, "limit": 1000},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for bar in data:
            dt = datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc)
            result[dt.strftime("%Y-%m-%d")] = float(bar[4])  # close
        start_ms = data[-1][0] + 86_400_000
        if len(data) < 1000:
            break
        time.sleep(0.2)
    return result


def fetch_yahoo(symbol: str, start: str) -> dict[str, float]:
    """Download daily adj-close from Yahoo Finance v8."""
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


def fetch_funding() -> float | None:
    """Current BTC funding rate from Binance premiumIndex."""
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": "BTCUSDT"}, timeout=10,
        )
        if r.status_code != 200:
            return None
        return float(r.json()["lastFundingRate"])
    except Exception as e:
        print(f"  [funding] fetch error: {e}")
        return None


def fetch_peg() -> float | None:
    """USDC/USDT mid deviation from 1.0 in bps."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/bookTicker",
            params={"symbol": "USDCUSDT"}, timeout=10,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        mid = (float(d["bidPrice"]) + float(d["askPrice"])) / 2
        return (mid - 1.0) * 10_000  # bps
    except Exception as e:
        print(f"  [peg] fetch error: {e}")
        return None


# ── Alignment & Features ────────────────────────────────────────────────
def align_series(*series_dicts) -> list[str]:
    """Return sorted dates present in ALL series (inner join, no forward-fill)."""
    common = set(series_dicts[0].keys())
    for s in series_dicts[1:]:
        common &= s.keys()
    return sorted(common)


def _percentile_rank(val: float, sorted_vals: list[float]) -> float:
    """Percentile rank (0-100) using mid-rank method. sorted_vals must be pre-sorted."""
    n = len(sorted_vals)
    if n == 0:
        return 50.0
    lo = bisect.bisect_left(sorted_vals, val)
    hi = bisect.bisect_right(sorted_vals, val)
    return (lo + hi) / 2 / n * 100


def compute_features(
    dates: list[str],
    series: dict[str, dict[str, float]],
) -> dict[str, dict[str, dict]]:
    """
    Compute per-indicator features for every date from index 5 onward.
    Returns {date: {indicator: {level, chg5d, pct_level, pct_chg5d}}}.
    Percentiles are against the FULL distribution (descriptive, not predictive).
    """
    indicators = list(series.keys())

    # Build level arrays aligned to dates
    all_levels = {ind: [series[ind][d] for d in dates] for ind in indicators}

    # Compute 5-trading-day changes
    all_chg5d: dict[str, list[float]] = {}
    for ind in indicators:
        vals = all_levels[ind]
        chg = []
        for i in range(5, len(vals)):
            if ind in PRICE_INDICATORS:
                chg.append((vals[i] / vals[i - 5] - 1) * 100 if vals[i - 5] else 0.0)
            elif ind in YIELD_INDICATORS:
                chg.append((vals[i] - vals[i - 5]) * 100)  # bps
            else:  # POINT_INDICATORS
                chg.append(vals[i] - vals[i - 5])
        all_chg5d[ind] = chg

    # Pre-sort for fast percentile lookup
    sorted_levels = {ind: sorted(all_levels[ind]) for ind in indicators}
    sorted_chg5d = {ind: sorted(all_chg5d[ind]) for ind in indicators}

    result = {}
    for i in range(5, len(dates)):
        d = dates[i]
        feat = {}
        ci = i - 5  # index into chg5d arrays
        for ind in indicators:
            level = all_levels[ind][i]
            chg = all_chg5d[ind][ci]
            feat[ind] = {
                "level": round(level, 4),
                "chg5d": round(chg, 4),
                "pct_level": round(_percentile_rank(level, sorted_levels[ind]), 1),
                "pct_chg5d": round(_percentile_rank(chg, sorted_chg5d[ind]), 1),
            }
        result[d] = feat
    return result


def _compute_indicator_latest(
    data: dict[str, float], indicator: str,
) -> tuple[dict, str]:
    """Compute features for one indicator's latest date from its OWN full history.
    Returns (feature_dict_with_asof, asof_date_str). Used by snapshot mode only."""
    dates = sorted(data.keys())
    levels = [data[d] for d in dates]
    if len(dates) < 6:
        raise ValueError(f"{indicator}: need >=6 observations, got {len(dates)}")

    chg5d_all: list[float] = []
    for i in range(5, len(levels)):
        if indicator in PRICE_INDICATORS:
            chg5d_all.append((levels[i] / levels[i - 5] - 1) * 100 if levels[i - 5] else 0.0)
        elif indicator in YIELD_INDICATORS:
            chg5d_all.append((levels[i] - levels[i - 5]) * 100)  # bps
        else:
            chg5d_all.append(levels[i] - levels[i - 5])

    asof = dates[-1]
    return {
        "level": round(levels[-1], 4),
        "chg5d": round(chg5d_all[-1], 4),
        "pct_level": round(_percentile_rank(levels[-1], sorted(levels)), 1),
        "pct_chg5d": round(_percentile_rank(chg5d_all[-1], sorted(chg5d_all)), 1),
        "asof": asof,
    }, asof


# ── Classification ──────────────────────────────────────────────────────
def classify_day(
    feat: dict[str, dict],
    funding_pct: float | None = None,
    funding_raw: float | None = None,
    peg_bps: float | None = None,
) -> list[str]:
    """Apply pre-committed regime rules. Returns fired regimes, severity-ordered."""
    fired = []

    # 1. DOLLAR_SQUEEZE (severity 1)
    dollar_squeeze = (
        feat["dxy"]["pct_chg5d"] >= 90
        and (feat["y10"]["pct_chg5d"] >= 80 or feat["vix"]["pct_level"] >= 80)
    )
    if dollar_squeeze:
        fired.append("DOLLAR_SQUEEZE")

    # 2. FEAR_SPIKE (severity 2, squeeze supersedes)
    fear_spike = (
        feat["vix"]["pct_level"] >= 90 or feat["vix"]["pct_chg5d"] >= 95
    )
    if fear_spike and not dollar_squeeze:
        fired.append("FEAR_SPIKE")

    # 3. CRYPTO_STRESS (severity 3, fires independently)
    crypto_btc = feat["btc"]["pct_chg5d"] <= 5
    crypto_peg = peg_bps is not None and abs(peg_bps) >= 20
    crypto_funding = False
    if funding_pct is not None:
        crypto_funding = funding_pct <= 5
    elif funding_raw is not None:
        crypto_funding = funding_raw <= -0.0005
    if crypto_btc or crypto_peg or crypto_funding:
        fired.append("CRYPTO_STRESS")

    # 4. RATE_SHOCK (severity 4, without dollar/vix legs of squeeze)
    if feat["y10"]["pct_chg5d"] >= 95 and not dollar_squeeze:
        fired.append("RATE_SHOCK")

    # 5. CALM
    if not fired:
        fired.append("CALM")

    return fired


def _severity_of(regimes: list[str]) -> int:
    return min(REGIME_RULES[r]["severity"] for r in regimes)


def _playbook_ref(regimes: list[str]) -> str:
    if regimes == ["CALM"]:
        return "none (calm)"
    top = min(regimes, key=lambda r: REGIME_RULES[r]["severity"])
    return REGIME_RULES[top]["playbook"]


# ── Snapshots ───────────────────────────────────────────────────────────
def _read_snapshots() -> list[dict]:
    if not os.path.exists(SNAPSHOTS_FILE):
        return []
    rows = []
    with open(SNAPSHOTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _compute_streaks(
    snapshots: list[dict], regimes_today: list[str], today: str,
) -> dict[str, int]:
    """Count consecutive days each regime has fired (including today)."""
    streaks = {}
    recent = sorted(snapshots, key=lambda s: s["date"])
    for regime in regimes_today:
        if regime == "CALM":
            continue
        streak = 1  # today counts
        for snap in reversed(recent):
            if snap["date"] >= today:
                continue
            if regime in snap.get("regimes_fired", []):
                streak += 1
            else:
                break
        streaks[regime] = streak
    return streaks


# ── Commands ────────────────────────────────────────────────────────────
def _fetch_all() -> tuple[dict[str, dict[str, float]], list[str]]:
    """Fetch all historical series, inner-join on common dates. Used by BACKTEST
    only — snapshot mode computes per-indicator features independently."""
    print("Fetching indicators...")
    macro = {}
    for name, sid in FRED_SERIES.items():
        macro[name] = fetch_fred(sid, START_DATE)
        print(f"  {name} ({sid}): {len(macro[name])} obs")

    print("  btc (Binance BTCUSDT):", end=" ", flush=True)
    btc = fetch_binance_daily("BTCUSDT", START_DATE)
    print(f"{len(btc)} days")

    print("  gold (GLD Yahoo v8):", end=" ", flush=True)
    gold = fetch_yahoo("GLD", START_DATE)
    print(f"{len(gold)} days")

    all_series = {**macro, "btc": btc, "gold": gold}
    dates = align_series(*all_series.values())
    print(f"  Aligned: {len(dates)} common days ({dates[0]} to {dates[-1]})")
    return all_series, dates


def cmd_snapshot():
    """Fetch, classify today using each indicator's own freshest data, append snapshot.

    Unlike backtest (which inner-joins all series on common dates), snapshot mode
    computes each indicator from its OWN full history and latest observation.
    Crypto legs (btc/funding/peg) are real-time; FRED legs lag ~3-5 business days.
    This eliminates classification lag from the slowest source.
    """
    print("Fetching indicators...")
    raw_series: dict[str, dict[str, float]] = {}
    for name, sid in FRED_SERIES.items():
        raw_series[name] = fetch_fred(sid, START_DATE)
        print(f"  {name} ({sid}): {len(raw_series[name])} obs")

    print("  btc (Binance BTCUSDT):", end=" ", flush=True)
    raw_series["btc"] = fetch_binance_daily("BTCUSDT", START_DATE)
    print(f"{len(raw_series['btc'])} days")

    print("  gold (GLD Yahoo v8):", end=" ", flush=True)
    raw_series["gold"] = fetch_yahoo("GLD", START_DATE)
    print(f"{len(raw_series['gold'])} days")

    funding_raw = fetch_funding()
    peg_bps = fetch_peg()

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Per-indicator features from each indicator's own history (no cross-series join)
    feat: dict[str, dict] = {}
    asof_dates: dict[str, str] = {}
    for ind, data in raw_series.items():
        f, asof = _compute_indicator_latest(data, ind)
        feat[ind] = f
        asof_dates[ind] = asof

    # Funding/peg are current-value-only; asof = run_date when available
    if funding_raw is not None:
        asof_dates["funding"] = run_date
    if peg_bps is not None:
        asof_dates["peg"] = run_date

    # Staleness: how far each leg trails run_date
    run_dt = datetime.strptime(run_date, "%Y-%m-%d")
    stale_legs: dict[str, int] = {}
    max_staleness = 0
    for ind, asof in asof_dates.items():
        days_behind = (run_dt - datetime.strptime(asof, "%Y-%m-%d")).days
        max_staleness = max(max_staleness, days_behind)
        if days_behind > STALE_WARN_DAYS:
            stale_legs[ind] = days_behind

    # Funding/peg percentiles from accumulated snapshots
    existing = _read_snapshots()

    funding_pct = None
    hist_funding: list[float] = []
    if funding_raw is not None:
        hist_funding = [
            s["indicators"]["funding"]["level"]
            for s in existing
            if "funding" in s.get("indicators", {})
            and s["indicators"]["funding"].get("level") is not None
        ]
        if len(hist_funding) >= ACCUMULATED_MIN_N:
            funding_pct = _percentile_rank(funding_raw, sorted(hist_funding))

    peg_pct = None
    hist_peg: list[float] = []
    if peg_bps is not None:
        hist_peg = [
            s["indicators"]["peg"]["level"]
            for s in existing
            if "peg" in s.get("indicators", {})
            and s["indicators"]["peg"].get("level") is not None
        ]
        if len(hist_peg) >= ACCUMULATED_MIN_N:
            peg_pct = _percentile_rank(peg_bps, sorted(hist_peg))

    # Classify
    regimes = classify_day(
        feat, funding_pct=funding_pct, funding_raw=funding_raw, peg_bps=peg_bps,
    )
    sev = _severity_of(regimes)
    pref = _playbook_ref(regimes)
    # "date" is now run_date (previously was the inner-joined data date)
    streaks = _compute_streaks(existing, regimes, run_date)

    # Build indicator dict for JSONL (includes per-indicator asof)
    indicators: dict[str, dict] = {}
    for ind in feat:
        indicators[ind] = dict(feat[ind])  # already contains asof
    indicators["funding"] = {
        "level": funding_raw,
        "asof": run_date if funding_raw is not None else None,
    }
    if funding_pct is not None:
        indicators["funding"]["pct_level"] = round(funding_pct, 1)
    elif funding_raw is not None:
        indicators["funding"]["note"] = f"insufficient history (n={len(hist_funding)})"
    indicators["peg"] = {
        "level": round(peg_bps, 2) if peg_bps is not None else None,
        "asof": run_date if peg_bps is not None else None,
    }
    if peg_pct is not None:
        indicators["peg"]["pct_level"] = round(peg_pct, 1)
    elif peg_bps is not None:
        indicators["peg"]["note"] = f"insufficient history (n={len(hist_peg)})"

    snapshot = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "date": run_date,
        "run_date": run_date,
        "stale_legs": stale_legs,
        "max_staleness_days": max_staleness,
        "indicators": indicators,
        "regimes_fired": regimes,
        "severity_top": sev,
        "streaks": streaks,
        "playbook_ref": pref,
    }
    with open(SNAPSHOTS_FILE, "a") as f:
        f.write(json.dumps(snapshot) + "\n")

    # ── Human-readable stdout ──
    print(f"\n{'=' * 75}")
    print(f"REGIME MONITOR — run {run_date}")
    print(f"{'=' * 75}")
    for ind in ["dxy", "vix", "y10", "y02", "btc", "gold"]:
        f = feat[ind]
        unit = "%" if ind in PRICE_INDICATORS else ("bp" if ind in YIELD_INDICATORS else "pt")
        lvl_fmt = f"{f['level']:>10.0f}" if ind == "btc" else f"{f['level']:>10.2f}"
        print(
            f"  {ind:>5}: {lvl_fmt}  chg5d {f['chg5d']:>+8.2f}{unit:<3}"
            f"lvl_pct {f['pct_level']:>5.1f}  chg_pct {f['pct_chg5d']:>5.1f}"
            f"  asof {asof_dates[ind]}"
        )
    if funding_raw is not None:
        pct_s = f"  pct {funding_pct:.1f}" if funding_pct is not None else f"  (n<{ACCUMULATED_MIN_N})"
        print(f"  funding: {funding_raw:+.6f}{pct_s}  asof {run_date}")
    else:
        print(f"  funding: unavailable")
    if peg_bps is not None:
        pct_s = f"  pct {peg_pct:.1f}" if peg_pct is not None else f"  (n<{ACCUMULATED_MIN_N})"
        print(f"    peg: {peg_bps:+.2f} bps{pct_s}  asof {run_date}")
    else:
        print(f"    peg: unavailable")

    print()
    if regimes == ["CALM"]:
        print("  REGIMES: CALM")
    else:
        for r in regimes:
            streak_s = f" (streak: {streaks[r]}d)" if r in streaks else ""
            print(f"  REGIME: {r} — {REGIME_RULES[r]['desc']}{streak_s}")
    print(f"  PLAYBOOK: {pref}")

    if stale_legs:
        parts = [f"{ind} {d}d behind" for ind, d in sorted(stale_legs.items())]
        print(f"  [!] stale legs: {', '.join(parts)} — macro regimes may lag")

    # ── Alert file ──
    freshest = max(asof_dates.values()) if asof_dates else run_date
    if sev <= 3:
        summary = (
            f"{run_date} (data thru {freshest}): "
            f"{', '.join(r for r in regimes if r != 'CALM')}"
        )
        with open(ALERT_FILE, "w") as f:
            f.write(summary + "\n")
        print(f"\n  ALERT written to {ALERT_FILE}")
    elif os.path.exists(ALERT_FILE):
        os.remove(ALERT_FILE)
        print(f"\n  Stale alert removed from {ALERT_FILE}")


def cmd_report():
    """Pretty-print last 14 snapshots."""
    snapshots = _read_snapshots()
    if not snapshots:
        print("No snapshots yet.")
        return
    recent = sorted(snapshots, key=lambda s: s["date"])[-14:]

    print(f"\n{'=' * 70}")
    print(f"REGIME MONITOR — last {len(recent)} snapshots")
    print(f"{'=' * 70}\n")
    print(f"  {'date':>10}  {'dxy':>7} {'vix':>6} {'y10':>5} {'btc':>8} {'gold':>7}  regimes")
    print(f"  {'-' * 68}")
    for s in recent:
        ind = s.get("indicators", {})
        vals = []
        for k, w, fmt in [("dxy", 7, ".1f"), ("vix", 6, ".1f"), ("y10", 5, ".2f"),
                           ("btc", 8, ".0f"), ("gold", 7, ".1f")]:
            v = ind.get(k, {}).get("level")
            vals.append(f"{v:{w}{fmt}}" if isinstance(v, (int, float)) else f"{'?':>{w}}")
        regs = ", ".join(s.get("regimes_fired", []))
        streaks = s.get("streaks", {})
        streak_s = ""
        if streaks:
            streak_s = " (" + ", ".join(f"{r}:{d}d" for r, d in streaks.items()) + ")"
        print(f"  {s['date']:>10}  {' '.join(vals)}  {regs}{streak_s}")


def cmd_backtest():
    """Classify every historical day, report totals and longest episodes.

    Uses inner join on aligned dates BY DESIGN — historical day-by-day
    classification needs all indicators on the same date, and lag is irrelevant
    retrospectively. Do NOT unify with the snapshot path (which uses per-indicator
    freshest data to eliminate FRED lag).
    """
    all_series, dates = _fetch_all()
    features = compute_features(dates, all_series)
    classifiable = sorted(features.keys())

    print(f"  Classifiable dates (with 5d lookback): {len(classifiable)}")
    print(f"  (funding/peg legs unavailable — btc leg only for CRYPTO_STRESS)\n")

    # Classify every date
    daily: dict[str, list[str]] = {}
    for d in classifiable:
        daily[d] = classify_day(features[d])

    # ── Totals ──
    counts: dict[str, int] = defaultdict(int)
    for regs in daily.values():
        for r in regs:
            counts[r] += 1

    total = len(classifiable)
    print(f"{'=' * 70}")
    print("BACKTEST RESULTS")
    print(f"{'=' * 70}")
    print(f"\nTotal classifiable days: {total}\n")
    print(f"  {'Regime':<20} {'Days':>6} {'Share':>8}")
    print(f"  {'-' * 36}")
    for r in ["DOLLAR_SQUEEZE", "FEAR_SPIKE", "CRYPTO_STRESS", "RATE_SHOCK", "CALM"]:
        c = counts.get(r, 0)
        print(f"  {r:<20} {c:>6} {c / total * 100:>7.1f}%")

    # ── Contiguous episodes ──
    episodes = []  # (regime, start, end, days)
    for regime in ["DOLLAR_SQUEEZE", "FEAR_SPIKE", "CRYPTO_STRESS", "RATE_SHOCK"]:
        run_start = None
        run_end = None
        run_len = 0
        for d in classifiable:
            if regime in daily[d]:
                if run_start is None:
                    run_start = d
                run_end = d
                run_len += 1
            else:
                if run_start is not None:
                    episodes.append((regime, run_start, run_end, run_len))
                    run_start = None
                    run_len = 0
        if run_start is not None:
            episodes.append((regime, run_start, run_end, run_len))

    episodes.sort(key=lambda e: e[3], reverse=True)

    print(f"\n  12 longest contiguous episodes:")
    print(f"  {'Regime':<20} {'Start':>12} {'End':>12} {'Days':>6}")
    print(f"  {'-' * 54}")
    for regime, start, end, days in episodes[:12]:
        print(f"  {regime:<20} {start:>12} {end:>12} {days:>6}")

    calm_share = counts.get("CALM", 0) / total * 100
    print(f"\n  CALM share: {calm_share:.1f}% (expect >75%)")
    if calm_share < 75:
        print("  WARNING: CALM share below expected 75% — review thresholds")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: regime_monitor.py <snapshot|report|backtest>")
        return
    cmd = sys.argv[1]
    if cmd == "snapshot":
        cmd_snapshot()
    elif cmd == "report":
        cmd_report()
    elif cmd == "backtest":
        cmd_backtest()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
