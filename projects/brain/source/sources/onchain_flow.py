"""
On-chain flow probe: does stablecoin supply growth LEAD crypto price?

Tests the cleanest on-chain signal: USDT + USDC circulating supply change
(minting = new capital entering; burning = capital leaving). Better-attributed
than exchange-flow guessing (supply is unambiguous, no wallet labels needed).

THE QUESTION: does this signal LEAD price (tradeable, beats null + cost)
or move coincidentally (echo, the latency wall wins again)?

Data: DefiLlama stablecoins API (free, daily) + Binance BTC/ETH klines.
"""

import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

# ── Config ──────────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "onchain_flow_data.jsonl")
START_DATE = "2021-01-01"  # post-DeFi-summer, stablecoin data gets clean

# DefiLlama stablecoin IDs
STABLECOINS = [
    {"id": 1, "symbol": "USDT"},
    {"id": 2, "symbol": "USDC"},
]

CRYPTO_PAIRS = ["BTCUSDT", "ETHUSDT"]
COST_BPS = 15


# ── Download ────────────────────────────────────────────────────────────
def fetch_stablecoin_supply(coin_id: int) -> dict[str, float]:
    """Fetch daily circulating supply from DefiLlama."""
    url = f"https://stablecoins.llama.fi/stablecoin/{coin_id}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    tokens = data.get("tokens", [])
    result = {}
    for t in tokens:
        dt = datetime.fromtimestamp(t["date"], tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d")
        if date_str < START_DATE:
            continue
        circ = t.get("circulating", {}).get("peggedUSD", 0)
        if circ > 0:
            result[date_str] = circ
    return result


def fetch_binance_daily(symbol: str, start: str) -> dict[str, float]:
    start_ms = int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000)
    result = {}
    while True:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval=1d&startTime={start_ms}&limit=1000"
        )
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for bar in data:
            dt = datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc)
            result[dt.strftime("%Y-%m-%d")] = float(bar[4])
        start_ms = data[-1][0] + 86_400_000
        if len(data) < 1000:
            break
        time.sleep(0.2)
    return result


def align_series(*series_dicts) -> list[str]:
    common = set(series_dicts[0].keys())
    for s in series_dicts[1:]:
        common &= s.keys()
    return sorted(common)


# ── Stats ───────────────────────────────────────────────────────────────
def pearson(x, y):
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / (n - 1))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / (n - 1))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1) / (sx * sy)


