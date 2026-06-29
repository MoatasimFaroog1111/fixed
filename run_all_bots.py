"""
Run Guardian metal bots as separate processes.

Risk note:
- By default, only SILVER is started for real trading because it is the most
  practical metal for small balances and usually has better tradability.
- Use ENABLED_BOTS in Railway Variables to choose the active metals.
  Examples:
    ENABLED_BOTS=SILVER
    ENABLED_BOTS=SILVER,PLATINUM
    ENABLED_BOTS=ALL
"""
import subprocess
import sys
import time
import os
import signal
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent
PYTHON_BIN = sys.executable

BOTS = {
    "GOLD":     "bot_gold.py",
    "PLATINUM": "bot_platinum.py",
    "SILVER":    "bot_silver.py",
    "PALLADIUM": "bot_palladium.py",
}

SERVICES = {
    "TELEGRAM_CMD": "telegram_control_v4_secure.py",
}

DEFAULT_ENABLED_BOTS = "SILVER"


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
        print("  Option 1: export BV_USERNAME=... BV_PASSWORD=...")
        print("  Option 2: create a .env file (see .env.example)")
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


def start_bot(name: str, filename: str):
    path = BASE_DIR / filename
    if not path.exists():
        print(f"[{name}] {filename} not found — skipping.")
        return None
    print(f"[{name}] Starting {filename} ...")
    return subprocess.Popen(
        [PYTHON_BIN, str(path)],
        cwd=BASE_DIR,
        env=os.environ.copy(),
    )


def main():
    load_env(BASE_DIR / ".env")
    check_credentials()

    processes = {}
    active_bots = _parse_enabled_bots()
    all_procs = {**active_bots, **SERVICES}
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
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("All stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
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
                    all_procs_map = {**active_bots, **SERVICES}
                    if name not in all_procs_map:
                        processes.pop(name, None)
                        continue
                    new_proc = start_bot(name, all_procs_map[name])
                    if new_proc:
                        processes[name] = new_proc
        time.sleep(5)


if __name__ == "__main__":
    main()
