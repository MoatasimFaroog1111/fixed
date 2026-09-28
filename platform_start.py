"""
Platform-neutral startup wrapper for Guardian BullionVault bots.

Secrets come only from environment variables. Mutable state goes to
GUARDIAN_RUNTIME_DIR. Trading remains controlled by the bot classes, which are
currently hard-locked to DRY_RUN=True.
"""
from __future__ import annotations

import json
import os
import sys
import pickle
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.environ.get("GUARDIAN_RUNTIME_DIR", "/data")).resolve()
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"

EXPECTED_FEATURE_COUNT = 80
METALS = ["AUXLN", "AGXLN", "PTXLN", "PDXLN"]


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


def ensure_runtime() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["GUARDIAN_RUNTIME_DIR"] = str(RUNTIME_DIR)


def ensure_authorized_users() -> None:
    owners = _parse_ids("TG_OWNER_IDS", "TG_CHAT_ID", "CHAT_ID")
    admins = _parse_ids("TG_ADMIN_IDS", "TG_ALLOWED_CHAT_IDS")
    viewers = _parse_ids("TG_VIEWER_IDS")
    auth = {
        "owners": owners,
        "admins": [x for x in admins if x not in owners],
        "viewers": [x for x in viewers if x not in owners and x not in admins],
    }
    (RUNTIME_DIR / "authorized_users.json").write_text(
        json.dumps(auth, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def validate_required_env() -> None:
    missing = [name for name in ("BV_USERNAME", "BV_PASSWORD") if not os.getenv(name)]
    if missing:
        print("ERROR: missing required BullionVault variables: " + ", ".join(missing))
        sys.exit(1)


def _model_needs_retrain(security_id: str) -> bool:
    model_path = MODELS_DIR / f"{security_id}_model.pkl"
    scaler_path = MODELS_DIR / f"{security_id}_scaler.pkl"

    if not model_path.exists() or not scaler_path.exists():
        return True

    try:
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        n_features = getattr(scaler, "n_features_in_", None)
        return n_features is not None and n_features != EXPECTED_FEATURE_COUNT
    except Exception:
        return True


def auto_retrain_if_needed() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    has_data = any(
        (DATA_DIR / f"{sid}_hourly.pkl").exists()
        or (DATA_DIR / f"{sid}_daily.pkl").exists()
        for sid in METALS
    )
    if not has_data:
        print("[TRAIN] No historical dataset found; keeping existing/fallback predictor.")
        return

    needs = [sid for sid in METALS if _model_needs_retrain(sid)]
    if not needs:
        print("[TRAIN] Models are compatible.")
        return

    print(f"[TRAIN] Retraining required for: {needs}")
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "historical_trainer.py")],
        cwd=str(BASE_DIR),
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        print(f"[TRAIN] Trainer exited with {result.returncode}; continuing with safe fallback behavior.")


def main() -> None:
    _load_dotenv_if_available()
    ensure_runtime()
    ensure_authorized_users()
    validate_required_env()
    auto_retrain_if_needed()
    os.execvpe(
        sys.executable,
        [sys.executable, str(BASE_DIR / "run_all_bots.py")],
        os.environ.copy(),
    )


if __name__ == "__main__":
    main()