# ── Main ────────────────────────────────────────────────────────────────
def main():
    # Download stablecoin supply
    print("Downloading stablecoin supply (DefiLlama)...")
    supplies = {}
    for sc in STABLECOINS:
        supplies[sc["symbol"]] = fetch_stablecoin_supply(sc["id"])
        print(f"  {sc['symbol']}: {len(supplies[sc['symbol']])} daily observations")

    # Download crypto prices
    print("\nDownloading crypto prices (Binance)...")
    prices = {}
    for pair in CRYPTO_PAIRS:
        prices[pair] = fetch_binance_daily(pair, START_DATE)
        print(f"  {pair}: {len(prices[pair])} days")

    # Align all series
    dates = align_series(*supplies.values(), *prices.values())
    print(f"\nAligned: {len(dates)} common days ({dates[0]} to {dates[-1]})")

    # Compute combined stablecoin supply
    combined = {d: sum(supplies[sc["symbol"]][d] for sc in STABLECOINS) for d in dates}

    # Write aligned data
    with open(DATA_FILE, "w") as f:
        for d in dates:
            f.write(json.dumps({
                "date": d,
                "usdt": supplies["USDT"][d],
                "usdc": supplies["USDC"][d],
                "combined": combined[d],
                "btc": prices["BTCUSDT"][d],
                "eth": prices["ETHUSDT"][d],
            }) + "\n")

    ret_dates = dates[1:]
    n = len(ret_dates)

    # Daily returns / changes
    btc_ret = [(prices["BTCUSDT"][dates[i]] - prices["BTCUSDT"][dates[i - 1]]) / prices["BTCUSDT"][dates[i - 1]]
               for i in range(1, len(dates))]
    eth_ret = [(prices["ETHUSDT"][dates[i]] - prices["ETHUSDT"][dates[i - 1]]) / prices["ETHUSDT"][dates[i - 1]]
               for i in range(1, len(dates))]

    # Stablecoin supply change (absolute and %)
    supply_chg_pct = [(combined[dates[i]] - combined[dates[i - 1]]) / combined[dates[i - 1]]
                      for i in range(1, len(dates))]
    supply_chg_abs = [(combined[dates[i]] - combined[dates[i - 1]]) / 1e9
                      for i in range(1, len(dates))]

    # 7-day smoothed supply change (reduces daily noise)
    supply_7d = []
    for i in range(len(supply_chg_pct)):
        window = supply_chg_pct[max(0, i - 6):i + 1]
        supply_7d.append(statistics.mean(window))

    print(f"\n{'=' * 70}")
    print("ON-CHAIN FLOW PROBE: STABLECOIN SUPPLY → CRYPTO PRICE?")
    print(f"{'=' * 70}")
    print(f"Period: {dates[0]} to {dates[-1]}  |  n = {n} days")
    print(f"Signal: daily USDT+USDC circulating supply change (DefiLlama)")
    print(f"Supply: ${combined[dates[0]]/1e9:.0f}B → ${combined[dates[-1]]/1e9:.0f}B")

    # ── Overall correlation ──
    print(f"\n--- Overall Correlation ---\n")
    for label, crypto_ret in [("BTC", btc_ret), ("ETH", eth_ret)]:
        rc = pearson(supply_chg_pct, crypto_ret)
        rc_7d = pearson(supply_7d, crypto_ret)
        print(f"  Supply_change × {label}_return (daily):     ρ = {rc:+.4f}")
        print(f"  Supply_change_7d × {label}_return (daily):  ρ = {rc_7d:+.4f}")

    # ── LEAD-LAG (the key test) ──
    print(f"\n--- Lead-Lag: supply[t] vs BTC[t] (contemp) vs BTC[t+1] (lagged) ---\n")
    print(f"  {'Signal':>20} {'contemp ρ':>12} {'lag-1d ρ':>12} {'lag-7d ρ':>12} {'verdict':>20}")
    print(f"  {'-' * 80}")

    for label, sig in [("Supply Δ%", supply_chg_pct), ("Supply Δ% 7d-avg", supply_7d)]:
        rc = pearson(sig, btc_ret)
        rl1 = pearson(sig[:-1], btc_ret[1:])
        rl7 = pearson(sig[:-7], btc_ret[7:]) if len(sig) > 7 else 0

        if abs(rl1) > abs(rc) * 0.5 and abs(rl1) > 0.03:
            v = "POSSIBLE LEAD"
        elif abs(rc) > 0.03:
            v = "ECHO (same-day)"
        else:
            v = "NO SIGNAL"
        print(f"  {label:>20} {rc:>+12.4f} {rl1:>+12.4f} {rl7:>+12.4f} {v:>20}")

    # ── Null baseline (shuffle) ──
    random.seed(42)
    N_SHUFFLES = 1000
    print(f"\n--- Null Test: real lag-1d ρ vs {N_SHUFFLES} shuffled ---\n")
    for label, sig in [("Supply Δ%", supply_chg_pct), ("Supply Δ% 7d-avg", supply_7d)]:
        real_lag = pearson(sig[:-1], btc_ret[1:])
        nulls = []
        for _ in range(N_SHUFFLES):
            shuf = btc_ret[1:][:]
            random.shuffle(shuf)
            nulls.append(pearson(sig[:-1], shuf))
        nm = statistics.mean(nulls)
        ns = statistics.stdev(nulls)
        sep = (real_lag - nm) / ns if ns > 0 else 0
        print(f"  {label:>20}: lag-1d ρ = {real_lag:+.4f}  null μ = {nm:+.4f}  σ = {ns:.4f}  sep = {sep:+.2f}σ")

    # ── Conditional returns (top/bottom decile of supply change) ──
    print(f"\n--- Conditional BTC Returns on Supply-Change Days ---\n")
    sorted_idx = sorted(range(n), key=lambda i: supply_7d[i])
    top_decile = sorted_idx[int(n * 0.9):]
    bot_decile = sorted_idx[:int(n * 0.1)]
    mid = [i for i in sorted_idx if i not in set(top_decile) and i not in set(bot_decile)]

    for label, indices in [("Minting surge (top 10%)", top_decile),
                           ("Burning surge (bot 10%)", bot_decile),
                           ("Normal (middle 80%)", mid)]:
        rets = [btc_ret[i] for i in indices]
        if rets:
            mean = statistics.mean(rets)
            med = statistics.median(rets)
            hit = sum(1 for r in rets if r > 0) / len(rets)
            print(f"  {label:>30}: BTC mean {mean:+.2%}  median {med:+.2%}  hit {hit:.0%}  n={len(rets)}")

    # Next-day conditional (the tradeable version)
    print(f"\n  NEXT-DAY returns (supply signal[t] → BTC[t+1]):")
    for label, indices in [("Minting surge (top 10%)", top_decile),
                           ("Burning surge (bot 10%)", bot_decile)]:
        rets = [btc_ret[i + 1] for i in indices if i + 1 < n]
        if rets:
            mean = statistics.mean(rets)
            hit = sum(1 for r in rets if r > 0) / len(rets)
            print(f"  {label:>30}: BTC next-day mean {mean:+.2%}  hit {hit:.0%}  n={len(rets)}")

    # ── Stability per year ──
    print(f"\n--- Stability by Year (lag-1d ρ: supply→BTC[t+1]) ---\n")
    year_idx = defaultdict(list)
    for i, d in enumerate(ret_dates):
        year_idx[d[:4]].append(i)

    for year in sorted(year_idx):
        idx = year_idx[year]
        if len(idx) < 30:
            continue
        yr_sig = [supply_7d[i] for i in idx if i < len(supply_7d)]
        yr_btc_next = [btc_ret[i + 1] for i in idx if i + 1 < n]
        min_n = min(len(yr_sig), len(yr_btc_next))
        if min_n < 20:
            continue
        yr_lag = pearson(yr_sig[:min_n - 1], yr_btc_next[:min_n - 1])
        print(f"  {year}: ρ(supply_7d[t] → BTC[t+1]) = {yr_lag:+.4f}  n={min_n}")

    # ── Tradeability ──
    cost = COST_BPS / 10000
    print(f"\n--- Tradeability ({COST_BPS}bps cost) ---\n")
    print(f"  Strategy: long BTC when 7d-avg supply growth > 0, flat when < 0")
    print(f"  (Position changes = entry/exit cost each time)\n")

    strat_rets = []
    trades = 0
    in_position = False
    for i in range(len(supply_7d) - 1):
        signal_positive = supply_7d[i] > 0
        if signal_positive:
            if not in_position:
                trades += 1
                strat_rets.append(btc_ret[i + 1] - cost)  # entry cost
                in_position = True
            else:
                strat_rets.append(btc_ret[i + 1])  # hold, no cost
        else:
            if in_position:
                strat_rets.append(-cost)  # exit cost, flat
                in_position = False
                trades += 1
            else:
                strat_rets.append(0)  # flat, no cost

    bh_total = sum(btc_ret[1:len(strat_rets) + 1])
    strat_total = sum(strat_rets)
    time_in = sum(1 for s in supply_7d[:-1] if s > 0) / len(supply_7d[:-1])

    print(f"  Strategy return: {strat_total:+.1%}")
    print(f"  Buy-and-hold:    {bh_total:+.1%}")
    print(f"  Trades: {trades}  Time in market: {time_in:.0%}")
    print(f"  {'BEATS' if strat_total > bh_total else 'LOSES TO'} buy-and-hold")

    # ── VERDICT ──
    print(f"\n{'=' * 70}")
    print("VERDICT")
    print(f"{'=' * 70}\n")

    rc = pearson(supply_chg_pct, btc_ret)
    rl = pearson(supply_chg_pct[:-1], btc_ret[1:])
    rc_7d = pearson(supply_7d, btc_ret)
    rl_7d = pearson(supply_7d[:-1], btc_ret[1:])

    print(f"  Contemporaneous ρ (supply vs BTC same-day): {rc:+.4f} (raw), {rc_7d:+.4f} (7d-avg)")
    print(f"  Lagged ρ (supply[t] → BTC[t+1]):            {rl:+.4f} (raw), {rl_7d:+.4f} (7d-avg)")
    print()

    if abs(rl_7d) > 0.05 and abs(rl_7d) > abs(rc_7d) * 0.3:
        print("  POSSIBLE lead signal — but check null separation above.")
    elif abs(rc_7d) > 0.05:
        print("  COINCIDENT (echo): supply and price move together same-day.")
        print("  The latency wall holds: even aggregation-based signals are priced coincidentally.")
    else:
        print("  NO SIGNAL: stablecoin supply changes don't predict or correlate with crypto price.")

    print(f"\n  Does the latency wall break for aggregation-based signals?")


if __name__ == "__main__":
    main()
