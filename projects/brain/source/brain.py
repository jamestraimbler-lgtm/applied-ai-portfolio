#!/usr/bin/env python3
"""brain.py — calibrated forecasting engine with brain-vs-market edge scoring."""

import argparse
import json
import os
import uuid
from datetime import datetime, timezone

PRED_LOG = "predictions.jsonl"
MODEL = "claude-opus-4-6"

# Decision-relevant category keyword map.  Checked case-insensitively against
# question text; category with the most keyword hits wins, ties broken by dict
# order.  "other" is the fallback when nothing matches — never guess-stretch.
CATEGORY_KEYWORDS = {
    "macro_rates": ["interest rate", "inflation", "cpi", "gdp", "recession",
                    "federal reserve", "unemployment", "treasury", "fomc",
                    "rate cut", "rate hike", "monetary policy", "central bank",
                    "tariff", "debt ceiling", "yield curve", "bond market"],
    "regulation": ["regulation", "regulatory", "lawsuit", "legislation",
                   "etf approval", "court ruling", "enforcement", "indictment",
                   "executive order", "ban crypto", "compliance", " sec ",
                   " cftc "],
    "crypto_struct": ["bitcoin", " btc", "ethereum", " eth", "crypto",
                      "defi", "blockchain", "stablecoin", "halving", "solana",
                      "binance", "coinbase", "token unlock", "mining",
                      "altcoin"],
    "geopolitics": ["war ", "election", "president", "china", "russia",
                    "ukraine", "nato", "military", "invasion", "nuclear",
                    "iran", "north korea", "ceasefire", "geopoliti"],
    "tech_ai": ["artificial intelligence", " ai ", "openai", " gpt",
                "anthropic", "nvidia", "semiconductor", "machine learning",
                " agi ", " llm", "deepmind"],
}


