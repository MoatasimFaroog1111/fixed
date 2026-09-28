"""
Run Guardian metal bots as separate processes.

Migration safety:
- The trading classes remain DRY_RUN=True.
- ENABLE_TELEGRAM_COMMANDS can disable the Telegram command poller while a
  shadow/standby instance is running, preventing duplicate Telegram polling.
- GUARDIAN_RUNTIME_DIR moves mutable state off the application image.
"""
import subprocess
import sys
import time
import os
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("GUARDIAN_RUNTIME_DIR", str(BASE_DIR))).resolve()
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
PYTHON_BIN = sys.executable

BOTS = {
    "GOLD": "bot_gold.py",
    "PLATINUM": "bot_platinum.py",
    "SILVER": "bot_silver.py",
    "PALLADIUM": "bot_palladium.py",
}

TELEGRAM_SERVICE = {
    "TELEGRAM_CMD": "telegram_control_v4_secure.py",
}

DEFAULT_ENABLED_BOTS = "SILVER"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_env(path: Path):
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    print(f"[ENV] Loaded {path}")


def check_credentials():
    username = os.environ.get("BV_USERNAME")
    password = os.environ.get("BV_PASSWORD")
    if not username or not password:
        print("ERROR: BV_USERNAME and BV_PASSWORD must be set.")
        sys.exit(1)
    print("[ENV] BullionVault credentials loaded.")


def _parse_enabled_bots() -> dict:
    raw = os.environ.get("ENABLED_BOTS", DEFAULT_ENABLED_BOTS).strip()
    if not raw:
        raw = DEFAULT_ENABLED_BOTS

    wanted = [x.strip().upper() for x in raw.replace(";", ",").split(",") if x.strip()]
    if "ALL" in wanted:
        selected = dict(BOTS)
    else:
        selected = {name: BOTS[name] for name in wanted if name in BOTS}
        unknown = [name for name in wanted if name not in BOTS]
        for name in unknown:
            print(f"[CONFIG] Unknown bot in ENABLED_BOTS ignored: {name}")

    if not selected:
        print("[CONFIG] No valid trading bots selected. Falling back to SILVER only.")
        selected = {"SILVER": BOTS["SILVER"]}

    print("[CONFIG] Enabled trading bots: " + ", ".join(selected.keys()))
    return selected


def _service_map(active_bots: dict) -> dict:
    services = dict(active_bots)
    if _env_bool("ENABLE_TELEGRAM_COMMANDS", True):
        services.update(TELEGRAM_SERVICE)
        print("[CONFIG] Telegram command service enabled.")
    else:
        print("[CONFIG] Telegram command service disabled (shadow/standby-safe).")
    return services


def start_bot(name: str, filename: str):
    path = BASE_DIR / filename
    if not path.exists():
        print(f"[{name}] {filename} not found — skipping.")
        return None
    print(f"[{name}] Starting {filename} ... runtime={RUNTIME_DIR}")
    env = os.environ.copy()
    env["GUARDIAN_RUNTIME_DIR"] = str(RUNTIME_DIR)
    return subprocess.Popen(
        [PYTHON_BIN, str(path)],
        cwd=RUNTIME_DIR,
        env=env,
    )


def main():
    load_env(BASE_DIR / ".env")
    check_credentials()

    processes = {}
    active_bots = _parse_enabled_bots()
    all_procs = _service_map(active_bots)
    restart_counts = {name: 0 for name in all_procs}
    max_restarts = int(os.environ.get("MAX_PROCESS_RESTARTS", "12"))

    for name, file in all_procs.items():
        proc = start_bot(name, file)
        if proc:
            processes[name] = proc
        time.sleep(2)

    if not processes:
        print("No bots started.")
        sys.exit(1)

    print(f"\n{len(processes)} process(es) running. Press Ctrl+C to stop all.\n")

    def shutdown(sig, frame):
        print("\nStopping all bots...")
        for metal, proc in processes.items():
            print(f"  [{metal}] Terminating...")
            proc.terminate()
        for metal, proc in processes.items():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("All stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    restart_after = {}

    while True:
        now = time.time()
        for name, proc in list(processes.items()):
            ret = proc.poll()
            if ret is not None:
                if restart_counts.get(name, 0) >= max_restarts:
                    print(f"[{name}] Exited with code {ret}. Restart limit reached; not restarting.")
                    processes.pop(name, None)
                    continue

                if name not in restart_after:
                    restart_counts[name] = restart_counts.get(name, 0) + 1
                    wait = min(300, 10 * restart_counts[name])
                    print(f"[{name}] Exited with code {ret}. Restart #{restart_counts[name]} in {wait}s...")
                    restart_after[name] = now + wait
                elif now >= restart_after[name]:
                    del restart_after[name]
                    all_procs_map = _service_map(active_bots)
                    if name not in all_procs_map:
                        processes.pop(name, None)
                        continue
                    new_proc = start_bot(name, all_procs_map[name])
                    if new_proc:
                        processes[name] = new_proc
        time.sleep(5)


if __name__ == "__main__":
    main()
