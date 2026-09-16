"""
Cross-exchange funding differential probe.

Tests: does shorting the high-funding perp + longing the low-funding perp
(same coin, different exchanges) capture a PERSISTENT differential after
2-leg cost? Or is it arbed thin / redundant with single-exchange carry?

Exchanges: Binance, Bybit, OKX — all have free public funding rate APIs.
Coins: BTC, ETH, SOL.
All exchanges use 8h funding intervals (3x/day).
"""

import json
import math
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

# ── Config ──────────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "xexch_funding_data.jsonl")
LOOKBACK_DAYS = 180  # 6 months
FUNDING_PER_DAY = 3
COST_PER_LEG_BPS = 4  # taker spread per leg (conservative)
ANNUAL_FACTOR = 365  # funding rate × 3 × 365 = annualized

COINS = [
    {"name": "BTC", "binance": "BTCUSDT", "bybit": "BTCUSDT", "okx": "BTC-USDT-SWAP"},
    {"name": "ETH", "binance": "ETHUSDT", "bybit": "ETHUSDT", "okx": "ETH-USDT-SWAP"},
    {"name": "SOL", "binance": "SOLUSDT", "bybit": "SOLUSDT", "okx": "SOL-USDT-SWAP"},
]


# ── Fetch funding rates ────────────────────────────────────────────────
def fetch_binance_funding(symbol: str, start_ms: int) -> list[dict]:
    """Binance: paginated by startTime, up to 1000 per request."""
    all_data = []
    cursor = start_ms
    while True:
        url = (
            f"https://fapi.binance.com/fapi/v1/fundingRate"
            f"?symbol={symbol}&startTime={cursor}&limit=1000"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for d in data:
            all_data.append({
                "ts": d["fundingTime"],
                "rate": float(d["fundingRate"]),
            })
        cursor = data[-1]["fundingTime"] + 1
        if len(data) < 1000:
            break
        time.sleep(0.1)
    return all_data


def fetch_bybit_funding(symbol: str, start_ms: int) -> list[dict]:
    """Bybit: paginated by endTime, newest-first, 200 per request."""
    all_data = []
    end_cursor = int(datetime.now().timestamp() * 1000)
    while True:
        url = (
            f"https://api.bybit.com/v5/market/funding/history"
            f"?category=linear&symbol={symbol}&limit=200&endTime={end_cursor}"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        result = r.json()["result"]["list"]
        if not result:
            break
        for d in result:
            ts = int(d["fundingRateTimestamp"])
            if ts < start_ms:
                all_data.sort(key=lambda x: x["ts"])
                return all_data
            all_data.append({
                "ts": ts,
                "rate": float(d["fundingRate"]),
            })
        end_cursor = int(result[-1]["fundingRateTimestamp"]) - 1
        if len(result) < 200:
            break
        time.sleep(0.1)
    all_data.sort(key=lambda x: x["ts"])
    return all_data


def fetch_okx_funding(inst_id: str, start_ms: int) -> list[dict]:
    """OKX: paginated by before (oldest timestamp), 100 per request."""
    all_data = []
    before = ""
    while True:
        url = (
            f"https://www.okx.com/api/v5/public/funding-rate-history"
            f"?instId={inst_id}&limit=100"
        )
        if before:
            url += f"&before={before}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()["data"]
        if not data:
            break
        for d in data:
            ts = int(d["fundingTime"])
            if ts < start_ms:
                all_data.sort(key=lambda x: x["ts"])
                return all_data
            all_data.append({
                "ts": ts,
                "rate": float(d["fundingRate"]),
            })
        before = data[-1]["fundingTime"]
        if len(data) < 100:
            break
        time.sleep(0.2)
    all_data.sort(key=lambda x: x["ts"])
    return all_data


# ── Align funding timestamps ───────────────────────────────────────────
def align_funding(*rate_lists) -> list[int]:
    """Find common timestamps across all rate lists (8h-aligned)."""
    sets = [set(d["ts"] for d in rl) for rl in rate_lists]
    common = sets[0]
    for s in sets[1:]:
        common &= s
    return sorted(common)


def rates_by_ts(rate_list: list[dict]) -> dict[int, float]:
    return {d["ts"]: d["rate"] for d in rate_list}


# ── Main ────────────────────────────────────────────────────────────────
def main():
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    print(f"Fetching {LOOKBACK_DAYS}d of funding rates from 3 exchanges...\n")

    # Fetch all data
    all_funding = {}  # {coin: {exchange: [{ts, rate}]}}
    for coin in COINS:
        all_funding[coin["name"]] = {}
        print(f"  {coin['name']}:")

        bn = fetch_binance_funding(coin["binance"], start_ms)
        print(f"    Binance: {len(bn)} records")
        all_funding[coin["name"]]["binance"] = bn

        bb = fetch_bybit_funding(coin["bybit"], start_ms)
        print(f"    Bybit:   {len(bb)} records")
        all_funding[coin["name"]]["bybit"] = bb

        okx = fetch_okx_funding(coin["okx"], start_ms)
        print(f"    OKX:     {len(okx)} records")
        all_funding[coin["name"]]["okx"] = okx

    # Write raw data
    with open(DATA_FILE, "w") as f:
        for coin_name, exchanges in all_funding.items():
            for exch, rates in exchanges.items():
                for r in rates:
                    f.write(json.dumps({
                        "coin": coin_name, "exchange": exch,
                        "ts": r["ts"], "rate": r["rate"],
                    }) + "\n")

    exchanges = ["binance", "bybit", "okx"]
    pairs = [("binance", "bybit"), ("binance", "okx"), ("bybit", "okx")]

    # ══ ANALYSIS ══
    print(f"\n{'=' * 74}")
    print("CROSS-EXCHANGE FUNDING DIFFERENTIAL")
    print(f"{'=' * 74}")

    all_diffs = defaultdict(list)  # for aggregate stats
    single_carry = defaultdict(list)  # for redundancy test

    for coin in COINS:
        coin_name = coin["name"]
        exch_data = all_funding[coin_name]

        print(f"\n--- {coin_name} ---\n")

        rate_maps = {exch: rates_by_ts(data) for exch, data in exch_data.items()}

        # Per-exchange average funding (use own full series)
        print(f"\n  Average funding rate (per 8h, annualized):")
        for exch in exchanges:
            rates = [d["rate"] for d in exch_data.get(exch, [])]
            if rates:
                avg = statistics.mean(rates)
                ann = avg * FUNDING_PER_DAY * ANNUAL_FACTOR * 100
                print(f"    {exch:>8}: {avg*10000:+.2f}bp per 8h  ({ann:+.1f}% ann)  n={len(rates)}")

        # PAIRWISE alignment and differentials (not 3-way)
        print(f"\n  Pairwise differential (A - B, per 8h → annualized):")
        print(f"  {'Pair':>18} {'Mean bp':>9} {'Med bp':>9} {'Ann %':>8} {'Flip%':>7} {'|Mean|bp':>9} {'n':>5}")
        print(f"  {'-' * 68}")

        for exch_a, exch_b in pairs:
            if exch_a not in exch_data or exch_b not in exch_data:
                continue
            pair_ts = align_funding(exch_data[exch_a], exch_data[exch_b])
            if len(pair_ts) < 50:
                print(f"  {exch_a}-{exch_b}: only {len(pair_ts)} common — skipping")
                continue

            diffs = [rate_maps[exch_a][ts] - rate_maps[exch_b][ts] for ts in pair_ts]
            mean_d = statistics.mean(diffs)
            med_d = statistics.median(diffs)
            abs_mean = statistics.mean(abs(d) for d in diffs)
            ann_pct = mean_d * FUNDING_PER_DAY * ANNUAL_FACTOR * 100
            flips = sum(1 for i in range(1, len(diffs)) if diffs[i] * diffs[i - 1] < 0) / max(len(diffs) - 1, 1)

            label = f"{exch_a}-{exch_b}"
            print(
                f"  {label:>18} {mean_d*10000:>+8.2f} {med_d*10000:>+8.2f} "
                f"{ann_pct:>+7.1f}% {flips:>6.0%} {abs_mean*10000:>8.2f} {len(diffs):>5}"
            )

            all_diffs[label].extend(diffs)

            # Store for redundancy test
            avg_abs = [(rate_maps[exch_a][ts] + rate_maps[exch_b][ts]) / 2 for ts in pair_ts]
            single_carry[f"{coin_name}_{label}"] = (diffs, avg_abs)

    # ══ AGGREGATE ACROSS COINS ══
    print(f"\n{'=' * 74}")
    print("AGGREGATE: all coins combined")
    print(f"{'=' * 74}\n")

    print(f"  {'Pair':>18} {'Mean bp':>9} {'|Mean|bp':>9} {'Ann % signed':>13} {'Ann % |abs|':>12} {'Flip%':>7}")
    print(f"  {'-' * 72}")
    for label, diffs in sorted(all_diffs.items()):
        mean_d = statistics.mean(diffs)
        abs_mean = statistics.mean(abs(d) for d in diffs)
        ann_signed = mean_d * FUNDING_PER_DAY * ANNUAL_FACTOR * 100
        ann_abs = abs_mean * FUNDING_PER_DAY * ANNUAL_FACTOR * 100
        flips = sum(1 for i in range(1, len(diffs)) if diffs[i] * diffs[i - 1] < 0) / max(len(diffs) - 1, 1)
        print(
            f"  {label:>18} {mean_d*10000:>+8.2f} {abs_mean*10000:>8.2f} "
            f"{ann_signed:>+12.1f}% {ann_abs:>11.1f}% {flips:>6.0%}"
        )

    # ══ 2-LEG COST TEST ══
    print(f"\n{'=' * 74}")
    print(f"COST TEST: can the differential survive 2-leg execution?")
    print(f"{'=' * 74}\n")

    entry_exit_cost = 2 * COST_PER_LEG_BPS / 10000  # 2 legs × spread
    rebalance_cost_per_flip = entry_exit_cost  # cost to flip the direction
    print(f"  Assumed cost: {COST_PER_LEG_BPS}bp per leg × 2 legs = {COST_PER_LEG_BPS*2}bp entry/exit")

    for label, diffs in sorted(all_diffs.items()):
        n = len(diffs)
        # Strategy: always be long the lower-funding, short the higher-funding
        # Each funding period: collect |diff| - but pay rebalance cost on flips
        abs_carry = sum(abs(d) for d in diffs)
        flips = sum(1 for i in range(1, n) if diffs[i] * diffs[i - 1] < 0)
        total_flip_cost = flips * rebalance_cost_per_flip
        gross = abs_carry
        net = gross - entry_exit_cost - total_flip_cost
        gross_ann = gross * FUNDING_PER_DAY * ANNUAL_FACTOR / (n / FUNDING_PER_DAY / ANNUAL_FACTOR) if n > 0 else 0
        net_ann = net * FUNDING_PER_DAY * ANNUAL_FACTOR / (n / FUNDING_PER_DAY / ANNUAL_FACTOR) if n > 0 else 0

        # Simpler: annualize directly
        days = n / FUNDING_PER_DAY
        gross_ann_pct = (abs_carry / days * ANNUAL_FACTOR) * 100 if days > 0 else 0
        cost_ann_pct = ((entry_exit_cost + total_flip_cost) / days * ANNUAL_FACTOR) * 100 if days > 0 else 0
        net_ann_pct = gross_ann_pct - cost_ann_pct

        print(
            f"  {label:>18}: gross {gross_ann_pct:+.1f}% ann  "
            f"cost {cost_ann_pct:.1f}% ann ({flips} flips)  "
            f"NET {net_ann_pct:+.1f}% ann  "
            f"{'SURVIVES' if net_ann_pct > 1.0 else 'DIES' if net_ann_pct < 0 else 'MARGINAL'}"
        )

    # ══ REDUNDANCY TEST ══
    print(f"\n{'=' * 74}")
    print("REDUNDANCY TEST: is this just 'more of the same' as single-exchange carry?")
    print(f"{'=' * 74}\n")

    for key, (diffs, avg_abs) in sorted(single_carry.items()):
        n = len(diffs)
        if n < 20:
            continue
        mx = sum(avg_abs) / n
        my = sum(diffs) / n
        sx = math.sqrt(sum((x - mx) ** 2 for x in avg_abs) / (n - 1))
        sy = math.sqrt(sum((y - my) ** 2 for y in diffs) / (n - 1))
        if sx > 0 and sy > 0:
            corr = sum((avg_abs[i] - mx) * (diffs[i] - my) for i in range(n)) / (n - 1) / (sx * sy)
        else:
            corr = 0
        print(f"  {key}: diff × avg_funding ρ = {corr:+.3f}")

    print(f"\n  High ρ = differential tracks absolute level (redundant)")
    print(f"  Low ρ  = differential is independent (potentially diversifying)")

    # ══ VERDICT ══
    print(f"\n{'=' * 74}")
    print("VERDICT")
    print(f"{'=' * 74}\n")

    # Summarize
    for label, diffs in sorted(all_diffs.items()):
        mean_d = statistics.mean(diffs)
        abs_mean = statistics.mean(abs(d) for d in diffs)
        ann_abs = abs_mean * FUNDING_PER_DAY * ANNUAL_FACTOR * 100
        flips = sum(1 for i in range(1, len(diffs)) if diffs[i] * diffs[i - 1] < 0) / max(len(diffs) - 1, 1)

        if ann_abs < 3:
            verdict = "ARBED THIN — differential too small"
        elif flips > 0.45:
            verdict = "SIGN-FLIPPING NOISE — no persistent direction"
        else:
            verdict = "PERSISTENT differential exists"

        print(f"  {label:>18}: {verdict} (|mean| {abs_mean*10000:.2f}bp, flip {flips:.0%}, {ann_abs:.1f}% ann gross)")

    print(f"\n  TAIL NOTE: cross-exchange carry adds 2-venue counterparty risk.")
    print(f"  During liquidation cascades, one exchange's perp can dislocate from")
    print(f"  the other (basis risk). The 'same underlying' assumption breaks")
    print(f"  exactly when you need it most. This is unquantifiable from funding")
    print(f"  rate data alone — it's a structural operational risk.")


if __name__ == "__main__":
    main()
