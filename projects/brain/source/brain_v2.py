#!/usr/bin/env python3
"""brain_v2.py — informed brain with FORCED decomposition + adversarial premortem.
Forces superforecaster decomposition (ref class, 3 for/against w/ weights, crux,
base-rate adjustment, update trigger), then a 2nd pass red-teams & may revise.
Logs first-pass AND revised numbers. Blind to market. Tag '+v2'. Auto-loads memory."""
import argparse, json, os, uuid
from datetime import datetime, timezone

PRED_LOG = "predictions.jsonl"
MEM_FILE = "brain_memory.md"
MODEL = "claude-opus-4-6"

SEARCH_SYSTEM = """You are a calibrated superforecaster with live web access. Estimate the probability of a well-defined future event. Scored by Brier score: calibration beats confidence.

FIRST search for CURRENT facts (recent developments, current levels, whether something already happened, scheduled dates). Don't rely only on training knowledge.

THEN reason with this FORCED decomposition — do every step:
1. REFERENCE CLASS: name the class of events this belongs to and its base rate. Anchor here FIRST.
2. THREE REASONS FOR (YES), each with a rough weight (small/medium/large pull on probability).
3. THREE REASONS AGAINST (NO), each with a rough weight.
4. THE CRUX: the single unknown that would move your estimate the most if you knew it.
5. ADJUST FROM BASE RATE: start at the base rate, then move for the net of your for/against weights. Show the arithmetic.
6. PRE-COMMIT: state what new fact would make you update your number by >10 points.
7. FINAL probability (0-100%). Avoid lazy 50% and false-confident extremes unless the outside view truly supports them.

Output ONLY this JSON (decomposition lives in the fields, keep each terse):
{"searched_for":["..."],"key_current_facts":["..."],"reference_class":"...","base_rate_pct":<n>,"reasons_for":[{"r":"...","weight":"small|medium|large"}],"reasons_against":[{"r":"...","weight":"small|medium|large"}],"crux":"...","adjustment_note":"...","update_trigger":"...","probability_pct":<n>,"confidence":"low|medium|high","one_line_reasoning":"..."}"""

PREMORTEM_SYSTEM = """You are stress-testing your own probability forecast for CALIBRATION errors. You receive a question and your first-pass probability. Do NOT assume the opposite outcome happens — instead check BOTH ways the NUMBER could be miscalibrated:
- Could it be too HIGH? (overconfident toward YES — what are you overweighting?)
- Could it be too LOW? (overconfident toward NO — what are you dismissing?)
Weigh both. Then give your best-calibrated probability. Only revise if you find a genuine error; revisions should usually be SMALL (a few points). A large revision is only justified if you missed a decisive fact, not because you flipped perspective. The first pass was a careful decomposition — respect it unless there's a real reason.

Output ONLY this JSON:
{"could_be_too_high":"...","could_be_too_low":"...","revised_probability_pct":<n>,"revision_reason":"...","changed_by_pts":<n>}"""


def load_memory_system(base):
    if os.path.exists(MEM_FILE):
        return base + "\n\n=== OPERATOR CONTEXT & MEMORY ===\n" + open(MEM_FILE).read()
    return base


def build_user_prompt(q):
    return f"""QUESTION: {q['question']}

RESOLUTION CRITERIA: {q['resolution_criteria']}
RESOLVES BY: {q['resolution_date']}
CATEGORY: {q.get('category','general')}
TODAY'S DATE: {datetime.now(timezone.utc).date()}

Search for current facts, then run the full decomposition. Output only the JSON."""


def build_premortem_user(q, first):
    return f"""QUESTION: {q['question']}
YOUR FIRST-PASS PROBABILITY: {first['probability_pct']}%
KEY REASONING: base rate {first.get('base_rate_pct')}%, crux: "{first.get('crux')}", {first.get('one_line_reasoning')}

Stress-test this NUMBER for calibration errors both ways (too high? too low?). Give your best-calibrated probability; revise only if you find a real error. Output only the JSON."""


def call_search(system, user, model=MODEL, max_tokens=3000):
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


