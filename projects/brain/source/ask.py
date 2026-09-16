#!/usr/bin/env python3
"""ask.py — Ask the brain open-ended questions (with live web search)."""
import argparse, sys
from anthropic import Anthropic

MODEL = "claude-opus-4-6"

SYSTEM = """You are a sharp, honest research analyst with live web access. The user is a one-person crypto/trading developer based in the Netherlands who values calibrated honesty over encouragement. When facts are needed, search for current ones rather than relying on training knowledge. Distinguish clearly between what you know, what you found via search (cite recency), and what you're inferring. If the premise of a question is flawed, say so. Be concise and concrete; no filler, no hedging theater."""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="+")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--no-search", action="store_true")
    args = ap.parse_args()
    question = " ".join(args.question)
    import os
    system = SYSTEM
    if os.path.exists("brain_memory.md"):
        system += "\n\n=== OPERATOR CONTEXT & MEMORY ===\n" + open("brain_memory.md").read()
    client = Anthropic()
    kwargs = {
        "model": args.model,
        "max_tokens": 2000,
        "system": system,
        "messages": [{"role": "user", "content": question}],
    }
    if not args.no_search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
    resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    n = sum(1 for b in resp.content if getattr(b, "type", None) == "server_tool_use")
    print(text)
    if n:
        print(f"\n[{n} web searches used]")


if __name__ == "__main__":
    main()
