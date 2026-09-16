#!/usr/bin/env python3
"""strategy_eval.py — Have the informed brain assess crypto trading strategies (skeptical)."""
import argparse, json, os
from datetime import datetime, timezone

MODEL = "claude-opus-4-6"
OUT_LOG = "strategy_evals.jsonl"

EVAL_SYSTEM = """You are a skeptical quant evaluating whether a crypto trading strategy is worth a one-person operator's time. You have web search — use it to find CURRENT (2026) evidence on whether the strategy still works, returns, and who's competing in it.

Apply these hard-learned principles:
- Pattern-finding on price history is almost always overfit noise; real edges are STRUCTURAL (funding mechanics, basis, liquidity provision, a behavioral pattern with a reason to persist) not PREDICTIVE.
- Edges decay as markets get efficient. An edge that worked in 2021 may be dead in 2026. Check recency.
- "Beats average retail" is NOT enough — you're graded against the marginal sharp price-setter.
- Diversification multiplies existing edge; it doesn't manufacture edge from nothing.
- Returns quoted gross of costs are fantasy; what matters is net of fees/slippage/funding.
- One-person constraints: limited capital, no co-location/speed, residential IP, must be legal from the Netherlands (no Kalshi/Polymarket trading, no US-only venues).

Be honest and calibrated. Most strategies should score LOW. Only genuinely structural, still-alive, accessible edges score high. Do not inflate scores to be encouraging.

After searching, output ONLY this JSON:
{"strategy": "...", "edge_type": "structural|predictive|mixed", "still_alive_2026": "yes|partly|no|unknown", "evidence": ["recent fact 1","recent fact 2"], "accessibility_nl_oneperson": "high|medium|low", "realistic_net_return": "<honest range or 'likely negative'>", "what_kills_it": "...", "worth_investigating_1to10": <int>, "verdict": "<two sentences, honest>"}"""


def build_prompt(strategy):
    return f"""STRATEGY TO EVALUATE: {strategy}

TODAY: {datetime.now(timezone.utc).date()}

Search for current (2026) evidence on whether this still works, real net returns, and competition. Then give your structured, skeptical verdict. Output only the JSON."""


def call_with_search(system, user, model=MODEL, max_tokens=3000):
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    n = sum(1 for b in resp.content if getattr(b, "type", None) == "server_tool_use")
    return text, n


def parse(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s == -1:
        raise ValueError(f"No JSON: {text[:200]}")
    return json.loads(text[s:e+1])


def cmd_eval(args):
    if args.file:
        strategies = json.load(open(args.file))
        if strategies and isinstance(strategies[0], dict):
            strategies = [s.get("strategy") or s.get("name") for s in strategies]
    else:
        strategies = [args.strategy]
    results = []
    for strat in strategies:
        print(f"\n{'='*64}\nEVALUATING: {strat}\n{'='*64}")
        if args.mock:
            text = json.dumps({"strategy": strat, "edge_type": "structural",
                "still_alive_2026": "partly", "evidence": ["mock evidence"],
                "accessibility_nl_oneperson": "medium", "realistic_net_return": "5-10%",
                "what_kills_it": "competition", "worth_investigating_1to10": 6,
                "verdict": "Mock verdict. Plausible but modest."})
            n = 1
        else:
            text, n = call_with_search(EVAL_SYSTEM, build_prompt(strat), model=args.model)
        v = parse(text)
        v["evaluated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        v["n_searches"] = n
        with open(OUT_LOG, "a") as f:
            f.write(json.dumps(v) + "\n")
        results.append(v)
        print(f"  edge type:        {v.get('edge_type')}")
        print(f"  still alive 2026: {v.get('still_alive_2026')}")
        print(f"  accessible (NL):  {v.get('accessibility_nl_oneperson')}")
        print(f"  realistic net:    {v.get('realistic_net_return')}")
        print(f"  what kills it:    {v.get('what_kills_it')}")
        print(f"  SCORE (1-10):     {v.get('worth_investigating_1to10')}   ({n} searches)")
        print(f"  verdict: {v.get('verdict')}")
    if len(results) > 1:
        print(f"\n{'='*64}\nRANKED:\n{'='*64}")
        for v in sorted(results, key=lambda x: x.get("worth_investigating_1to10", 0), reverse=True):
            print(f"  [{v.get('worth_investigating_1to10')}/10] {str(v.get('strategy'))[:50]:50} "
                  f"({v.get('edge_type')}, {v.get('still_alive_2026')} alive)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy")
    ap.add_argument("--file")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--mock", action="store_true")
    ap.set_defaults(func=cmd_eval)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
