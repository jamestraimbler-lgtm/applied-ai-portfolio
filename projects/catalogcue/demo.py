#!/usr/bin/env python3
"""Run the real monitoring engine with simulated pages and notifications."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import storewatch


def run_demo() -> list[dict[str, object]]:
    """Keep all configuration/state temporary; mock only the external adapters."""
    target = {
        "name": "Demo product",
        "url": "https://example.com/product",
        "price_regex": r"<span>EUR ([^<]+)</span>",
        "price_change_pct": 5,
        "in_stock_markers": ["add to cart"],
        "out_of_stock_markers": ["sold out"],
        "content_regex": r"<h1>(.*?)</h1>",
    }
    scenarios = [
        ("baseline", 100, True),
        ("temporary-drop", 90, True),
        ("price-restored", 100, True),
        ("first-lower-observation", 90, True),
        ("confirmed-but-offline", 90, False),
        ("delivery-recovered", 90, True),
    ]
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="catalogcue-demo-") as directory:
        root = Path(directory)
        config = root / "config.json"
        state_path = root / "state.json"
        config.write_text(json.dumps({
            "state_path": str(state_path),
            "summary": {"enabled": False},
            "change_confirmations": 2,
            "targets": [target],
        }), encoding="utf-8")

        for step, price, delivery_succeeds in scenarios:
            observation = storewatch.extract_snapshot(
                f"<title>Demo product</title><h1>Demo product</h1>"
                f"<span>EUR {price}</span><button>Add to cart</button>",
                status=200,
                checked_at="2026-09-13T12:00:00+00:00",
                target=target,
            )
            with (
                patch.dict(os.environ, {"CATALOGCUE_NTFY_TOPIC": "demo-only"}),
                patch.object(storewatch, "fetch_snapshot", return_value=observation),
                patch.object(storewatch, "send_ntfy", return_value=delivery_succeeds) as send,
                patch.object(storewatch, "local_clock", return_value=datetime(2026, 9, 13, 12, tzinfo=timezone.utc)),
                redirect_stdout(io.StringIO()),
            ):
                exit_code = storewatch.run(config, dry_run=False)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            meta = state["_meta"]
            record = next(iter(state["targets"].values()))
            results.append({
                "step": step,
                "observed_price": price,
                "baseline_price": record["baseline"]["price"],
                "confirmed_changes": meta["stats"]["product_changes"],
                "delivered": send.call_count if delivery_succeeds else 0,
                "pending": len(meta["pending_notifications"]),
                "engine_exit": exit_code,
            })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSONL for verification")
    args = parser.parse_args()
    rows = run_demo()
    if args.json:
        for row in rows:
            print(json.dumps(row, sort_keys=True))
    else:
        print("CatalogCue offline walkthrough — simulated pages and delivery")
        for row in rows:
            print(
                f"{row['step']}: observed={row['observed_price']}, "
                f"baseline={row['baseline_price']:g}, "
                f"confirmed changes={row['confirmed_changes']}, "
                f"delivered={row['delivered']}, pending={row['pending']}"
            )
        print("No HTTP request or real notification was sent. Temporary state was removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
