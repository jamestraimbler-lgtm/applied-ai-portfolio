"""Forward logger for funding-carry viability on NL-accessible venues.

STEP 0 of analysis/deployment_basket.md: log perp funding + book spreads on
Deribit and Hyperliquid, and spot book spreads on Kraken (the spot leg).
Measurement only — no orders, no keys, no advice.

Companion to paper_carry.py (which logs Binance as the backtest-reference
venue; keep both running).

Funding normalization table:
  Venue        Quoted period   Conversion to APR
  ──────────── ──────────────  ──────────────────
  Deribit      8h (funding_8h) funding_8h * (8760/8) * 100
  Hyperliquid  1h (hourly)     funding   * (8760/1) * 100
  Binance      8h (reference)  rate      * (8760/8) * 100
"""

import argparse, json, os, statistics, time
from datetime import datetime, timezone

import requests

SNAPSHOTS_FILE = "venue_carry_snapshots.jsonl"
BINANCE_SNAPSHOTS = "paper_carry_snapshots.jsonl"

# The 12 tokens that survived 2x fees in the funding carry backtest
# (same list as paper_carry.py — the canonical source)
WINNERS = [
    "BTC", "ETH", "BNB", "XRP", "DOGE", "ADA",
    "LINK", "UNI", "LTC", "NEAR", "SUI", "ARB",
]

# ── Deribit ──────────────────────────────────────────────────────────────

def _deribit_discover_instruments():
    """Discover available perpetual instruments on Deribit."""
    instruments = {}
    # Inverse perps (coin-margined): BTC, ETH
    for ccy in ("BTC", "ETH"):
        name = f"{ccy}-PERPETUAL"
        instruments[ccy] = instruments.get(ccy, [])
        instruments[ccy].append({"instrument_name": name, "margin_type": "inverse"})

    # Linear (USDC-margined) perps
    try:
        resp = requests.get(
            "https://www.deribit.com/api/v2/public/get_instruments",
            params={"currency": "USDC", "kind": "future"},
            timeout=15,
        ).json()
        for inst in resp.get("result", []):
            name = inst["instrument_name"]
            if not name.endswith("-PERPETUAL"):
                continue
            base = inst.get("base_currency", name.split("_")[0].split("-")[0])
            if base in WINNERS:
                instruments.setdefault(base, [])
                instruments[base].append({"instrument_name": name, "margin_type": "linear"})
    except Exception as e:
        print(f"  [deribit] USDC instrument discovery failed: {e}")

    return instruments


def _deribit_snapshot(now):
    """Fetch Deribit perp tickers for all discoverable winner instruments."""
    rows = []
    instruments = _deribit_discover_instruments()
    if not instruments:
        print("  [deribit] no instruments discovered")
        return rows

    for sym, insts in sorted(instruments.items()):
        for inst in insts:
            name = inst["instrument_name"]
            try:
                resp = requests.get(
                    "https://www.deribit.com/api/v2/public/ticker",
                    params={"instrument_name": name},
                    timeout=15,
                ).json()
                r = resp.get("result", {})
                bid = r.get("best_bid_price")
                ask = r.get("best_ask_price")
                mark = r.get("mark_price")
                index = r.get("index_price")
                funding = r.get("current_funding")
                funding_8h = r.get("funding_8h")
                oi = r.get("open_interest")

                if bid and ask and bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    spread_bps = (ask - bid) / mid * 10_000
                else:
                    spread_bps = None

                # Deribit quotes funding_8h as the 8-hour rate
                raw = funding_8h
                period_h = 8
                apr = raw * (8760 / period_h) * 100 if raw is not None else None

                rows.append({
                    "ts": now,
                    "venue": "deribit",
                    "symbol": sym,
                    "instrument": name,
                    "margin_type": inst["margin_type"],
                    "bid": bid,
                    "ask": ask,
                    "spread_bps": round(spread_bps, 3) if spread_bps is not None else None,
                    "mark": mark,
                    "funding_raw": raw,
                    "funding_period_h": period_h,
                    "funding_apr": round(apr, 4) if apr is not None else None,
                    "open_interest": oi,
                })
            except Exception as e:
                rows.append({
                    "ts": now, "venue": "deribit", "symbol": sym,
                    "instrument": name, "margin_type": inst["margin_type"],
                    "error": str(e),
                })
    return rows


