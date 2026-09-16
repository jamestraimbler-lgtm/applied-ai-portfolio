"""Token-unlock structural probe (arm #10).

Tests whether cliff-type token unlocks (>= 1% of circulating supply) produce
a fillable short-side edge. Pre-registered in unlock_prereg.json BEFORE any
measurement code was written.

Windows (all vs BTC excess):
  anticipation  T-30d → T-7d   (context only)
  fillable      T-7d  → T+1d   (PRIMARY — realistic perp short entry to cover)
  post          T+1d  → T+7d   (context only)

Direction: short (sell pressure hypothesis). Measurement via Binance hourly
klines (measurer.py infra). Raw price legs stored write-once to
unlock_trades.jsonl (paper_book pattern). Costs derived at read time.

CLI:
  sync     — refresh calendar from DefiLlama, log new qualifying events
  measure  — fetch raw price legs for matured event windows
  placebo  — generate matched control timestamps
  verdict  — load prereg, compute stats, print verdict (gated on min_sample)
"""

import argparse, json, os, random, statistics, time
from datetime import datetime, timezone

import numpy as np

from measurer import _fetch_klines, _pair
from validation import PreRegistration, permutation_test, bootstrap_ci, holm_bonferroni

EVENTS_FILE = "unlock_events.jsonl"
TRADES_FILE = "unlock_trades.jsonl"
PLACEBOS_FILE = "unlock_placebos.jsonl"
PREREG_FILE = "unlock_prereg.json"

# Window definitions (seconds)
_DAY = 86400
WINDOWS = {
    "anticipation": (-30 * _DAY, -7 * _DAY),   # T-30d → T-7d
    "fillable":     (-7 * _DAY,   1 * _DAY),    # T-7d  → T+1d  (PRIMARY)
    "post":         (1 * _DAY,    7 * _DAY),     # T+1d  → T+7d
}

# Window → kline hours needed
def _window_hours(start_offset: int, end_offset: int) -> int:
    return abs(end_offset - start_offset) // 3600


# ── Load/persist helpers ─────────────────────────────────────────────

def _load_events() -> list[dict]:
    if not os.path.exists(EVENTS_FILE):
        return []
    return [json.loads(l) for l in open(EVENTS_FILE) if l.strip()]


def _load_trades() -> dict[tuple[str, int, str], dict]:
    """Keyed on (symbol, unlock_ts, window)."""
    if not os.path.exists(TRADES_FILE):
        return {}
    out = {}
    for line in open(TRADES_FILE):
        line = line.strip()
        if line:
            t = json.loads(line)
            out[(t["symbol"], t["unlock_ts"], t["window"])] = t
    return out


def _load_placebos() -> list[dict]:
    if not os.path.exists(PLACEBOS_FILE):
        return []
    return [json.loads(l) for l in open(PLACEBOS_FILE) if l.strip()]


# ── Rate-limit-aware kline fetch ─────────────────────────────────────

def _fetch_klines_safe(pair: str, start_ms: int, limit: int = 80) -> list:
    """Wrapper around _fetch_klines with 429/ban retry."""
    import requests as _req
    params: dict = {"symbol": pair, "interval": "1h", "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    for attempt in range(2):
        try:
            r = _req.get("https://api.binance.com/api/v3/klines",
                         params=params, timeout=15)
        except Exception:
            if attempt == 0:
                time.sleep(60)
                continue
            return []
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 418) or b"-1003" in r.content:
            if attempt == 0:
                print(f"    [rate-limit] {pair} — sleeping 60s...")
                time.sleep(60)
                continue
            raise SystemExit("Binance ban persists after retry — rerun later (command is resumable)")
        return []
    return []


# ── Kline-based measurement ─────────────────────────────────────────

def _measure_window(symbol: str, unlock_ts: int, window_name: str,
                    cache: dict) -> dict | None:
    """Fetch raw price legs for one event+window. Returns dict or None."""
    start_off, end_off = WINDOWS[window_name]
    entry_ts = unlock_ts + start_off
    exit_ts = unlock_ts + end_off

    # Floor to hour boundary
    entry_ms = entry_ts * 1000
    entry_ms = entry_ms - (entry_ms % 3_600_000)

    n_hours = _window_hours(start_off, end_off)
    limit = n_hours + 5  # small buffer

    pair = _pair(symbol)
    btc_pair = _pair("BTC")

    def _cached_kl(p, ms):
        key = (p, ms)
        if key not in cache:
            cache[key] = _fetch_klines_safe(p, ms, limit=min(limit, 1000))
            time.sleep(0.15)
        return cache[key]

    a_kl = _cached_kl(pair, entry_ms)
    b_kl = _cached_kl(btc_pair, entry_ms)

    if len(a_kl) < n_hours or len(b_kl) < n_hours:
        return None

    # Entry = close of first candle, exit = close of candle at n_hours
    ae = float(a_kl[0][4])
    ax = float(a_kl[n_hours - 1][4])
    be = float(b_kl[0][4])
    bx = float(b_kl[n_hours - 1][4])

    if ae == 0 or be == 0:
        return None

    return {
        "symbol": symbol,
        "unlock_ts": unlock_ts,
        "window": window_name,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_px": ae,
        "exit_px": ax,
        "btc_entry_px": be,
        "btc_exit_px": bx,
    }


