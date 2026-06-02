from datetime import datetime
from celery_app import celery_app
from db_logger import update_bot_status, log_trade


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 10},
)
def record_bot_status_task(self, bot_name, status, message=""):
    row_id = update_bot_status(bot_name, status, message)
    return {
        "ok": True,
        "row_id": row_id,
        "bot_name": bot_name,
        "status": status,
        "logged_at": datetime.utcnow().isoformat(),
    }


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 10},
)
def record_trade_task(self, symbol, side, quantity, price, status, bot_name):
    row_id = log_trade(symbol, side, quantity, price, status, bot_name)
    return {
        "ok": True,
        "row_id": row_id,
        "symbol": symbol,
        "side": side,
        "status": status,
        "logged_at": datetime.utcnow().isoformat(),
    }


@celery_app.task
def health_check_task():
    return {
        "ok": True,
        "service": "celery",
        "checked_at": datetime.utcnow().isoformat(),
    }
