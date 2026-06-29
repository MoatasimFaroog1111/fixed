"""
Shared utilities for the BullionVault trading bot system.

Consolidates duplicated patterns:
- Control state reading/writing
- RSI calculation
- USD balance extraction
- JSON file persistence helpers
- Bot entry-point launcher
- Logging setup
"""
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from logging.handlers import RotatingFileHandler


# ── Control State ──────────────────────────────────────────────────────────

CONTROL_STATE_PATH = Path(
    os.environ.get("CONTROL_STATE_PATH", "control_state.json")
)

DEFAULT_CONTROL_STATE = {
    "paused": False,
    "allow_buy": True,
    "allow_sell": True,
    "silver_enabled": True,
    "palladium_enabled": True,
    "stop_loss_enabled": True,
    "emergency_close_all": False,
    "paused_after_close_all": True,
}


def read_control_state(path: Path = None, logger: logging.Logger = None) -> dict:
    """Read control_state.json with fallback defaults."""
    path = path or CONTROL_STATE_PATH
    state = dict(DEFAULT_CONTROL_STATE)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            state.update(data)
    except Exception as exc:
        if logger:
            logger.warning(f"control_state read failed: {exc}")
    return state


def save_control_state(state: dict, path: Path = None):
    """Write control_state.json atomically."""
    path = path or CONTROL_STATE_PATH
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── RSI Calculation ────────────────────────────────────────────────────────

def calculate_rsi(prices: Sequence[float], period: int = 14) -> float:
    """
    Calculate RSI using simple average of gains/losses.
    Returns 50.0 if insufficient data.
    """
    clean_prices = [float(p) for p in prices if p and float(p) > 0]
    if len(clean_prices) < period + 1:
        return 50.0

    gains = []
    losses = []
    relevant = clean_prices[-(period + 1):]
    for prev, curr in zip(relevant, relevant[1:]):
        change = curr - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_rsi_wilder(prices: Sequence[float], period: int = 14) -> float:
    """
    Calculate RSI using Wilder's exponential smoothing method.
    Returns 50.0 if insufficient data.
    """
    import numpy as np

    if len(prices) < period + 1:
        return 50.0

    p = np.array(prices[-(period + 1):], dtype=float)
    deltas = np.diff(p)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    gain = gains[:period].mean()
    loss = losses[:period].mean()

    for g, l_val in zip(gains[period:], losses[period:]):
        gain = (gain * (period - 1) + g) / period
        loss = (loss * (period - 1) + l_val) / period

    rs = gain / (loss + 1e-10)
    return float(100 - (100 / (1 + rs)))


# ── USD Balance Extraction ─────────────────────────────────────────────────

def extract_usd_available(balance: dict) -> float:
    """
    Extract available USD from a parsed balance dict.
    Handles both dict-style and direct float values.
    """
    raw = balance.get("USD", 0)
    if isinstance(raw, dict):
        return float(raw.get("available", 0) or 0)
    return float(raw or 0)


# ── JSON Persistence Helpers ───────────────────────────────────────────────

def append_json_log(path: str, entry: dict, max_entries: int = 500):
    """Append an entry to a JSON array file, keeping only the last max_entries."""
    try:
        data = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.append(entry)
        data = data[-max_entries:]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def append_jsonl(path: str, entry: dict):
    """Append an entry as a JSONL line."""
    try:
        entry["logged_at"] = datetime.utcnow().isoformat()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Logging Setup ──────────────────────────────────────────────────────────

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 3


def setup_logger(
    bot_name: str,
    log_file: str,
    level: int = logging.INFO,
    max_bytes: int = MAX_LOG_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
    rotating: bool = True,
) -> logging.Logger:
    """
    Unified logging setup with optional rotation.
    Returns existing logger if already configured.
    """
    logger = logging.getLogger(bot_name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    if rotating:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")

    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


def _install_quiet_shutdown(bot):
    """Stop bot processes cleanly without spamming Telegram on normal redeploys.

    Railway sends SIGTERM during redeploys/restarts. The original BaseMetalBot
    shutdown handler sends "Bot stopping..." to Telegram for every metal bot,
    which creates noisy duplicate messages. Keep this quiet by default and allow
    opt-in with NOTIFY_BOT_STOP=1 when needed.
    """
    if os.environ.get("NOTIFY_BOT_STOP", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return

    def quiet_shutdown(signum, frame):
        try:
            bot.logger.info("Shutdown. Stopping %s quietly...", bot.BOT_NAME)
        except Exception:
            pass
        bot.running = False
        bot._alerted_profit_100 = False
        bot._alerted_loss_35 = False
        bot._last_alert_date = None

    signal.signal(signal.SIGINT, quiet_shutdown)
    signal.signal(signal.SIGTERM, quiet_shutdown)


# ── Bot Launcher ───────────────────────────────────────────────────────────

def launch_bot(bot_class):
    """
    Standard entry-point for bot_*.py scripts.
    Loads .env, reads BV_USERNAME/BV_PASSWORD, instantiates and runs the bot.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    except ImportError:
        pass

    username = os.environ.get("BV_USERNAME", "")
    password = os.environ.get("BV_PASSWORD", "")
    if not username or not password:
        print("ERROR: BV_USERNAME / BV_PASSWORD not set.")
        sys.exit(1)

    bot = bot_class(username, password)
    _install_quiet_shutdown(bot)
    bot.run()