# ── Commands ─────────────────────────────────────────────────────────

def cmd_sync(_args):
    """Refresh calendar from DefiLlama, log new qualifying events."""
    from sources.unlocks import fetch_unlock_calendar
    fetch_unlock_calendar()


def cmd_measure(_args):
    """Fetch raw price legs for matured event windows."""
    events = _load_events()
    if not events:
        print("No events. Run sync first.")
        return

    existing = _load_trades()
    now = time.time()

    # Skip events before 2020 — Binance kline history is unreliable earlier
    min_ts = 1577836800  # 2020-01-01

    # Only measure windows that are fully matured
    new_trades = []
    cache = {}
    n_checked = 0
    n_skipped_old = 0
    # Track symbols that fail (no klines) to avoid re-trying
    dead_syms: set[str] = set()

    for ev in events:
        sym = ev["symbol"]
        uts = ev["unlock_ts"]

        if uts < min_ts:
            n_skipped_old += 1
            continue
        if sym in dead_syms:
            continue

        for wname, (start_off, end_off) in WINDOWS.items():
            exit_ts = uts + end_off
            if exit_ts > now:
                continue  # not matured
            if (sym, uts, wname) in existing:
                continue  # already logged

            n_checked += 1
            result = _measure_window(sym, uts, wname, cache)
            if result:
                new_trades.append(result)
            elif wname == "fillable":
                # If the primary window fails, the symbol likely has no data
                dead_syms.add(sym)
                break

        # Flush periodically to avoid losing progress
        if len(new_trades) >= 50:
            with open(TRADES_FILE, "a") as f:
                for t in sorted(new_trades, key=lambda x: (x["unlock_ts"], x["window"])):
                    f.write(json.dumps(t) + "\n")
            existing.update({(t["symbol"], t["unlock_ts"], t["window"]): t for t in new_trades})
            print(f"  flushed {len(new_trades)} trades (checked {n_checked})...")
            new_trades = []

    if new_trades:
        with open(TRADES_FILE, "a") as f:
            for t in sorted(new_trades, key=lambda x: (x["unlock_ts"], x["window"])):
                f.write(json.dumps(t) + "\n")

    all_trades = _load_trades()
    print(f"Logged trades (checked {n_checked}, skipped {n_skipped_old} pre-2020, "
          f"{len(dead_syms)} dead symbols).")

    by_window: dict[str, list] = {}
    for (_, _, w), t in all_trades.items():
        by_window.setdefault(w, []).append(t)
    for w in WINDOWS:
        print(f"  {w}: {len(by_window.get(w, []))} trades")


