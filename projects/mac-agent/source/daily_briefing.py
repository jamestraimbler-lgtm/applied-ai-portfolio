#!/usr/bin/env python3
"""
Daily Briefing — generates a morning report at 8:00 AM local time
=================================================================
Collects portfolio status, crypto prices, project priorities, alerts,
and system health into a clean markdown report.

Scheduled via LaunchAgent: com.macagent.daily-briefing (8:00 AM daily)
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_store import store, recall, search
from project_tracker import daily_summary as project_summary

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
BRIEFING_DIR = os.path.join(AGENT_DIR, "briefings")
ALERTS_FILE = os.path.join(AGENT_DIR, "alerts.txt")


def _crypto_prices() -> dict:
    """Fetch current prices from Binance REST API."""
    prices = {}
    for symbol, label in [("BTCUSDT", "BTC"), ("ETHUSDT", "ETH"),
                           ("SOLUSDT", "SOL"), ("XRPUSDT", "XRP")]:
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            r = urllib.request.urlopen(url, timeout=5)
            data = json.loads(r.read())
            prices[label] = float(data["price"])
        except Exception:
            prices[label] = None
        time.sleep(0.1)
    return prices


def _system_health() -> dict:
    """Check disk space, memory, uptime."""
    health = {}
    try:
        total, used, free = shutil.disk_usage("/")
        health["disk_total_gb"] = round(total / (1024**3), 1)
        health["disk_used_gb"] = round(used / (1024**3), 1)
        health["disk_free_gb"] = round(free / (1024**3), 1)
        health["disk_pct"] = round(used / total * 100, 1)
    except Exception:
        pass

    try:
        result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split("\n")
        page_size = 16384
        for line in lines:
            if "page size of" in line:
                page_size = int(line.split()[-2])
                break
        stats = {}
        for line in lines[1:]:
            if ":" in line:
                key, val = line.split(":", 1)
                val = val.strip().rstrip(".")
                try:
                    stats[key.strip()] = int(val)
                except ValueError:
                    pass
        free_pages = stats.get("Pages free", 0) + stats.get("Pages inactive", 0)
        health["memory_free_gb"] = round(free_pages * page_size / (1024**3), 1)
    except Exception:
        pass

    try:
        result = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
        health["uptime"] = result.stdout.strip()
    except Exception:
        pass

    return health


def _recent_alerts(hours: int = 24) -> list[str]:
    """Read alerts from the last N hours."""
    if not os.path.exists(ALERTS_FILE):
        return []
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    alerts = []
    try:
        with open(ALERTS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and line[1:17] >= cutoff:
                    alerts.append(line)
    except Exception:
        pass
    return alerts


def generate():
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # Collect data
    bot_status = recall("bot:status")
    crypto = _crypto_prices()
    projects = project_summary()
    alerts = _recent_alerts(24)
    health = _system_health()

    # Build report
    lines = [
        f"# Daily Briefing — {date_str} {time_str}",
        "",
        "## Portfolio",
    ]

    if bot_status and bot_status.get("balance"):
        b = bot_status["balance"]
        state = "Running" if bot_status.get("running") else "STOPPED"
        lines.append(f"- Bot: **{state}**")
        lines.append(f"- Balance: ${b['balance']:,.2f}")
        lines.append(f"- Positions: ${b['positions']:,.2f}")
        lines.append(f"- Portfolio: **${b['portfolio']:,.2f}**")
        if bot_status.get("daily_pnl") is not None:
            pnl = bot_status["daily_pnl"]
            sign = "+" if pnl >= 0 else ""
            lines.append(f"- Daily P&L: {sign}${pnl:,.2f}")
        if bot_status.get("win_rate"):
            wr = bot_status["win_rate"]
            lines.append(f"- Win rate: {wr['wins']}W-{wr['losses']}L ({wr['open']} open)")
        if bot_status.get("today_activity"):
            a = bot_status["today_activity"]
            lines.append(f"- Today: {a.get('buys', 0)} buys, {a.get('sells', 0)} sells")
    else:
        lines.append("- Bot status unavailable (run bot_monitor.py first)")

    lines.append("")
    lines.append("## Crypto Prices")
    for coin, price in crypto.items():
        if price is not None:
            if price >= 100:
                lines.append(f"- {coin}: ${price:,.0f}")
            else:
                lines.append(f"- {coin}: ${price:,.2f}")
        else:
            lines.append(f"- {coin}: unavailable")

    lines.append("")
    lines.append("## Projects")
    lines.append(projects)

    if alerts:
        lines.append("")
        lines.append(f"## Alerts ({len(alerts)})")
        for a in alerts:
            lines.append(f"- {a}")

    lines.append("")
    lines.append("## System")
    if health.get("disk_pct"):
        lines.append(f"- Disk: {health['disk_used_gb']}GB / {health['disk_total_gb']}GB ({health['disk_pct']}%)")
    if health.get("memory_free_gb"):
        lines.append(f"- Free memory: ~{health['memory_free_gb']}GB")
    if health.get("uptime"):
        lines.append(f"- {health['uptime']}")

    lines.append("")
    lines.append(f"---\nGenerated at {now.strftime('%Y-%m-%d %H:%M:%S')}")

    report = "\n".join(lines)

    # Write briefing file
    os.makedirs(BRIEFING_DIR, exist_ok=True)
    path = os.path.join(BRIEFING_DIR, f"{date_str}.md")
    with open(path, "w") as f:
        f.write(report)

    # Store summary in memory
    store("daily:briefing", {
        "date": date_str,
        "portfolio": bot_status.get("balance", {}).get("portfolio") if bot_status and bot_status.get("balance") else None,
        "crypto": crypto,
        "alerts_count": len(alerts),
    }, category="daily")

    print(f"[BRIEFING] Wrote {path}")
    print(report)
    return path


if __name__ == "__main__":
    generate()
