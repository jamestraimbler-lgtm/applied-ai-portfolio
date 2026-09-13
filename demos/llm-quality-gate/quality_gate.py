#!/usr/bin/env python3
"""Deterministic quality checks for structured LLM evaluation records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


def _strings(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item for item in value if item.strip()]


def _contains_all(response: str, terms: Iterable[str]) -> bool:
    folded = response.casefold()
    return all(term.casefold() in folded for term in terms)


def evaluate_record(record: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one record without returning the response text itself."""
    case_id = record.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("case_id must be a non-empty string")

    response = record.get("response")
    if not isinstance(response, str):
        raise ValueError("response must be a string")

    required_terms = _strings(record.get("required_terms"), "required_terms")
    forbidden_terms = _strings(record.get("forbidden_terms"), "forbidden_terms")
    required_evidence = _strings(
        record.get("required_evidence"), "required_evidence"
    )
    citations = _strings(record.get("citations"), "citations")

    min_chars = record.get("min_chars", 1)
    max_chars = record.get("max_chars", 2000)
    if not isinstance(min_chars, int) or not isinstance(max_chars, int):
        raise ValueError("min_chars and max_chars must be integers")
    if min_chars < 0 or max_chars < min_chars:
        raise ValueError("character limits are invalid")

    checks = {
        "non_empty": bool(response.strip()),
        "minimum_length": len(response) >= min_chars,
        "maximum_length": len(response) <= max_chars,
        "required_terms": _contains_all(response, required_terms),
        "forbidden_terms_absent": not any(
            term.casefold() in response.casefold() for term in forbidden_terms
        ),
        "required_evidence": _contains_all(response, required_evidence),
        "citations_present": (
            not bool(record.get("must_have_citation", False)) or bool(citations)
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    score = round(sum(checks.values()) / len(checks), 2)
    return {
        "case_id": case_id,
        "passed": not failures,
        "score": score,
        "response_chars": len(response),
        "checks": checks,
        "failures": failures,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL and attach line numbers to malformed records."""
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number}: record must be a JSON object")
        records.append(value)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSONL evaluation records")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="always exit zero after printing the report",
    )
    args = parser.parse_args(argv)

    try:
        results = [evaluate_record(record) for record in read_jsonl(args.input)]
    except (OSError, ValueError) as exc:
        print(f"quality-gate: {exc}", file=sys.stderr)
        return 2

    for result in results:
        print(json.dumps(result, sort_keys=True))
    failed = any(not result["passed"] for result in results)
    return 0 if args.report_only or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
