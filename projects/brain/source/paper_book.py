#!/usr/bin/env python3
"""paper_book.py — Net-of-cost shadow book for news-flag signals.

Turns each matured flag into a hypothetical trade and tracks cumulative P&L.
Two modes:
  directional    — long/short the flagged coin (market-exposed)
  market_neutral — long coin / short BTC (isolates news edge, hedges beta)

Raw price legs persisted write-once to shadow_trades.jsonl (cost-agnostic).
All returns derived at read time from stored prices + --cost-bps.
Uses measurer.py's kline infrastructure. No exchange connection or orders.
"""

import argparse, json, os, random, statistics, time

from measurer import _fetch_klines, _pair, HORIZON_INDEX

FLAGS_LOG = "news_flags.jsonl"
TRADES_LOG = "shadow_trades.jsonl"
ALL_HORIZONS = ["1h", "4h", "24h", "72h"]


# --------------------------------------------------------------------------- #
# Kline cache + raw price extraction
# --------------------------------------------------------------------------- #

def _cached_kl(pair, start_ms, cache):
    key = (pair, start_ms)
    if key not in cache:
        cache[key] = _fetch_klines(pair, start_ms)
    return cache[key]


def _raw_prices(ts_ms, symbol, cache):
    """Per-horizon raw entry/exit prices for asset and BTC."""
    start_ms = int(ts_ms) - (int(ts_ms) % 3_600_000)
    a_kl = _cached_kl(_pair(symbol), start_ms, cache)
    b_kl = _cached_kl(_pair("BTC"), start_ms, cache)
    out = {}
    for h, idx in HORIZON_INDEX.items():
        if len(a_kl) <= idx or len(b_kl) <= idx:
            continue
        ae, ax = float(a_kl[0][4]), float(a_kl[idx][4])
        be, bx = float(b_kl[0][4]), float(b_kl[idx][4])
        if ae == 0 or be == 0:
            continue
        out[h] = {"entry_px": ae, "exit_px": ax,
                  "btc_entry_px": be, "btc_exit_px": bx}
    return out


# --------------------------------------------------------------------------- #
# Persistence — write-once, keyed on (flagged_at_ms, horizon)
# --------------------------------------------------------------------------- #

def _load_trades():
    if not os.path.exists(TRADES_LOG):
        return {}
    out = {}
    for line in open(TRADES_LOG):
        line = line.strip()
        if line:
            t = json.loads(line)
            out[(t["flagged_at_ms"], t["horizon"])] = t
    return out


def _append_trades(new_trades):
    with open(TRADES_LOG, "a") as f:
        for t in sorted(new_trades.values(),
                        key=lambda x: (x["flagged_at_ms"], x["horizon"])):
            f.write(json.dumps(t) + "\n")


# --------------------------------------------------------------------------- #
# Refresh: fetch only newly-matured horizons not already on file
# --------------------------------------------------------------------------- #

def _refresh_trades(flags, existing):
    """Return dict of new trades (raw price legs) for unlogged horizons only."""
    cache = {}
    new = {}
    for f in flags:
        ts_ms = int(f["flagged_at_ms"])
        missing = [h for h in ALL_HORIZONS if (ts_ms, h) not in existing]
        if not missing:
            continue
        prices = _raw_prices(ts_ms, f["symbol"], cache)
        for h in missing:
            if h in prices:
                p = prices[h]
                new[(ts_ms, h)] = {
                    "flagged_at_ms": ts_ms,
                    "flagged_at": f["flagged_at"],
                    "symbol": f["symbol"],
                    "direction": f["direction"],
                    "horizon": h,
                    "entry_px": p["entry_px"],
                    "exit_px": p["exit_px"],
                    "btc_entry_px": p["btc_entry_px"],
                    "btc_exit_px": p["btc_exit_px"],
                }
    return new


# --------------------------------------------------------------------------- #
# Derive returns from raw prices at read time (cost-agnostic storage)
# --------------------------------------------------------------------------- #

def _derive(trade, cost_bps, mode):
    """Compute asset_ret, btc_ret, gross, net from stored price legs."""
    ar = trade["exit_px"] / trade["entry_px"] - 1
    br = trade["btc_exit_px"] / trade["btc_entry_px"] - 1
    sign = 1 if trade["direction"] == "bullish" else -1
    cost = cost_bps / 10_000
    if mode == "directional":
        gross = sign * ar
    else:
        gross = sign * (ar - br)
    return {"asset_ret": ar, "btc_ret": br, "gross": gross, "net": gross - cost}


# --------------------------------------------------------------------------- #
# Null baseline (reuses make_measurer's cache)
# --------------------------------------------------------------------------- #

