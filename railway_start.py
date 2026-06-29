"""
Secure Railway startup wrapper for Guardian BullionVault bots.

This file prepares runtime-only files from environment variables, avoids
committing secrets to Git, and then starts run_all_bots.py.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LEGACY_DIR = Path("/home/moatasim/fixed")


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv(BASE_DIR / ".env")


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


def ensure_authorized_users() -> None:
    """Create authorized_users.json from env vars at runtime only."""
    owners = _parse_ids("TG_OWNER_IDS", "TG_CHAT_ID", "CHAT_ID")
    admins = _parse_ids("TG_ADMIN_IDS", "TG_ALLOWED_CHAT_IDS")
    viewers = _parse_ids("TG_VIEWER_IDS")

    auth = {
        "owners": owners,
        "admins": [x for x in admins if x not in owners],
        "viewers": [x for x in viewers if x not in owners and x not in admins],
    }

    path = BASE_DIR / "authorized_users.json"
    path.write_text(json.dumps(auth, indent=2, ensure_ascii=False), encoding="utf-8")

    if not owners and not admins and not viewers:
        print(
            "WARNING: no Telegram authorized users configured. "
            "Set TG_OWNER_IDS or TG_CHAT_ID in Railway Variables."
        )
    else:
        print(
            "[SECURITY] authorized_users.json generated from environment "
            f"(owners={len(owners)}, admins={len(auth['admins'])}, viewers={len(auth['viewers'])})."
        )


def ensure_legacy_path() -> None:
    """
    Keep compatibility with older modules that still reference /home/moatasim/fixed.
    The preferred runtime path is BASE_DIR; this compatibility shim prevents crashes
    while the codebase is being fully migrated to relative paths.
    """
    try:
        if LEGACY_DIR.resolve() == BASE_DIR.resolve():
            return
    except Exception:
        pass

    if LEGACY_DIR.exists():
        return

    try:
        LEGACY_DIR.parent.mkdir(parents=True, exist_ok=True)
        LEGACY_DIR.symlink_to(BASE_DIR, target_is_directory=True)
        print(f"[COMPAT] Created legacy path symlink: {LEGACY_DIR} -> {BASE_DIR}")
    except Exception as exc:
        print(f"WARNING: could not create legacy path {LEGACY_DIR}: {exc}")


def validate_required_env() -> None:
    missing = [name for name in ("BV_USERNAME", "BV_PASSWORD") if not os.getenv(name)]
    if missing:
        print("ERROR: missing required BullionVault variables: " + ", ".join(missing))
        sys.exit(1)

    if not (os.getenv("TG_TOKEN_SILVER") or os.getenv("TG_TOKEN")):
        print("WARNING: Telegram token not set. Telegram command center will not start correctly.")


def main() -> None:
    _load_dotenv_if_available()
    ensure_legacy_path()
    ensure_authorized_users()
    validate_required_env()

    target = BASE_DIR / "run_all_bots.py"
    os.execvpe(sys.executable, [sys.executable, str(target)], os.environ.copy())


if __name__ == "__main__":
    main()
