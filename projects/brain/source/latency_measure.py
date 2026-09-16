"""Listing-specific measurement — minute-resolution klines.

Measures tradeable listing events at fine-grained horizons (1m → 24h).
Two entry legs per event:
  publish:     OPEN of 1m candle at announcement time (only if klines existed)
  first_trade: OPEN of first available 1m candle after announcement

Reports: inaccessible gap, accessible returns, fraction remaining, price paths.
Does NOT reuse the RSS measurer's hour-flooring — the listing move lives in
minutes, not hours.
"""

import json, os, random, statistics
from datetime import datetime, timezone

import requests

EVENTS_FILE = "listings_events.jsonl"
TRADES_FILE = "listings_trades.jsonl"

HORIZONS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "24h": 1440}


# ── Kline fetch (1m, with pagination) ───────────────────────────────

def _fetch_1m(pair, start_ms, need):
    """Fetch >= `need` 1-minute klines from start_ms, paginating."""
    out, cur = [], start_ms
    while len(out) < need:
        lim = min(1000, need - len(out) + 5)
        r = requests.get("https://api.binance.com/api/v3/klines", params={
            "symbol": pair, "interval": "1m",
            "startTime": cur, "limit": lim,
        }, timeout=15)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < lim:
            break
        cur = batch[-1][0] + 60_000
    return out


# ── Persistence (write-once, same pattern as shadow_trades) ─────────

def _load_events():
    if not os.path.exists(EVENTS_FILE):
        return []
    return [json.loads(l) for l in open(EVENTS_FILE) if l.strip()]


def _load_trades():
    if not os.path.exists(TRADES_FILE):
        return {}
    out = {}
    for l in open(TRADES_FILE):
        if l.strip():
            t = json.loads(l)
            out[(t["announce_id"], t["horizon"], t["entry_type"])] = t
    return out


def _append_trades(new):
    with open(TRADES_FILE, "a") as f:
        for t in new.values():
            f.write(json.dumps(t) + "\n")


# ── Measurement ──────────────────────────────────────────────────────

def measure():
    events = [e for e in _load_events()
              if e["tradeable"] and e["source"] == "binance_listing"]
    existing = _load_trades()
    print(f"Measuring {len(events)} tradeable spot listing events...")

    new_trades = {}
    cache = {}
    max_need = max(HORIZONS.values()) + 2

    for ev in events:
        sym = ev["symbol"]
        pair = f"{sym.upper()}USDT"
        btc = "BTCUSDT"

        # --- First-trade entry ---
        ft_ms = int(ev["first_trade_ts"] * 1000)
        ft_ms -= ft_ms % 60_000  # floor to minute

        for p in (pair, btc):
            if (p, ft_ms) not in cache:
                cache[(p, ft_ms)] = _fetch_1m(p, ft_ms, max_need)
        a_kl = cache[(pair, ft_ms)]
        b_kl = cache[(btc, ft_ms)]

        for h_label, h_idx in HORIZONS.items():
            key = (ev["announce_id"], h_label, "first_trade")
            if key in existing or len(a_kl) <= h_idx or len(b_kl) <= h_idx:
                continue
            entry_px = float(a_kl[0][1])  # OPEN of first candle
            if entry_px == 0:
                continue
            new_trades[key] = {
                "announce_id": ev["announce_id"], "symbol": sym,
                "direction": ev["direction"], "horizon": h_label,
                "entry_type": "first_trade",
                "entry_ts": ev["first_trade_ts"],
                "entry_px": entry_px,
                "exit_px": float(a_kl[h_idx][4]),
                "btc_entry_px": float(b_kl[0][1]),
                "btc_exit_px": float(b_kl[h_idx][4]),
            }

        # --- Publish entry (only if token already had klines) ---
        pub_ms = int(ev["publish_ts"] * 1000)
        pub_ms -= pub_ms % 60_000

        for p in (pair, btc):
            if (p, pub_ms) not in cache:
                cache[(p, pub_ms)] = _fetch_1m(p, pub_ms, max_need)
        pa_kl = cache[(pair, pub_ms)]
        pb_kl = cache[(btc, pub_ms)]

        # Token was trading at announcement if first kline ≈ pub_ms
        if pa_kl and pa_kl[0][0] <= pub_ms + 60_000:
            for h_label, h_idx in HORIZONS.items():
                key = (ev["announce_id"], h_label, "publish")
                if key in existing or len(pa_kl) <= h_idx or len(pb_kl) <= h_idx:
                    continue
                entry_px = float(pa_kl[0][1])
                if entry_px == 0:
                    continue
                new_trades[key] = {
                    "announce_id": ev["announce_id"], "symbol": sym,
                    "direction": ev["direction"], "horizon": h_label,
                    "entry_type": "publish",
                    "entry_ts": ev["publish_ts"],
                    "entry_px": entry_px,
                    "exit_px": float(pa_kl[h_idx][4]),
                    "btc_entry_px": float(pb_kl[0][1]),
                    "btc_exit_px": float(pb_kl[h_idx][4]),
                }

    if new_trades:
        _append_trades(new_trades)
        print(f"Logged {len(new_trades)} new trade legs.")
    else:
        print("No new trade legs.")

    all_t = {**existing, **new_trades}
    _report(events, all_t)


