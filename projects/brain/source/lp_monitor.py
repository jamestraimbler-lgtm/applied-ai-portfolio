"""Forward-only logger for stable-LP edge validation.

Logs live pool state (fee APY, TVL, peg deviation) for the confirmed
USDC/USDT stable-pair LP. Validates whether the backtested +5.5% fee
yield persists and whether the stablecoin peg holds.
"""

import json, os, time
from datetime import datetime, timezone

import requests

SNAPSHOTS_FILE = "lp_monitor_snapshots.jsonl"

# Confirmed stable pool + cross-checks
POOLS = [
    {"name": "USDC/USDT Uniswap (Ethereum)",
     "id": "e737d721-f45c-40f0-9793-9f56261862b9"},
    {"name": "USDC/USDT Curve (Ethereum)",
     "id": "e8dda16a-ad63-4925-b234-06861cff79c7"},
]

BACKTEST_APY = 5.5  # the backtested baseline to compare against


def snapshot():
    """Capture current stable-pool state + peg deviation."""
    now = time.time()
    rows = []

    # ── Peg check: USDC/USDT from Binance ──
    peg_dev = None
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/bookTicker",
                         params={"symbol": "USDCUSDT"}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            mid = (float(d["bidPrice"]) + float(d["askPrice"])) / 2
            peg_dev = (mid - 1.0) * 10_000  # bps from 1.0000
    except Exception as e:
        print(f"  peg check failed: {e}")

    # ── Pool data from DefiLlama ──
    try:
        r = requests.get("https://yields.llama.fi/pools", timeout=30)
        if r.status_code != 200:
            print(f"  DefiLlama pools failed: {r.status_code}")
            return
        all_pools = {p["pool"]: p for p in r.json().get("data", [])}
    except Exception as e:
        print(f"  DefiLlama fetch failed: {e}")
        return

    for pool in POOLS:
        p = all_pools.get(pool["id"])
        if not p:
            print(f"  {pool['name']}: not found in DefiLlama")
            continue

        row = {
            "ts": now,
            "pool_id": pool["id"],
            "pool_name": pool["name"],
            "fee_apy": p.get("apyBase") or 0,
            "tvl_usd": p.get("tvlUsd") or 0,
            "peg_deviation_bps": round(peg_dev, 2) if peg_dev is not None else None,
        }
        rows.append(row)

    with open(SNAPSHOTS_FILE, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    ts_str = datetime.fromtimestamp(now, tz=timezone.utc
                                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Snapshot at {ts_str}: {len(rows)} pools")
    print(f"  {'pool':>30}  {'fee APY':>8}  {'TVL':>12}  {'peg dev':>8}")

    for r in rows:
        tvl_str = f"${r['tvl_usd'] / 1e6:.1f}M"
        peg_str = (f"{r['peg_deviation_bps']:+.2f}bp"
                   if r['peg_deviation_bps'] is not None else "N/A")
        delta = r['fee_apy'] - BACKTEST_APY
        flag = " ← " + ("above" if delta > 1 else
                         "ON TARGET" if delta > -1 else "BELOW") + " backtest"
        print(f"  {r['pool_name']:>30}  {r['fee_apy']:>7.2f}%  "
              f"{tvl_str:>12}  {peg_str:>8}{flag}")

    if peg_dev is not None:
        print(f"\n  USDC/USDT peg: {1.0 + peg_dev / 10_000:.6f} "
              f"({peg_dev:+.2f}bp from 1.0000)"
              f"{'  ← TIGHT' if abs(peg_dev) < 5 else '  ← WATCH' if abs(peg_dev) < 20 else '  ← WARNING'}")


def report():
    """Analyze accumulated snapshots vs backtest baseline."""
    if not os.path.exists(SNAPSHOTS_FILE):
        print("No snapshots yet.")
        return

    rows = [json.loads(l) for l in open(SNAPSHOTS_FILE) if l.strip()]
    n_events = len(set(round(r["ts"]) for r in rows))
    if n_events < 3:
        print(f"Only {n_events} snapshots — need ≥3 (3+ days). Wait.")
        return

    import statistics

    by_pool = {}
    for r in rows:
        by_pool.setdefault(r["pool_name"], []).append(r)

    print(f"LP monitor report — {len(rows)} rows, {n_events} snapshots\n")

    for name, sr in by_pool.items():
        apys = [r["fee_apy"] for r in sr]
        tvls = [r["tvl_usd"] for r in sr]
        pegs = [r["peg_deviation_bps"] for r in sr
                if r["peg_deviation_bps"] is not None]

        print(f"  {name}:")
        print(f"    Fee APY:  mean={statistics.mean(apys):.2f}%  "
              f"median={statistics.median(apys):.2f}%  "
              f"min={min(apys):.2f}%  max={max(apys):.2f}%")
        print(f"    Backtest: {BACKTEST_APY:.1f}%  "
              f"→ forward {'MATCHES' if abs(statistics.mean(apys) - BACKTEST_APY) < 2 else 'DIVERGED'}")
        print(f"    TVL:      mean=${statistics.mean(tvls)/1e6:.1f}M  "
              f"range=[${min(tvls)/1e6:.1f}M, ${max(tvls)/1e6:.1f}M]")
        if pegs:
            print(f"    Peg dev:  mean={statistics.mean(pegs):+.2f}bp  "
                  f"max |dev|={max(abs(p) for p in pegs):.2f}bp  "
                  f"{'PEG HELD' if max(abs(p) for p in pegs) < 20 else 'PEG STRESSED'}")
        print()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Stable LP monitor")
    ap.add_argument("cmd", choices=["snapshot", "report"])
    args = ap.parse_args()
    {"snapshot": snapshot, "report": report}[args.cmd]()
