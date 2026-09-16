#!/usr/bin/env python3
"""mm_sim.py — Zero-capital paper-MM simulator on Hyperliquid.

Measures the ONE thing the seat analysis couldn't see: adverse selection.
Records real HL books + trades, simulates passive quotes, tracks fills +
markouts. Runs as a continuous-loop launchd service.

MARKOUT: after a simulated fill, where is mid at +10s/+60s/+5min?
  Positive markout = benign (you keep the spread).
  Negative markout = toxic (informed trader picked you off).

Fill logic is PESSIMISTIC by design:
  - Fill only when a real trade prints AT or THROUGH our price
  - Queue-position pessimism: existing BBO size trades through first
  - No fills assumed from mid-crosses alone

PRE-REGISTERED THRESHOLDS (review after 3-4 weeks):
  BUILD-REAL: markout-adjusted net > $20/day aggregate, <40% negative markouts
  PARK: $0-20/day
  DEAD: negative (seats are adverse-selection traps)
"""

import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
FILLS_FILE = BASE / "mm_sim_fills.jsonl"
STATE_FILE = BASE / "mm_sim_state.json"
LOCK_FILE = Path("/tmp/brain_mmsim.lock")

# ── Configuration ──────────────────────────────────────────────────────

MARKETS = ["MORPHO", "JUP", "PENDLE", "PYTH", "SPX", "FARTCOIN", "BTC"]
QUOTE_SIZE_USD = 200          # per side per market
MAKER_FEE_BPS = 1.0           # default tier, no rebate (honest)
INVENTORY_LIMIT_MULT = 3      # stop quoting a side at 3x quote size
CYCLE_SLEEP_S = 45            # seconds between full market cycles
MARKOUT_HORIZONS_S = [10, 60, 300]  # +10s, +1min, +5min


# ── State management ──────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "inventory": {m: 0.0 for m in MARKETS},
        "pending_markouts": [],  # [{fill_id, ts, coin, side, px, sz, markouts: {}}]
        "last_mids": {},         # {coin: [(ts, mid), ...]}
        "stats": {m: {"fills": 0, "vol_usd": 0, "gross_pnl": 0, "fees": 0}
                  for m in MARKETS},
    }


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def append_fill(fill):
    with open(FILLS_FILE, "a") as f:
        f.write(json.dumps(fill) + "\n")


# ── HL API helpers ─────────────────────────────────────────────────────

