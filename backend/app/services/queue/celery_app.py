"""
Celery application configuration.

Background job queue for document processing, embedding, and analysis.
"""

from celery import Celery

# Ensure every ORM model is registered before any task touches the database.
# Without this the worker crashes on first query with NoReferencedTableError.
import app.models  # noqa: E402,F401
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "knowops",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    task_default_queue=settings.celery_queue,
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=840,
    task_time_limit=900,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 1200},
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Auto-discover tasks from modules
celery_app.autodiscover_tasks(
    [
        "app.modules.ingestion",
        "app.modules.knowledge_quality",
        "app.modules.actions",
    ]
)
