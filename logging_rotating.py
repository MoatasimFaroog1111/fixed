"""
logging_rotating.py — Guardian v7
Log Rotation مع حد 10MB لكل ملف، الاحتفاظ بـ 3 نسخ فقط.
يُستدعى بدلاً من logging.FileHandler في base_bot.py إذا أردت rotation مستقلاً.
الاستخدام:
    from logging_rotating import setup_rotating_logger
    logger = setup_rotating_logger("SilverBot", "bot_silver.log")
"""
import logging
import os
from logging.handlers import RotatingFileHandler

MAX_BYTES    = 10 * 1024 * 1024   # 10 MB لكل ملف
BACKUP_COUNT = 3                   # 3 نسخ = إجمالي ≤ 40 MB لكل بوت


def setup_rotating_logger(
    bot_name: str,
    log_file: str,
    max_bytes: int = MAX_BYTES,
    backup_count: int = BACKUP_COUNT,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    يُنشئ logger بـ RotatingFileHandler.
    - log_file     : مسار ملف اللوج (مثل "bot_silver.log")
    - max_bytes    : الحجم الأقصى للملف قبل التدوير (افتراضي 10MB)
    - backup_count : عدد النسخ الاحتياطية (افتراضي 3 → إجمالي ≤ 40MB)
    """
    logger = logging.getLogger(bot_name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # ── Rotating file handler ──────────────────────────────────────────
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # ── Stream handler (console) ───────────────────────────────────────
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    logger.info(
        f"Logger initialized | file={log_file} | "
        f"max={max_bytes//1024//1024}MB | backups={backup_count}"
    )
    return logger


def cleanup_old_logs(log_dir: str = ".", pattern: str = ".log", keep_mb: int = 100):
    """
    أداة يدوية: احذف ملفات اللوج القديمة إذا تجاوز مجموعها keep_mb ميجابايت.
    شغّلها يدوياً عند الحاجة فقط — لا تُستدعى تلقائياً.
    """
    import glob

    files = sorted(
        glob.glob(os.path.join(log_dir, f"*{pattern}*")),
        key=os.path.getmtime,
    )
    total_bytes = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
    limit_bytes = keep_mb * 1024 * 1024

    removed = []
    while total_bytes > limit_bytes and files:
        oldest = files.pop(0)
        size = os.path.getsize(oldest)
        os.remove(oldest)
        total_bytes -= size
        removed.append(oldest)

    if removed:
        print(f"[cleanup] Removed {len(removed)} log file(s): {removed}")
    else:
        print(f"[cleanup] Total log size {total_bytes//1024//1024}MB — no cleanup needed.")


# ─── تعليمات التكامل مع base_bot.py ───────────────────────────────────────
# في base_bot.py استبدل دالة _setup_logging الحالية بما يلي:
#
# from logging_rotating import setup_rotating_logger
#
# def _setup_logging(bot_name, log_file):
#     return setup_rotating_logger(bot_name, log_file)
#
# بدلاً عن:
#     file_handler = logging.FileHandler(log_file, encoding="utf-8")
# ─────────────────────────────────────────────────────────────────────────
