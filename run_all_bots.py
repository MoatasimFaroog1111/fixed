"""
Run all metal bots as separate processes — Guardian v7
إصلاح L-03: لا طباعة لاسم المستخدم في stdout
"""
import subprocess
import sys
import time
import os
import signal
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent
PYTHON_BIN = sys.executable

# ─── حالة المعادن ──────────────────────────────────────────────────────────
#
#  SILVER    ✅ مفعَّل   — AGXLN | bot_silver.py
#  PALLADIUM ✅ مفعَّل   — PDXLN | bot_palladium.py
#
#  GOLD      ⏸ معطَّل   — سبب التعطيل:
#              BullionVault يشترط حد أدنى من رأس المال لتداول الذهب (AUXLN)
#              وهذا الرصيد غير متوفر حالياً في الحساب.
#              لتفعيله: تأكد من وجود رصيد USD كافٍ ثم أزل تعليق السطر أدناه.
#
#  PLATINUM  ⏸ معطَّل   — سبب التعطيل:
#              سيولة منخفضة في سوق البلاتين (PTXLN) على BullionVault
#              خلال ساعات التداول الحالية، مما يؤدي إلى رفض معظم الأوامر.
#              لتفعيله: راقب السيولة أولاً ثم أزل تعليق السطر أدناه.
#
# ───────────────────────────────────────────────────────────────────────────
BOTS = {
    "GOLD":     "bot_gold.py",      # ⏸ معطَّل — رأس مال غير كافٍ
    "PLATINUM": "bot_platinum.py",  # ⏸ معطَّل — سيولة منخفضة
    "SILVER":    "bot_silver.py",
    "PALLADIUM": "bot_palladium.py",
}

# ملف مستقل يُشغَّل كعملية منفصلة
SERVICES = {
    "TELEGRAM_CMD": "telegram_control_v4.py",
}


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
    all_procs = {**BOTS, **SERVICES}
    restart_counts = {name: 0 for name in all_procs}
    for name, file in all_procs.items():
        proc = start_bot(name, file)
        if proc:
            processes[name] = proc
        time.sleep(2)

    if not processes:
        print("No bots started.")
        sys.exit(1)

    print(f"\n{len(processes)} bot(s) running. Press Ctrl+C to stop all.\n")

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

    restart_after = {}  # metal -> timestamp موعد إعادة التشغيل

    while True:
        now = time.time()
        for name, proc in list(processes.items()):
            ret = proc.poll()
            if ret is not None:
                if name not in restart_after:
                    restart_counts[name] = restart_counts.get(name, 0) + 1
                    wait = min(300, 10 * restart_counts[name])
                    print(f"[{name}] Exited with code {ret}. Restart #{restart_counts[name]} in {wait}s...")
                    restart_after[name] = now + wait
                elif now >= restart_after[name]:
                    del restart_after[name]
                    all_procs_map = {**BOTS, **SERVICES}
                    new_proc = start_bot(name, all_procs_map[name])
                    if new_proc:
                        processes[name] = new_proc
        time.sleep(5)


if __name__ == "__main__":
    main()