def call_plain(system, user, model=MODEL, max_tokens=1000):
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    s, e = text.find("{"), text.rfind("}")
    if s == -1:
        raise ValueError(f"No JSON: {text[:200]}")
    return json.loads(text[s:e+1])


def log_prediction(q, fc, model, n_searches, premortem):
    rec = {
        "id": (q.get("id") or f"Q{uuid.uuid4().hex[:8]}") + "_v2",
        "base_id": q.get("id"),
        "question": q["question"],
        "resolution_criteria": q["resolution_criteria"],
        "resolution_date": q["resolution_date"],
        "category": q.get("category", "general"),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model + "+v2",
        "n_searches": n_searches,
        "probability_pct": fc["probability_pct"],
        "first_pass_pct": fc.get("first_pass_pct"),
        "market_implied_pct": q.get("market_implied_pct"),
        "confidence": fc.get("confidence"),
        "reasoning": fc.get("one_line_reasoning"),
        "crux": fc.get("crux"),
        "current_facts": fc.get("key_current_facts"),
        "premortem": premortem,
        "full_forecast": fc,
        "outcome": None, "resolved_at": None,
    }
    with open(PRED_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def cmd_forecast(args):
    questions = json.load(open(args.file)) if args.file else [{
        "question": args.question,
        "resolution_criteria": args.criteria or "Resolves YES if the stated event occurs.",
        "resolution_date": args.date or "unspecified",
        "category": args.category or "general", "id": args.id,
    }]
    search_sys = load_memory_system(SEARCH_SYSTEM)
    for q in questions:
        mkt = q.get("market_implied_pct")
        mkt_str = f"  [market: {mkt:.0f}%]" if mkt is not None else ""
        print(f"\n=== {q['question']}{mkt_str}")
        if args.mock:
            fc = {"searched_for": ["mock"], "key_current_facts": ["mock fact"],
                  "reference_class": "mock", "base_rate_pct": 40,
                  "reasons_for": [{"r": "a", "weight": "medium"}],
                  "reasons_against": [{"r": "b", "weight": "small"}],
                  "crux": "mock crux", "adjustment_note": "40 -> 55",
                  "update_trigger": "if X", "probability_pct": 55,
                  "confidence": "medium", "one_line_reasoning": "mock"}
            n = 1
        else:
            text, n = call_search(search_sys, build_user_prompt(q), model=args.model)
            fc = parse_json(text)
        premortem = None
        if not args.no_premortem:
            if args.mock:
                pm = {"could_be_too_high": "mock high risk", "could_be_too_low": "mock low risk",
                      "revised_probability_pct": 52, "revision_reason": "mock revise",
                      "changed_by_pts": -3}
            else:
                pm_text = call_plain(PREMORTEM_SYSTEM, build_premortem_user(q, fc), model=args.model)
                pm = parse_json(pm_text)
            fc["first_pass_pct"] = fc["probability_pct"]
            fc["probability_pct"] = pm["revised_probability_pct"]
            premortem = pm
        rec = log_prediction(q, fc, args.model, n, premortem)
        gap = f"  | gap: {fc['probability_pct']-mkt:+.0f}pts" if mkt is not None else ""
        if premortem:
            print(f"  -> first {fc['first_pass_pct']}% -> premortem {fc['probability_pct']}%  "
                  f"({premortem['changed_by_pts']:+}pts)  [{fc.get('confidence')}]  ({n} searches){gap}")
            print(f"     crux: {fc.get('crux')}")
            print(f"     too-high risk: {premortem.get('could_be_too_high','')[:55]}")
            print(f"     too-low risk:  {premortem.get('could_be_too_low','')[:55]}")
        else:
            print(f"  -> {fc['probability_pct']}%  [{fc.get('confidence')}]  ({n} searches){gap}")
            print(f"     crux: {fc.get('crux')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast")
    f.add_argument("--question"); f.add_argument("--criteria"); f.add_argument("--date")
    f.add_argument("--category"); f.add_argument("--id"); f.add_argument("--file")
    f.add_argument("--model", default=MODEL)
    f.add_argument("--no-premortem", action="store_true")
    f.add_argument("--mock", action="store_true")
    f.set_defaults(func=cmd_forecast)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
