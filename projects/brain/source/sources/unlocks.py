"""Token unlock calendar poller — DefiLlama emissionsIndex source.

Fetches cliff-type unlock events from the free DefiLlama emissionsIndex
endpoint, filters by >= 1% of circulating supply, maps gecko_id -> symbol
via CoinGecko coins/list, checks Binance pair measurability, and records
NL-perp availability (Hyperliquid/Deribit) per token.

Persists qualifying events to unlock_events.jsonl (write-once per
symbol+unlock_ts). Follows the sources/ poller pattern (listings.py etc).
"""

import json, os, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS_FILE = os.path.join(_DIR, "unlock_events.jsonl")

EMISSIONS_INDEX_URL = "https://defillama-datasets.llama.fi/emissionsIndex"
COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
MIN_PCT_SUPPLY = 1.0  # pre-registered filter: >= 1% of circulating


# ── CoinGecko ID → symbol mapping ────────────────────────────────────

def _fetch_gecko_map() -> dict[str, str]:
    """Return {gecko_id: SYMBOL} from CoinGecko coins/list."""
    r = requests.get(COINGECKO_LIST_URL, timeout=30)
    r.raise_for_status()
    return {c["id"]: c["symbol"].upper() for c in r.json()}


# ── NL-perp availability ─────────────────────────────────────────────

def _hl_listed_symbols() -> set[str]:
    """Return set of symbols with a Hyperliquid perp."""
    try:
        r = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "metaAndAssetCtxs"},
            timeout=15,
        ).json()
        if isinstance(r, list) and r:
            return {a["name"] for a in r[0].get("universe", [])}
    except Exception:
        pass
    return set()


def _deribit_listed_symbols() -> set[str]:
    """Return set of base symbols with a Deribit perpetual."""
    syms = set()
    for ccy in ("BTC", "ETH", "USDC"):
        try:
            r = requests.get(
                "https://www.deribit.com/api/v2/public/get_instruments",
                params={"currency": ccy, "kind": "future"},
                timeout=15,
            ).json()
            for inst in r.get("result", []):
                if inst["instrument_name"].endswith("-PERPETUAL"):
                    base = inst.get("base_currency", inst["instrument_name"].split("_")[0].split("-")[0])
                    syms.add(base)
        except Exception:
            pass
    return syms


# ── Binance measurability gate (reuse measurer logic) ─────────────────

def _binance_pair_exists(symbol: str) -> bool:
    """Check if SYMBOLUSDT has recent klines on Binance."""
    pair = f"{symbol}USDT"
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": pair, "interval": "1h", "limit": 2},
            timeout=10,
        )
        if r.status_code != 200:
            return False
        klines = r.json()
        if not klines:
            return False
        # Check not stale (within 48h of now)
        last_open_ms = klines[-1][0]
        now_ms = int(time.time() * 1000)
        return (now_ms - last_open_ms) < 48 * 3_600_000
    except Exception:
        return False


# ── Persistence ──────────────────────────────────────────────────────

def _load_existing() -> set[tuple[str, int]]:
    """Return set of (symbol, unlock_ts) already logged."""
    seen = set()
    if os.path.exists(EVENTS_FILE):
        for line in open(EVENTS_FILE):
            line = line.strip()
            if line:
                ev = json.loads(line)
                seen.add((ev["symbol"], ev["unlock_ts"]))
    return seen


# ── Main fetch ───────────────────────────────────────────────────────