def cmd_placebo(_args):
    """Generate matched placebos AND measure them (stored with excess)."""
    events = _load_events()
    if not events:
        print("No events. Run sync first.")
        return

    # Only generate placebos for events that have a measured fillable trade
    trades = _load_trades()
    measurable = {(sym, uts) for (sym, uts, w) in trades if w == "fillable"}
    events = [ev for ev in events if (ev["symbol"], ev["unlock_ts"]) in measurable]
    print(f"  {len(measurable)} events with measured fillable trades")

    existing_placebos = _load_placebos()
    existing_keys = {(p["symbol"], p["unlock_ts"], p["placebo_unlock_ts"])
                     for p in existing_placebos if "excess" in p}

    # Build per-symbol event timestamps for exclusion
    sym_event_ts: dict[str, list[int]] = {}
    for ev in events:
        sym_event_ts.setdefault(ev["symbol"], []).append(ev["unlock_ts"])

    rng = random.Random(42)
    now = time.time()
    min_ts = 1577836800  # 2020-01-01 (match measure cutoff)

    # Generate placebo timestamps
    candidates = []
    already_generated = {(p["symbol"], p["unlock_ts"]) for p in existing_placebos}

    for ev in events:
        sym = ev["symbol"]
        uts = ev["unlock_ts"]
        if (sym, uts) in already_generated:
            continue

        real_ts_list = sym_event_ts.get(sym, [])
        attempts = 0
        generated = 0
        while generated < 5 and attempts < 100:
            attempts += 1
            shift = rng.uniform(60 * _DAY, 365 * _DAY)
            placebo_unlock_ts = int(uts - shift)

            if placebo_unlock_ts < min_ts:
                continue

            # Exclude if within 73h of any real event for this symbol
            contaminated = False
            for rts in real_ts_list:
                if abs(placebo_unlock_ts - rts) < 73 * 3600:
                    contaminated = True
                    break
            if contaminated:
                continue

            _, fillable_end_off = WINDOWS["fillable"]
            if placebo_unlock_ts + fillable_end_off > now:
                continue

            candidates.append({
                "symbol": sym,
                "unlock_ts": uts,
                "placebo_unlock_ts": placebo_unlock_ts,
            })
            generated += 1

    # Measure each placebo window and store with excess
    cache = {}
    new_placebos = []
    dead_syms: set[str] = set()

    for i, c in enumerate(candidates):
        sym = c["symbol"]
        puts = c["placebo_unlock_ts"]
        key = (sym, c["unlock_ts"], puts)
        if key in existing_keys or sym in dead_syms:
            continue

        excess: dict[str, float] = {}
        for wname in WINDOWS:
            result = _measure_window(sym, puts, wname, cache)
            if result:
                ar = result["exit_px"] / result["entry_px"] - 1
                br = result["btc_exit_px"] / result["btc_entry_px"] - 1
                excess[wname] = -(ar - br)  # short direction
            elif wname == "fillable":
                dead_syms.add(sym)
                break

        if not excess:
            continue

        new_placebos.append({
            "symbol": sym,
            "unlock_ts": c["unlock_ts"],
            "placebo_unlock_ts": puts,
            "excess": excess,
            "logged_at": now,
        })

        if len(new_placebos) % 50 == 0:
            with open(PLACEBOS_FILE, "a") as f:
                for p in new_placebos[-50:]:
                    f.write(json.dumps(p) + "\n")
            print(f"  flushed {len(new_placebos)} placebos...")

    # Flush remaining
    remainder = len(new_placebos) % 50
    if remainder > 0:
        with open(PLACEBOS_FILE, "a") as f:
            for p in new_placebos[-remainder:]:
                f.write(json.dumps(p) + "\n")

    print(f"Logged {len(new_placebos)} new placebos ({len(dead_syms)} dead symbols skipped).")

    all_placebos = _load_placebos()
    n_with_excess = sum(1 for p in all_placebos if "excess" in p)
    n_events_covered = len({(p["symbol"], p["unlock_ts"]) for p in all_placebos})
    print(f"  Total: {len(all_placebos)} placebos ({n_with_excess} measured), "
          f"covering {n_events_covered} events")


