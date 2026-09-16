# Mac Agent — local memory, task tracking and daily briefings

An archived Python utility project connecting a SQLite memory store, project
priorities, process/log inspection and Markdown daily reports. Built with
substantial AI assistance as personal tooling, before a professional role.

## Read the actual code

- [Memory store](source/memory_store.py): SQLite, full-text search, categories,
  expiry timestamps and thread-local connections.
- [Project tracker](source/project_tracker.py): persistent projects and tasks.
- [Daily briefing](source/daily_briefing.py): combines saved context, system
  information and a public price API into a report.
- [Process/log monitor](source/bot_monitor.py): historical monitoring component
  tied to an older local bot directory and log format.

## Try it offline

```bash
python3 projects/mac-agent/demo.py
```

Uses the real memory module to write, retrieve, search and delete an example
record in a temporary database. Requires only Python with SQLite FTS5 support.
No scheduling, live process inspection or network requests occur in this demo.

## Evidence and limits

The source came from the retained `mac_agent.zip` archive. The public copy adds
`MAC_AGENT_DB` so the demonstration can isolate its database. The four original
modules are included; private memory databases, report contents and scheduler
configuration are omitted.

Retained dated reports are evidence of saved artifacts, not proof of continuous
uptime or successful delivery every day. The full monitoring system has not been
restarted. Its process matching and source-specific parsing need review before
reuse. The small offline demo verifies only the memory-store workflow.

[Portfolio](../../README.md) · [Verification](../../docs/verification-2026-09-16.md)
