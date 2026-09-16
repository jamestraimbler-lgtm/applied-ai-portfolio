"""Binance listing announcement poller.

Fetches new-listing and futures-launch announcements from Binance's public
CMS API, extracts tickers, checks tradeability, and logs events to
listings_events.jsonl.  Completely separate from the RSS news-flag pipeline.
"""

import json, os, re, time
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENTS_FILE = os.path.join(_DIR, "listings_events.jsonl")
SEEN_FILE = os.path.join(_DIR, "seen_listings.json")

API_URL = ("https://www.binance.com/bapi/composite/v1/public/cms/"
           "article/list/query")
CATALOG_ID = 48  # "New Cryptocurrency Listing"


# ── Binance CMS helpers ──────────────────────────────────────────────

def _fetch_page(page, size=20):
    r = requests.get(API_URL, params={
        "type": 1, "catalogId": CATALOG_ID,
        "pageNo": page, "pageSize": size,
    }, timeout=15)
    if r.status_code != 200:
        return []
    cats = r.json().get("data", {}).get("catalogs", [])
    return cats[0].get("articles", []) if cats else []


# ── Title parsers ────────────────────────────────────────────────────

def _parse_spot(title):
    """'Binance Will List X (TICKER) ...' → ['TICKER', ...]"""
    if not title.startswith("Binance Will List"):
        return []
    return re.findall(r'\(([A-Z][A-Z0-9]+)\)', title)


def _parse_futures(title):
    """'Binance Futures Will Launch ... TICKERUSDT Perpetual ...' → list"""
    if "Futures Will Launch" not in title or "Perpetual" not in title:
        return []
    if "Multiple" in title:
        return []
    return re.findall(r'\b([A-Z][A-Z0-9]+)USDT\b', title)


# ── Kline probe ──────────────────────────────────────────────────────

def _first_kline_after(symbol, after_s):
    """Open time (seconds) of first 1m kline at/after after_s, or None.

    For brand-new listings the pair may not exist yet → returns None.
    For existing tokens this returns a candle at or very near after_s.
    """
    pair = f"{symbol.upper()}USDT"
    r = requests.get("https://api.binance.com/api/v3/klines", params={
        "symbol": pair, "interval": "1m",
        "startTime": int(after_s * 1000), "limit": 1,
    }, timeout=15)
    if r.status_code != 200:
        return None
    kl = r.json()
    return kl[0][0] / 1000.0 if kl else None


# ── Persistence ──────────────────────────────────────────────────────

def _load_seen():
    return set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()

def _save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f)

def _load_events():
    if not os.path.exists(EVENTS_FILE):
        return []
    return [json.loads(l) for l in open(EVENTS_FILE) if l.strip()]

def _save_events(events):
    with open(EVENTS_FILE, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

def _ts(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Main poll loop ───────────────────────────────────────────────────

def poll(backfill_pages=1):
    seen = _load_seen()
    events = _load_events()
    known = {e["announce_id"] for e in events}
    new = []

    for page in range(1, backfill_pages + 1):
        articles = _fetch_page(page)
        if not articles:
            break
        for art in articles:
            code = art["code"]
            if code in seen:
                continue
            title = art["title"]
            pub_ms = art["releaseDate"]

            pairs = ([(t, "binance_listing") for t in _parse_spot(title)] +
                     [(t, "binance_futures") for t in _parse_futures(title)])
            if not pairs:
                seen.add(code)
                continue

            now_s = time.time()
            pub_s = pub_ms / 1000.0
            url = f"https://www.binance.com/en/support/announcement/{code}"

            for ticker, src in pairs:
                eid = f"{code}:{ticker}"
                if eid in known:
                    continue

                ft = _first_kline_after(ticker, pub_s)
                ev = {
                    "announce_id": eid,
                    "symbol": ticker,
                    "direction": "bullish",
                    "publish_ts": pub_s,
                    "detect_ts": now_s,
                    "source": src,
                    "title": title,
                    "url": url,
                    "tradeable": ft is not None,
                    "first_trade_ts": ft,
                }
                new.append(ev)
                known.add(eid)

                lag = now_s - pub_s
                ft_str = (f"first_trade={_ts(ft)}" if ft
                          else "first_trade=N/A")
                print(f"  LISTING {ticker} | publish={_ts(pub_s)} "
                      f"detect={_ts(now_s)} lag={lag:.0f}s | "
                      f"{ft_str} | tradeable={ft is not None} | {src}")
            seen.add(code)

    if new:
        with open(EVENTS_FILE, "a") as f:
            for e in new:
                f.write(json.dumps(e) + "\n")

    # Re-check events still pending (tradeable=False, first_trade_ts=None)
    all_ev = _load_events()
    dirty = False
    for e in all_ev:
        if not e["tradeable"]:
            ft = _first_kline_after(e["symbol"], e["publish_ts"])
            if ft is not None:
                e["tradeable"] = True
                e["first_trade_ts"] = ft
                dirty = True
                print(f"  UPDATED {e['symbol']} -> tradeable | "
                      f"first_trade={_ts(ft)}")
    if dirty:
        _save_events(all_ev)
    _save_seen(seen)

    n_spot = sum(1 for e in all_ev if e["source"] == "binance_listing")
    n_fut = sum(1 for e in all_ev if e["source"] == "binance_futures")
    n_trd = sum(1 for e in all_ev if e["tradeable"])
    print(f"\nTotal: {len(new)} new ({n_spot} spot, {n_fut} futures), "
          f"{n_trd} tradeable, {len(all_ev) - n_trd} pending")
    return new


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Binance listing poller")
    ap.add_argument("--backfill", type=int, default=1,
                    help="Pages to fetch (20 per page)")
    args = ap.parse_args()
    poll(backfill_pages=args.backfill)
