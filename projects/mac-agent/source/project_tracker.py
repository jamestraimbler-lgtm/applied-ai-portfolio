#!/usr/bin/env python3
"""
Project Tracker — tracks active projects, tasks, and priorities
===============================================================
Uses memory_store with category="projects". Each project is stored as a
JSON blob under key "project:{name}".

Usage:
    python3 project_tracker.py list
    python3 project_tracker.py show <project>
    python3 project_tracker.py add-project <name> <description> [--status active]
    python3 project_tracker.py add-task <project> <task> [--priority medium] [--status todo]
    python3 project_tracker.py update-task <project> <task> <status>
    python3 project_tracker.py summary
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from memory_store import store, recall, search

CATEGORY = "projects"


def _project_key(name: str) -> str:
    return f"project:{name.lower().replace(' ', '_')}"


def add_project(name: str, description: str, status: str = "active") -> dict:
    key = _project_key(name)
    existing = recall(key)
    if existing:
        existing["description"] = description
        existing["status"] = status
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        store(key, existing, category=CATEGORY)
        return existing

    project = {
        "name": name,
        "description": description,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": [],
        "notes": [],
    }
    store(key, project, category=CATEGORY)
    return project


def add_task(project_name: str, task: str, priority: str = "medium", status: str = "todo") -> dict:
    key = _project_key(project_name)
    project = recall(key)
    if not project:
        raise ValueError(f"Project not found: {project_name}")

    task_entry = {
        "task": task,
        "priority": priority,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    project["tasks"].append(task_entry)
    project["updated_at"] = datetime.now(timezone.utc).isoformat()
    store(key, project, category=CATEGORY)
    return task_entry


def update_task(project_name: str, task_substr: str, status: str) -> bool:
    key = _project_key(project_name)
    project = recall(key)
    if not project:
        raise ValueError(f"Project not found: {project_name}")

    found = False
    for t in project["tasks"]:
        if task_substr.lower() in t["task"].lower():
            t["status"] = status
            t["updated_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if found:
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        store(key, project, category=CATEGORY)
    return found


def get_project(name: str) -> dict | None:
    return recall(_project_key(name))


def list_projects(status: str = None) -> list[dict]:
    results = search("project", category=CATEGORY, limit=50)
    projects = []
    for r in results:
        p = r["value"]
        if isinstance(p, dict) and "name" in p:
            if status is None or p.get("status") == status:
                projects.append(p)
    return projects


def daily_summary() -> str:
    projects = list_projects(status="active")
    if not projects:
        return "No active projects."

    lines = ["# Daily Summary", ""]
    for p in projects:
        lines.append(f"## {p['name']} ({p['status']})")
        lines.append(f"  {p['description']}")

        tasks = p.get("tasks", [])
        in_progress = [t for t in tasks if t["status"] == "in_progress"]
        todo = [t for t in tasks if t["status"] == "todo"]
        blocked = [t for t in tasks if t["status"] == "blocked"]

        if in_progress:
            lines.append("  In progress:")
            for t in in_progress:
                lines.append(f"    - [{t['priority']}] {t['task']}")
        if blocked:
            lines.append("  Blocked:")
            for t in blocked:
                lines.append(f"    - [{t['priority']}] {t['task']}")
        if todo:
            # Show top 3 todos by priority
            prio_order = {"high": 0, "medium": 1, "low": 2}
            todo.sort(key=lambda t: prio_order.get(t["priority"], 1))
            lines.append(f"  Next up ({len(todo)} tasks):")
            for t in todo[:3]:
                lines.append(f"    - [{t['priority']}] {t['task']}")
        lines.append("")

    return "\n".join(lines)


def _seed_projects():
    """Pre-populate with initial projects."""
    p1 = add_project("Polymarket Bot", "Automated prediction market trading bot on Polymarket", "active")
    if not p1.get("notes"):
        p1["notes"] = [
            "Portfolio ~$950, V2 migrated (April 28 2026)",
            "Win rate 403W-2L on RESOLVED_BOND strategy",
            "Running on Mac Mini via launchd",
        ]
        store(_project_key("Polymarket Bot"), p1, category=CATEGORY)

    p2 = add_project("Agent Framework", "Mac Mini agent framework — shared memory, monitoring, daily briefings", "active")
    if not p2.get("notes"):
        p2["notes"] = ["This project — the framework itself"]
        store(_project_key("Agent Framework"), p2, category=CATEGORY)
    add_task("Agent Framework", "Build memory_store.py", priority="high", status="done")
    add_task("Agent Framework", "Build project_tracker.py", priority="high", status="done")
    add_task("Agent Framework", "Build bot_monitor.py", priority="high", status="done")
    add_task("Agent Framework", "Build daily_briefing.py", priority="high", status="done")
    add_task("Agent Framework", "Test all LaunchAgents", priority="medium", status="todo")

    p3 = add_project("Creative Lab", "Music and art generation experiments", "planned")
    if not p3.get("notes"):
        p3["notes"] = ["Future project — music and art generation"]
        store(_project_key("Creative Lab"), p3, category=CATEGORY)


def main():
    parser = argparse.ArgumentParser(description="Project Tracker")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all projects")

    p_show = sub.add_parser("show", help="Show project details")
    p_show.add_argument("project")

    p_add = sub.add_parser("add-project", help="Add a project")
    p_add.add_argument("name")
    p_add.add_argument("description")
    p_add.add_argument("--status", default="active")

    p_task = sub.add_parser("add-task", help="Add a task")
    p_task.add_argument("project")
    p_task.add_argument("task")
    p_task.add_argument("--priority", default="medium")
    p_task.add_argument("--status", default="todo")

    p_upd = sub.add_parser("update-task", help="Update task status")
    p_upd.add_argument("project")
    p_upd.add_argument("task")
    p_upd.add_argument("status")

    sub.add_parser("summary", help="Daily summary")
    sub.add_parser("seed", help="Pre-populate initial projects")

    args = parser.parse_args()

    if args.command == "list":
        for p in list_projects():
            tasks = p.get("tasks", [])
            done = len([t for t in tasks if t["status"] == "done"])
            total = len(tasks)
            print(f"  [{p['status']}] {p['name']} — {p['description'][:60]} ({done}/{total} tasks)")

    elif args.command == "show":
        p = get_project(args.project)
        if not p:
            print(f"Not found: {args.project}")
            sys.exit(1)
        print(json.dumps(p, indent=2))

    elif args.command == "add-project":
        add_project(args.name, args.description, args.status)
        print(f"Added: {args.name}")

    elif args.command == "add-task":
        add_task(args.project, args.task, args.priority, args.status)
        print(f"Added task to {args.project}")

    elif args.command == "update-task":
        if update_task(args.project, args.task, args.status):
            print(f"Updated: {args.task} -> {args.status}")
        else:
            print(f"Task not found: {args.task}")

    elif args.command == "summary":
        print(daily_summary())

    elif args.command == "seed":
        _seed_projects()
        print("Seeded initial projects.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