# ── Hyperliquid ──────────────────────────────────────────────────────────

def _hl_snapshot(now):
    """Fetch Hyperliquid perp funding + book spreads for winner tokens."""
    rows = []
    try:
        meta_resp = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "metaAndAssetCtxs"},
            timeout=15,
        ).json()
    except Exception as e:
        print(f"  [hyperliquid] meta call failed: {e}")
        return rows

    # meta_resp is [meta, assetCtxs]
    if not isinstance(meta_resp, list) or len(meta_resp) < 2:
        print(f"  [hyperliquid] unexpected meta shape: {type(meta_resp)}")
        return rows

    meta, ctxs = meta_resp[0], meta_resp[1]
    assets = meta.get("universe", [])

    # Build name→ctx map
    asset_map = {}
    for i, a in enumerate(assets):
        name = a.get("name", "")
        if i < len(ctxs):
            asset_map[name] = ctxs[i]

    listed = set(asset_map.keys())
    for sym in WINNERS:
        if sym not in listed:
            continue
        ctx = asset_map[sym]
        funding_raw = float(ctx.get("funding", 0))
        mark = float(ctx.get("markPx", 0))
        oi = float(ctx.get("openInterest", 0))

        # Hyperliquid funding is HOURLY
        period_h = 1
        apr = funding_raw * (8760 / period_h) * 100

        # Fetch L2 book for spread
        bid = ask = spread_bps = None
        try:
            time.sleep(0.2)
            book = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "l2Book", "coin": sym},
                timeout=10,
            ).json()
            levels = book.get("levels", [[], []])
            if levels[0] and levels[1]:
                bid = float(levels[0][0].get("px", 0))
                ask = float(levels[1][0].get("px", 0))
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    spread_bps = round((ask - bid) / mid * 10_000, 3)
        except Exception as e:
            print(f"  [hyperliquid] book for {sym} failed: {e}")

        rows.append({
            "ts": now,
            "venue": "hyperliquid",
            "symbol": sym,
            "instrument": f"{sym}-PERP",
            "margin_type": "linear",
            "bid": bid,
            "ask": ask,
            "spread_bps": spread_bps,
            "mark": mark,
            "funding_raw": funding_raw,
            "funding_period_h": period_h,
            "funding_apr": round(apr, 4),
            "open_interest": oi,
        })
    return rows


# ── Kraken spot ──────────────────────────────────────────────────────────

# Kraken pair naming is irregular; map winners to known pairs
_KRAKEN_PAIR_MAP = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "XRP": "XRPUSD",
    "DOGE": "XDGUSD",  # Kraken calls DOGE "XDG"
}


def _kraken_discover_pairs():
    """Discover which WINNERS have USD pairs on Kraken."""
    pairs = dict(_KRAKEN_PAIR_MAP)
    try:
        resp = requests.get(
            "https://api.kraken.com/0/public/AssetPairs",
            timeout=15,
        ).json()
        all_pairs = resp.get("result", {})
        for pname, pinfo in all_pairs.items():
            base = pinfo.get("base", "")
            quote = pinfo.get("quote", "")
            # Kraken uses X-prefixed and Z-prefixed names sometimes
            base_clean = base.lstrip("XZ") if len(base) > 3 else base
            if base_clean == "XBT":
                base_clean = "BTC"
            if quote not in ("ZUSD", "USD"):
                continue
            if base_clean in WINNERS and base_clean not in pairs:
                pairs[base_clean] = pname
    except Exception as e:
        print(f"  [kraken] pair discovery failed: {e}")
    return pairs


