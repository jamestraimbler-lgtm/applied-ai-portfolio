[Nederlands](README.nl.md) · [English](README.md)

# LLM Quality Gate

A small, dependency-free evaluator for structured AI responses.

The tool is intentionally deterministic. It does not pretend that string
matching can judge every semantic property of an LLM response. Instead, it
implements the repeatable checks that should sit beside human review or a
model-based judge: required evidence, forbidden claims, citations and length.

## Input format

One JSON object per line:

```json
{"case_id":"shipping-1","response":"Your order ships tomorrow. Source: order record.","required_terms":["ships tomorrow"],"required_evidence":["order record"],"must_have_citation":true,"citations":["order-123"],"max_chars":220}
```

## Run it

```bash
python3 quality_gate.py examples/responses.jsonl --report-only
```

The command emits one JSON result per case. Without `--report-only`, the
process exits with status 1 when any case fails, which makes the tool usable in
CI or a deployment gate.

## Test it

```bash
python3 -m unittest discover -s . -p 'test_*.py'
```

## What the checks establish

Required evidence uses case-insensitive substring matching. Citation checking
only checks for a non-empty citation list; it does not retrieve sources or
verify support. The score is the fraction of checks that pass, not a
probability that an answer is correct. An incorrect response can pass.

## End of track

**Completed small deterministic demo.** All six tests passed locally on
13 September 2026. The examples produce two passes and an intentional failure.
Without `--report-only`, that fixture exits 1; malformed input exits 2. No
model API is called. This is not a complete hallucination detector.
[Project register](../../docs/project-status.md).