def hl_info(payload, timeout=10):
    r = requests.post("https://api.hyperliquid.xyz/info",
                      json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_book(coin):
    return hl_info({"type": "l2Book", "coin": coin})


def get_recent_trades(coin):
    return hl_info({"type": "recentTrades", "coin": coin})


def book_mid(book):
    levels = book.get("levels", [[], []])
    bids, asks = levels[0], levels[1]
    if not bids or not asks:
        return None
    bb = float(bids[0]["px"])
    ba = float(asks[0]["px"])
    return (bb + ba) / 2


def book_bbo(book):
    levels = book.get("levels", [[], []])
    bids, asks = levels[0], levels[1]
    if not bids or not asks:
        return None, None, None, None, None, None
    bb = float(bids[0]["px"])
    ba = float(asks[0]["px"])
    bs = float(bids[0]["sz"])
    as_ = float(asks[0]["sz"])
    bn = int(bids[0].get("n", 1))
    an = int(asks[0].get("n", 1))
    return bb, ba, bs, as_, bn, an


# ── Fill simulation ────────────────────────────────────────────────────

def simulate_fills(coin, our_bid, our_ask, our_size_coins, bbo_bid_sz,
                   bbo_ask_sz, trades, state):
    """Check if real trades would have filled our simulated quotes.

    PESSIMISTIC: we're LAST in queue at each level. The existing BBO size
    must trade through completely before our fill counts.
    """
    fills = []
    now_ms = int(time.time() * 1000)
    inventory = state["inventory"].get(coin, 0.0)
    inv_limit = our_size_coins * INVENTORY_LIMIT_MULT

    for trade in trades:
        trade_px = float(trade["px"])
        trade_sz = float(trade["sz"])
        trade_side = trade["side"]  # B = buyer initiated (taker buys), A = seller initiated
        trade_ts = trade["time"]

        # Taker BUY hits our ASK (we sell to them)
        if trade_side == "B" and our_ask is not None:
            if trade_px >= our_ask:
                # Queue check: existing ask size must be consumed first
                if trade_sz > bbo_ask_sz:
                    # Trade was large enough to eat through the queue + hit us
                    fill_sz = min(our_size_coins, trade_sz - bbo_ask_sz)
                    if fill_sz > 0 and inventory > -inv_limit:
                        fills.append({
                            "fill_id": f"{coin}_{trade_ts}_{trade['tid']}",
                            "ts": trade_ts,
                            "coin": coin,
                            "side": "sell",
                            "px": our_ask,
                            "sz": fill_sz,
                            "sz_usd": fill_sz * our_ask,
                            "trade_px": trade_px,
                            "trade_sz": trade_sz,
                            "markouts": {},
                        })
                        state["inventory"][coin] = inventory - fill_sz
                        inventory = state["inventory"][coin]

        # Taker SELL hits our BID (we buy from them)
        elif trade_side == "A" and our_bid is not None:
            if trade_px <= our_bid:
                if trade_sz > bbo_bid_sz:
                    fill_sz = min(our_size_coins, trade_sz - bbo_bid_sz)
                    if fill_sz > 0 and inventory < inv_limit:
                        fills.append({
                            "fill_id": f"{coin}_{trade_ts}_{trade['tid']}",
                            "ts": trade_ts,
                            "coin": coin,
                            "side": "buy",
                            "px": our_bid,
                            "sz": fill_sz,
                            "sz_usd": fill_sz * our_bid,
                            "trade_px": trade_px,
                            "trade_sz": trade_sz,
                            "markouts": {},
                        })
                        state["inventory"][coin] = inventory + fill_sz
                        inventory = state["inventory"][coin]

    return fills


# ── Markout resolution ─────────────────────────────────────────────────

def resolve_markouts(state, current_mids):
    """Backfill markout data for pending fills using current mid prices."""
    now_ms = int(time.time() * 1000)
    still_pending = []

    for fill in state["pending_markouts"]:
        coin = fill["coin"]
        fill_ts = fill["ts"]
        fill_px = fill["px"]
        side_mult = 1 if fill["side"] == "buy" else -1  # buy: profit if mid goes up
        mid_now = current_mids.get(coin)

        if mid_now is None:
            still_pending.append(fill)
            continue

        elapsed_s = (now_ms - fill_ts) / 1000
        all_resolved = True

        for horizon_s in MARKOUT_HORIZONS_S:
            key = f"mo_{horizon_s}s"
            if key not in fill["markouts"]:
                if elapsed_s >= horizon_s:
                    # Use current mid as the markout price
                    markout = (mid_now - fill_px) * side_mult
                    markout_bps = markout / fill_px * 10000
                    fill["markouts"][key] = {
                        "mid": mid_now,
                        "markout_usd": markout * fill["sz"],
                        "markout_bps": markout_bps,
                        "elapsed_s": elapsed_s,
                    }
                else:
                    all_resolved = False

        if all_resolved:
            # Write completed fill to disk
            append_fill(fill)
            # Update stats
            coin_stats = state["stats"].setdefault(coin, {
                "fills": 0, "vol_usd": 0, "gross_pnl": 0, "fees": 0
            })
            coin_stats["fills"] += 1
            coin_stats["vol_usd"] += fill["sz_usd"]
            # Gross P&L = half-spread captured (simplified)
            # Fee = maker fee on the fill
            fee_usd = fill["sz_usd"] * MAKER_FEE_BPS / 10000
            coin_stats["fees"] += fee_usd
            # Net markout at 5min
            mo_5m = fill["markouts"].get("mo_300s", {}).get("markout_usd", 0)
            coin_stats["gross_pnl"] += mo_5m - fee_usd
        else:
            still_pending.append(fill)

    state["pending_markouts"] = still_pending


# ── One cycle ──────────────────────────────────────────────────────────

def run_one_cycle(state, verbose=False):
    """Run one complete cycle across all markets."""
    now = datetime.now(timezone.utc)
    current_mids = {}
    cycle_fills = 0

    for coin in MARKETS:
        try:
            book = get_book(coin)
            trades = get_recent_trades(coin)
        except Exception as e:
            if verbose:
                print(f"  {coin}: API error ({e})")
            continue

        mid = book_mid(book)
        if mid is None or mid == 0:
            continue
        current_mids[coin] = mid

        bb, ba, bs, as_, bn, an = book_bbo(book)
        if bb is None:
            continue

        spread_bps = (ba - bb) / mid * 10000

        # Our simulated quotes: join the BBO
        our_size_coins = QUOTE_SIZE_USD / mid
        inventory = state["inventory"].get(coin, 0.0)
        inv_limit = our_size_coins * INVENTORY_LIMIT_MULT

        # Inventory guard: don't quote the side that would increase inventory past limit
        our_bid = bb if inventory < inv_limit else None
        our_ask = ba if inventory > -inv_limit else None

        # Simulate fills
        fills = simulate_fills(coin, our_bid, our_ask, our_size_coins,
                               bs, as_, trades, state)

        for fill in fills:
            state["pending_markouts"].append(fill)
            cycle_fills += 1

        if verbose:
            inv = state["inventory"].get(coin, 0)
            inv_usd = inv * mid
            bid_str = f"${bb:.4f}" if our_bid else "PAUSED"
            ask_str = f"${ba:.4f}" if our_ask else "PAUSED"
            print(f"  {coin:>10}  mid=${mid:.4f}  spread={spread_bps:.1f}bp  "
                  f"bbo={bs:.1f}×{as_:.1f}  bid={bid_str}  ask={ask_str}  "
                  f"inv={inv:.2f}(${inv_usd:.0f})  fills={len(fills)}")

        time.sleep(1)  # respect rate limits between markets

    # Resolve pending markouts
    resolve_markouts(state, current_mids)

    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = len(state["pending_markouts"])
    if verbose or cycle_fills > 0:
        print(f"  [{ts}] Cycle done: {cycle_fills} new fills, {pending} pending markouts")

    return cycle_fills


# ── Report ─────────────────────────────────────────────────────────────

def report():
    """Analyze accumulated fill data."""
    if not FILLS_FILE.exists():
        print("No fill data yet.")
        return

    fills = [json.loads(l) for l in open(FILLS_FILE) if l.strip()]
    if not fills:
        print("No completed fills yet.")
        return

    state = load_state()
    n_pending = len(state.get("pending_markouts", []))

    first_ts = min(f["ts"] for f in fills)
    last_ts = max(f["ts"] for f in fills)
    days = max((last_ts - first_ts) / 86400000, 1)

    print(f"\n{'='*72}")
    print(f"  MM SIMULATOR REPORT")
    print(f"{'='*72}")
    print(f"  Period: {datetime.fromtimestamp(first_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d')} "
          f"to {datetime.fromtimestamp(last_ts/1000, tz=timezone.utc).strftime('%Y-%m-%d')} "
          f"({days:.1f} days)")
    print(f"  Total fills: {len(fills)}")
    print(f"  Pending markouts: {n_pending}")

    # Per-market breakdown
    by_coin = defaultdict(list)
    for f in fills:
        by_coin[f["coin"]].append(f)

    print(f"\n  {'coin':>10} {'fills':>6} {'vol$':>10} {'fills/d':>8} "
          f"{'mo10s':>8} {'mo60s':>8} {'mo5m':>8} {'neg%':>5} {'net$/d':>8}")

    total_net = 0
    total_fills = 0
    total_neg = 0
    total_n = 0

    for coin in MARKETS:
        cf = by_coin.get(coin, [])
        if not cf:
            print(f"  {coin:>10} {'0':>6} {'$0':>10}")
            continue

        vol = sum(f["sz_usd"] for f in cf)
        fills_per_day = len(cf) / days
        fees = sum(f["sz_usd"] * MAKER_FEE_BPS / 10000 for f in cf)

        # Markout analysis
        mo_10 = [f["markouts"].get("mo_10s", {}).get("markout_bps", 0) for f in cf
                 if "mo_10s" in f.get("markouts", {})]
        mo_60 = [f["markouts"].get("mo_60s", {}).get("markout_bps", 0) for f in cf
                 if "mo_60s" in f.get("markouts", {})]
        mo_300 = [f["markouts"].get("mo_300s", {}).get("markout_bps", 0) for f in cf
                  if "mo_300s" in f.get("markouts", {})]

        mo_300_usd = [f["markouts"].get("mo_300s", {}).get("markout_usd", 0) for f in cf
                      if "mo_300s" in f.get("markouts", {})]

        neg_pct = (sum(1 for m in mo_300 if m < 0) / len(mo_300) * 100) if mo_300 else 0
        net_usd = sum(mo_300_usd) - fees if mo_300_usd else 0
        net_per_day = net_usd / days

        mo10_med = statistics.median(mo_10) if mo_10 else 0
        mo60_med = statistics.median(mo_60) if mo_60 else 0
        mo300_med = statistics.median(mo_300) if mo_300 else 0

        total_net += net_usd
        total_fills += len(cf)
        total_neg += sum(1 for m in mo_300 if m < 0)
        total_n += len(mo_300)

        print(f"  {coin:>10} {len(cf):>6} ${vol:>8,.0f} {fills_per_day:>7.1f} "
              f"{mo10_med:>+7.1f} {mo60_med:>+7.1f} {mo300_med:>+7.1f} "
              f"{neg_pct:>4.0f}% ${net_per_day:>6.1f}")

    total_neg_pct = (total_neg / total_n * 100) if total_n else 0
    total_per_day = total_net / days

    print(f"\n  AGGREGATE: {total_fills} fills, net ${total_per_day:+.1f}/day, "
          f"{total_neg_pct:.0f}% negative markouts")

    # Pre-registered verdict
    print(f"\n  PRE-REGISTERED THRESHOLDS:")
    print(f"    BUILD-REAL: net > $20/day AND <40% negative markouts")
    print(f"    PARK:       $0-20/day")
    print(f"    DEAD:       negative")

    if days < 14:
        print(f"\n  STATUS: ACCUMULATING ({days:.0f} days, need 21+)")
    else:
        if total_per_day > 20 and total_neg_pct < 40:
            print(f"\n  >>> VERDICT: BUILD-REAL")
        elif total_per_day > 0:
            print(f"\n  >>> VERDICT: PARK")
        else:
            print(f"\n  >>> VERDICT: DEAD")

    # BTC control check
    btc_fills = by_coin.get("BTC", [])
    if btc_fills:
        btc_mo = [f["markouts"].get("mo_300s", {}).get("markout_usd", 0)
                  for f in btc_fills if "mo_300s" in f.get("markouts", {})]
        btc_net = sum(btc_mo)
        btc_per_day = btc_net / days
        print(f"\n  BTC CONTROL: ${btc_per_day:+.1f}/day "
              f"({'GOOD — near-zero as expected' if abs(btc_per_day) < 5 else 'WARNING — check fill logic'})")


# ── Commands ───────────────────────────────────────────────────────────

def cmd_once(args):
    """Run one cycle (manual test)."""
    state = load_state()
    print(f"Running one cycle across {len(MARKETS)} markets...")
    run_one_cycle(state, verbose=True)
    save_state(state)
    print("State saved.")


def cmd_loop(args):
    """Continuous loop (for launchd)."""
    # Single-instance lock
    try:
        os.mkdir(str(LOCK_FILE))
    except FileExistsError:
        print(f"Lock exists: {LOCK_FILE} — another instance running?")
        sys.exit(1)

    try:
        state = load_state()
        cycle = 0
        while True:
            cycle += 1
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            try:
                n_fills = run_one_cycle(state, verbose=False)
                if n_fills > 0 or cycle % 20 == 0:
                    pending = len(state["pending_markouts"])
                    inv_str = "  ".join(f"{c}:{state['inventory'].get(c,0):.2f}"
                                       for c in MARKETS if abs(state["inventory"].get(c, 0)) > 0.01)
                    print(f"[{ts}] cycle={cycle} fills={n_fills} pending={pending} "
                          f"inv=[{inv_str}]")
                save_state(state)
            except Exception as e:
                print(f"[{ts}] cycle={cycle} ERROR: {e}")
            time.sleep(CYCLE_SLEEP_S)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        try:
            os.rmdir(str(LOCK_FILE))
        except OSError:
            pass
        save_state(state)
        print("State saved. Lock released.")


def cmd_report(args):
    """Print analysis report."""
    report()


def cmd_status(args):
    """Quick status."""
    state = load_state()
    fills = []
    if FILLS_FILE.exists():
        fills = [json.loads(l) for l in open(FILLS_FILE) if l.strip()]
    pending = len(state.get("pending_markouts", []))
    inv = {c: v for c, v in state.get("inventory", {}).items() if abs(v) > 0.01}
    print(f"Completed fills: {len(fills)}")
    print(f"Pending markouts: {pending}")
    print(f"Inventory: {json.dumps(inv) if inv else 'flat'}")
    stats = state.get("stats", {})
    for coin, s in stats.items():
        if s.get("fills", 0) > 0:
            print(f"  {coin}: {s['fills']} fills, ${s['vol_usd']:,.0f} vol, "
                  f"net ${s['gross_pnl']:.2f}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once", help="Run one cycle (manual test)")
    sub.add_parser("loop", help="Continuous loop (for launchd)")
    sub.add_parser("report", help="Analysis report")
    sub.add_parser("status", help="Quick status")
    args = ap.parse_args()
    {"once": cmd_once, "loop": cmd_loop, "report": cmd_report,
     "status": cmd_status}[args.cmd](args)