def classify_category(question_text):
    """Classify question into a decision-relevant category via keyword match."""
    q = f" {question_text.lower()} "
    scores = {cat: sum(1 for kw in kws if kw in q)
              for cat, kws in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"

FORECAST_SYSTEM = """You are a calibrated superforecaster. Your job is to estimate the probability of a well-defined future event. You are scored by Brier score, so calibration matters more than confidence: if you say 70%, it should happen ~70% of the time.

Follow this process explicitly:
1. REFERENCE CLASS (outside view): What broad class of events is this? What's the base rate for that class? Anchor here FIRST, before any specifics.
2. EVIDENCE (inside view): What specific, verifiable factors push the probability above or below the base rate? Weigh each.
3. SCENARIOS: Sketch 2-3 distinct ways this could resolve, with rough probabilities.
4. PREMORTEM: Assume your forecast is badly wrong. Why? What are you likely over/under-weighting?
5. TIME: How does the time remaining until resolution affect the estimate?
6. FINAL: State a single probability (0-100%). Avoid lazy 50%. Avoid false-confident 99%/1% unless the outside view truly supports it.

Be concrete and calibrated, not persuasive. You will be wrong sometimes; the goal is to be wrong in a well-calibrated way.

Output ONLY valid JSON, no markdown, no preamble:
{"reference_class": "...", "base_rate_pct": <number>, "key_evidence": ["..."], "scenarios": [{"desc":"...","pct":<number>}], "premortem": "...", "probability_pct": <number>, "confidence": "low|medium|high", "one_line_reasoning": "..."}"""


def build_user_prompt(q):
    return f"""QUESTION: {q['question']}

RESOLUTION CRITERIA: {q['resolution_criteria']}
RESOLVES BY: {q['resolution_date']}
CATEGORY: {q.get('category','general')}
TODAY'S DATE: {datetime.now(timezone.utc).date()}

Estimate the probability this resolves YES. Output only the JSON object."""


def call_model(system, user, model=MODEL, max_tokens=1500):
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def parse_forecast(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found: {text[:200]}")
    return json.loads(text[start:end + 1])


def log_prediction(q, forecast, model):
    rec = {
        "id": q.get("id") or f"Q{uuid.uuid4().hex[:8]}",
        "question": q["question"],
        "resolution_criteria": q["resolution_criteria"],
        "resolution_date": q["resolution_date"],
        "category": classify_category(q["question"]),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "probability_pct": forecast["probability_pct"],
        "market_implied_pct": q.get("market_implied_pct"),
        "confidence": forecast.get("confidence"),
        "reasoning": forecast.get("one_line_reasoning"),
        "full_forecast": forecast,
        "outcome": None,
        "resolved_at": None,
    }
    with open(PRED_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def load_predictions():
    if not os.path.exists(PRED_LOG):
        return []
    return [json.loads(l) for l in open(PRED_LOG) if l.strip()]


def save_all(preds):
    with open(PRED_LOG, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")


def cmd_forecast(args):
    if args.file:
        questions = json.load(open(args.file))
    else:
        questions = [{
            "question": args.question,
            "resolution_criteria": args.criteria or "Resolves YES if the stated event occurs.",
            "resolution_date": args.date or "unspecified",
            "category": args.category or "general",
        }]
    for q in questions:
        mkt = q.get("market_implied_pct")
        mkt_str = f"  [market: {mkt:.0f}%]" if mkt is not None else ""
        print(f"\n=== {q['question']}{mkt_str}")
        if args.mock:
            text = json.dumps({"reference_class": "mock", "base_rate_pct": 30,
                "key_evidence": ["mock"], "scenarios": [{"desc": "yes", "pct": 35}],
                "premortem": "mock", "probability_pct": 35, "confidence": "medium",
                "one_line_reasoning": "mock reasoning"})
        else:
            text = call_model(FORECAST_SYSTEM, build_user_prompt(q), model=args.model)
        forecast = parse_forecast(text)
        rec = log_prediction(q, forecast, args.model)
        edge_str = ""
        if mkt is not None:
            diff = forecast["probability_pct"] - mkt
            edge_str = f"  | brain-market gap: {diff:+.0f}pts"
        print(f"  -> brain P(YES) = {forecast['probability_pct']}%  "
              f"[{forecast.get('confidence')}]  id={rec['id']}{edge_str}")
        print(f"     {forecast.get('one_line_reasoning')}")


def cmd_resolve(args):
    preds = load_predictions()
    found = False
    for p in preds:
        if p["id"] == args.id:
            p["outcome"] = 1 if args.outcome.lower() in ("yes", "1", "true") else 0
            p["resolved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            found = True
            mkt = p.get("market_implied_pct")
            mkt_str = f", market said {mkt:.0f}%" if mkt is not None else ""
            print(f"Resolved {args.id}: outcome={p['outcome']} "
                  f"(brain said {p['probability_pct']}%{mkt_str})")
    if not found:
        print(f"No prediction with id {args.id}")
    save_all(preds)


def cmd_score(args):
    preds = load_predictions()
    resolved = [p for p in preds if p.get("outcome") in (0, 1)]
    if not resolved:
        print("No resolved predictions yet.")
        return
    n = len(resolved)
    brain_brier = sum((p["probability_pct"]/100 - p["outcome"])**2 for p in resolved) / n
    mean_out = sum(p["outcome"] for p in resolved) / n
    baseline = sum((mean_out - p["outcome"])**2 for p in resolved) / n
    print(f"Resolved predictions: {n}")
    print(f"Brain Brier:          {brain_brier:.4f}   (lower better; 0.25 = coin flip)")
    print(f"Base-rate baseline:   {baseline:.4f}   (always guessing mean {mean_out:.2f})")
    print(f"Brain skill vs base:  {baseline - brain_brier:+.4f}   "
          f"({'beating base rate' if baseline > brain_brier else 'NOT beating base rate'})")
    with_mkt = [p for p in resolved if p.get("market_implied_pct") is not None]
    if with_mkt:
        m = len(with_mkt)
        b_brier = sum((p["probability_pct"]/100 - p["outcome"])**2 for p in with_mkt) / m
        mk_brier = sum((p["market_implied_pct"]/100 - p["outcome"])**2 for p in with_mkt) / m
        print(f"\n  HEAD-TO-HEAD vs MARKET ({m} questions with a market price):")
        print(f"  Brain Brier:  {b_brier:.4f}")
        print(f"  Market Brier: {mk_brier:.4f}")
        print(f"  EDGE:         {mk_brier - b_brier:+.4f}   "
              f"({'BRAIN BEATS MARKET' if b_brier < mk_brier else 'market beats brain'})")
        disagree = [p for p in with_mkt
                    if abs(p["probability_pct"] - p["market_implied_pct"]) >= 10]
        if disagree:
            brain_closer = sum(1 for p in disagree
                if abs(p["probability_pct"]/100 - p["outcome"])
                 < abs(p["market_implied_pct"]/100 - p["outcome"]))
            print(f"\n  On {len(disagree)} DISAGREEMENTS (>=10pt gap), "
                  f"brain was closer {brain_closer}/{len(disagree)} times "
                  f"({brain_closer/len(disagree)*100:.0f}%)")
            print(f"  (This is the real edge signal: when brain differs from crowd, is it right?)")
    buckets = {}
    for p in resolved:
        buckets.setdefault(min(int(p["probability_pct"] // 10), 9), []).append(p)
    print(f"\n  Calibration (brain predicted % vs actual YES rate):")
    print(f"  {'bucket':>10} {'n':>4} {'predicted':>10} {'actual':>8}")
    for b in sorted(buckets):
        ps = buckets[b]
        print(f"  {b*10:>3}-{b*10+10:<6} {len(ps):>4} "
              f"{sum(x['probability_pct'] for x in ps)/len(ps):>9.1f}% "
              f"{sum(x['outcome'] for x in ps)/len(ps)*100:>7.1f}%")

    # Per-category Brier table
    cats = {}
    for p in resolved:
        cat = p.get("category", "other")
        if cat not in CATEGORY_KEYWORDS and cat != "other":
            cat = "other"
        cats.setdefault(cat, []).append(p)
    print(f"\n  Per-category Brier scores:")
    print(f"  {'category':>15} {'n':>4} {'brain':>8} {'market':>8} {'edge':>8}  note")
    usable = []
    for cat in sorted(cats):
        ps = cats[cat]
        nc = len(ps)
        b_brier = sum((p["probability_pct"]/100 - p["outcome"])**2 for p in ps) / nc
        with_m = [p for p in ps if p.get("market_implied_pct") is not None]
        note = "" if nc >= 30 else "n<30 -- not usable for decisions"
        if with_m:
            m_brier = sum((p["market_implied_pct"]/100 - p["outcome"])**2
                          for p in with_m) / len(with_m)
            edge = m_brier - b_brier
            print(f"  {cat:>15} {nc:>4} {b_brier:>8.4f} {m_brier:>8.4f} {edge:>+8.4f}  {note}")
            if nc >= 30 and b_brier <= m_brier:
                usable.append(cat)
        else:
            print(f"  {cat:>15} {nc:>4} {b_brier:>8.4f} {'---':>8} {'---':>8}  {note}")
    if usable:
        print(f"\n  Calibrated enough to consult: {', '.join(usable)}")
    else:
        print(f"\n  No category yet has n>=30 AND brain<=market Brier.")


def cmd_show(args):
    preds = load_predictions()
    if not preds:
        print("No predictions logged yet.")
        return
    for p in preds:
        status = "OPEN" if p["outcome"] is None else f"resolved={p['outcome']}"
        mkt = p.get("market_implied_pct")
        mkt_str = f" mkt={mkt:.0f}%" if mkt is not None else ""
        print(f"  {p['id']:>16}  brain={p['probability_pct']:>3}%{mkt_str:>9}  "
              f"[{status:>10}]  by {p['resolution_date']}  | {p['question'][:50]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast")
    f.add_argument("--question"); f.add_argument("--criteria")
    f.add_argument("--date"); f.add_argument("--category")
    f.add_argument("--file"); f.add_argument("--model", default=MODEL)
    f.add_argument("--mock", action="store_true")
    f.set_defaults(func=cmd_forecast)
    r = sub.add_parser("resolve")
    r.add_argument("--id", required=True); r.add_argument("--outcome", required=True)
    r.set_defaults(func=cmd_resolve)
    sub.add_parser("score").set_defaults(func=cmd_score)
    sub.add_parser("show").set_defaults(func=cmd_show)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
