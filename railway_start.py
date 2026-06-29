"""
Secure Railway startup wrapper for Guardian BullionVault bots.

This file prepares runtime-only files from environment variables, avoids
committing secrets to Git, and then starts run_all_bots.py.

v2: تدريب تلقائي عند كل deploy إذا كانت النماذج غائبة أو بنيتها قديمة.
"""
from __future__ import annotations

import json
import os
import sys
import pickle
import subprocess
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent
LEGACY_DIR = Path("/home/moatasim/fixed")
MODELS_DIR = BASE_DIR / "models"
DATA_DIR   = BASE_DIR / "data"

# عدد الـ features في v8 — إذا تغيّر يُعاد التدريب تلقائياً
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


def ensure_authorized_users() -> None:
    owners  = _parse_ids("TG_OWNER_IDS", "TG_CHAT_ID", "CHAT_ID")
    admins  = _parse_ids("TG_ADMIN_IDS", "TG_ALLOWED_CHAT_IDS")
    viewers = _parse_ids("TG_VIEWER_IDS")

    auth = {
        "owners":  owners,
        "admins":  [x for x in admins  if x not in owners],
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
            f"[SECURITY] authorized_users.json generated "
            f"(owners={len(owners)}, admins={len(auth['admins'])}, viewers={len(auth['viewers'])})."
        )


def ensure_legacy_path() -> None:
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
        print("WARNING: Telegram token not set.")


def _model_needs_retrain(security_id: str) -> bool:
    """
    يرجع True إذا:
      - النموذج غير موجود
      - عدد الـ features لا يطابق v8 (80 feature)
    """
    model_path  = MODELS_DIR / f"{security_id}_model.pkl"
    scaler_path = MODELS_DIR / f"{security_id}_scaler.pkl"

    if not model_path.exists() or not scaler_path.exists():
        print(f"[TRAIN] {security_id}: نموذج غير موجود → يحتاج تدريب")
        return True

    # تحقق من عدد الـ features في الـ scaler
    try:
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        n_features = getattr(scaler, "n_features_in_", None)
        if n_features is not None and n_features != EXPECTED_FEATURE_COUNT:
            print(
                f"[TRAIN] {security_id}: features قديمة ({n_features}) ≠ v8 ({EXPECTED_FEATURE_COUNT}) "
                f"→ يحتاج تدريب"
            )
            return True
    except Exception as e:
        print(f"[TRAIN] {security_id}: خطأ في فحص النموذج: {e} → يحتاج تدريب")
        return True

    return False


def auto_retrain_if_needed() -> None:
    """
    يفحص كل معدن — إذا أي نموذج يحتاج تدريب، يشغّل historical_trainer.py.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # تحقق هل يوجد بيانات للتدريب
    has_data = any(
        (DATA_DIR / f"{sid}_hourly.pkl").exists() or
        (DATA_DIR / f"{sid}_daily.pkl").exists()
        for sid in METALS
    )

    if not has_data:
        print(
            "[TRAIN] لا توجد بيانات تاريخية — تخطي التدريب وسيعمل البوت بـ FallbackPredictor."
        )
        return

    needs = [sid for sid in METALS if _model_needs_retrain(sid)]

    if not needs:
        print("[✅ TRAIN] جميع النماذج v8 جاهزة — لا حاجة لإعادة تدريب.")
        return

    print(f"[TRAIN] تدريب مطلوب لـ: {needs}")
    print("[TRAIN] جاري تشغيل historical_trainer.py...")

    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "historical_trainer.py")],
        cwd=str(BASE_DIR),
        env=os.environ.copy(),
    )

    if result.returncode == 0:
        print("[✅ TRAIN] اكتمل التدريب بنجاح.")
    else:
        print(
            f"[⚠️ TRAIN] خرج المدرب بكود {result.returncode}. "
            f"سيعمل البوت بالنماذج القديمة أو FallbackPredictor."
        )


def main() -> None:
    _load_dotenv_if_available()
    ensure_legacy_path()
    ensure_authorized_users()
    validate_required_env()

    # ── الجديد: تدريب تلقائي قبل تشغيل البوتات ──
    auto_retrain_if_needed()

    target = BASE_DIR / "run_all_bots.py"
    os.execvpe(sys.executable, [sys.executable, str(target)], os.environ.copy())


if __name__ == "__main__":
    main()
