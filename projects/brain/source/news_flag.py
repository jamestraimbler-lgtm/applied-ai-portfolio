#!/usr/bin/env python3
"""news_flag.py — Forward-only crypto news-reaction study (no hindsight).

Brain flags news significant + predicts direction WITH timestamp BEFORE outcome.
Later we measure post-flag price vs BTC baseline. Edge = flagged tokens move in
predicted direction MORE than market, AFTER the public flag. Logged-before, scored-after.
"""
import argparse, json, os, time
from datetime import datetime, timezone

import requests

from measurer import is_measurable

FLAGS_LOG = "news_flags.jsonl"
SEEN_FILE = "seen_headlines.json"
MODEL = "claude-sonnet-4-6"

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://www.theblock.co/rss.xml",
]

CLASSIFY_SYSTEM = """You classify crypto news headlines for TRADEABLE significance. For each headline decide: is this genuinely market-moving for a SPECIFIC token, and is the move likely NOT already fully priced?

Be STRICT. Most headlines are noise (opinion, recaps, price commentary, vague speculation). Flag ONLY headlines that are concrete, specific, and likely to move a specific token: partnerships, listings, regulatory rulings, major protocol upgrades, ETF decisions, hacks, delistings, big institutional adoption.

For each headline you flag as significant, output direction and an expected move. You are predicting the move that happens AFTER this headline is already public, so consider whether fast money has already reacted.

Output ONLY a JSON list (possibly empty) of the SIGNIFICANT ones:
[{"headline_idx": <int>, "symbol": "<TICKER like XRP, no USDT>", "direction": "bullish|bearish", "expected_move_pct": <number>, "confidence": "low|medium|high", "already_priced_risk": "low|medium|high", "reasoning": "<one line>"}]
If none are significant, output []."""


def fetch_news(max_items=40):
    items = []
    try:
        import feedparser
        for url in RSS_FEEDS:
            try:
                d = feedparser.parse(url)
                for e in d.entries[:15]:
                    items.append({
                        "title": e.get("title", "").strip(),
                        "link": e.get("link", ""),
                        "published": e.get("published", ""),
                        "source": url.split("/")[2],
                    })
            except Exception as ex:
                print(f"  feed error {url}: {ex}")
    except ImportError:
        print("  feedparser not installed; run: pip install feedparser")
    seen = set()
    out = []
    for it in items:
        if it["title"] and it["title"] not in seen:
            seen.add(it["title"])
            out.append(it)
    return out[:max_items]


def load_seen():
    if os.path.exists(SEEN_FILE):
        return set(json.load(open(SEEN_FILE)))
    return set()


def save_seen(seen):
    json.dump(list(seen), open(SEEN_FILE, "w"))


def classify(headlines, model=MODEL):
    from anthropic import Anthropic
    client = Anthropic()
    listing = "\n".join(f"{i}: {h['title']}" for i, h in enumerate(headlines))
    user = f"Headlines:\n{listing}\n\nOutput the JSON list of significant ones."
    resp = client.messages.create(
        model=model, max_tokens=1500, system=CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1:
        return []
    return json.loads(text[start:end+1])


def binance_price(symbol):
    r = requests.get("https://api.binance.com/api/v3/ticker/price",
                     params={"symbol": f"{symbol}USDT"}, timeout=15)
    if r.status_code != 200:
        return None
    return float(r.json()["price"])


def binance_klines(symbol, start_ms, hours=80):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": f"{symbol}USDT", "interval": "1h",
                             "startTime": int(start_ms), "limit": hours}, timeout=15)
    if r.status_code != 200:
        return []
    return r.json()


