"""Volume spike detector — zero external deps, pure Binance 1m klines.

Detects 1m volume Z-score spikes (>3σ on 20-period lookback) and measures
forward drift from the NEXT candle's open (causal guard: can't act until
the spike candle closes and you've observed the spike).

Reports both:
  (a) signed by spike direction — does the move CONTINUE?
  (b) absolute |excess| — does VOLATILITY expand regardless of direction?
Null baseline: random non-spike (Z<1) candles, same symbols, same horizons.
"""

import json, os, random, statistics, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UNIVERSE = [
    "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX",
    "DOT", "LINK", "UNI", "LTC", "NEAR", "APT", "SUI",
    "ONDO", "ZEC", "PEPE", "ARB", "OP",
]

LOOKBACK = 20
Z_DEFAULT = 3.0
HORIZONS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
TRADES_FILE = os.path.join(_DIR, "volspike_trades.jsonl")
COST_BPS = 15


def _fetch_1m(pair, start_ms, limit=1000):
    r = requests.get("https://api.binance.com/api/v3/klines", params={
        "symbol": pair, "interval": "1m",
        "startTime": start_ms, "limit": limit,
    }, timeout=15)
    return r.json() if r.status_code == 200 else []


def _fetch_range(pair, start_ms, end_ms):
    out, cur = [], start_ms
    while cur < end_ms:
        batch = _fetch_1m(pair, cur)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1000:
            break
        cur = batch[-1][0] + 60_000
    return out


def _vol_zscore(klines, lookback=LOOKBACK):
    vols = [float(k[5]) for k in klines]
    zs = [None] * len(vols)
    for i in range(lookback, len(vols)):
        w = vols[i - lookback:i]
        mu = statistics.mean(w)
        sd = statistics.stdev(w) if len(w) > 1 else 0
        if sd < 1e-12:
            continue
        zs[i] = (vols[i] - mu) / sd
    return zs


def backfill_and_measure(days=7, z_thr=Z_DEFAULT, null_ratio=3, seed=42):
    random.seed(seed)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 86_400_000
    max_h = max(HORIZONS.values())

    print(f"Fetching BTC 1m klines ({days}d)...")
    btc_kl = _fetch_range("BTCUSDT", start_ms, now_ms)
    btc_by_ts = {k[0]: k for k in btc_kl}
    print(f"  BTC: {len(btc_kl)} candles")

    all_real, all_null = [], []
    new_trades = []
    total_spikes = 0

    for sym in UNIVERSE:
        pair = f"{sym}USDT"
        print(f"  {sym}...", end=" ", flush=True)
        klines = _fetch_range(pair, start_ms, now_ms)
        if len(klines) < LOOKBACK + max_h + 2:
            print(f"skip ({len(klines)} candles)")
            continue

        zs = _vol_zscore(klines)
        spikes, non_spikes = [], []

        for i in range(LOOKBACK, len(klines) - max_h - 2):
            z = zs[i]
            if z is None:
                continue
            if z >= z_thr:
                spikes.append(i)
            elif z < 1.0:
                non_spikes.append(i)

        print(f"{len(spikes)} spikes, {len(non_spikes)} null candidates")
        total_spikes += len(spikes)

        def _measure(idx_list, is_real):
            rows = []
            for i in idx_list:
                sk = klines[i]
                ek = klines[i + 1]  # CAUSAL: next candle after signal
                s_dir = 1 if float(sk[4]) >= float(sk[1]) else -1
                epx = float(ek[1])  # OPEN of next candle
                ets = ek[0]
                if epx == 0:
                    continue
                bek = btc_by_ts.get(ets)
                if not bek:
                    continue
                bpx = float(bek[1])
                if bpx == 0:
                    continue

                for h_label, h_off in HORIZONS.items():
                    xi = i + 1 + h_off
                    if xi >= len(klines):
                        continue
                    xk = klines[xi]
                    bxk = btc_by_ts.get(xk[0])
                    if not bxk:
                        continue
                    xpx = float(xk[4])
                    bxpx = float(bxk[4])

                    ar = (xpx / epx - 1) * 100
                    br = (bxpx / bpx - 1) * 100
                    exc = ar - br

                    rows.append({
                        "h": h_label, "ret": ar, "exc": exc,
                        "dir": s_dir, "sym": sym,
                    })

                    if is_real:
                        new_trades.append({
                            "symbol": sym,
                            "spike_ts": sk[0] / 1000,
                            "vol_z": round(zs[i], 2),
                            "spike_direction": s_dir,
                            "horizon": h_label,
                            "entry_ts": ets / 1000,
                            "entry_px": epx,
                            "exit_px": xpx,
                            "btc_entry_px": bpx,
                            "btc_exit_px": bxpx,
                        })
            return rows

        all_real.extend(_measure(spikes, True))
        n_null = min(len(non_spikes), len(spikes) * null_ratio)
        if n_null > 0:
            all_null.extend(_measure(
                random.sample(non_spikes, n_null), False))

    # Store trades
    if new_trades:
        with open(TRADES_FILE, "w") as f:
            for t in new_trades:
                f.write(json.dumps(t) + "\n")
        print(f"\nStored {len(new_trades)} trade legs to volspike_trades.jsonl")

    print(f"Total: {total_spikes} spike events, "
          f"{len(all_real)} real measurements, "
          f"{len(all_null)} null measurements")

    _report(all_real, all_null)


