#!/usr/bin/env python3
"""
Bot Monitor — watches Polymarket bot health every 5 minutes
============================================================
Checks process, logs, balance, P&L, errors. Stores results in memory_store
and writes human-readable status + alerts.

Scheduled via LaunchAgent: com.macagent.bot-monitor (every 300s)
"""

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_store import store, recall

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.join(os.path.dirname(AGENT_DIR), "polymarket_bot")
LOG_DIR = os.path.join(BOT_DIR, "logs")
STATUS_FILE = os.path.join(AGENT_DIR, "bot_status.txt")
ALERTS_FILE = os.path.join(AGENT_DIR, "alerts.txt")

BAL_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*"
    r"Balance: \$([\d,.]+) \| Positions: \$([\d,.]+) \| Portfolio: \$([\d,.]+)"
)


def _is_bot_running() -> tuple[bool, int | None]:
    """Check if the bot process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-fi", "python.*main.py"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            pid = int(result.stdout.strip().split("\n")[0])
            return True, pid
    except Exception:
        pass
    return False, None


def _log_files_recent(n: int = 5) -> list[str]:
    """Get the N most recently modified non-empty bot log files."""
    pattern = os.path.join(LOG_DIR, "bot_*.log")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return [f for f in files if os.path.getsize(f) > 0][:n]


def _parse_last_balance(log_path: str) -> dict | None:
    """Get the last balance/portfolio line from a log file."""
    last = None
    try:
        with open(log_path) as f:
            for line in f:
                m = BAL_RE.match(line)
                if m:
                    last = {
                        "timestamp": m.group(1),
                        "balance": float(m.group(2).replace(",", "")),
                        "positions": float(m.group(3).replace(",", "")),
                        "portfolio": float(m.group(4).replace(",", "")),
                    }
    except Exception:
        pass
    return last


def _last_log_timestamp(log_path: str) -> str | None:
    """Get timestamp from the last line of the log."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            pos = max(0, size - 4096)
            f.seek(pos)
            lines = f.read().decode("utf-8", errors="replace").strip().split("\n")
            for line in reversed(lines):
                m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def _count_today_activity(log_path: str) -> dict:
    """Count today's buys, sells, errors."""
    today = datetime.now().strftime("%Y-%m-%d")
    buys = sells = errors = 0
    try:
        with open(log_path) as f:
            for line in f:
                if not line.startswith(today):
                    continue
                if "[RBOND] BUY" in line:
                    buys += 1
                if "[MATURITY] SELL " in line:
                    sells += 1
                if "[ERROR]" in line:
                    errors += 1
    except Exception:
        pass
    return {"buys": buys, "sells": sells, "errors": errors}


def _recent_errors(log_path: str, hours: int = 1) -> list[str]:
    """Get ERROR lines from the last N hours."""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    errors = []
    try:
        with open(log_path) as f:
            for line in f:
                if "[ERROR]" in line and line[:16] >= cutoff:
                    errors.append(line.strip()[:120])
    except Exception:
        pass
    return errors[-5:]


def _compute_daily_pnl(current_portfolio: float) -> float | None:
    """Compare current portfolio to stored previous day value."""
    prev = recall("bot:yesterday_portfolio")
    if prev is not None:
        return round(current_portfolio - prev, 2)
    return None


def _win_rate_from_trades() -> dict | None:
    """Read trade_log.json for win rate stats."""
    trade_log = os.path.join(BOT_DIR, "trade_log.json")
    if not os.path.exists(trade_log):
        return None
    try:
        with open(trade_log) as f:
            trades = json.load(f)
        buys = [t for t in trades if t.get("side") == "BUY"]
        wins = len([t for t in buys if t.get("status") == "sold"])
        losses = len([t for t in buys if t.get("status") == "resolved_lost"])
        open_count = len([t for t in buys if t.get("status") in ("matched", "open")])
        return {"wins": wins, "losses": losses, "open": open_count, "total_trades": len(trades)}
    except Exception:
        return None


