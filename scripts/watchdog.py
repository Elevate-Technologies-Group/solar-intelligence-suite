#!/usr/bin/env python3
"""
watchdog.py — Solar Intelligence Suite API Server Watchdog

Monitors the FastAPI server health endpoint and auto-restarts it
if it becomes unresponsive. Designed to be run as a cron job or
long-running background process.

Usage:
    python scripts/watchdog.py                 # one-shot check + restart if needed
    python scripts/watchdog.py --loop          # loop forever, check every 60s
    python scripts/watchdog.py --loop --interval 30
    python scripts/watchdog.py --status        # just print server status and exit

Cron (check every 5 minutes):
    */5 * * * * GOOGLE_MAPS_API_KEY=<key> python /root/solar-tools/scripts/watchdog.py >> /root/solar-tools/cache/watchdog.log 2>&1
"""

import os
import sys
import time
import subprocess
import argparse
import requests
import signal
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Config ────────────────────────────────────────────────────────────────────

SERVER_URL   = "http://localhost:8765"
HEALTH_URL   = f"{SERVER_URL}/health"
SERVER_CMD   = [
    "python3", "-m", "uvicorn", "api:app",
    "--host", "0.0.0.0",
    "--port", "8765"
]
WORKDIR      = str(ROOT)
PIDFILE      = ROOT / "cache" / "server.pid"
LOG_FILE     = ROOT / "cache" / "watchdog.log"
MAX_RESTARTS = 5        # in a 10-minute window
CHECK_TIMEOUT = 5       # seconds for health check

# ── Logging ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(msg: str, also_print: bool = True):
    line = f"[{_ts()}] {msg}"
    if also_print:
        print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Health check ──────────────────────────────────────────────────────────────

def check_health() -> bool:
    """Return True if the server is healthy."""
    try:
        resp = requests.get(HEALTH_URL, timeout=CHECK_TIMEOUT)
        return resp.status_code == 200
    except Exception:
        return False


