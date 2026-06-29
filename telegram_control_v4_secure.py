"""
Secure launcher for Guardian Telegram Command Center v4.

It keeps telegram_control_v4.py unchanged, but patches runtime paths and
credentials before starting the original main loop. This prevents hardcoded
/home/moatasim/fixed paths from breaking Railway deployments and keeps
Telegram authorization in runtime-only configuration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - optional dependency during bootstrapping
    load_dotenv = None

if load_dotenv:
    load_dotenv(Path(__file__).resolve().parent / ".env")

from api_client import BullionVaultAPI
import telegram_control_v4 as cockpit

BASE_DIR = Path(__file__).resolve().parent


def _parse_ids(*env_names: str) -> list[int]:
    ids: list[int] = []
    for name in env_names:
        raw = os.getenv(name, "")
        for part in raw.replace(";", ",").split(","):
            value = part.strip()
            if not value:
                continue
            try:
                user_id = int(value)
            except ValueError:
                print(f"WARNING: ignoring invalid Telegram user id in {name}: {value!r}")
                continue
            if user_id not in ids:
                ids.append(user_id)
    return ids


def _ensure_authorized_users() -> None:
    owners = _parse_ids("TG_OWNER_IDS", "TG_CHAT_ID", "CHAT_ID")
    admins = _parse_ids("TG_ADMIN_IDS", "TG_ALLOWED_CHAT_IDS")
    viewers = _parse_ids("TG_VIEWER_IDS")
    data = {
        "owners": owners,
        "admins": [x for x in admins if x not in owners],
        "viewers": [x for x in viewers if x not in owners and x not in admins],
    }
    cockpit.AUTH_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    if not owners and not admins and not viewers:
        print("WARNING: Telegram cockpit has no authorized users configured.")


def _patch_paths() -> None:
    cockpit.OFFSET_FILE = BASE_DIR / "telegram_offset.txt"
    cockpit.CONTROL_FILE = BASE_DIR / "control_state.json"
    cockpit.TRADE_LOG = BASE_DIR / "trade_log.json"
    cockpit.AUTH_FILE = BASE_DIR / "authorized_users.json"
    cockpit.PENDING_ORDER = BASE_DIR / "pending_order.json"

    cockpit.STATE_FILES = {
        "gold": BASE_DIR / "state_AUXLN.json",
        "silver": BASE_DIR / "state_AGXLN.json",
        "platinum": BASE_DIR / "state_PTXLN.json",
        "palladium": BASE_DIR / "state_PDXLN.json",
    }
    cockpit.PRICE_LOG_FILES = {
        "gold": BASE_DIR / "price_log_AUXLN.json",
        "silver": BASE_DIR / "price_log_AGXLN.json",
        "platinum": BASE_DIR / "price_log_PTXLN.json",
        "palladium": BASE_DIR / "price_log_PDXLN.json",
    }


def _patch_api() -> None:
    username = os.getenv("BV_USERNAME", "")
    password = os.getenv("BV_PASSWORD", "")
    if not username or not password:
        print("WARNING: BV_USERNAME / BV_PASSWORD not set — BullionVault API calls will fail")
    cockpit._api = BullionVaultAPI(username, password)
    cockpit._api_logged_in = False


def main() -> None:
    _patch_paths()
    _patch_api()
    _ensure_authorized_users()
    cockpit.main()


if __name__ == "__main__":
    main()
