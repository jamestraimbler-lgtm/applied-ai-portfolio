"""Bybit cross-exchange listing signal.

Hypothesis: when Bybit announces a listing for a token that ALREADY TRADES
ON BINANCE SPOT, does the BINANCE price drift? Uses Bybit publishTime as
signal. Entry = OPEN of Binance 1m candle AFTER the signal candle (causal).

Also reports the publish→entry inaccessible gap: did Binance already move
BEFORE the announcement, implying Bybit is reacting to a move, not causing it?
"""

import json, os, random, re, statistics, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BYBIT_API = "https://api.bybit.com/v5/announcements/index"
EVENTS_FILE = os.path.join(_DIR, "bybit_events.jsonl")
TRADES_FILE = os.path.join(_DIR, "bybit_trades.jsonl")
HORIZONS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
COST_BPS = 15


# ── Bybit API ────────────────────────────────────────────────────────

def _fetch_bybit(page, limit=20):
    r = requests.get(BYBIT_API, params={
        "locale": "en-US", "type": "new_crypto",
        "page": page, "limit": limit,
    }, timeout=15)
    if r.status_code != 200:
        return [], 0
    d = r.json().get("result", {})
    return d.get("list", []), d.get("total", 0)


def _parse_tickers(title):
    """Extract token tickers from Bybit announcement titles."""
    # "New listing: TICKERUSDT Perpetual Contract..."
    m = re.findall(r'\b([A-Z][A-Z0-9]+)USDT\b', title)
    if m:
        return [t for t in m if t not in ("USD",)]
    # "New listing: TICKER/USDT..."
    return re.findall(r'\b([A-Z][A-Z0-9]+)/USDT\b', title)


# ── Binance kline helpers ────────────────────────────────────────────

def _fetch_1m(pair, start_ms, limit=1000):
    r = requests.get("https://api.binance.com/api/v3/klines", params={
        "symbol": pair, "interval": "1m",
        "startTime": start_ms, "limit": limit,
    }, timeout=15)
    return r.json() if r.status_code == 200 else []


def _fetch_1m_full(pair, start_ms, need):
    out, cur = [], start_ms
    while len(out) < need:
        lim = min(1000, need - len(out) + 5)
        batch = _fetch_1m(pair, cur, lim)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < lim:
            break
        cur = batch[-1][0] + 60_000
    return out


# ── Poll & filter ────────────────────────────────────────────────────

