import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "").strip()

if REDIS_URL:
    broker_url = REDIS_URL
    result_backend = REDIS_URL
    task_always_eager = False
else:
    broker_url = "memory://"
    result_backend = "cache+memory://"
    task_always_eager = True

celery_app = Celery(
    "guardian_trading_bot",
    broker=broker_url,
    backend=result_backend,
    include=["celery_tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Riyadh",
    enable_utc=True,
    task_always_eager=task_always_eager,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