# ── Reporting ────────────────────────────────────────────────────────

def _report(events, trades):
    if not events:
        print("No tradeable events to report.")
        return

    _sep = "=" * 64

    # ── 1. Inaccessible gap ──
    print(f"\n{_sep}")
    print("INACCESSIBLE GAP (publish → first trade)")
    print(_sep)

    gaps = []
    for ev in events:
        gap_s = ev["first_trade_ts"] - ev["publish_ts"]
        pub_t = trades.get((ev["announce_id"], "1m", "publish"))
        ft_t = trades.get((ev["announce_id"], "1m", "first_trade"))
        inac = None
        if pub_t and ft_t and pub_t["entry_px"] > 0:
            inac = (ft_t["entry_px"] / pub_t["entry_px"] - 1) * 100
        gaps.append({"sym": ev["symbol"], "gap_s": gap_s, "inac": inac})
        i_str = (f"move={inac:+.2f}%" if inac is not None
                 else "move=N/A (new listing)")
        print(f"  {ev['symbol']:>10}: gap={gap_s:>8.0f}s "
              f"({gap_s / 3600:>6.1f}h) | {i_str}")

    gs = [g["gap_s"] for g in gaps]
    print(f"\n  Gap: median={statistics.median(gs) / 3600:.1f}h  "
          f"mean={statistics.mean(gs) / 3600:.1f}h  "
          f"[{min(gs) / 3600:.1f}h — {max(gs) / 3600:.1f}h]")
    inacs = [g["inac"] for g in gaps if g["inac"] is not None]
    if inacs:
        print(f"  Inaccessible move: median={statistics.median(inacs):+.2f}%  "
              f"mean={statistics.mean(inacs):+.2f}%")
    else:
        print("  Inaccessible move: all N/A (new listings, no pre-existing klines)")

    # ── 2. Accessible returns (first-trade entry) ──
    print(f"\n{_sep}")
    print("ACCESSIBLE RETURNS (from first-trade open, excess vs BTC)")
    print(_sep)
    print(f"  {'hz':>6}  {'n':>3}  {'mean ret':>10}  {'mean exc':>10}  "
          f"{'med exc':>10}  {'wins':>7}")

    for h in ["1m", "5m", "15m", "1h", "4h", "24h"]:
        rows = []
        for ev in events:
            t = trades.get((ev["announce_id"], h, "first_trade"))
            if not t or t["entry_px"] == 0 or t["btc_entry_px"] == 0:
                continue
            ar = (t["exit_px"] / t["entry_px"] - 1) * 100
            br = (t["btc_exit_px"] / t["btc_entry_px"] - 1) * 100
            rows.append({"ret": ar, "exc": ar - br, "sym": t["symbol"]})
        if not rows:
            print(f"  {h:>6}    —")
            continue
        rets = [r["ret"] for r in rows]
        excs = [r["exc"] for r in rows]
        w = sum(1 for r in rets if r > 0)
        print(f"  {h:>6}  {len(rows):>3}  {statistics.mean(rets):>+9.2f}%  "
              f"{statistics.mean(excs):>+9.2f}%  "
              f"{statistics.median(excs):>+9.2f}%  {w}/{len(rows)}")

    # ── 3. Fraction of move remaining ──
    print(f"\n{_sep}")
    print("FRACTION OF MOVE REMAINING (accessible / total)")
    print(_sep)
    any_frac = False
    for h in ["1m", "5m", "15m", "1h", "4h", "24h"]:
        fracs = []
        for ev in events:
            pt = trades.get((ev["announce_id"], h, "publish"))
            ft = trades.get((ev["announce_id"], h, "first_trade"))
            if not pt or not ft or pt["entry_px"] == 0:
                continue
            total = pt["exit_px"] / pt["entry_px"] - 1
            accessible = ft["exit_px"] / ft["entry_px"] - 1
            if abs(total) > 0.0001:
                fracs.append(accessible / total * 100)
        if fracs:
            any_frac = True
            print(f"  {h:>6}: {statistics.mean(fracs):>6.1f}% remaining  "
                  f"(n={len(fracs)})")
        else:
            print(f"  {h:>6}: N/A")
    if not any_frac:
        print("\n  (All listings are brand-new tokens — no pre-listing klines,")
        print("   so publish entry unavailable. Fraction requires both legs.)")

    # ── 4. Price paths ──
    print(f"\n{_sep}")
    print("PRICE PATHS (first 3 tradeable listings)")
    print(_sep)
    for ev in events[:3]:
        pub_str = datetime.fromtimestamp(
            ev["publish_ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        ft_str = datetime.fromtimestamp(
            ev["first_trade_ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        gap_h = (ev["first_trade_ts"] - ev["publish_ts"]) / 3600
        print(f"\n  {ev['symbol']} | announced {pub_str} | "
              f"first trade {ft_str} (gap {gap_h:.1f}h)")

        for h in ["1m", "5m", "15m", "1h", "4h", "24h"]:
            t = trades.get((ev["announce_id"], h, "first_trade"))
            if t and t["entry_px"] > 0:
                ret = (t["exit_px"] / t["entry_px"] - 1) * 100
                btc_r = ((t["btc_exit_px"] / t["btc_entry_px"] - 1) * 100
                         if t["btc_entry_px"] > 0 else 0)
                exc = ret - btc_r
                # Arrow for quick visual: ↗ still up, ↘ reversed
                arrow = "↗" if ret > 0 else "↘"
                print(f"    +{h:>4}: {ret:>+8.2f}% raw  "
                      f"{exc:>+8.2f}% exc  {arrow}  "
                      f"(${t['entry_px']:.6f} → ${t['exit_px']:.6f})")


# ── Part 1: Honest entry analysis ─────────────────────────────────────

_ENTRIES = [
    # (label,       candle_idx, kline_field)
    ("1m_open",     0,          1),   # open of candle 0
    ("1m_close",    0,          4),   # close of candle 0
    ("5m_close",    4,          4),   # close of candle 4
    ("15m_close",   14,         4),   # close of candle 14
]
_H_HORIZONS = {"1h": 60, "4h": 240, "24h": 1440}


def honest_entry():
    """Re-measure spot listings with 4 entry points × 3 horizons × costs."""
    events = [e for e in _load_events()
              if e["tradeable"] and e["source"] == "binance_listing"]
    cache = {}
    max_need = 14 + 1440 + 2  # worst-case: 15m entry + 24h horizon

    rows = []
    print(f"Fetching 1m klines for {len(events)} spot listings...")

    for ev in events:
        pair = f"{ev['symbol'].upper()}USDT"
        btc = "BTCUSDT"
        ft_ms = int(ev["first_trade_ts"] * 1000)
        ft_ms -= ft_ms % 60_000

        for p in (pair, btc):
            if (p, ft_ms) not in cache:
                cache[(p, ft_ms)] = _fetch_1m(p, ft_ms, max_need)

        a, b = cache[(pair, ft_ms)], cache[(btc, ft_ms)]
        if len(a) <= 1454 or len(b) <= 1454:
            print(f"  {ev['symbol']}: insufficient klines ({len(a)}), skip")
            continue

        c0 = (float(a[0][1]), float(a[0][2]),
              float(a[0][3]), float(a[0][4]))   # O H L C

        entry_rets = {}
        for ename, cidx, pidx in _ENTRIES:
            epx = float(a[cidx][pidx])
            bpx = float(b[cidx][pidx])
            if epx == 0 or bpx == 0:
                continue
            rets = {}
            for hname, hoff in _H_HORIZONS.items():
                eidx = cidx + hoff
                ar = (float(a[eidx][4]) / epx - 1) * 100
                br = (float(b[eidx][4]) / bpx - 1) * 100
                rets[hname] = {"ret": ar, "exc": ar - br}
            entry_rets[ename] = rets

        rows.append({"sym": ev["symbol"], "c0": c0, "rets": entry_rets})

    if not rows:
        print("No events with enough klines.")
        return

    n = len(rows)
    _sep = "=" * 72

    # ── Mean excess tables: gross, net 50bps, net 100bps ──
    for label, cost in [("GROSS", 0), ("NET 50bps", 0.50), ("NET 100bps", 1.00)]:
        print(f"\n{_sep}")
        print(f"MEAN EXCESS RETURN — {label}  (n={n})")
        print(_sep)
        print(f"  {'entry':>14}     +1h        +4h       +24h")

        for ename, _, _ in _ENTRIES:
            parts = []
            for h in ["1h", "4h", "24h"]:
                vals = [r["rets"][ename][h]["exc"] - cost
                        for r in rows
                        if ename in r["rets"] and h in r["rets"][ename]]
                parts.append(f"{statistics.mean(vals):>+9.2f}%"
                             if vals else f"{'N/A':>10}")
            print(f"  {ename:>14}  {'  '.join(parts)}")

    # ── Median (net 50bps) ──
    print(f"\n{_sep}")
    print(f"MEDIAN EXCESS — NET 50bps  (n={n})")
    print(_sep)
    print(f"  {'entry':>14}     +1h        +4h       +24h")
    for ename, _, _ in _ENTRIES:
        parts = []
        for h in ["1h", "4h", "24h"]:
            vals = [r["rets"][ename][h]["exc"] - 0.50
                    for r in rows
                    if ename in r["rets"] and h in r["rets"][ename]]
            parts.append(f"{statistics.median(vals):>+9.2f}%"
                         if vals else f"{'N/A':>10}")
        print(f"  {ename:>14}  {'  '.join(parts)}")

    # ── Win rate (excess > cost) ──
    print(f"\n{_sep}")
    print(f"WIN RATE (excess > 50bps)  (n={n})")
    print(_sep)
    print(f"  {'entry':>14}     +1h        +4h       +24h")
    for ename, _, _ in _ENTRIES:
        parts = []
        for h in ["1h", "4h", "24h"]:
            vals = [r["rets"][ename][h]["exc"]
                    for r in rows
                    if ename in r["rets"] and h in r["rets"][ename]]
            if vals:
                w = sum(1 for v in vals if v > 0.50)
                parts.append(f" {w:>2}/{len(vals):<2} {w / len(vals) * 100:>4.0f}%")
            else:
                parts.append(f"{'N/A':>10}")
        print(f"  {ename:>14}  {'  '.join(parts)}")

    # ── First candle OHLC ──
    print(f"\n{_sep}")
    print("FIRST CANDLE (1m) OHLC — price discovery violence")
    print(_sep)
    print(f"  {'symbol':>10}  {'open':>12}  {'high':>12}  "
          f"{'low':>12}  {'close':>12}  {'range':>7}  {'1m ret':>7}")

    for r in rows:
        o, hi, lo, c = r["c0"]
        rng = (hi / lo - 1) * 100 if lo > 0 else 0
        ret = (c / o - 1) * 100 if o > 0 else 0

        def _px(p):
            if p >= 100:   return f"${p:>10.2f}"
            if p >= 1:     return f"${p:>10.4f}"
            if p >= 0.01:  return f"${p:>10.6f}"
            return f"${p:>10.8f}"

        print(f"  {r['sym']:>10}  {_px(o)}  {_px(hi)}  {_px(lo)}  "
              f"{_px(c)}  {rng:>+6.0f}%  {ret:>+6.0f}%")


# ── Part 2: Futures arm ───────────────────────────────────────────────

FUTURES_TRADES_FILE = "futures_trades.jsonl"
_F_HORIZONS = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}


def _load_futures_trades():
    if not os.path.exists(FUTURES_TRADES_FILE):
        return {}
    out = {}
    for l in open(FUTURES_TRADES_FILE):
        if l.strip():
            t = json.loads(l)
            out[(t["announce_id"], t["horizon"])] = t
    return out


def _append_futures_trades(new):
    with open(FUTURES_TRADES_FILE, "a") as f:
        for t in new.values():
            f.write(json.dumps(t) + "\n")


def futures_arm():
    """Measure SPOT price drift after futures-launch announcements."""
    random.seed(42)
    events = [e for e in _load_events() if e["source"] == "binance_futures"]
    existing = _load_futures_trades()
    cache = {}
    max_need = max(_F_HORIZONS.values()) + 2
    btc = "BTCUSDT"

    # ── Find which futures events have existing spot klines ──
    measurable = []
    print(f"Checking {len(events)} futures events for spot klines "
          f"at announcement time...")

    for ev in events:
        pair = f"{ev['symbol'].upper()}USDT"
        pub_ms = int(ev["publish_ts"] * 1000)
        pub_ms -= pub_ms % 60_000

        if (pair, pub_ms) not in cache:
            cache[(pair, pub_ms)] = _fetch_1m(pair, pub_ms, max_need)
        kl = cache[(pair, pub_ms)]

        if kl and kl[0][0] <= pub_ms + 60_000:
            measurable.append(ev)

    skip = len(events) - len(measurable)
    print(f"  {len(measurable)} have spot klines at announcement "
          f"({skip} skipped — no spot pair)")

    if not measurable:
        print("\nNo measurable futures events. All futures announcements "
              "preceded the spot listing — the underlying didn't trade on "
              "Binance spot at announcement time.")
        print("\nThis is the finding: Binance's listing flow is "
              "futures-first, so the 'existing token gets futures' "
              "scenario doesn't occur in this dataset.")
        return

    # ── Measure real events ──
    new_trades = {}
    for ev in measurable:
        pair = f"{ev['symbol'].upper()}USDT"
        pub_ms = int(ev["publish_ts"] * 1000)
        pub_ms -= pub_ms % 60_000

        for p in (pair, btc):
            if (p, pub_ms) not in cache:
                cache[(p, pub_ms)] = _fetch_1m(p, pub_ms, max_need)

        a_kl = cache[(pair, pub_ms)]
        b_kl = cache[(btc, pub_ms)]

        for h_label, h_idx in _F_HORIZONS.items():
            key = (ev["announce_id"], h_label)
            if key in existing or len(a_kl) <= h_idx or len(b_kl) <= h_idx:
                continue
            epx = float(a_kl[0][1])
            if epx == 0:
                continue
            new_trades[key] = {
                "announce_id": ev["announce_id"],
                "symbol": ev["symbol"],
                "publish_ts": ev["publish_ts"],
                "horizon": h_label,
                "entry_px": epx,
                "exit_px": float(a_kl[h_idx][4]),
                "btc_entry_px": float(b_kl[0][1]),
                "btc_exit_px": float(b_kl[h_idx][4]),
            }

    if new_trades:
        _append_futures_trades(new_trades)
        print(f"Logged {len(new_trades)} futures trade legs.")

    all_t = {**existing, **new_trades}

    # ── Null comparison: 10 random timestamps per event ──
    null_by_h = {h: [] for h in _F_HORIZONS}
    print("Generating null (10 random timestamps per event, seed=42)...")

    for ev in measurable:
        pair = f"{ev['symbol'].upper()}USDT"
        pub_s = ev["publish_ts"]

        for _ in range(10):
            rand_s = pub_s - random.uniform(7 * 86400, 30 * 86400)
            rand_ms = int(rand_s * 1000)
            rand_ms -= rand_ms % 60_000

            for p in (pair, btc):
                if (p, rand_ms) not in cache:
                    cache[(p, rand_ms)] = _fetch_1m(p, rand_ms, max_need)

            na = cache.get((pair, rand_ms), [])
            nb = cache.get((btc, rand_ms), [])

            for h_label, h_idx in _F_HORIZONS.items():
                if len(na) <= h_idx or len(nb) <= h_idx:
                    continue
                ep = float(na[0][1])
                bp = float(nb[0][1])
                if ep == 0 or bp == 0:
                    continue
                ar = (float(na[h_idx][4]) / ep - 1) * 100
                br = (float(nb[h_idx][4]) / bp - 1) * 100
                null_by_h[h_label].append(ar - br)

    # ── Report ──
    _sep = "=" * 72
    print(f"\n{_sep}")
    print(f"FUTURES ANNOUNCEMENT → SPOT DRIFT  (n={len(measurable)})")
    print(_sep)
    print(f"  {'hz':>6}  {'n':>3}  {'mean exc':>10}  {'med exc':>10}  "
          f"{'wins':>7}  {'null μ':>10}  {'null σ':>8}  {'sep':>6}")

    for h in ["1m", "5m", "15m", "1h", "4h"]:
        reals = []
        for ev in measurable:
            t = all_t.get((ev["announce_id"], h))
            if not t or t["entry_px"] == 0 or t["btc_entry_px"] == 0:
                continue
            ar = (t["exit_px"] / t["entry_px"] - 1) * 100
            br = (t["btc_exit_px"] / t["btc_entry_px"] - 1) * 100
            reals.append(ar - br)

        nulls = null_by_h.get(h, [])
        if not reals:
            print(f"  {h:>6}    —")
            continue

        r_mean = statistics.mean(reals)
        r_med = statistics.median(reals)
        w = sum(1 for v in reals if v > 0)

        if len(nulls) > 1:
            n_mean = statistics.mean(nulls)
            n_std = statistics.stdev(nulls)
            sep = (r_mean - n_mean) / n_std if n_std > 0 else 0
            print(f"  {h:>6}  {len(reals):>3}  {r_mean:>+9.2f}%  "
                  f"{r_med:>+9.2f}%  {w:>2}/{len(reals):<2}  "
                  f"{n_mean:>+9.2f}%  {n_std:>7.2f}%  {sep:>+5.2f}σ")
        else:
            print(f"  {h:>6}  {len(reals):>3}  {r_mean:>+9.2f}%  "
                  f"{r_med:>+9.2f}%  {w:>2}/{len(reals):<2}")

    # Per-event detail
    print(f"\n  Per-event detail (1h excess):")
    for ev in measurable:
        t = all_t.get((ev["announce_id"], "1h"))
        if t and t["entry_px"] > 0 and t["btc_entry_px"] > 0:
            ar = (t["exit_px"] / t["entry_px"] - 1) * 100
            br = (t["btc_exit_px"] / t["btc_entry_px"] - 1) * 100
            print(f"    {ev['symbol']:>10}: {ar - br:>+8.2f}% exc  "
                  f"(spot ${t['entry_px']:.4f} → ${t['exit_px']:.4f})")


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Listing measurement")
    ap.add_argument("cmd", nargs="?", default="measure",
                    choices=["measure", "honest", "futures"])
    args = ap.parse_args()
    {"measure": measure, "honest": honest_entry, "futures": futures_arm
     }[args.cmd]()