def poll_and_filter():
    """Fetch all Bybit new_crypto announcements, keep only already-on-Binance."""
    print("Fetching Bybit new_crypto announcements...")
    all_arts = []
    page = 1
    while True:
        arts, total = _fetch_bybit(page)
        if not arts:
            break
        all_arts.extend(arts)
        if page % 10 == 0:
            print(f"  page {page}, {len(all_arts)}/{total}")
        if len(all_arts) >= total:
            break
        page += 1
        time.sleep(0.05)
    print(f"  Fetched {len(all_arts)} announcements")

    # Check which tickers have Binance spot klines at announcement time
    pair_cache = {}  # (pair, pub_floor_ms) -> bool

    events = []
    for art in all_arts:
        title = art.get("title", "")
        pub_ms = art.get("publishTime", 0)
        if not pub_ms:
            continue
        tickers = _parse_tickers(title)
        if not tickers:
            continue

        pub_s = pub_ms / 1000.0
        for ticker in tickers:
            if ticker == "BTC":
                continue
            pair = f"{ticker}USDT"
            pub_floor = pub_ms - (pub_ms % 60_000)

            cache_key = pair  # check once per pair (any time)
            if cache_key not in pair_cache:
                kl = _fetch_1m(pair, pub_floor, 1)
                pair_cache[cache_key] = bool(
                    kl and kl[0][0] <= pub_floor + 60_000)

            if not pair_cache[cache_key]:
                continue

            events.append({
                "symbol": ticker,
                "publish_ts": pub_s,
                "title": title,
                "source": "bybit_listing",
            })

    # Dedup: same (symbol, minute)
    seen = set()
    deduped = []
    for ev in events:
        key = (ev["symbol"], int(ev["publish_ts"] // 60))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)

    with open(EVENTS_FILE, "w") as f:
        for e in deduped:
            f.write(json.dumps(e) + "\n")

    # Summary
    syms = set(e["symbol"] for e in deduped)
    print(f"  Qualifying: {len(deduped)} events, {len(syms)} unique symbols")
    return deduped


# ── Measure & report ─────────────────────────────────────────────────

def measure_and_report(seed=42):
    random.seed(seed)
    if not os.path.exists(EVENTS_FILE):
        print("No events. Run poll first.")
        return

    events = [json.loads(l) for l in open(EVENTS_FILE) if l.strip()]
    if not events:
        print("No qualifying events.")
        return

    cache = {}
    max_need = max(HORIZONS.values()) + 2
    btc = "BTCUSDT"
    pre_candles = 10  # fetch 10 candles before signal for inaccessible gap

    real_by_h = {h: [] for h in HORIZONS}
    gaps = []
    new_trades = []

    print(f"Measuring {len(events)} events on Binance spot...")

    for ev in events:
        pair = f"{ev['symbol']}USDT"
        pub_ms = int(ev["publish_ts"] * 1000)
        sig_floor = pub_ms - (pub_ms % 60_000)
        entry_ms = sig_floor + 60_000  # CAUSAL: next minute after signal

        # Fetch from 10 min before signal for inaccessible gap
        fetch_start = sig_floor - pre_candles * 60_000

        for p in (pair, btc):
            if (p, fetch_start) not in cache:
                cache[(p, fetch_start)] = _fetch_1m_full(
                    p, fetch_start, max_need + pre_candles + 2)

        a_kl = cache.get((pair, fetch_start), [])
        b_kl = cache.get((btc, fetch_start), [])
        if not a_kl or not b_kl:
            continue

        # Build timestamp lookups
        a_ts = {k[0]: k for k in a_kl}
        b_ts = {k[0]: k for k in b_kl}

        entry_k = a_ts.get(entry_ms)
        btc_entry_k = b_ts.get(entry_ms)
        if not entry_k or not btc_entry_k:
            continue

        epx = float(entry_k[1])  # OPEN of entry candle
        bepx = float(btc_entry_k[1])
        if epx == 0 or bepx == 0:
            continue

        # Inaccessible gap: 5 min before signal → entry
        pre_ms = sig_floor - 5 * 60_000
        pre_k = a_ts.get(pre_ms)
        pre_btc = b_ts.get(pre_ms)
        if pre_k and pre_btc:
            pre_px = float(pre_k[1])
            pre_bpx = float(pre_btc[1])
            if pre_px > 0 and pre_bpx > 0:
                gap_ret = (epx / pre_px - 1) * 100
                gap_btc = (bepx / pre_bpx - 1) * 100
                gaps.append({
                    "sym": ev["symbol"], "gap_exc": gap_ret - gap_btc})

        # Forward measurement
        for h_label, h_off in HORIZONS.items():
            exit_ms = entry_ms + h_off * 60_000
            exit_k = a_ts.get(exit_ms)
            btc_exit_k = b_ts.get(exit_ms)
            if not exit_k or not btc_exit_k:
                continue

            xpx = float(exit_k[4])
            bxpx = float(btc_exit_k[4])
            ar = (xpx / epx - 1) * 100
            br = (bxpx / bepx - 1) * 100

            real_by_h[h_label].append({
                "ret": ar, "exc": ar - br, "sym": ev["symbol"]})

            new_trades.append({
                "symbol": ev["symbol"],
                "publish_ts": ev["publish_ts"],
                "horizon": h_label,
                "entry_px": epx, "exit_px": xpx,
                "btc_entry_px": bepx, "btc_exit_px": bxpx,
            })

    if new_trades:
        with open(TRADES_FILE, "w") as f:
            for t in new_trades:
                f.write(json.dumps(t) + "\n")
        print(f"Stored {len(new_trades)} trade legs.")

    # ── Null comparison ──
    null_by_h = {h: [] for h in HORIZONS}
    sample_events = events[:80] if len(events) > 80 else events
    print(f"Generating null (5 random per event, {len(sample_events)} events)...")

    for ev in sample_events:
        pair = f"{ev['symbol']}USDT"
        pub_s = ev["publish_ts"]
        for _ in range(5):
            rand_s = pub_s - random.uniform(7 * 86400, 60 * 86400)
            rand_ms = int(rand_s * 1000)
            rand_ms -= rand_ms % 60_000
            null_entry = rand_ms + 60_000

            for p in (pair, btc):
                k = (p, rand_ms)
                if k not in cache:
                    cache[k] = _fetch_1m_full(p, rand_ms, max_need + 2)

            na = cache.get((pair, rand_ms), [])
            nb = cache.get((btc, rand_ms), [])
            na_ts = {k[0]: k for k in na}
            nb_ts = {k[0]: k for k in nb}

            nek = na_ts.get(null_entry)
            nbek = nb_ts.get(null_entry)
            if not nek or not nbek:
                continue
            nep = float(nek[1])
            nbep = float(nbek[1])
            if nep == 0 or nbep == 0:
                continue

            for h_label, h_off in HORIZONS.items():
                xms = null_entry + h_off * 60_000
                nxk = na_ts.get(xms)
                nbxk = nb_ts.get(xms)
                if not nxk or not nbxk:
                    continue
                ar = (float(nxk[4]) / nep - 1) * 100
                br = (float(nbxk[4]) / nbep - 1) * 100
                null_by_h[h_label].append(ar - br)

    _report(events, real_by_h, null_by_h, gaps)


def _report(events, real_by_h, null_by_h, gaps):
    cost = COST_BPS / 100
    _sep = "=" * 72

    # ── Inaccessible gap ──
    print(f"\n{_sep}")
    print("INACCESSIBLE GAP (5min before signal → entry)")
    print("  Did Binance already move BEFORE the Bybit announcement?")
    print(_sep)
    if gaps:
        g_vals = [g["gap_exc"] for g in gaps]
        print(f"  n={len(gaps)}  mean={statistics.mean(g_vals):+.4f}%  "
              f"median={statistics.median(g_vals):+.4f}%")
        pos = sum(1 for g in g_vals if g > 0)
        print(f"  Positive (Binance moved up before announcement): "
              f"{pos}/{len(gaps)} ({pos / len(gaps) * 100:.0f}%)")
    else:
        print("  No gap data.")

    # ── Forward drift ──
    print(f"\n{_sep}")
    print(f"BYBIT LISTING → BINANCE SPOT DRIFT  "
          f"(n={len(events)} events)")
    print(f"  entry = OPEN of Binance 1m candle AFTER signal | "
          f"net {COST_BPS}bps")
    print(_sep)
    print(f"  {'hz':>6}  {'n':>4}  {'mean exc':>10}  {'med exc':>10}  "
          f"{'wins':>8}  {'null μ':>10}  {'null σ':>8}  {'sep':>6}")

    for h in ["1m", "5m", "15m", "1h", "4h"]:
        rs = real_by_h.get(h, [])
        ns = null_by_h.get(h, [])
        if not rs:
            print(f"  {h:>6}    —")
            continue
        excs = [r["exc"] - cost for r in rs]
        r_mean = statistics.mean(excs)
        r_med = statistics.median(excs)
        wins = sum(1 for e in excs if e > 0)

        if len(ns) > 1:
            n_vals = [n - cost for n in ns]
            n_mean = statistics.mean(n_vals)
            n_std = statistics.stdev(n_vals)
            sep = (r_mean - n_mean) / n_std if n_std > 0 else 0
            print(f"  {h:>6}  {len(rs):>4}  {r_mean:>+9.4f}%  "
                  f"{r_med:>+9.4f}%  {wins:>3}/{len(rs):<4} "
                  f"{n_mean:>+9.4f}%  {n_std:>7.4f}%  {sep:>+5.2f}σ")
        else:
            print(f"  {h:>6}  {len(rs):>4}  {r_mean:>+9.4f}%  "
                  f"{r_med:>+9.4f}%  {wins:>3}/{len(rs):<4}")

    # Top symbols
    sym_c = {}
    for ev in events:
        sym_c[ev["symbol"]] = sym_c.get(ev["symbol"], 0) + 1
    top = sorted(sym_c.items(), key=lambda x: -x[1])[:10]
    if top:
        print(f"\n  Top symbols: "
              f"{', '.join(f'{s}({n})' for s, n in top)}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="both",
                    choices=["poll", "measure", "both"])
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.cmd in ("poll", "both"):
        poll_and_filter()
    if args.cmd in ("measure", "both"):
        measure_and_report(seed=args.seed)
