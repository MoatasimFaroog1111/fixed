import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from monitoring import read_heartbeat, heartbeat_age_seconds
from db_logger import update_bot_status

BOT_CMD = [sys.executable, "bot_silver.py"]
PID_FILE = Path("runtime/pids/silver_bot.pid")
LOG_FILE = Path("runtime/logs/silver_bot_watchdog.log")
MAX_HEARTBEAT_AGE = 120


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " | " + msg
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def read_pid():
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def start_bot():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    out = open("runtime/logs/silver_bot.out.log", "a", encoding="utf-8")
    err = open("runtime/logs/silver_bot.err.log", "a", encoding="utf-8")

    p = subprocess.Popen(
        BOT_CMD,
        stdout=out,
        stderr=err,
        cwd=str(Path.cwd()),
    )

    PID_FILE.write_text(str(p.pid), encoding="utf-8")
    update_bot_status("SilverBot", "WATCHDOG_STARTED", f"Started PID {p.pid}")
    log(f"Started SilverBot PID={p.pid}")


def stop_dead_state():
    pid = read_pid()
    if pid and not is_process_alive(pid):
        log(f"Removing dead PID={pid}")
        PID_FILE.unlink(missing_ok=True)


def main():
    log("Watchdog started")

    while True:
        stop_dead_state()

        pid = read_pid()
        age = heartbeat_age_seconds()

        if not pid:
            log("No PID found. Starting bot.")
            start_bot()

        elif not is_process_alive(pid):
            log(f"PID {pid} not alive. Restarting bot.")
            PID_FILE.unlink(missing_ok=True)
            start_bot()

        elif age is None:
            log("No heartbeat yet. Bot process alive.")
            update_bot_status("SilverBot", "WATCHDOG_WAITING_HEARTBEAT", f"PID {pid}")

        elif age > MAX_HEARTBEAT_AGE:
            log(f"Heartbeat stale age={age:.1f}s. Restarting PID={pid}.")
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(5)
            except Exception:
                pass
            PID_FILE.unlink(missing_ok=True)
            start_bot()

        else:
            log(f"OK PID={pid} heartbeat_age={age:.1f}s")

        time.sleep(60)


if __name__ == "__main__":
    main()
