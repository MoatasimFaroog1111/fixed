import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy.exc import OperationalError

from database import SessionLocal, TradeLog, BotStatus, init_db

logger = logging.getLogger(__name__)
_db_ready = False


def _ensure_db_ready():
    """Create SQLite/Postgres tables before writing bot logs.

    Railway creates a fresh filesystem on deploy, so guardian.db may exist
    without the required tables, or may not exist at all. Calling init_db()
    is idempotent and prevents repeated "no such table: bot_status" errors.
    """
    global _db_ready
    if _db_ready:
        return
    try:
        init_db()
        _db_ready = True
    except Exception as e:
        logger.error("DB init error: %s", e)


@contextmanager
def _db_session():
    """Context manager for safe DB session handling."""
    _ensure_db_ready()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except OperationalError as e:
        db.rollback()
        # If the DB file was recreated or tables are missing, retry table creation
        # once for the next call instead of crashing the bot loop.
        if "no such table" in str(e).lower():
            global _db_ready
            _db_ready = False
            _ensure_db_ready()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def log_trade(symbol, side, quantity, price, status, bot_name):
    try:
        with _db_session() as db:
            row = TradeLog(
                symbol=symbol,
                side=side,
                quantity=float(quantity or 0),
                price=float(price or 0),
                status=status,
                bot_name=bot_name,
                created_at=datetime.utcnow(),
            )
            db.add(row)
            db.flush()
            return row.id
    except Exception as e:
        logger.error("DB log_trade error: %s", e)
        return None


def update_bot_status(bot_name, status, message=""):
    try:
        with _db_session() as db:
            row = BotStatus(
                bot_name=bot_name,
                status=status,
                message=message,
                updated_at=datetime.utcnow(),
            )
            db.add(row)
            db.flush()
            return row.id
    except Exception as e:
        logger.error("DB update_bot_status error: %s", e)
        return None
