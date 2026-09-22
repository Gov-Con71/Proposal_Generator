"""Transactional outbox with at-least-once publication and serialized execution.

The dispatcher runs independently of the broker. PostgreSQL session advisory
locks protect running work without timing out healthy, long LLM calls. A dead
worker releases its lock and the dispatcher re-delivers its stable job ID.
"""
import hashlib
import json
import logging
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException
from psycopg2.extras import Json, RealDictCursor
from app.core.db import get_connection, transaction

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
MAX_PUBLISH_FAILURES = 10


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@contextmanager
def request(user_id, operation, key, payload):
    """Serialize matching HTTP retries and compose domain/outbox persistence."""
    if key is not None and (not key.strip() or len(key) > 128):
        raise HTTPException(422, 'Idempotency-Key must contain 1–128 characters.')
    digest = fingerprint(payload)
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        previous = None
        if key:
            cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'{user_id}:{operation}:{key}',))
            cur.execute('SELECT request_hash,response FROM dispatch_jobs WHERE user_id=%s AND operation=%s AND idempotency_key=%s', (str(user_id), operation, key))
            previous = cur.fetchone()
            if previous and previous['request_hash'] != digest:
                raise HTTPException(409, 'This idempotency key was already used for a different request.')
        yield previous['response'] if previous else None, digest


def enqueue(user_id, operation, entity_id, payload, response, request_hash, key=None, job_id=None):
    job_id = str(job_id or uuid4())
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute('''INSERT INTO dispatch_jobs(job_id,user_id,operation,entity_id,payload,response,request_hash,idempotency_key)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (job_id, str(user_id), operation, str(entity_id), Json(payload), Json(response), request_hash, key))
    finally:
        conn.close()
    return job_id


def _domain_status(job, failed, error=None):
    from app.services import document_service, proposals_service, export_service, drafting_runs
    entity = str(job['entity_id'])
    if job['operation'] == 'draft_proposal':
        if failed:
            drafting_runs.fail(job['payload']['run_id'], error or 'Draft failed')
        else:
            proposals_service.set_drafting_status(entity, 'drafting')
    elif job['operation'] == 'ingest_document':
        document_service.update_status(entity, 'failed' if failed else 'pending', error)
    else:
        export_service._mark(entity, 'failed' if failed else 'pending', error=error)


def _terminal(job, error):
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("UPDATE dispatch_jobs SET status='failed',error=%s,updated_at=now() WHERE job_id=%s", (error[:500], str(job['job_id'])))
        _domain_status(job, True, error)


def dispatch_once(limit=20):
    from app.worker.celery_app import celery_app
    # Keep the claim transaction brief and independent of the broker call.
    with transaction() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""SELECT * FROM dispatch_jobs WHERE status IN ('queued','running')
            AND next_dispatch_at<=now() ORDER BY next_dispatch_at LIMIT %s FOR UPDATE SKIP LOCKED""", (limit,))
        jobs = cur.fetchall()
        for job in jobs:
            cur.execute("UPDATE dispatch_jobs SET next_dispatch_at=now()+interval '30 seconds' WHERE job_id=%s", (str(job['job_id']),))
    for job in jobs:
        lock = get_connection()
        lock.autocommit = True
        try:
            with lock.cursor() as cur:
                cur.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))', (str(job['job_id']),))
                if not cur.fetchone()[0]:
                    continue  # healthy work owns the lock, however long it takes
                # A worker may have finished after this dispatcher claimed it.
                cur.execute('SELECT status FROM dispatch_jobs WHERE job_id=%s', (str(job['job_id']),))
                state = cur.fetchone()
                if not state or state[0] in ('completed', 'failed'):
                    continue
            try:
                celery_app.send_task('execute_dispatch_job', args=[str(job['job_id'])], retry=False)
                with lock.cursor() as cur:
                    cur.execute('UPDATE dispatch_jobs SET publish_failures=0,error=NULL WHERE job_id=%s', (str(job['job_id']),))
            except Exception:
                logger.exception('Broker dispatch failed for job %s', job['job_id'])
                failures = job['publish_failures'] + 1
                if failures >= MAX_PUBLISH_FAILURES:
                    _terminal(job, 'The work could not be queued. Restore the queue service and retry.')
                else:
                    with lock.cursor() as cur:
                        cur.execute("UPDATE dispatch_jobs SET publish_failures=%s,error=%s,next_dispatch_at=now()+(%s * interval '1 second') WHERE job_id=%s", (failures, 'Queue unavailable; dispatch will retry.', min(300, 2 ** failures), str(job['job_id'])))
        finally:
            lock.close()  # session locks released even on exceptions
    return len(jobs)


def execute(job_id):
    from app.services.ingestion import run_ingestion_sync
    from app.agent import run_drafting_sync
    from app.services.export_service import run_export_render
    from app.services.drafting_runs import DraftConflict
    lock = get_connection()
    lock.autocommit = True
    try:
        with lock.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired', (str(job_id),))
            if not cur.fetchone()['acquired']:
                return {'status': 'already_running'}
            cur.execute('SELECT * FROM dispatch_jobs WHERE job_id=%s', (str(job_id),))
            job = cur.fetchone()
            if job is None or job['status'] in ('completed', 'failed'):
                return {'status': job['status'] if job else 'missing'}
            # Serialize different jobs affecting the same resource as well.
            resource = f"{job['operation']}:{job['entity_id']}"
            cur.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired', (resource,))
            if not cur.fetchone()['acquired']:
                return {'status': 'resource_busy'}
            if job['attempts'] >= MAX_ATTEMPTS:
                _terminal(job, 'Worker recovery attempts exhausted. Retry the operation.')
                return {'status': 'failed'}
            cur.execute("UPDATE dispatch_jobs SET status='running',attempts=attempts+1,updated_at=now() WHERE job_id=%s", (str(job_id),))
        try:
            if job['operation'] == 'ingest_document':
                run_ingestion_sync(str(job['entity_id']))
            elif job['operation'] == 'draft_proposal':
                run_drafting_sync(str(job['entity_id']), run_id=job['payload']['run_id'], retrieval_filters=job['payload'].get('retrieval_filters'))
            else:
                run_export_render(str(job['entity_id']))
        except Exception as exc:
            logger.exception('Job %s execution failed', job_id)
            if isinstance(exc, DraftConflict) or job['attempts'] + 1 >= MAX_ATTEMPTS:
                _terminal(job, 'Work failed after retries. Check the document and service configuration, then retry.' if not isinstance(exc, DraftConflict) else str(exc))
                return {'status': 'failed'}
            with transaction() as conn, conn.cursor() as cur:
                cur.execute("UPDATE dispatch_jobs SET status='queued',error=%s,next_dispatch_at=now()+interval '10 seconds',updated_at=now() WHERE job_id=%s", ('Work interrupted; retry scheduled.', str(job_id)))
                _domain_status(job, False)
            return {'status': 'queued'}
        with lock.cursor() as cur:
            cur.execute("UPDATE dispatch_jobs SET status='completed',error=NULL,updated_at=now() WHERE job_id=%s", (str(job_id),))
        return {'status': 'completed'}
    finally:
        lock.close()
