"""Celery application wiring (Story 2.5).

Broker + result backend come from settings (Redis by default). Set
`CELERY_TASK_ALWAYS_EAGER=true` to run tasks inline without a broker — used by
the integration test and handy for local debugging.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "proposal_ingestion",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
)
