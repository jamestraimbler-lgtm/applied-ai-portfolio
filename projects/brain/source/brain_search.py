#!/usr/bin/env python3
"""brain_search.py — The reasoning brain WITH live web search (informed mode)."""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone

from brain import classify_category

PRED_LOG = "predictions.jsonl"
MODEL = "claude-opus-4-6"

SEARCH_SYSTEM = """You are a calibrated superforecaster with live web access. Estimate the probability of a well-defined future event. You are scored by Brier score: calibration matters more than confidence.

FIRST, use web search to gather CURRENT facts relevant to the question — recent polls, current prices/levels, the state of any ongoing event, whether something has already happened, scheduled dates, latest news. Do NOT rely only on prior knowledge; the question may hinge on recent developments past your training cutoff.

THEN reason:
1. REFERENCE CLASS (outside view): base rate for this class of event.
2. CURRENT EVIDENCE (from your search): what the latest facts say, with rough recency.
3. SCENARIOS: 2-3 ways it resolves, with rough probabilities.
4. PREMORTEM: if your forecast is badly wrong, why?
5. TIME: how time-to-resolution affects it.
6. FINAL: a single calibrated probability (0-100%). Avoid lazy 50% and false-confident extremes unless warranted.

After searching and reasoning, output ONLY this JSON (no markdown, no preamble):
{"searched_for": ["query1","query2"], "key_current_facts": ["fact1","fact2"], "reference_class": "...", "base_rate_pct": <num>, "probability_pct": <num>, "confidence": "low|medium|high", "one_line_reasoning": "..."}"""


def build_user_prompt(q):
    return f"""QUESTION: {q['question']}

RESOLUTION CRITERIA: {q['resolution_criteria']}
RESOLVES BY: {q['resolution_date']}
CATEGORY: {q.get('category','general')}
TODAY'S DATE: {datetime.now(timezone.utc).date()}

Search for current facts first, then estimate the probability this resolves YES. Output only the JSON object."""


def call_with_search(system, user, model=MODEL, max_tokens=3000):
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    n_searches = sum(1 for b in resp.content if getattr(b, "type", None) == "server_tool_use")
    return text, n_searches


def parse_forecast(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found: {text[:300]}")
    return json.loads(text[start:end + 1])


def log_prediction(q, forecast, model, n_searches):
    rec = {
        "id": (q.get("id") or f"Q{uuid.uuid4().hex[:8]}") + "_s",
        "base_id": q.get("id"),
        "question": q["question"],
        "resolution_criteria": q["resolution_criteria"],
        "resolution_date": q["resolution_date"],
        "category": classify_category(q["question"]),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model + "+search",
        "n_searches": n_searches,
        "probability_pct": forecast["probability_pct"],
        "market_implied_pct": q.get("market_implied_pct"),
        "confidence": forecast.get("confidence"),
        "reasoning": forecast.get("one_line_reasoning"),
        "current_facts": forecast.get("key_current_facts"),
        "full_forecast": forecast,
        "outcome": None,
        "resolved_at": None,
    }
    with open(PRED_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def cmd_forecast(args):
    if args.file:
        questions = json.load(open(args.file))
    else:
        questions = [{
            "question": args.question,
            "resolution_criteria": args.criteria or "Resolves YES if the stated event occurs.",
            "resolution_date": args.date or "unspecified",
            "category": args.category or "general",
            "id": args.id,
        }]
    for q in questions:
        mkt = q.get("market_implied_pct")
        mkt_str = f"  [market: {mkt:.0f}%]" if mkt is not None else ""
        print(f"\n=== {q['question']}{mkt_str}")
        if args.mock:
            text = json.dumps({"searched_for": ["mock query"],
                "key_current_facts": ["mock fact found via search"],
                "reference_class": "mock", "base_rate_pct": 30,
                "probability_pct": 41, "confidence": "medium",
                "one_line_reasoning": "mock reasoning after search"})
            n_searches = 1
        else:
            text, n_searches = call_with_search(SEARCH_SYSTEM, build_user_prompt(q), model=args.model)
        forecast = parse_forecast(text)
        rec = log_prediction(q, forecast, args.model, n_searches)
        gap = ""
        if mkt is not None:
            gap = f"  | gap: {forecast['probability_pct']-mkt:+.0f}pts"
        print(f"  -> brain P(YES) = {forecast['probability_pct']}%  "
              f"[{forecast.get('confidence')}]  ({n_searches} searches){gap}")
        facts = forecast.get("key_current_facts") or []
        if facts:
            print(f"     found: {facts[0][:90]}")
        print(f"     {forecast.get('one_line_reasoning')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast")
    f.add_argument("--question"); f.add_argument("--criteria")
    f.add_argument("--date"); f.add_argument("--category"); f.add_argument("--id")
    f.add_argument("--file"); f.add_argument("--model", default=MODEL)
    f.add_argument("--mock", action="store_true")
    f.set_defaults(func=cmd_forecast)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
