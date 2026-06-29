import os
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from db_logger import update_bot_status

logger = logging.getLogger(__name__)

RUNTIME_DIR = Path("runtime")
HEARTBEAT_FILE = RUNTIME_DIR / "heartbeat.json"

RUNTIME_DIR.mkdir(exist_ok=True)


def write_heartbeat(bot_name="GuardianBot", status="RUNNING", message=""):
    data = {
        "bot_name": bot_name,
        "status": status,
        "message": message,
        "pid": os.getpid(),
        "timestamp": time.time(),
        "iso_time": datetime.utcnow().isoformat(),
    }

    HEARTBEAT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    try:
        update_bot_status(bot_name, status, message)
    except Exception as e:
        logger.warning("Heartbeat DB status update failed: %s", e)

    return data


def read_heartbeat():
    if not HEARTBEAT_FILE.exists():
        return None
    try:
        return json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to read heartbeat file: %s", e)
        return None


def heartbeat_age_seconds():
    data = read_heartbeat()
    if not data:
        return None
    return time.time() - float(data.get("timestamp", 0))
