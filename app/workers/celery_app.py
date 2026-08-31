from celery import Celery

from app.config import settings

celery_app = Celery(
    "billing_engine",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Billing work is worth retrying on transient DB/broker failures.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
