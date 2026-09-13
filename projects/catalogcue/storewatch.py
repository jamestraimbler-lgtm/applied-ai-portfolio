#!/usr/bin/env python3
"""Reliable, read-only product-page monitoring with concise phone alerts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


USER_AGENT = (
    "Mozilla/5.0 (compatible; CatalogCue/1.0; "
    "+https://example.invalid/catalogcue)"
)
STATE_VERSION = 3


@dataclass(frozen=True)
class Snapshot:
    checked_at: str
    http_status: int | None
    available: bool
    title: str | None
    price: float | None
    in_stock: bool | None
    content_hash: str | None
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split()).strip()


def extracted_content(body: str, target: dict[str, Any]) -> str:
    """Return only the configured semantic content used for change detection."""
    item_regex = target.get("content_item_regex")
    if item_regex:
        matches = re.findall(str(item_regex), body, re.I | re.S)
        items: set[str] = set()
        for match in matches:
            if isinstance(match, tuple):
                match = next((part for part in match if part), "")
            value = normalized_text(str(match))
            if value:
                items.add(value)
        return "\n".join(sorted(items))

    content_regex = target.get("content_regex")
    if content_regex:
        match = re.search(str(content_regex), body, re.I | re.S)
        return match.group(1) if match else ""
    return body


def monitor_signature(target: dict[str, Any]) -> str:
    """Identify the configured signal definition so config edits reset cleanly."""
    signal_config = {
        "url": target.get("url"),
        "price_regex": target.get("price_regex"),
        "price_change_pct": target.get("price_change_pct"),
        "in_stock_markers": target.get("in_stock_markers", []),
        "out_of_stock_markers": target.get("out_of_stock_markers", []),
        "content_regex": target.get("content_regex"),
        "content_item_regex": target.get("content_item_regex"),
    }
    return hashlib.sha256(
        json.dumps(signal_config, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def parse_number(value: str) -> float | None:
    cleaned = re.sub(r"[^\d,.\-]", "", value).strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        tail = cleaned.rsplit(",", 1)[-1]
        cleaned = (
            cleaned.replace(",", ".")
            if len(tail) <= 2
            else cleaned.replace(",", "")
        )
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_snapshot(
    body: str,
    *,
    status: int,
    target: dict[str, Any],
    checked_at: str | None = None,
) -> Snapshot:
    lower = body.lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    title = normalized_text(title_match.group(1)) if title_match else None

    price = None
    price_regex = target.get("price_regex")
    if price_regex:
        match = re.search(str(price_regex), body, re.I | re.S)
        if match:
            price = parse_number(match.group(1))

    positive = [
        str(marker).lower() for marker in target.get("in_stock_markers", [])
    ]
    negative = [
        str(marker).lower() for marker in target.get("out_of_stock_markers", [])
    ]
    has_positive = any(marker in lower for marker in positive)
    has_negative = any(marker in lower for marker in negative)
    if has_negative:
        in_stock: bool | None = False
    elif has_positive:
        in_stock = True
    else:
        in_stock = None

    normalized = normalized_text(extracted_content(body, target))
    content_hash = (
        hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        if normalized
        else None
    )
    return Snapshot(
        checked_at=checked_at or utc_now(),
        http_status=status,
        available=200 <= status < 400,
        title=title,
        price=price,
        in_stock=in_stock,
        content_hash=content_hash,
    )


def failed_snapshot(error: Exception) -> Snapshot:
    return Snapshot(
        checked_at=utc_now(),
        http_status=None,
        available=False,
        title=None,
        price=None,
        in_stock=None,
        content_hash=None,
        error=f"{type(error).__name__}: {str(error)[:160]}",
    )


def fetch_snapshot(
    target: dict[str, Any],
    timeout: float,
    *,
    attempts: int = 3,
    backoff_seconds: float = 0.5,
) -> Snapshot:
    request = urllib.request.Request(
        str(target["url"]),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(3_000_000).decode(
                    "utf-8", errors="replace"
                )
                return extract_snapshot(
                    body, status=int(response.status), target=target
                )
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < max(1, attempts):
                time.sleep(backoff_seconds * (2**attempt))
    assert last_error is not None
    return failed_snapshot(last_error)


def pct_change(previous: float, current: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def changes(
    name: str,
    previous: Snapshot | None,
    current: Snapshot,
    target: dict[str, Any],
) -> list[str]:
    """Return material changes between two successful observations."""
    if previous is None:
        return [f"{name}: monitoring started"]

    events: list[str] = []
    if previous.available != current.available:
        events.append(
            f"{name}: page {'recovered' if current.available else 'unavailable'}"
        )
    if (
        previous.in_stock is not None
        and current.in_stock is not None
        and previous.in_stock != current.in_stock
    ):
        events.append(
            f"{name}: {'back in stock' if current.in_stock else 'out of stock'}"
        )
    if previous.price is not None and current.price is not None:
        delta = pct_change(previous.price, current.price)
        threshold = float(target.get("price_change_pct", 0))
        if delta is not None and abs(delta) >= threshold:
            direction = "up" if delta > 0 else "down"
            events.append(
                f"{name}: price {direction} {abs(delta):.1f}% "
                f"({previous.price:g} → {current.price:g})"
            )
    if (
        previous.content_hash
        and current.content_hash
        and previous.content_hash != current.content_hash
        and not events
    ):
        events.append(f"{name}: monitored content changed")
    return events


def signal_signature(snapshot: Snapshot) -> str:
    payload = {
        "available": snapshot.available,
        "price": snapshot.price,
        "in_stock": snapshot.in_stock,
        "content_hash": snapshot.content_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def validate_observation(
    snapshot: Snapshot, target: dict[str, Any]
) -> Snapshot:
    """Turn configured extraction failures into visible monitor-health failures."""
    if not snapshot.available:
        return snapshot
    missing: list[str] = []
    if target.get("price_regex") and snapshot.price is None:
        missing.append("price")
    if (
        target.get("in_stock_markers") or target.get("out_of_stock_markers")
    ) and snapshot.in_stock is None:
        missing.append("stock")
    if (
        target.get("content_regex") or target.get("content_item_regex")
    ) and snapshot.content_hash is None:
        missing.append("content")
    if not missing:
        return snapshot
    return replace(
        snapshot,
        available=False,
        error=f"Configured extraction failed: {', '.join(missing)}",
    )


def safe_audit_error(error: str | None) -> str:
    """Keep failure diagnostics useful without logging URL query secrets."""
    if not error:
        return "unknown error"
    value = " ".join(str(error).split())
    value = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[redacted]", value)
    return value[:240]


def log_observation_audit(
    *,
    name: str,
    current: Snapshot,
    previous_record: dict[str, Any] | None,
    record: dict[str, Any],
    events: list[str],
) -> None:
    """Write timestamped machine-readable failure and recovery evidence."""
    if not current.available:
        payload = {
            "checked_at": current.checked_at,
            "consecutive_failures": int(
                record.get("consecutive_failures", 0)
            ),
            "error": safe_audit_error(current.error),
            "event": "check_failed",
            "http_status": current.http_status,
            "target": name,
        }
        print("AUDIT " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    recovery_event = f"{name}: monitor check recovered"
    if recovery_event not in events:
        return
    payload = {
        "checked_at": current.checked_at,
        "event": "check_recovered",
        "failed_checks": int(
            (previous_record or {}).get("consecutive_failures", 0)
        ),
        "http_status": current.http_status,
        "target": name,
    }
    print("AUDIT " + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def send_ntfy(
    *,
    server: str,
    topic: str,
    title: str,
    message: str,
    timeout: float,
) -> bool:
    payload = json.dumps(
        {
            "topic": topic,
            "title": title,
            "message": message,
            "priority": 3,
            "tags": ["shopping_cart"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        server.rstrip("/") + "/",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except (OSError, urllib.error.URLError):
            if attempt < 2:
                time.sleep(2**attempt)
    return False


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def empty_stats(local_date: str) -> dict[str, Any]:
    return {
        "date": local_date,
        "checks": 0,
        "successes": 0,
        "failures": 0,
        "product_changes": 0,
        "health_events": 0,
    }


def new_state(local_date: str) -> dict[str, Any]:
    return {
        "_meta": {
            "version": STATE_VERSION,
            "last_summary_date": None,
            "pending_notifications": [],
            "stats": empty_stats(local_date),
        },
        "targets": {},
    }


def migrate_state(raw: Any, local_date: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return new_state(local_date)

    meta = raw.get("_meta", {})
    if isinstance(meta, dict) and meta.get("version") in {2, STATE_VERSION}:
        raw.setdefault("targets", {})
        meta["version"] = STATE_VERSION
        meta.setdefault("pending_notifications", [])
        meta.setdefault("last_summary_date", None)
        stats = meta.get("stats")
        if not isinstance(stats, dict) or stats.get("date") != local_date:
            stats = empty_stats(local_date)
        else:
            # Version 2 mixed product changes with failure/recovery events.
            # Preserve check totals, but never carry that ambiguous counter
            # into either customer-facing category.
            stats = {
                "date": local_date,
                "checks": int(stats.get("checks", 0)),
                "successes": int(stats.get("successes", 0)),
                "failures": int(stats.get("failures", 0)),
                "product_changes": int(stats.get("product_changes", 0)),
                "health_events": int(stats.get("health_events", 0)),
            }
        meta["stats"] = stats
        raw["_meta"] = meta
        return raw

    migrated = new_state(local_date)
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        try:
            snapshot = Snapshot(**value)
        except TypeError:
            continue
        migrated["targets"][key] = {
            "baseline": asdict(snapshot),
            "candidate": None,
            "candidate_count": 0,
            "consecutive_failures": 0,
            "failure_alerted": False,
        }
    return migrated


def merge_observation(baseline: Snapshot, current: Snapshot) -> Snapshot:
    """Refresh diagnostics without moving the last meaningful signal baseline."""
    return replace(
        baseline,
        checked_at=current.checked_at,
        http_status=current.http_status,
        available=current.available,
        title=current.title or baseline.title,
        error=current.error,
    )


def evaluate_target(
    *,
    name: str,
    target: dict[str, Any],
    record: dict[str, Any] | None,
    current: Snapshot,
    change_confirmations: int,
    failure_confirmations: int,
) -> tuple[dict[str, Any], list[str], list[str]]:
    record = dict(record or {})
    configured_signature = monitor_signature(target)
    if record.get("target_signature") != configured_signature:
        record = {"target_signature": configured_signature}
    else:
        record["target_signature"] = configured_signature
    baseline_raw = record.get("baseline")
    baseline = Snapshot(**baseline_raw) if baseline_raw else None
    product_events: list[str] = []
    health_events: list[str] = []

    if not current.available:
        failure_count = int(record.get("consecutive_failures", 0)) + 1
        failure_alerted = bool(record.get("failure_alerted", False))
        if failure_count >= failure_confirmations and not failure_alerted:
            health_events.append(
                f"{name}: monitor check failed after {failure_count} checks"
            )
            failure_alerted = True
        record.update(
            {
                "consecutive_failures": failure_count,
                "failure_alerted": failure_alerted,
                "last_observation": asdict(current),
            }
        )
        return record, product_events, health_events

    if record.get("failure_alerted"):
        health_events.append(f"{name}: monitor check recovered")
    record["consecutive_failures"] = 0
    record["failure_alerted"] = False
    record["last_observation"] = asdict(current)

    if baseline is None:
        record.update(
            {
                "baseline": asdict(current),
                "candidate": None,
                "candidate_count": 0,
            }
        )
        return record, product_events, health_events

    material = changes(name, baseline, current, target)
    if not material:
        record["baseline"] = asdict(merge_observation(baseline, current))
        record["candidate"] = None
        record["candidate_count"] = 0
        return record, product_events, health_events

    signature = signal_signature(current)
    candidate = record.get("candidate")
    if isinstance(candidate, dict) and candidate.get("signature") == signature:
        candidate_count = int(record.get("candidate_count", 0)) + 1
    else:
        candidate_count = 1
    record["candidate"] = {
        "signature": signature,
        "snapshot": asdict(current),
        "events": material,
    }
    record["candidate_count"] = candidate_count

    if candidate_count >= max(1, change_confirmations):
        product_events.extend(material)
        record["baseline"] = asdict(current)
        record["candidate"] = None
        record["candidate_count"] = 0
    return record, product_events, health_events


def queue_notification(
    state: dict[str, Any],
    *,
    kind: str,
    title: str,
    message: str,
    dedupe_key: str,
) -> dict[str, Any]:
    queue = state["_meta"]["pending_notifications"]
    existing = next(
        (item for item in queue if item.get("dedupe_key") == dedupe_key),
        None,
    )
    if existing is not None:
        return existing
    item = {
        "kind": kind,
        "title": title,
        "message": message,
        "dedupe_key": dedupe_key,
        "created_at": utc_now(),
        "attempts": 0,
    }
    queue.append(item)
    return item


def counted(value: int, singular: str) -> str:
    return f"{value} {singular}{'' if value == 1 else 's'}"


def summary_message(stats: dict[str, Any], target_count: int) -> str:
    return (
        f"{stats['date']} · {target_count} pages\n"
        f"{stats['successes']}/{stats['checks']} checks successful · "
        f"{counted(stats['product_changes'], 'product change')}\n"
        f"{counted(stats['health_events'], 'health event')} · "
        f"{counted(stats['failures'], 'failed check')}"
    )


def local_clock(config: dict[str, Any]) -> datetime:
    summary = config.get("summary", {})
    timezone_name = str(summary.get("timezone", "Europe/Amsterdam"))
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"Unknown summary timezone: {timezone_name}") from exc
    return datetime.now(zone)


def flush_notifications(
    state: dict[str, Any],
    *,
    server: str,
    topic: str,
    timeout: float,
) -> tuple[int, int]:
    pending = state["_meta"]["pending_notifications"]
    remaining: list[dict[str, Any]] = []
    sent = 0
    for item in pending:
        delivered = send_ntfy(
            server=server,
            topic=topic,
            title=str(item["title"]),
            message=str(item["message"]),
            timeout=timeout,
        )
        if delivered:
            sent += 1
            if item.get("kind") == "summary":
                state["_meta"]["last_summary_date"] = item.get("summary_date")
        else:
            item["attempts"] = int(item.get("attempts", 0)) + 1
            remaining.append(item)
    state["_meta"]["pending_notifications"] = remaining
    return sent, len(remaining)


def validate_config(config: Any, config_path: Path) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise SystemExit(f"Invalid config: {config_path}")
    targets = config.get("targets")
    if not isinstance(targets, list) or not targets:
        raise SystemExit("Config must contain at least one target")
    for index, target in enumerate(targets):
        if not isinstance(target, dict) or not str(target.get("url", "")).strip():
            raise SystemExit(f"Target {index + 1} must contain a URL")
    return config


def run(config_path: Path, *, dry_run: bool) -> int:
    config = validate_config(load_json(config_path, None), config_path)
    targets = config["targets"]
    state_path = Path(str(config.get("state_path", "catalogcue_state.json")))
    if not state_path.is_absolute():
        state_path = config_path.parent / state_path

    now_local = local_clock(config)
    local_date = now_local.date().isoformat()
    state = migrate_state(load_json(state_path, {}), local_date)
    meta = state["_meta"]
    stats = meta.get("stats", empty_stats(local_date))
    if stats.get("date") != local_date:
        stats = empty_stats(local_date)
    meta["stats"] = stats

    timeout = float(config.get("timeout_seconds", 12))
    fetch_attempts = int(config.get("fetch_attempts", 3))
    change_confirmations = int(config.get("change_confirmations", 2))
    failure_confirmations = int(config.get("failure_confirmations", 2))
    product_events: list[str] = []
    health_events: list[str] = []
    active_target_keys: set[str] = set()

    for target in targets:
        name = str(target.get("name") or target["url"])
        key = hashlib.sha256(str(target["url"]).encode()).hexdigest()[:16]
        active_target_keys.add(key)
        previous_record = state["targets"].get(key)
        current = validate_observation(
            fetch_snapshot(
                target,
                timeout,
                attempts=fetch_attempts,
                backoff_seconds=float(
                    config.get("fetch_backoff_seconds", 0.5)
                ),
            ),
            target,
        )
        stats["checks"] += 1
        if current.available:
            stats["successes"] += 1
        else:
            stats["failures"] += 1
        record, target_product_events, target_health_events = evaluate_target(
            name=name,
            target=target,
            record=previous_record,
            current=current,
            change_confirmations=change_confirmations,
            failure_confirmations=failure_confirmations,
        )
        log_observation_audit(
            name=name,
            current=current,
            previous_record=previous_record,
            record=record,
            events=target_product_events + target_health_events,
        )
        state["targets"][key] = record
        product_events.extend(target_product_events)
        health_events.extend(target_health_events)

    state["targets"] = {
        key: record
        for key, record in state["targets"].items()
        if key in active_target_keys
    }

    if product_events:
        stats["product_changes"] += len(product_events)
        message = "\n".join(product_events)
        print(message)
        queue_notification(
            state,
            kind="change",
            title="CatalogCue update",
            message=message,
            dedupe_key="change:"
            + hashlib.sha256(message.encode("utf-8")).hexdigest()[:16],
        )
    if health_events:
        stats["health_events"] += len(health_events)
        message = "\n".join(health_events)
        print(message)
        queue_notification(
            state,
            kind="health",
            title="CatalogCue health",
            message=message,
            dedupe_key="health:"
            + hashlib.sha256(message.encode("utf-8")).hexdigest()[:16],
        )
    if not product_events and not health_events:
        print("No confirmed material changes.")

    summary_config = config.get("summary", {})
    summary_enabled = bool(summary_config.get("enabled", True))
    summary_hour = int(summary_config.get("hour_local", 18))
    if (
        summary_enabled
        and now_local.hour >= summary_hour
        and meta.get("last_summary_date") != local_date
    ):
        summary_item = queue_notification(
            state,
            kind="summary",
            title="CatalogCue daily summary",
            message=summary_message(stats, len(targets)),
            dedupe_key=f"summary:{local_date}",
        )
        summary_item["summary_date"] = local_date

    if dry_run:
        print(
            f"Dry run: {len(meta['pending_notifications'])} notification(s) "
            "would be pending; state unchanged."
        )
        return 0

    topic = os.environ.get("CATALOGCUE_NTFY_TOPIC", "").strip()
    if not topic:
        raise SystemExit(
            "CATALOGCUE_NTFY_TOPIC is required for a production run"
        )
    sent, pending = flush_notifications(
        state,
        server=str(config.get("ntfy_server", "https://ntfy.sh")),
        topic=topic,
        timeout=timeout,
    )
    atomic_write_json(state_path, state)
    print(f"Notifications delivered: {sent}; pending retry: {pending}")
    return 1 if pending else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
