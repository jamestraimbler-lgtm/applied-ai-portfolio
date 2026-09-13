import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from storewatch import (
    Snapshot,
    changes,
    evaluate_target,
    extract_snapshot,
    flush_notifications,
    log_observation_audit,
    monitor_signature,
    migrate_state,
    parse_number,
    queue_notification,
    run,
    summary_message,
    validate_observation,
)


def snapshot(
    *,
    price=100.0,
    in_stock=True,
    content_hash="same",
    available=True,
    error=None,
):
    return Snapshot(
        "now",
        200 if available else None,
        available,
        "Shoe",
        price if available else None,
        in_stock if available else None,
        content_hash if available else None,
        error,
    )


def record_for(target, baseline):
    return {
        "target_signature": monitor_signature(target),
        "baseline": baseline.__dict__,
    }


class StoreWatchTests(unittest.TestCase):
    def test_parses_common_prices(self):
        self.assertEqual(parse_number("$1,249.95"), 1249.95)
        self.assertEqual(parse_number("€1.249,95"), 1249.95)

    def test_extracts_price_stock_and_content(self):
        result = extract_snapshot(
            "<title>Shoe</title><h1>Runner</h1>"
            "<span>€129,99</span><button>Add to cart</button>",
            status=200,
            checked_at="now",
            target={
                "price_regex": r"<span>€([^<]+)</span>",
                "in_stock_markers": ["add to cart"],
                "out_of_stock_markers": ["sold out"],
                "content_regex": r"<h1>(.*?)</h1>",
            },
        )
        self.assertEqual(result.title, "Shoe")
        self.assertEqual(result.price, 129.99)
        self.assertTrue(result.in_stock)
        self.assertIsNotNone(result.content_hash)

    def test_content_items_ignore_dynamic_shell_duplicates_and_order(self):
        target = {
            "content_item_regex": r'href=["\']\s*(/products/[^"\'?#\s]+)'
        }
        first = extract_snapshot(
            '<script>request="one"</script>'
            '<a href="/products/red?variant=1">Red</a>'
            '<a href=" /products/blue">Blue</a>'
            '<a href="/products/red">Red again</a>',
            status=200,
            checked_at="now",
            target=target,
        )
        second = extract_snapshot(
            '<script>request="two"</script>'
            '<a href="/products/red">Red</a>'
            '<a href="/products/blue#details">Blue</a>',
            status=200,
            checked_at="later",
            target=target,
        )
        changed = extract_snapshot(
            '<a href="/products/red">Red</a>'
            '<a href="/products/green">Green</a>',
            status=200,
            checked_at="later",
            target=target,
        )
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.content_hash, changed.content_hash)

    def test_material_price_and_stock_change(self):
        previous = snapshot(price=100.0, in_stock=False, content_hash="a")
        current = snapshot(price=90.0, in_stock=True, content_hash="b")
        events = changes(
            "Runner",
            previous,
            current,
            {"price_change_pct": 5},
        )
        self.assertIn("Runner: back in stock", events)
        self.assertIn("Runner: price down 10.0% (100 → 90)", events)

    def test_small_price_move_is_silent(self):
        self.assertEqual(
            changes(
                "Runner",
                snapshot(),
                snapshot(price=102.0),
                {"price_change_pct": 5},
            ),
            [],
        )

    def test_change_requires_two_matching_observations(self):
        target = {"price_change_pct": 5}
        baseline = snapshot(price=100.0)
        record = record_for(target, baseline)
        changed = snapshot(price=90.0)
        record, first_events, first_health = evaluate_target(
            name="Runner",
            target=target,
            record=record,
            current=changed,
            change_confirmations=2,
            failure_confirmations=2,
        )
        self.assertEqual(first_events, [])
        self.assertEqual(first_health, [])
        self.assertEqual(record["candidate_count"], 1)

        record, second_events, second_health = evaluate_target(
            name="Runner",
            target=target,
            record=record,
            current=changed,
            change_confirmations=2,
            failure_confirmations=2,
        )
        self.assertEqual(
            second_events, ["Runner: price down 10.0% (100 → 90)"]
        )
        self.assertEqual(second_health, [])
        self.assertEqual(record["candidate_count"], 0)
        self.assertEqual(record["baseline"]["price"], 90.0)

    def test_unstable_content_never_confirms(self):
        target = {"price_change_pct": 5}
        record = record_for(target, snapshot(content_hash="base"))
        for content_hash in ("dynamic-a", "dynamic-b", "dynamic-c"):
            record, events, health_events = evaluate_target(
                name="Collection",
                target=target,
                record=record,
                current=snapshot(content_hash=content_hash),
                change_confirmations=2,
                failure_confirmations=2,
            )
            self.assertEqual(events, [])
            self.assertEqual(health_events, [])
            self.assertEqual(record["candidate_count"], 1)
        self.assertEqual(record["baseline"]["content_hash"], "base")

    def test_failure_and_recovery_are_confirmed(self):
        target = {}
        record = record_for(target, snapshot())
        failed = snapshot(available=False, error="timeout")
        record, first_product, first_health = evaluate_target(
            name="Runner",
            target=target,
            record=record,
            current=failed,
            change_confirmations=2,
            failure_confirmations=2,
        )
        self.assertEqual(first_product, [])
        self.assertEqual(first_health, [])
        record, second_product, second_health = evaluate_target(
            name="Runner",
            target=target,
            record=record,
            current=failed,
            change_confirmations=2,
            failure_confirmations=2,
        )
        self.assertEqual(second_product, [])
        self.assertEqual(
            second_health, ["Runner: monitor check failed after 2 checks"]
        )
        record, recovery_product, recovery_health = evaluate_target(
            name="Runner",
            target=target,
            record=record,
            current=snapshot(),
            change_confirmations=2,
            failure_confirmations=2,
        )
        self.assertEqual(recovery_product, [])
        self.assertEqual(recovery_health, ["Runner: monitor check recovered"])

    def test_signal_config_change_resets_without_false_alert(self):
        old_target = {"content_regex": r"<main>(.*?)</main>"}
        new_target = {
            "content_item_regex": r'href=["\'](/products/[^"\']+)'
        }
        record = record_for(old_target, snapshot(content_hash="old-shell"))
        record, events, health_events = evaluate_target(
            name="Collection",
            target=new_target,
            record=record,
            current=snapshot(content_hash="semantic-list"),
            change_confirmations=2,
            failure_confirmations=2,
        )
        self.assertEqual(events, [])
        self.assertEqual(health_events, [])
        self.assertEqual(record["candidate_count"], 0)
        self.assertEqual(record["baseline"]["content_hash"], "semantic-list")

    def test_configured_extraction_failure_is_unhealthy(self):
        result = validate_observation(
            snapshot(price=None),
            {"price_regex": r"price=(\d+)"},
        )
        self.assertFalse(result.available)
        self.assertIn("price", result.error)

    def test_failure_and_recovery_audit_is_timestamped_and_sanitized(self):
        failed = Snapshot(
            checked_at="2026-07-31T17:00:00+00:00",
            http_status=None,
            available=False,
            title=None,
            price=None,
            in_stock=None,
            content_hash=None,
            error="Request failed at https://example.com/p?token=secret-value",
        )
        failed_record = {"consecutive_failures": 2}
        output = io.StringIO()
        with redirect_stdout(output):
            log_observation_audit(
                name="Example",
                current=failed,
                previous_record={"consecutive_failures": 1},
                record=failed_record,
                events=["Example: monitor check failed after 2 checks"],
            )
            log_observation_audit(
                name="Example",
                current=Snapshot(
                    checked_at="2026-07-31T17:10:00+00:00",
                    http_status=200,
                    available=True,
                    title="Recovered",
                    price=None,
                    in_stock=None,
                    content_hash=None,
                    error=None,
                ),
                previous_record=failed_record,
                record={"consecutive_failures": 0},
                events=["Example: monitor check recovered"],
            )
        audit = output.getvalue()
        self.assertIn('"event": "check_failed"', audit)
        self.assertIn('"event": "check_recovered"', audit)
        self.assertIn('"consecutive_failures": 2', audit)
        self.assertIn('"failed_checks": 2', audit)
        self.assertIn("2026-07-31T17:00:00+00:00", audit)
        self.assertIn("https://example.com/p?[redacted]", audit)
        self.assertNotIn("secret-value", audit)

    def test_legacy_state_migrates(self):
        legacy = {"abc": snapshot().__dict__}
        state = migrate_state(legacy, "2026-07-30")
        self.assertEqual(state["_meta"]["version"], 3)
        self.assertEqual(state["targets"]["abc"]["baseline"]["price"], 100.0)

    def test_version_two_stats_migrate_without_misclassifying_events(self):
        state = {
            "_meta": {
                "version": 2,
                "last_summary_date": None,
                "pending_notifications": [],
                "stats": {
                    "date": "2026-08-02",
                    "checks": 12,
                    "successes": 10,
                    "failures": 2,
                    "changes": 4,
                },
            },
            "targets": {"abc": {"baseline": snapshot().__dict__}},
        }
        migrated = migrate_state(state, "2026-08-02")
        self.assertEqual(migrated["_meta"]["version"], 3)
        self.assertEqual(migrated["_meta"]["stats"]["checks"], 12)
        self.assertEqual(migrated["_meta"]["stats"]["failures"], 2)
        self.assertEqual(migrated["_meta"]["stats"]["product_changes"], 0)
        self.assertEqual(migrated["_meta"]["stats"]["health_events"], 0)
        self.assertIn("abc", migrated["targets"])

    def test_summary_is_concise(self):
        message = summary_message(
            {
                "date": "2026-07-30",
                "checks": 24,
                "successes": 23,
                "failures": 1,
                "product_changes": 2,
                "health_events": 1,
            },
            3,
        )
        self.assertIn("3 pages", message)
        self.assertIn("23/24 checks successful", message)
        self.assertIn("2 product changes", message)
        self.assertIn("1 health event", message)
        self.assertIn("1 failed check", message)

    def test_failed_notification_stays_in_outbox(self):
        state = migrate_state({}, "2026-07-30")
        queue_notification(
            state,
            kind="change",
            title="Update",
            message="Changed",
            dedupe_key="change:1",
        )
        with patch("storewatch.send_ntfy", return_value=False):
            sent, pending = flush_notifications(
                state,
                server="https://ntfy.invalid",
                topic="private",
                timeout=1,
            )
        self.assertEqual((sent, pending), (0, 1))
        self.assertEqual(
            state["_meta"]["pending_notifications"][0]["attempts"], 1
        )

    def test_dry_run_does_not_write_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            state_path = root / "state.json"
            config_path.write_text(
                json.dumps(
                    {
                        "state_path": str(state_path),
                        "summary": {"enabled": False},
                        "targets": [
                            {"name": "Example", "url": "https://example.com"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch("storewatch.fetch_snapshot", return_value=snapshot()):
                self.assertEqual(run(config_path, dry_run=True), 0)
            self.assertFalse(state_path.exists())

    def test_production_run_persists_confirmation_and_delivers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            state_path = root / "state.json"
            config_path.write_text(
                json.dumps(
                    {
                        "state_path": str(state_path),
                        "summary": {"enabled": False},
                        "targets": [
                            {
                                "name": "Runner",
                                "url": "https://example.com/product",
                                "price_change_pct": 5,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {"CATALOGCUE_NTFY_TOPIC": "private"},
                    clear=False,
                ),
                patch("storewatch.send_ntfy", return_value=True) as deliver,
                patch(
                    "storewatch.fetch_snapshot",
                    side_effect=[
                        snapshot(price=100),
                        snapshot(price=90),
                        snapshot(price=90),
                    ],
                ),
            ):
                self.assertEqual(run(config_path, dry_run=False), 0)
                self.assertEqual(run(config_path, dry_run=False), 0)
                self.assertEqual(run(config_path, dry_run=False), 0)
            deliver.assert_called_once()
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            record = next(iter(persisted["targets"].values()))
            self.assertEqual(record["baseline"]["price"], 90)
            self.assertEqual(
                persisted["_meta"]["pending_notifications"], []
            )

    def test_health_events_are_not_counted_as_product_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            state_path = root / "state.json"
            config_path.write_text(
                json.dumps(
                    {
                        "state_path": str(state_path),
                        "failure_confirmations": 2,
                        "summary": {"enabled": False},
                        "targets": [
                            {"name": "Runner", "url": "https://example.com"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {"CATALOGCUE_NTFY_TOPIC": "private"},
                    clear=False,
                ),
                patch("storewatch.send_ntfy", return_value=True) as deliver,
                patch(
                    "storewatch.fetch_snapshot",
                    side_effect=[
                        snapshot(),
                        snapshot(available=False, error="offline"),
                        snapshot(available=False, error="offline"),
                        snapshot(),
                    ],
                ),
            ):
                for _ in range(4):
                    self.assertEqual(run(config_path, dry_run=False), 0)

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            stats = persisted["_meta"]["stats"]
            self.assertEqual(stats["product_changes"], 0)
            self.assertEqual(stats["health_events"], 2)
            self.assertEqual(stats["failures"], 2)
            self.assertEqual(deliver.call_count, 2)
            self.assertTrue(
                all(call.kwargs["title"] == "CatalogCue health" for call in deliver.call_args_list)
            )

    def test_daily_summary_delivers_once_per_local_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            state_path = root / "state.json"
            config_path.write_text(
                json.dumps(
                    {
                        "state_path": str(state_path),
                        "summary": {
                            "enabled": True,
                            "hour_local": 18,
                            "timezone": "Europe/Amsterdam",
                        },
                        "targets": [
                            {"name": "Example", "url": "https://example.com"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            clock = datetime(
                2026, 7, 30, 18, 30, tzinfo=ZoneInfo("Europe/Amsterdam")
            )
            with (
                patch.dict(
                    os.environ,
                    {"CATALOGCUE_NTFY_TOPIC": "private"},
                    clear=False,
                ),
                patch("storewatch.local_clock", return_value=clock),
                patch("storewatch.fetch_snapshot", return_value=snapshot()),
                patch("storewatch.send_ntfy", return_value=True) as deliver,
            ):
                self.assertEqual(run(config_path, dry_run=False), 0)
                self.assertEqual(run(config_path, dry_run=False), 0)
            self.assertEqual(deliver.call_count, 1)
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["_meta"]["last_summary_date"], "2026-07-30"
            )


if __name__ == "__main__":
    unittest.main()