def _null_means(flags, seed=42, n_null=50):
    """Quick null: random timestamps/directions, same symbol pool.

    Uses make_measurer (excess returns) — matches cmd_shuffle's methodology.
    """
    from measurer import make_measurer
    symbols = list({f["symbol"] for f in flags})
    ts_list = [f["flagged_at_ms"] for f in flags]
    ts_min, ts_max = min(ts_list), max(ts_list)
    rng = random.Random(seed)
    measurer = make_measurer()
    buckets = {h: [] for h in ALL_HORIZONS}
    for _ in range(n_null):
        ts_ms = rng.uniform(ts_min, ts_max)
        sym = rng.choice(symbols)
        sign = rng.choice([1, -1])
        raw = measurer(ts_ms / 1000.0, sym)
        time.sleep(0.02)
        for h, val in raw.items():
            if val is not None:
                buckets[h].append(sign * val)
    return {h: statistics.mean(v) if v else None for h, v in buckets.items()}


# --------------------------------------------------------------------------- #
# Sparkline
# --------------------------------------------------------------------------- #

def _sparkline(vals):
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return "\u2585" * len(vals)
    blocks = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    return "".join(blocks[min(8, int((v - lo) / (hi - lo) * 8))] for v in vals)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def cmd_report(args):
    if not os.path.exists(FLAGS_LOG):
        print("No flags yet.")
        return
    flags = [json.loads(l) for l in open(FLAGS_LOG) if l.strip()]
    if not flags:
        print("No flags yet.")
        return

    cost_bps = args.cost_bps
    mode = args.mode

    # Load stored trades, fetch only new ones, append
    existing = _load_trades()
    new = _refresh_trades(flags, existing)
    if new:
        _append_trades(new)
        print(f"Logged {len(new)} new trade(s).")
    all_trades = {**existing, **new}

    # Null baseline
    null_means = _null_means(flags)

    horizons = [args.horizon] if args.horizon else ALL_HORIZONS

    label = ("DIRECTIONAL (long/short coin)" if mode == "directional"
             else "MARKET NEUTRAL (long coin / short BTC)")
    print(f"Shadow book \u2014 {label}  |  cost: {cost_bps} bps round-trip")
    print(f"Flags: {len(flags)}")
    print()

    for h in horizons:
        ht = sorted([t for t in all_trades.values() if t["horizon"] == h
                     and (mode != "market_neutral" or t["symbol"] != "BTC")],
                     key=lambda t: t["flagged_at_ms"])
        if not ht:
            print(f"  +{h:>3}: no matured trades")
            print()
            continue

        derived = [_derive(t, cost_bps, mode) for t in ht]
        nets = [d["net"] for d in derived]
        grosses = [d["gross"] for d in derived]
        btc_rets = [d["btc_ret"] for d in derived]
        n = len(nets)
        wins = [x for x in nets if x > 0]
        losses = [x for x in nets if x <= 0]
        hit = len(wins) / n
        avg_w = statistics.mean(wins) if wins else 0.0
        avg_l = statistics.mean(losses) if losses else 0.0
        sw = sum(wins) if wins else 0.0
        sl = abs(sum(losses)) if losses else 0.0
        pf = sw / sl if sl > 0 else float("inf") if sw > 0 else 0.0

        # Equity curve (multiplicative compounding)
        cum = 1.0
        eq = [1.0]
        peak = 1.0
        mdd = 0.0
        for r in nets:
            cum *= (1 + r)
            eq.append(cum)
            if cum > peak:
                peak = cum
            dd = (peak - cum) / peak
            if dd > mdd:
                mdd = dd

        # BTC benchmark: buy-and-hold over the same trade windows
        btc_cum = 1.0
        for r in btc_rets:
            btc_cum *= (1 + r)

        nm = null_means.get(h)
        pf_s = f"{pf:.2f}" if pf != float("inf") else "inf"

        print(f"  +{h:>3}  ({n} trades)")
        print(f"    hit rate:       {hit:.0%}  ({len(wins)}/{n})")
        print(f"    avg win:        {avg_w * 100:+.2f}%")
        print(f"    avg loss:       {avg_l * 100:+.2f}%")
        print(f"    profit factor:  {pf_s}")
        print(f"    gross mean:     {statistics.mean(grosses) * 100:+.2f}%")
        print(f"    net mean:       {statistics.mean(nets) * 100:+.2f}%")
        print(f"    cumulative:     {(cum - 1) * 100:+.2f}%")
        print(f"    max drawdown:   {mdd * 100:.2f}%")
        print(f"    equity:         {_sparkline(eq)}")
        print(f"    BTC benchmark:  {(btc_cum - 1) * 100:+.2f}%  (buy-and-hold, same windows)")
        if nm is not None:
            print(f"    null mean:      {nm * 100:+.2f}%  (shuffle excess, sanity ceiling)")
        print()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--horizon", choices=ALL_HORIZONS)
    rp.add_argument("--cost-bps", type=int, default=15)
    rp.add_argument("--mode", choices=["directional", "market_neutral"],
                    default="directional")
    rp.set_defaults(func=cmd_report)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