def get_server_info() -> dict:
    """Return server info dict or empty dict on failure."""
    try:
        resp = requests.get(HEALTH_URL, timeout=CHECK_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


# ── PID tracking ──────────────────────────────────────────────────────────────

def _read_pid() -> int | None:
    """Read saved server PID from file."""
    try:
        return int(PIDFILE.read_text().strip())
    except Exception:
        return None


def _write_pid(pid: int):
    PIDFILE.write_text(str(pid))


def _process_running(pid: int) -> bool:
    """Check if a process with given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def find_server_pid() -> int | None:
    """Find the uvicorn process PID via ps."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "uvicorn.*api:app.*8765"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        pids = [int(p) for p in out.splitlines() if p.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        pass

    # Fallback: check saved PID file
    saved = _read_pid()
    if saved and _process_running(saved):
        return saved
    return None


# ── Server start ──────────────────────────────────────────────────────────────

def start_server() -> bool:
    """Start the uvicorn server. Returns True if it started successfully."""
    google_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not google_key:
        _log("⚠️  GOOGLE_MAPS_API_KEY not set — server may have limited functionality")

    env = os.environ.copy()
    env["GOOGLE_MAPS_API_KEY"] = google_key

    _log(f"🚀 Starting server: {' '.join(SERVER_CMD)}")

    try:
        proc = subprocess.Popen(
            SERVER_CMD,
            cwd=WORKDIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True   # detach from watchdog process group
        )
        _write_pid(proc.pid)
        _log(f"   Server process started (PID {proc.pid})")

        # Wait up to 15s for the health endpoint to respond
        for i in range(15):
            time.sleep(1)
            if check_health():
                info = get_server_info()
                version = info.get("version", "?")
                _log(f"✅ Server healthy after {i+1}s (version {version})")
                return True

        _log("❌ Server did not become healthy within 15s")
        return False

    except Exception as e:
        _log(f"❌ Failed to start server: {e}")
        return False


def stop_server(pid: int) -> bool:
    """Gracefully stop the server process."""
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        if _process_running(pid):
            os.kill(pid, signal.SIGKILL)
        _log(f"🛑 Stopped server (PID {pid})")
        return True
    except Exception as e:
        _log(f"⚠️  Could not stop PID {pid}: {e}")
        return False


# ── Main watchdog logic ───────────────────────────────────────────────────────

_restart_times: list[float] = []


def _too_many_restarts() -> bool:
    """True if we've restarted MAX_RESTARTS times in the last 10 minutes."""
    now = time.time()
    window = [t for t in _restart_times if now - t < 600]
    _restart_times.clear()
    _restart_times.extend(window)
    return len(window) >= MAX_RESTARTS


def run_check(notify_discord: bool = True) -> str:
    """
    Run one watchdog check cycle.
    Returns: 'healthy' | 'restarted' | 'failed' | 'rate_limited'
    """
    healthy = check_health()

    if healthy:
        info = get_server_info()
        v = info.get("version", "?")
        _log(f"✅ Server healthy (v{v}) — {SERVER_URL}")
        return "healthy"

    # Unhealthy — try to restart
    _log(f"⚠️  Server not responding at {HEALTH_URL}")

    if _too_many_restarts():
        _log(f"🚨 Rate limit: {MAX_RESTARTS} restarts in 10 min. Backing off.")

        # Try Discord notification if configured
        if notify_discord:
            try:
                from integrations.discord_alerts import post_message
                post_message(
                    f"🚨 **Solar Intelligence Suite** — Server restarted **{MAX_RESTARTS}x** "
                    f"in 10 minutes. Backing off! Manual intervention may be needed.\n"
                    f"Host: `{os.uname().nodename}`"
                )
            except Exception:
                pass
        return "rate_limited"

    # Kill any stale process first
    pid = find_server_pid()
    if pid:
        _log(f"   Found stale server process PID={pid}, stopping...")
        stop_server(pid)

    # Start fresh
    _restart_times.append(time.time())
    ok = start_server()

    if ok:
        _log("✅ Server successfully restarted")

        if notify_discord:
            try:
                from integrations.discord_alerts import post_message
                post_message(
                    f"⚠️ **Solar Intelligence Suite** — Server was down and has been **restarted** ✅\n"
                    f"Host: `{os.uname().nodename}` | Time: `{_ts()}`"
                )
            except Exception:
                pass
        return "restarted"

    else:
        _log("❌ Server restart FAILED — check logs")

        if notify_discord:
            try:
                from integrations.discord_alerts import post_message
                post_message(
                    f"🚨 **Solar Intelligence Suite** — Server restart **FAILED** ❌\n"
                    f"Host: `{os.uname().nodename}` | Time: `{_ts()}`\n"
                    f"Manual intervention required!"
                )
            except Exception:
                pass
        return "failed"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Solar Intelligence Suite server watchdog")
    parser.add_argument("--loop",     action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds (default: 60)")
    parser.add_argument("--status",   action="store_true", help="Print server status and exit")
    parser.add_argument("--start",    action="store_true", help="Start the server if not running")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord notifications")
    args = parser.parse_args()

    notify = not args.no_discord

    # Status-only mode
    if args.status:
        healthy = check_health()
        pid = find_server_pid()
        info = get_server_info() if healthy else {}
        print(f"Server:  {'✅ HEALTHY' if healthy else '❌ DOWN'}")
        print(f"URL:     {SERVER_URL}")
        print(f"PID:     {pid or 'not found'}")
        if info:
            print(f"Version: {info.get('version', '?')}")
            print(f"Service: {info.get('service', '?')}")
        sys.exit(0 if healthy else 1)

    # Start-only mode
    if args.start:
        if check_health():
            _log("✅ Server already running")
            sys.exit(0)
        ok = start_server()
        sys.exit(0 if ok else 1)

    # Main watchdog loop
    if args.loop:
        _log(f"🔄 Watchdog loop started — checking every {args.interval}s")
        try:
            while True:
                run_check(notify_discord=notify)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            _log("👋 Watchdog stopped by user")
    else:
        # One-shot check
        result = run_check(notify_discord=notify)
        sys.exit(0 if result in ("healthy", "restarted") else 1)


if __name__ == "__main__":
    main()
