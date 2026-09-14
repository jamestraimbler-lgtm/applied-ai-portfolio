[Nederlands](README.nl.md) · [English](README.md)

# CatalogCue monitoring engine

This is a sanitized portfolio copy of a read-only product-page monitoring
engine. It is included as runnable evidence of Python engineering practices;
the original personal pilot configuration, runtime state, notification topics,
deployment files and outreach material are intentionally excluded.

## What it demonstrates

- HTTP fetching with bounded retries and exponential backoff
- Price, stock and selected-content extraction
- Semantic content hashing to reduce dynamic-page noise
- Two-observation confirmation before material-change alerts
- Confirmed failure and recovery events
- Persistent notification outbox behaviour
- Dry-run support and audit-safe error sanitisation

## Run the tests

```bash
cd projects/catalogcue
python3 -m unittest discover -s . -p 'test_*.py'
```

The example configuration uses `example.com` and does not contain credentials.
Copy it to a local `config.json` only when experimenting; local configuration
is ignored by Git.

## Boundary

This is not presented as a hosted SaaS product or a customer-success claim. It
is a working monitoring engine and a case study in reliable automation.

## A concrete failure case

Run the offline walkthrough from the repository root:

```bash
python3 projects/catalogcue/demo.py
```

It uses the same `storewatch.run` path as the engine, with simulated HTML
responses and delivery outcomes. State is written only in a temporary folder.
No API account, live page or notification subscription is needed.

A price is 100. One observation reports 90, but the next reports 100. That
temporary change should not alert. Two matching observations of 90 confirm
the change. If delivery fails, the notification stays in the outbox for retry.

| Step | Observed price | Confirmed changes so far | Pending notifications |
| --- | --- | --- | --- |
| Baseline | 100 | 0 | 0 |
| Temporary drop | 90 | 0 | 0 |
| Price restored | 100 | 0 | 0 |
| First lower observation | 90 | 0 | 0 |
| Confirmed, delivery fails | 90 | 1 | 1 |
| Delivery recovers | 90 | 1 | 0 |

[Expected machine-readable results](demo-expected.jsonl) are checked by
`python3 scripts/verify.py`. A simulated failure returns engine exit 1 at the
fifth step; the demonstration itself finishes successfully after delivery
recovers. This is a controlled example, not a claim about a live service.

In [storewatch.py](storewatch.py), `evaluate_target` owns confirmation,
`queue_notification` retains the event, and `flush_notifications` keeps failed
deliveries. [The tests](test_storewatch.py) cover unstable observations,
confirmed changes, failed delivery, recovery and dry-run state preservation.

The outbox does not guarantee exactly-once delivery: a crash after a successful
send but before persisting state can cause a repeated notification. Page
extraction also needs validation for each actual target.

## End of track

**Runnable sample; wider product unfinished.** All 19 tests passed locally on
13 September 2026 with network calls and notifications mocked. They establish
tested behavior, not live operation or customer adoption.
[Project register](../../docs/project-status.md).
