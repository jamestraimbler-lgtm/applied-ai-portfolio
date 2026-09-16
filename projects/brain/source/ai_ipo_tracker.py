"""
AI IPO forward tracker — logs observable signals on SpaceX/OpenAI/Anthropic.

LOGS, does NOT predict. Same discipline as paper_carry.py / lp_monitor.py.

Three signal types:
  1. SPCX price/volume — AUTOMATED (Yahoo Finance v8, clean daily feed)
  2. Pre-IPO secondary valuations — MANUAL entry (no free programmatic source)
  3. Prediction-market IPO odds — MANUAL entry (no reliable free API found)

DATA QUALITY:
  automated = clean feed, logged programmatically
  manual    = human-entered from news/Forge/Hiive, tagged with source

Usage:
  python ai_ipo_tracker.py snapshot       # automated SPCX + any manual entries
  python ai_ipo_tracker.py manual <json>  # add a manual observation
  python ai_ipo_tracker.py report         # read the accumulated data
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), "ai_ipo_tracker.jsonl")
SPCX_TICKER = "SPCX"
IPO_PRICE = 135.0

# Known forced-buying calendar (public, scheduled — NOT predictions)
INCLUSION_CALENDAR = [
    ("2026-06-12", "ipo", "SpaceX IPO at $135"),
    ("2026-06-19", "crsp_add", "CRSP add (~5 trading days post-IPO, estimated)"),
    ("2026-07-03", "nasdaq100_fast", "Nasdaq-100 fast-entry (~15 trading days, estimated)"),
    ("2026-09-19", "russell_recon", "Russell reconstitution (September, estimated)"),
    ("2026-12-18", "russell_recon_dec", "Russell December reconstitution (estimated)"),
]

# Last-known anchors for manual-entry reference
ANCHORS = {
    "anthropic": {
        "official_val_B": 965,
        "official_date": "2026-05-28",
        "source": "Series H at $965B (TechCrunch)",
    },
    "openai": {
        "official_val_B": 852,
        "official_date": "2026-03-01",
        "source": "$122B raise at $852B post-money",
    },
}


# ── Write ───────────────────────────────────────────────────────────────
def append_row(row: dict):
    with open(DATA_FILE, "a") as f:
        f.write(json.dumps(row) + "\n")


def load_rows() -> list[dict]:
    if not os.path.exists(DATA_FILE):
        return []
    rows = []
    with open(DATA_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── SPCX automated feed ────────────────────────────────────────────────
def fetch_spcx() -> dict | None:
    """Fetch SPCX latest close + volume from Yahoo Finance v8."""
    try:
        url = (
            f"https://query2.finance.yahoo.com/v8/finance/chart/{SPCX_TICKER}"
            f"?range=5d&interval=1d"
        )
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        data = r.json()

        err = data.get("chart", {}).get("error")
        if err:
            return None

        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        timestamps = result.get("timestamp")

        if not timestamps:
            return None

        closes = result["indicators"]["adjclose"][0]["adjclose"]
        volumes = result["indicators"]["quote"][0].get("volume", [None] * len(timestamps))

        # Take the latest non-null data point
        for i in range(len(timestamps) - 1, -1, -1):
            if closes[i] is not None:
                dt = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)
                return {
                    "date": dt.strftime("%Y-%m-%d"),
                    "close": closes[i],
                    "volume": volumes[i] if i < len(volumes) else None,
                    "exchange": meta.get("exchangeName", "unknown"),
                }
        return None

    except Exception as e:
        print(f"  [spcx] fetch error: {e}")
        return None


def snapshot_spcx():
    """Log SPCX price + volume. Handles pre-IPO gracefully."""
    print("  SPCX (Yahoo Finance v8):")
    data = fetch_spcx()

    if data is None:
        print("    Not yet trading or no data available. Skipping.")
        return

    # Check if this is just the $135 reference (pre-trading)
    if data["volume"] is None or data["volume"] == 0:
        print(f"    Reference price: ${data['close']} (pre-trading, volume=0). Logging as reference.")
        data["note"] = "pre-trading reference"

    # Check if already logged today
    existing = load_rows()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    already = any(
        r.get("entity") == "spacex" and r.get("metric") == "price"
        and r.get("date") == data["date"]
        for r in existing
    )
    if already:
        print(f"    Already logged {data['date']}. Skipping.")
        return

    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "signal_type": "automated",
        "entity": "spacex",
        "metric": "price",
        "date": data["date"],
        "value": data["close"],
        "volume": data["volume"],
        "vs_ipo": round((data["close"] / IPO_PRICE - 1) * 100, 2),
        "source": "yahoo_v8",
    }
    if data.get("note"):
        row["note"] = data["note"]

    append_row(row)
    vs = row["vs_ipo"]
    vol_str = f"vol={data['volume']:,.0f}" if data["volume"] else "vol=n/a"
    print(f"    ${data['close']:.2f} ({vs:+.2f}% vs IPO)  {vol_str}  [{data['date']}]")

    # Flag proximity to inclusion dates
    for cal_date, cal_type, cal_desc in INCLUSION_CALENDAR:
        if data["date"] == cal_date:
            print(f"    >>> INCLUSION EVENT TODAY: {cal_desc}")
        elif data["date"] > cal_date:
            continue
        else:
            # Next upcoming event
            print(f"    Next calendar event: {cal_desc} ({cal_date})")
            break


# ── Manual entry ────────────────────────────────────────────────────────
def cmd_manual(args):
    """Add a manual observation. Expects JSON string."""
    if not args:
        print("Usage: ai_ipo_tracker.py manual '{\"entity\":\"openai\",\"metric\":\"secondary_val\",\"value\":900,\"source\":\"Forge Jun 2026\"}'")
        print()
        print("Required fields: entity, metric, value, source")
        print("Entities: spacex, openai, anthropic")
        print("Metrics: secondary_val (in $B), ipo_odds (0-1), price, other")
        return

    try:
        data = json.loads(args[0])
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        return

    required = ["entity", "metric", "value", "source"]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"Missing required fields: {missing}")
        return

    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "signal_type": "manual",
        "entity": data["entity"],
        "metric": data["metric"],
        "value": data["value"],
        "source": data["source"],
    }
    # Pass through any extra fields
    for k, v in data.items():
        if k not in row:
            row[k] = v

    append_row(row)
    print(f"  Logged: {data['entity']} / {data['metric']} = {data['value']} (source: {data['source']})")


# ── Report ──────────────────────────────────────────────────────────────
def cmd_report():
    rows = load_rows()
    if not rows:
        print("No data yet.")
        return

    print(f"\n{'=' * 70}")
    print(f"AI IPO TRACKER — {len(rows)} observations")
    print(f"{'=' * 70}")

    # Group by entity
    by_entity = {}
    for r in rows:
        e = r.get("entity", "unknown")
        by_entity.setdefault(e, []).append(r)

    # SPCX price series
    if "spacex" in by_entity:
        spcx = [r for r in by_entity["spacex"] if r.get("metric") == "price"]
        spcx.sort(key=lambda r: r.get("date", ""))
        print(f"\n--- SpaceX (SPCX) Price Series ({len(spcx)} days) ---")
        if spcx:
            print(f"  IPO reference: ${IPO_PRICE}")
            print(f"  {'Date':>12} {'Close':>10} {'vs IPO':>10} {'Volume':>14} {'Source':>10}")
            print(f"  {'-' * 60}")
            for r in spcx[-15:]:  # last 15
                vol = f"{r['volume']:>13,.0f}" if r.get("volume") else "          n/a"
                src = r.get("source", "?")[:10]
                print(f"  {r['date']:>12} ${r['value']:>8.2f} {r['vs_ipo']:>+9.2f}% {vol} {src:>10}")
            if len(spcx) > 1:
                latest = spcx[-1]["value"]
                first_trade = next((s for s in spcx if s.get("volume") and s["volume"] > 0), spcx[0])
                print(f"\n  Latest: ${latest:.2f} ({(latest/IPO_PRICE-1)*100:+.1f}% vs IPO)")

        # Calendar proximity
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        print(f"\n  Inclusion calendar (reference dates, not predictions):")
        for cal_date, cal_type, cal_desc in INCLUSION_CALENDAR:
            marker = " <<<" if cal_date <= today else ""
            print(f"    {cal_date}  {cal_desc}{marker}")

    # Secondary valuations
    for entity in ["openai", "anthropic"]:
        if entity in by_entity:
            vals = [r for r in by_entity[entity] if r.get("metric") == "secondary_val"]
            odds = [r for r in by_entity[entity] if r.get("metric") == "ipo_odds"]
            if vals or odds:
                print(f"\n--- {entity.title()} ---")
                if vals:
                    vals.sort(key=lambda r: r.get("ts", ""))
                    print(f"  Secondary valuations ({len(vals)} observations):")
                    for r in vals:
                        print(f"    {r['ts'][:10]}: ${r['value']}B  (source: {r['source']})")
                    anchor = ANCHORS.get(entity)
                    if anchor:
                        print(f"    Anchor: ${anchor['official_val_B']}B ({anchor['official_date']}, {anchor['source']})")
                if odds:
                    odds.sort(key=lambda r: r.get("ts", ""))
                    print(f"  IPO odds ({len(odds)} observations):")
                    for r in odds:
                        print(f"    {r['ts'][:10]}: {r['value']:.0%}  (source: {r['source']})")

    # Data quality summary
    auto_n = sum(1 for r in rows if r.get("signal_type") == "automated")
    manual_n = sum(1 for r in rows if r.get("signal_type") == "manual")
    print(f"\n--- Data Quality ---")
    print(f"  Automated (clean feed): {auto_n}")
    print(f"  Manual (human-entered): {manual_n}")
    print(f"  Total: {len(rows)}")


# ── Snapshot ────────────────────────────────────────────────────────────
def cmd_snapshot():
    print(f"AI IPO Tracker snapshot — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    snapshot_spcx()
    print()
    print("  Secondary prices (OpenAI/Anthropic): MANUAL ENTRY ONLY")
    print("    No free programmatic source exists. Use:")
    print("    python ai_ipo_tracker.py manual '{\"entity\":\"anthropic\",\"metric\":\"secondary_val\",\"value\":1000,\"source\":\"Forge Jun 9\"}'")
    print()
    print("  Prediction-market odds: MANUAL ENTRY ONLY")
    print("    Polymarket API tested — no IPO-specific markets found via gamma-api.")
    print("    Use:")
    print("    python ai_ipo_tracker.py manual '{\"entity\":\"openai\",\"metric\":\"ipo_odds\",\"value\":0.85,\"source\":\"Polymarket Jun 9\"}'")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: ai_ipo_tracker.py <snapshot|manual|report>")
        return

    cmd = sys.argv[1]
    if cmd == "snapshot":
        cmd_snapshot()
    elif cmd == "manual":
        cmd_manual(sys.argv[2:])
    elif cmd == "report":
        cmd_report()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