def monitor():
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    running, pid = _is_bot_running()
    log_files = _log_files_recent(5)

    # Find best data across recent log files
    last_ts = None
    balance_data = None
    activity = {}
    recent_errs = []
    for lf in log_files:
        if not last_ts:
            last_ts = _last_log_timestamp(lf)
        if not balance_data:
            balance_data = _parse_last_balance(lf)
        a = _count_today_activity(lf)
        if a.get("buys", 0) or a.get("sells", 0) or a.get("errors", 0):
            activity = a
        if not recent_errs:
            recent_errs = _recent_errors(lf)

    log_file = log_files[0] if log_files else None
    win_rate = _win_rate_from_trades()

    portfolio = balance_data["portfolio"] if balance_data else None
    daily_pnl = _compute_daily_pnl(portfolio) if portfolio else None

    # Detect stale logs (>10 min old)
    log_stale = False
    if last_ts:
        try:
            last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_dt).total_seconds() > 600:
                log_stale = True
        except Exception:
            pass

    # Build status
    status = {
        "checked_at": now_str,
        "running": running,
        "pid": pid,
        "log_file": os.path.basename(log_file) if log_file else None,
        "last_log_at": last_ts,
        "log_stale": log_stale,
        "balance": balance_data,
        "daily_pnl": daily_pnl,
        "today_activity": activity,
        "recent_errors": recent_errs,
        "win_rate": win_rate,
    }

    # Store in memory
    store("bot:status", status, category="portfolio")
    if portfolio:
        store("bot:portfolio_latest", portfolio, category="portfolio")

    # Store yesterday's portfolio at midnight for daily PnL
    hour = datetime.now().hour
    if hour == 0 and portfolio:
        store("bot:yesterday_portfolio", portfolio, category="portfolio")

    # Write human-readable status
    lines = [
        f"Bot Status — {now_local}",
        "=" * 50,
        f"Running: {'YES (PID {})'.format(pid) if running else 'NO'}",
        f"Last log: {last_ts or 'unknown'}{' (STALE!)' if log_stale else ''}",
    ]
    if balance_data:
        lines.append(f"Balance: ${balance_data['balance']:,.2f}")
        lines.append(f"Positions: ${balance_data['positions']:,.2f}")
        lines.append(f"Portfolio: ${balance_data['portfolio']:,.2f}")
    if daily_pnl is not None:
        sign = "+" if daily_pnl >= 0 else ""
        lines.append(f"Daily P&L: {sign}${daily_pnl:,.2f}")
    if activity:
        lines.append(f"Today: {activity.get('buys', 0)} buys, {activity.get('sells', 0)} sells, {activity.get('errors', 0)} errors")
    if win_rate:
        lines.append(f"Win rate: {win_rate['wins']}W-{win_rate['losses']}L ({win_rate['open']} open)")
    if recent_errs:
        lines.append(f"\nRecent errors ({len(recent_errs)}):")
        for e in recent_errs:
            lines.append(f"  {e}")
    lines.append("")

    with open(STATUS_FILE, "w") as f:
        f.write("\n".join(lines))

    # Alerts
    alerts = []
    if not running:
        alerts.append(f"[{now_local}] ALERT: Bot is NOT running!")
    if log_stale and running:
        alerts.append(f"[{now_local}] ALERT: Bot running but logs stale (last: {last_ts})")
    if portfolio and daily_pnl is not None and daily_pnl < -(portfolio * 0.10):
        alerts.append(f"[{now_local}] ALERT: Portfolio dropped >{10}% today (${daily_pnl:,.2f})")
    if recent_errs and len(recent_errs) >= 3:
        alerts.append(f"[{now_local}] ALERT: {len(recent_errs)} errors in last hour")

    if alerts:
        with open(ALERTS_FILE, "a") as f:
            for a in alerts:
                f.write(a + "\n")

    # Print summary
    state = "running" if running else "STOPPED"
    port_str = f"${portfolio:,.2f}" if portfolio else "unknown"
    print(f"[BOT-MONITOR] {state} | portfolio={port_str} | buys={activity.get('buys', 0)} sells={activity.get('sells', 0)}")


if __name__ == "__main__":
    monitor()