def _report(real, null):
    cost = COST_BPS / 100
    _sep = "=" * 72

    real_h = {}
    null_h = {}
    for r in real:
        real_h.setdefault(r["h"], []).append(r)
    for n in null:
        null_h.setdefault(n["h"], []).append(n)

    # ── SIGNED (continuation) ──
    print(f"\n{_sep}")
    print("SIGNED DRIFT — does the move CONTINUE after spike?")
    print(f"  signed_excess = spike_dir × excess_vs_BTC | net {COST_BPS}bps")
    print(f"  entry = OPEN of candle AFTER spike (causal)")
    print(_sep)
    print(f"  {'hz':>6}  {'n':>6}  {'mean':>9}  {'median':>9}  "
          f"{'wins':>8}  {'null μ':>9}  {'null σ':>8}  {'sep':>6}")

    for h in ["1m", "5m", "15m", "1h", "4h"]:
        rs = real_h.get(h, [])
        ns = null_h.get(h, [])
        if not rs:
            print(f"  {h:>6}    —")
            continue
        signed = [r["dir"] * r["exc"] - cost for r in rs]
        s_mean = statistics.mean(signed)
        s_med = statistics.median(signed)
        wins = sum(1 for s in signed if s > 0)

        if len(ns) > 1:
            n_signed = [n["dir"] * n["exc"] - cost for n in ns]
            n_mean = statistics.mean(n_signed)
            n_std = statistics.stdev(n_signed)
            sep = (s_mean - n_mean) / n_std if n_std > 0 else 0
            print(f"  {h:>6}  {len(rs):>6}  {s_mean:>+8.4f}%  "
                  f"{s_med:>+8.4f}%  {wins:>4}/{len(rs):<4} "
                  f"{n_mean:>+8.4f}%  {n_std:>7.4f}%  {sep:>+5.2f}σ")
        else:
            print(f"  {h:>6}  {len(rs):>6}  {s_mean:>+8.4f}%  "
                  f"{s_med:>+8.4f}%  {wins:>4}/{len(rs):<4}")

    # ── ABSOLUTE (volatility) ──
    print(f"\n{_sep}")
    print("ABSOLUTE DRIFT — does VOLATILITY expand after spike?")
    print(f"  |excess_vs_BTC| after spike vs null")
    print(_sep)
    print(f"  {'hz':>6}  {'n':>6}  {'real |exc|':>11}  "
          f"{'null |exc|':>11}  {'sep':>6}")

    for h in ["1m", "5m", "15m", "1h", "4h"]:
        rs = real_h.get(h, [])
        ns = null_h.get(h, [])
        if not rs:
            continue
        r_abs = [abs(r["exc"]) for r in rs]
        r_mean = statistics.mean(r_abs)
        if len(ns) > 1:
            n_abs = [abs(n["exc"]) for n in ns]
            n_mean = statistics.mean(n_abs)
            n_std = statistics.stdev(n_abs)
            sep = (r_mean - n_mean) / n_std if n_std > 0 else 0
            print(f"  {h:>6}  {len(rs):>6}  {r_mean:>10.4f}%  "
                  f"{n_mean:>10.4f}%  {sep:>+5.2f}σ")
        else:
            print(f"  {h:>6}  {len(rs):>6}  {r_mean:>10.4f}%")

    # ── Per-symbol spike counts ──
    sym_counts = {}
    for r in real:
        if r["h"] == "1m":
            sym_counts[r["sym"]] = sym_counts.get(r["sym"], 0) + 1
    top = sorted(sym_counts.items(), key=lambda x: -x[1])[:10]
    print(f"\n  Spike counts: {', '.join(f'{s}({n})' for s, n in top)}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Volume spike detector")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--z", type=float, default=Z_DEFAULT,
                    help="Z threshold (default 3, DO NOT tune post-hoc)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    backfill_and_measure(days=args.days, z_thr=args.z, seed=args.seed)
