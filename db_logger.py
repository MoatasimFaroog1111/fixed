from datetime import datetime
from database import SessionLocal, TradeLog, BotStatus


def log_trade(symbol, side, quantity, price, status, bot_name):
    db = SessionLocal()
    try:
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
        db.commit()
        return row.id
    except Exception as e:
        db.rollback()
        print(f"DB log_trade error: {e}")
        return None
    finally:
        db.close()


def update_bot_status(bot_name, status, message=""):
    db = SessionLocal()
    try:
        row = BotStatus(
            bot_name=bot_name,
            status=status,
            message=message,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        return row.id
    except Exception as e:
        db.rollback()
        print(f"DB update_bot_status error: {e}")
        return None
    finally:
        db.close()