def _kraken_snapshot(now):
    """Fetch Kraken spot ticker for winner tokens."""
    rows = []
    pairs = _kraken_discover_pairs()
    if not pairs:
        return rows

    pair_str = ",".join(pairs.values())
    try:
        resp = requests.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": pair_str},
            timeout=15,
        ).json()
        if resp.get("error"):
            print(f"  [kraken] API error: {resp['error']}")
    except Exception as e:
        print(f"  [kraken] request failed: {e}")
        return rows

    result = resp.get("result", {})
    # Build reverse map: kraken_name → our symbol
    # Kraken returns mangled names (XXBTZUSD for XBTUSD), so match flexibly
    rev = {v: k for k, v in pairs.items()}

    for kname, data in result.items():
        sym = rev.get(kname)
        if not sym:
            # Kraken prepends X to crypto, Z to fiat: XXBTZUSD = X+XBT+Z+USD
            for s, p in pairs.items():
                if p in kname or kname.startswith("X" + p.replace("USD", "ZUSD")):
                    sym = s
                    break
        if not sym:
            continue

        bid = float(data["b"][0])  # best bid
        ask = float(data["a"][0])  # best ask
        mid = (bid + ask) / 2
        spread_bps = round((ask - bid) / mid * 10_000, 3) if mid > 0 else None

        rows.append({
            "ts": now,
            "venue": "kraken",
            "symbol": sym,
            "instrument": pairs.get(sym, f"{sym}USD"),
            "margin_type": "spot",
            "bid": bid,
            "ask": ask,
            "spread_bps": spread_bps,
            "mark": mid,
            "funding_raw": None,
            "funding_period_h": None,
            "funding_apr": None,
            "open_interest": None,
        })
    return rows


# ── Commands ─────────────────────────────────────────────────────────────

def snapshot():
    """Fetch all venues, append rows, print summary table."""
    now = time.time()
    print(f"Token universe: {', '.join(WINNERS)}")

    all_rows = []
    for label, fetcher in [("Deribit", _deribit_snapshot),
                           ("Hyperliquid", _hl_snapshot),
                           ("Kraken", _kraken_snapshot)]:
        try:
            rows = fetcher(now)
            all_rows.extend(rows)
        except Exception as e:
            print(f"  [{label}] VENUE FAILED: {e}")
            all_rows.append({"ts": now, "venue": label.lower(), "error": str(e)})

    # Persist
    with open(SNAPSHOTS_FILE, "a") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")

    # Report unlisted tokens
    perp_venues = {"deribit", "hyperliquid"}
    listed_by_venue = {}
    for r in all_rows:
        v = r.get("venue", "")
        if v in perp_venues and "error" not in r:
            listed_by_venue.setdefault(v, set()).add(r.get("symbol"))

    all_listed = set()
    for s in listed_by_venue.values():
        all_listed |= s
    unlisted = [w for w in WINNERS if w not in all_listed]
    if unlisted:
        print(f"\n  UNLISTED on all perp venues: {', '.join(unlisted)}")

    # Summary table
    ts_str = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok_rows = [r for r in all_rows if "error" not in r]
    err_rows = [r for r in all_rows if "error" in r]
    print(f"\nSnapshot at {ts_str}: {len(ok_rows)} rows, {len(err_rows)} errors")
    print(f"  {'venue':>12}  {'sym':>5}  {'instrument':>20}  {'margin':>8}  "
          f"{'spread':>8}  {'fund_apr':>10}  {'OI':>12}")
    for r in ok_rows:
        sp = f"{r['spread_bps']:.2f}bp" if r.get("spread_bps") is not None else "n/a"
        fa = f"{r['funding_apr']:+.2f}%" if r.get("funding_apr") is not None else "n/a"
        oi = f"{r['open_interest']:.0f}" if r.get("open_interest") is not None else "n/a"
        print(f"  {r['venue']:>12}  {r['symbol']:>5}  {r['instrument']:>20}  "
              f"{r.get('margin_type',''):>8}  {sp:>8}  {fa:>10}  {oi:>12}")

    # Sanity: flag any |funding_apr| > 200%
    for r in ok_rows:
        apr = r.get("funding_apr")
        if apr is not None and abs(apr) > 200:
            print(f"  WARNING: {r['venue']} {r['symbol']} funding_apr={apr:.1f}% "
                  f"— probable unit bug (raw={r.get('funding_raw')}, "
                  f"period={r.get('funding_period_h')}h)")

    for r in err_rows:
        print(f"  ERROR: {r.get('venue')} {r.get('instrument', r.get('symbol', '?'))}: "
              f"{r.get('error')}")


