#!/usr/bin/env python3
"""Verify the public examples and local documentation without network access."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def run_python(arguments: list[str], expected_exit: int = 0) -> str:
    result = subprocess.run(
        [sys.executable, *arguments], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", timeout=60,
    )
    if result.returncode != expected_exit:
        raise RuntimeError(
            f"{' '.join(arguments)}: expected exit {expected_exit}, "
            f"received {result.returncode}\n{result.stdout}{result.stderr}"
        )
    return result.stdout


def main() -> int:
    try:
        for folder in ["demos/llm-quality-gate", "projects/catalogcue"]:
            run_python(["-m", "unittest", "discover", "-s", folder, "-p", "test_*.py"])
            print(f"PASS: {folder} tests")

        gate = "demos/llm-quality-gate/quality_gate.py"
        fixture = "demos/llm-quality-gate/examples/responses.jsonl"
        for extra, code in [(["--report-only"], 0), ([], 1)]:
            rows = [json.loads(line) for line in run_python([gate, fixture, *extra], code).splitlines()]
            if [(row["case_id"], row["passed"]) for row in rows] != [
                ("shipping-1", True), ("refund-1", True), ("unsafe-1", False),
            ]:
                raise RuntimeError("Quality-gate fixture results differ from the documented contract")
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.jsonl"
            malformed.write_text('{"case_id":', encoding="utf-8")
            run_python([gate, str(malformed)], 2)
        print("PASS: quality-gate examples and exit codes 0, 1 and 2")

        actual = [json.loads(line) for line in run_python(["projects/catalogcue/demo.py", "--json"]).splitlines()]
        expected = [json.loads(line) for line in (ROOT / "projects/catalogcue/demo-expected.jsonl").read_text(encoding="utf-8").splitlines()]
        if actual != expected:
            raise RuntimeError("CatalogCue walkthrough differs from its expected outcomes")
        print("PASS: CatalogCue confirmation and notification retry walkthrough")

        checked = 0
        for document in sorted(ROOT.rglob("*.md")):
            if any(part in {".git", ".venv", "venv", "node_modules"} for part in document.relative_to(ROOT).parts):
                continue
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                target = target.strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                path = Path(unquote(parsed.path))
                if path.is_absolute() or not (document.parent / path).exists():
                    raise RuntimeError(f"Invalid local link in {document.relative_to(ROOT)}: {target}")
                checked += 1
        print(f"PASS: {checked} relative document links (fragment anchors not checked)")
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("Portfolio verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