def cmd_verdict(_args):
    """Load prereg, compute per-window excess, print verdict."""
    if not os.path.exists(PREREG_FILE):
        print(f"Pre-registration not found: {PREREG_FILE}")
        return
    prereg, fingerprint, locked_at = PreRegistration.load(PREREG_FILE)
    print(f"Pre-registration: {fingerprint} (locked {locked_at})")
    print(f"  min_sample={prereg.min_sample}, alpha={prereg.alpha}, "
          f"min_effect={prereg.min_effect}")
    print()

    trades = _load_trades()
    placebos = _load_placebos()

    if not trades:
        print("No trades. Run measure first.")
        return

    # Compute excess returns for real events (direction = SHORT = -1)
    # Short excess = -(asset_ret - btc_ret) = btc_ret - asset_ret
    real_excess: dict[str, list[float]] = {w: [] for w in WINDOWS}
    real_events_by_window: dict[str, set] = {w: set() for w in WINDOWS}

    for (sym, uts, w), t in trades.items():
        asset_ret = t["exit_px"] / t["entry_px"] - 1
        btc_ret = t["btc_exit_px"] / t["btc_entry_px"] - 1
        excess = -(asset_ret - btc_ret)  # short direction
        real_excess[w].append(excess)
        real_events_by_window[w].add((sym, uts))

    # Load pre-measured placebo excess from placebos file
    placebo_excess: dict[str, list[float]] = {w: [] for w in WINDOWS}
    n_with_excess = 0
    for p in placebos:
        ex = p.get("excess", {})
        if not ex:
            continue
        n_with_excess += 1
        for w in WINDOWS:
            if w in ex:
                placebo_excess[w].append(ex[w])
    print(f"Loaded {n_with_excess} measured placebos from file")
    print()

    # Print results per window
    print("UNLOCK PROBE — RESULTS")
    print(f"  prereg: {fingerprint}")
    print(f"  historical arm (post-hoc measurement of pre-scheduled events)")
    print(f"  forward log continues to n={prereg.min_sample}+ for the formal verdict")
    print()

    cost_scenarios = [15, 30, 50]  # bps
    primary_window = "fillable"
    primary_n = len(real_excess.get(primary_window, []))
    sample_ok = primary_n >= prereg.min_sample

    print(f"  {'window':>14}  {'n':>4}  {'n_ev':>4}  {'mean':>8}  {'median':>8}  "
          f"{'placebo':>8}  {'p-value':>8}  {'95% CI':>22}")

    p_values = {}
    for w in WINDOWS:
        r_arr = np.asarray(real_excess[w])
        p_arr = np.asarray(placebo_excess[w])
        n_ev = len(real_events_by_window[w])

        if r_arr.size == 0:
            print(f"  {w:>14}  {'—':>4}")
            continue

        mean, ci_lo, ci_hi = bootstrap_ci(r_arr, seed=0)
        med = float(np.median(r_arr))
        p_mean = float(p_arr.mean()) if p_arr.size else float("nan")
        pval = permutation_test(r_arr, p_arr, seed=0) if p_arr.size else float("nan")
        p_values[w] = pval

        ci_str = f"[{ci_lo:+.4f},{ci_hi:+.4f}]"
        sig_mark = ""
        if not np.isnan(pval) and pval < prereg.alpha:
            sig_mark = " *"
        print(f"  {w:>14}  {r_arr.size:>4}  {n_ev:>4}  {mean:>+.4f}  {med:>+.4f}  "
              f"{p_mean:>+.4f}  {pval:>.4f}  {ci_str}{sig_mark}")

    # Holm correction across windows
    if p_values:
        survives = holm_bonferroni(p_values, prereg.alpha)
        print()
        print("  Holm-Bonferroni correction:")
        for w, s in survives.items():
            print(f"    {w}: {'SURVIVES' if s else 'does not survive'}")

    # Cost sensitivity (fillable window only)
    fill_arr = np.asarray(real_excess.get(primary_window, []))
    if fill_arr.size > 0:
        print()
        print("  Net-of-cost (fillable window):")
        for bps in cost_scenarios:
            cost = bps / 10_000
            net = fill_arr - cost
            net_mean = float(net.mean())
            net_wins = int((net > 0).sum())
            print(f"    {bps:>3}bps:  mean {net_mean:>+.4f}  "
                  f"hits {net_wins}/{fill_arr.size} ({net_wins/fill_arr.size:.0%})")

    # Verdict
    print()
    if not sample_ok:
        print(f"  VERDICT WITHHELD — only {primary_n} fillable-window events "
              f"(need {prereg.min_sample})")
    else:
        fill_pval = p_values.get(primary_window, float("nan"))
        fill_mean = float(fill_arr.mean()) if fill_arr.size else 0
        fill_survives = survives.get(primary_window, False) if p_values else False
        cost_30 = fill_mean - 30 / 10_000

        passed = (fill_survives
                  and fill_mean >= prereg.min_effect
                  and cost_30 > 0)

        if passed:
            print(f"  VERDICT: THESIS SUPPORTED — fillable leg significant "
                  f"(p={fill_pval:.4f}), effect {fill_mean:+.4f} > {prereg.min_effect}, "
                  f"net-of-30bps {cost_30:+.4f}")
        else:
            reasons = []
            if not fill_survives:
                reasons.append(f"p={fill_pval:.4f} does not survive Holm correction")
            if fill_mean < prereg.min_effect:
                reasons.append(f"effect {fill_mean:+.4f} < {prereg.min_effect}")
            if cost_30 <= 0:
                reasons.append(f"net-of-30bps {cost_30:+.4f} <= 0")
            print(f"  VERDICT: NOT SUPPORTED — {'; '.join(reasons)}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    sub.add_parser("measure")
    sub.add_parser("placebo")
    sub.add_parser("verdict")
    args = ap.parse_args()
    {"sync": cmd_sync, "measure": cmd_measure,
     "placebo": cmd_placebo, "verdict": cmd_verdict}[args.cmd](args)


if __name__ == "__main__":
    main()