def report():
    """Per-venue+symbol summary over all snapshots, with Binance comparison."""
    if not os.path.exists(SNAPSHOTS_FILE):
        print("No snapshots yet.")
        return

    rows = [json.loads(l) for l in open(SNAPSHOTS_FILE) if l.strip()]
    rows = [r for r in rows if "error" not in r]
    n_events = len(set(round(r["ts"]) for r in rows))
    print(f"Venue carry report — {len(rows)} rows, {n_events} capture events\n")

    # Load Binance reference
    binance_ref = {}
    if os.path.exists(BINANCE_SNAPSHOTS):
        brows = [json.loads(l) for l in open(BINANCE_SNAPSHOTS) if l.strip()]
        for r in brows:
            sym = r.get("symbol")
            binance_ref.setdefault(sym, []).append(r)

    # Group by venue+symbol
    groups = {}
    for r in rows:
        key = (r["venue"], r["symbol"])
        groups.setdefault(key, []).append(r)

    print(f"  {'venue':>12}  {'sym':>5}  {'n':>4}  {'med spread':>11}  "
          f"{'med fund_apr':>12}  {'%pos fund':>10}  {'binance ref':>12}")

    unlisted_all = set()
    perp_listed = set()

    for (venue, sym), recs in sorted(groups.items()):
        if venue in ("deribit", "hyperliquid"):
            perp_listed.add(sym)

        spreads = [r["spread_bps"] for r in recs if r.get("spread_bps") is not None]
        aprs = [r["funding_apr"] for r in recs if r.get("funding_apr") is not None]

        med_sp = statistics.median(spreads) if spreads else None
        med_apr = statistics.median(aprs) if aprs else None
        pct_pos = sum(1 for a in aprs if a > 0) / len(aprs) * 100 if aprs else None

        # Binance reference (median funding APR for same symbol)
        bref = binance_ref.get(sym, [])
        bin_apr = None
        if bref:
            bin_rates = [r["funding_rate"] for r in bref]
            bin_apr = statistics.median(bin_rates) * 3 * 365 * 100  # 8h→annual

        sp_str = f"{med_sp:.2f}bp" if med_sp is not None else "n/a"
        apr_str = f"{med_apr:+.2f}%" if med_apr is not None else "n/a"
        pos_str = f"{pct_pos:.0f}%" if pct_pos is not None else "n/a"
        bin_str = f"{bin_apr:+.2f}%" if bin_apr is not None else "n/a"

        print(f"  {venue:>12}  {sym:>5}  {len(recs):>4}  {sp_str:>11}  "
              f"{apr_str:>12}  {pos_str:>10}  {bin_str:>12}")

    unlisted_all = set(WINNERS) - perp_listed
    if unlisted_all:
        print(f"\n  Winner tokens not on any NL perp venue: {', '.join(sorted(unlisted_all))}")

    print(f"\n  Verdict input only after ~14 days of snapshots.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Venue carry logger (NL-accessible)")
    ap.add_argument("cmd", choices=["snapshot", "report"])
    args = ap.parse_args()
    {"snapshot": snapshot, "report": report}[args.cmd]()
