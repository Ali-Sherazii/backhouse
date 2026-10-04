from celery import Celery

from app.config import get_settings

celery_app = Celery("backhouse", broker=get_settings().redis_url, include=["app.pipeline.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="backhouse",
    broker_connection_retry_on_startup=True,
    # Exports are quick HTTP calls; keep them off the queue where OCR + LLM work can take minutes.
    task_routes={"backhouse.export_document": {"queue": "export"}},
)

PROCESS_TASK = "backhouse.process_document"
EXPORT_TASK = "backhouse.export_document"


def enqueue_processing(document_id: int) -> None:
    celery_app.send_task(PROCESS_TASK, args=[document_id])


def enqueue_export(document_id: int) -> None:
    celery_app.send_task(EXPORT_TASK, args=[document_id])
