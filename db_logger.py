from contextlib import contextmanager
from datetime import datetime
from database import SessionLocal, TradeLog, BotStatus


@contextmanager
def _db_session():
    """Context manager for safe DB session handling."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
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
        print(f"DB log_trade error: {e}")
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
        print(f"DB update_bot_status error: {e}")
        return None