def cmd_scan(args):
    news = fetch_news()
    seen = load_seen()
    fresh = [h for h in news if h["title"] not in seen]
    print(f"Pulled {len(news)} headlines, {len(fresh)} new.")
    if not fresh:
        print("Nothing new to classify.")
        return
    if args.mock:
        sig = [{"headline_idx": 0, "symbol": "XRP", "direction": "bullish",
                "expected_move_pct": 8, "confidence": "medium",
                "already_priced_risk": "medium", "reasoning": "mock significant event"}] if fresh else []
    else:
        try:
            sig = classify(fresh)
        except Exception as e:
            if "api_key" in str(e).lower() or "auth" in str(e).lower():
                print("[scan] no API key — skipping classification")
                return
            raise
    print(f"Brain flagged {len(sig)} significant event(s).")
    # Load existing flags for event dedup (same symbol+direction within 24h = echo)
    existing_flags = []
    if os.path.exists(FLAGS_LOG):
        existing_flags = [json.loads(l) for l in open(FLAGS_LOG) if l.strip()]

    for s in sig:
        idx = s.get("headline_idx")
        if not isinstance(idx, int) or not (0 <= idx < len(fresh)):
            print(f"  skip: classifier returned bad headline_idx {idx!r}")
            continue
        if s.get("direction") not in ("bullish", "bearish"):
            print(f"  skip: classifier returned bad direction {s.get('direction')!r}")
            continue
        h = fresh[idx]
        if not args.mock:
            if not is_measurable(s["symbol"]):
                print(f"  skip {s['symbol']}: not measurable (no recent klines)")
                continue
        # Event dedup: skip if same symbol+direction within past 24h
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        echo_of = None
        for i, ef in enumerate(existing_flags):
            if (ef["symbol"] == s["symbol"]
                    and ef["direction"] == s["direction"]
                    and (now_ms - ef["flagged_at_ms"]) < 86_400_000):
                echo_of = (i + 1, (now_ms - ef["flagged_at_ms"]) / 3_600_000)
                break
        if echo_of:
            print(f"  skip {s['symbol']} {s['direction']}: duplicate event "
                  f"(echo of flag #{echo_of[0]}, {echo_of[1]:.1f}h ago)")
            continue
        price = None if args.mock else binance_price(s["symbol"])
        if price is None and not args.mock:
            print(f"  skip {s['symbol']}: no Binance USDT pair")
            continue
        flag = {
            "flagged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "flagged_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "headline": h["title"], "link": h["link"], "source": h["source"],
            "symbol": s["symbol"], "direction": s["direction"],
            "expected_move_pct": s.get("expected_move_pct"),
            "confidence": s.get("confidence"),
            "already_priced_risk": s.get("already_priced_risk"),
            "reasoning": s.get("reasoning"),
            "entry_price": price if price else 1.0,
            "btc_entry": None if args.mock else binance_price("BTC"),
            "measured": False, "forward": {},
        }
        with open(FLAGS_LOG, "a") as f:
            f.write(json.dumps(flag) + "\n")
        existing_flags.append(flag)
        try:
            from placebo import on_flag_logged
            from validation import Flag
            same_asset_ts = tuple(
                ef["flagged_at_ms"] / 1000.0
                for ef in existing_flags
                if ef["symbol"] == flag["symbol"]
            )
            on_flag_logged(Flag(
                unix_ts=flag["flagged_at_ms"] / 1000.0,
                asset=flag["symbol"],
                direction={"bullish": 1, "bearish": -1}[flag["direction"]],
            ), avoid_ts=same_asset_ts)
        except Exception as e:
            print(f"  [placebo hook failed — flag still logged]: {e}")
        print(f"  FLAG {s['symbol']} {s['direction']} (~{s.get('expected_move_pct')}%) "
              f"@ {flag['entry_price']}  | {h['title'][:55]}")
    for h in fresh:
        seen.add(h["title"])
    save_seen(seen)


def cmd_measure(args):
    if not os.path.exists(FLAGS_LOG):
        print("No flags yet.")
        return
    flags = [json.loads(l) for l in open(FLAGS_LOG) if l.strip()]
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    horizons = [1, 4, 24, 72]
    changed = 0
    for fl in flags:
        if fl.get("measured"):
            continue
        age_h = (now_ms - fl["flagged_at_ms"]) / 3600000
        if age_h < 73:
            continue
        kl = binance_klines(fl["symbol"], fl["flagged_at_ms"])
        btc_kl = binance_klines("BTC", fl["flagged_at_ms"])
        if not kl or not btc_kl:
            continue
        entry = fl["entry_price"]
        btc_entry = fl.get("btc_entry") or float(btc_kl[0][1])
        fwd = {}
        for h in horizons:
            if len(kl) > h and len(btc_kl) > h:
                tok_ret = float(kl[h][4]) / entry - 1
                btc_ret = float(btc_kl[h][4]) / btc_entry - 1
                fwd[f"{h}h"] = {
                    "token_ret_pct": round(tok_ret*100, 2),
                    "btc_ret_pct": round(btc_ret*100, 2),
                    "excess_pct": round((tok_ret - btc_ret)*100, 2),
                }
        fl["forward"] = fwd
        fl["measured"] = True
        changed += 1
    with open(FLAGS_LOG, "w") as f:
        for fl in flags:
            f.write(json.dumps(fl) + "\n")
    print(f"Measured {changed} matured flags.")


def cmd_score(args):
    import statistics
    from measurer import make_measurer

    if not os.path.exists(FLAGS_LOG):
        print("No flags yet.")
        return
    flags = [json.loads(l) for l in open(FLAGS_LOG) if l.strip()]
    if not flags:
        print("No flags yet.")
        return

    measurer = make_measurer()

    # Measure all flags once; distribute to per-horizon buckets
    buckets = {h: [] for h in ["1h", "4h", "24h", "72h"]}
    for f in flags:
        sign = 1 if f["direction"] == "bullish" else -1
        ts = f["flagged_at_ms"] / 1000.0
        raw = measurer(ts, f["symbol"])
        for h in buckets:
            val = raw.get(h)
            if val is not None:
                buckets[h].append(sign * val * 100)

    print(f"Scoring {len(flags)} flags (per-horizon maturity — each horizon uses its own n):")
    print(f"  Edge = directional excess return vs BTC, AFTER the flag.")
    for h in ["1h", "4h", "24h", "72h"]:
        excesses = buckets[h]
        if not excesses:
            print(f"  +{h:>3}: no matured flags yet")
            continue
        mean = statistics.mean(excesses)
        median = statistics.median(excesses)
        wins = sum(1 for x in excesses if x > 0)
        n = len(excesses)
        edge = (mean > 0) and (median > 0)
        tag = "<- edge" if edge else "<- outlier-driven / no edge"
        print(f"  +{h:>3}: mean {mean:+.2f}%  median {median:+.2f}%  ({wins}/{n} positive)  {tag}")

    print("\n  Positive mean+median = flagged news had tradeable drift AFTER going public.")
    print("  Mean>0 but median<=0 = outlier-driven, no consistent edge.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--mock", action="store_true"); s.set_defaults(func=cmd_scan)
    m = sub.add_parser("measure"); m.set_defaults(func=cmd_measure)
    sc = sub.add_parser("score"); sc.set_defaults(func=cmd_score)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