def fetch_unlock_calendar() -> list[dict]:
    """Fetch qualifying cliff unlock events, check measurability, persist new ones.

    Returns list of ALL qualifying events (new + existing).
    """
    print("Fetching DefiLlama emissionsIndex...")
    r = requests.get(EMISSIONS_INDEX_URL, timeout=60)
    r.raise_for_status()
    protocols = r.json()["data"]
    print(f"  {len(protocols)} protocols in index")

    print("Fetching CoinGecko symbol map...")
    gecko_map = _fetch_gecko_map()
    print(f"  {len(gecko_map)} gecko IDs mapped")

    print("Checking NL-perp availability...")
    hl_syms = _hl_listed_symbols()
    db_syms = _deribit_listed_symbols()
    print(f"  Hyperliquid: {len(hl_syms)} perps, Deribit: {len(db_syms)} perps")

    # Extract qualifying cliff events
    candidates = []
    for p in protocols:
        circ = p.get("circSupply", 0) or 0
        gecko_id = p.get("gecko_id", "")
        name = p.get("name", "")
        slug = p.get("protocolSlug", "")
        if circ <= 0 or not gecko_id:
            continue

        symbol = gecko_map.get(gecko_id)
        if not symbol:
            continue

        all_events = (p.get("unlockEvents") or []) + (p.get("events") or [])
        for ev in all_events:
            if ev.get("unlockType") != "cliff":
                continue
            ts = ev.get("timestamp", 0)
            if not isinstance(ts, (int, float)) or ts <= 0:
                continue
            tokens = ev.get("noOfTokens", [])
            amt = tokens[0] if tokens else 0
            if amt <= 0:
                continue
            pct = amt / circ * 100
            if pct < MIN_PCT_SUPPLY:
                continue

            candidates.append({
                "name": name,
                "slug": slug,
                "gecko_id": gecko_id,
                "symbol": symbol,
                "unlock_ts": int(ts),
                "pct_of_supply": round(pct, 2),
                "amount": amt,
                "category": ev.get("category", ""),
                "description": ev.get("description", ""),
            })

    print(f"  {len(candidates)} cliff events >= {MIN_PCT_SUPPLY}% of circ supply")

    # Deduplicate: same (symbol, unlock_ts) from multiple event lists
    unique = {}
    for c in candidates:
        key = (c["symbol"], c["unlock_ts"])
        if key not in unique or c["pct_of_supply"] > unique[key]["pct_of_supply"]:
            unique[key] = c
    candidates = list(unique.values())
    print(f"  {len(candidates)} unique (symbol, unlock_ts) pairs")

    # Check Binance measurability (batch — only check symbols we haven't seen)
    existing = _load_existing()
    new_symbols = {c["symbol"] for c in candidates if (c["symbol"], c["unlock_ts"]) not in existing}
    print(f"  Checking Binance measurability for {len(new_symbols)} new symbols...")
    measurable_cache: dict[str, bool] = {}
    for sym in sorted(new_symbols):
        if sym not in measurable_cache:
            measurable_cache[sym] = _binance_pair_exists(sym)
            time.sleep(0.1)  # rate limit

    # Build final event list + persist new ones
    new_events = []
    now = time.time()
    for c in candidates:
        key = (c["symbol"], c["unlock_ts"])
        if key in existing:
            continue

        sym = c["symbol"]
        if sym in measurable_cache and not measurable_cache[sym]:
            continue  # no Binance pair

        event = {
            "symbol": sym,
            "name": c["name"],
            "gecko_id": c["gecko_id"],
            "unlock_ts": c["unlock_ts"],
            "pct_of_supply": c["pct_of_supply"],
            "amount": c["amount"],
            "kind": "cliff",
            "category": c["category"],
            "hl_perp": sym in hl_syms,
            "deribit_perp": sym in db_syms,
            "logged_at": now,
        }
        new_events.append(event)

    if new_events:
        new_events.sort(key=lambda e: e["unlock_ts"])
        with open(EVENTS_FILE, "a") as f:
            for ev in new_events:
                f.write(json.dumps(ev) + "\n")
        print(f"  Logged {len(new_events)} new events")
    else:
        print("  No new events to log")

    # Load all events for return
    all_events = []
    if os.path.exists(EVENTS_FILE):
        for line in open(EVENTS_FILE):
            line = line.strip()
            if line:
                all_events.append(json.loads(line))

    # Print summary
    unlisted = set()
    for ev in all_events:
        if not ev.get("hl_perp") and not ev.get("deribit_perp"):
            unlisted.add(ev["symbol"])

    n_past = sum(1 for e in all_events if e["unlock_ts"] <= now)
    n_future = sum(1 for e in all_events if e["unlock_ts"] > now)
    n_syms = len({e["symbol"] for e in all_events})
    print(f"\nCalendar: {len(all_events)} events, {n_syms} tokens, "
          f"{n_past} past / {n_future} upcoming")
    if unlisted:
        print(f"  No NL perp: {', '.join(sorted(unlisted)[:15])}"
              f"{'...' if len(unlisted) > 15 else ''}")

    return all_events


if __name__ == "__main__":
    fetch_unlock_calendar()
