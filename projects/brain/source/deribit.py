#!/usr/bin/env python3
"""deribit.py — Pull options-implied probabilities from Deribit (no API key).

A crypto option's delta ~ the risk-neutral probability it expires ITM.
call: P(S > K) ~ call_delta ; put: P(S > K) ~ 1 + put_delta (put delta negative).
Same target shape as a Manifold market, on a venue tradeable from NL.
"""
import argparse
import json
from datetime import datetime, timezone

import requests

BASE = "https://www.deribit.com/api/v2"


def api(method, params):
    r = requests.get(f"{BASE}/{method}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()["result"]


def get_option_instruments(currency):
    return api("public/get_instruments",
               {"currency": currency, "kind": "option", "expired": "false"})


def get_ticker(instrument_name):
    return api("public/ticker", {"instrument_name": instrument_name})


def nearest_expiry(instruments, target_dt):
    target_ms = target_dt.timestamp() * 1000
    expiries = sorted(set(i["expiration_timestamp"] for i in instruments))
    return min(expiries, key=lambda e: abs(e - target_ms))


def call_prob_from_delta(option_type, delta):
    if option_type == "call":
        return delta
    return 1 + delta


def implied_prob_for(currency, strike, target_dt, instruments=None, want_type="call"):
    if instruments is None:
        instruments = get_option_instruments(currency)
    exp = nearest_expiry(instruments, target_dt)
    cands = [i for i in instruments
             if i["expiration_timestamp"] == exp and i["option_type"] == want_type]
    if not cands:
        raise ValueError(f"No {want_type} options at that expiry")
    best = min(cands, key=lambda i: abs(i["strike"] - strike))
    t = get_ticker(best["instrument_name"])
    delta = t["greeks"]["delta"]
    prob = call_prob_from_delta(best["option_type"], delta)
    return {
        "instrument": best["instrument_name"],
        "strike": best["strike"],
        "expiry": datetime.fromtimestamp(exp/1000, tz=timezone.utc).strftime("%Y-%m-%d"),
        "delta": round(delta, 4),
        "implied_prob_pct": round(prob * 100, 1),
        "mark_iv": t.get("mark_iv"),
        "underlying": t.get("underlying_price") or t.get("index_price"),
    }


def cmd_chain(args):
    target_dt = datetime.strptime(args.expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    instruments = get_option_instruments(args.currency)
    exp = nearest_expiry(instruments, target_dt)
    exp_date = datetime.fromtimestamp(exp/1000, tz=timezone.utc).strftime("%Y-%m-%d")
    calls = sorted([i for i in instruments
                    if i["expiration_timestamp"] == exp and i["option_type"] == "call"],
                   key=lambda i: i["strike"])
    print(f"{args.currency} options-implied P(price > strike) at expiry {exp_date}:")
    print(f"  {'strike':>10} {'delta':>8} {'impl_prob':>10}")
    step = max(1, len(calls) // 12)
    for i in calls[::step]:
        t = get_ticker(i["instrument_name"])
        d = t["greeks"]["delta"]
        print(f"  {i['strike']:>10.0f} {d:>8.3f} {d*100:>9.1f}%")


def cmd_question(args):
    target_dt = datetime.strptime(args.expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    info = implied_prob_for(args.currency, args.strike, target_dt)
    q = {
        "id": f"{args.currency}-{int(info['strike'])}-{info['expiry'].replace('-','')}",
        "question": f"Will {args.currency} be above ${int(info['strike']):,} on {info['expiry']}?",
        "resolution_criteria": f"YES if Deribit {args.currency} index > {int(info['strike'])} at {info['expiry']} expiry",
        "resolution_date": info["expiry"],
        "category": "crypto_options",
        "market_implied_pct": info["implied_prob_pct"],
        "deribit_instrument": info["instrument"],
        "underlying_now": info["underlying"],
        "mark_iv": info["mark_iv"],
    }
    out = args.out or f"q_{q['id']}.json"
    json.dump([q], open(out, "w"), indent=2)
    print(f"Underlying {args.currency} now: ~${info['underlying']:,.0f}")
    print(f"Nearest option: {info['instrument']} (strike ${int(info['strike']):,}, delta {info['delta']})")
    print(f"Market-implied P({args.currency} > ${int(info['strike']):,} by {info['expiry']}): {info['implied_prob_pct']}%")
    print(f"Wrote brain-ready question to {out}")
    print(f"Next: ./venv/bin/python brain_search.py forecast --file {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chain")
    c.add_argument("--currency", default="BTC")
    c.add_argument("--expiry", required=True)
    c.set_defaults(func=cmd_chain)
    q = sub.add_parser("question")
    q.add_argument("--currency", default="BTC")
    q.add_argument("--strike", type=float, required=True)
    q.add_argument("--expiry", required=True)
    q.add_argument("--out")
    q.set_defaults(func=cmd_question)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
