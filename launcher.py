"""Persistent launcher that keeps the agent system running 24/7.

Usage:
    python launcher.py          # Start and monitor the agent system
    python launcher.py --stop   # Stop all agent processes

On Windows, this uses subprocess with CREATE_NEW_PROCESS_GROUP so the
agent process survives even if this launcher is killed.
"""

import os
import sys
import time
import subprocess
import signal

PID_FILE = "agent_system.pid"
LOG_FILE = "agent_output.log"


def start_system():
    """Start the agent system as a background process."""
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--deploy"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        stdout=open(LOG_FILE, "w"),
        stderr=subprocess.STDOUT,
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    print(f"Agent system started (PID: {proc.pid})")
    return proc


def stop_system():
    """Stop the agent system."""
    if not os.path.exists(PID_FILE):
        print("No PID file found. Try: taskkill /f /im python.exe")
        return
    with open(PID_FILE) as f:
        pid = f.read().strip()
    if pid:
        if sys.platform == "win32":
            os.system(f'taskkill /f /pid {pid} 2>nul')
        else:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        print(f"Stopped agent system (PID: {pid})")
    os.remove(PID_FILE)


def monitor():
    """Run as persistent monitor: start, watch, restart on crash."""
    print("=" * 50)
    print("  SUPER AGENT SYSTEM LAUNCHER")
    print("  Monitoring continuously — press Ctrl+C to stop")
    print("=" * 50)

    proc = start_system()
    consecutive_crashes = 0

    try:
        while True:
            time.sleep(5)
            ret = proc.poll()
            if ret is not None:
                print(f"[{time.strftime('%H:%M:%S')}] Agent system crashed (exit code: {ret})")
                consecutive_crashes += 1
                if consecutive_crashes >= 5:
                    print("Too many consecutive crashes (5). Waiting 60s...")
                    time.sleep(60)
                print(f"Restarting... (crash #{consecutive_crashes})")
                proc = start_system()
            else:
                consecutive_crashes = 0
    except KeyboardInterrupt:
        print("\nShutting down...")
        stop_system()
        print("Done.")


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop_system()
    else:
        monitor()
