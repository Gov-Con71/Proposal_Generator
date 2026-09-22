"""Durability, revision publication, and recovery regression tests."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import Mock, AsyncMock

import pytest
from moto import mock_aws

from test_workspace_rag import proposal_with_requirements, _auth, _conn
from app.services import dispatch_service as jobs, drafting_runs as runs, workspace_service as ws


def _job(entity):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT job_id FROM dispatch_jobs WHERE entity_id=%s ORDER BY created_at DESC LIMIT 1', (str(entity),))
            return str(cur.fetchone()[0])
    finally:
        conn.close()


def _stage(run, text='Fresh draft', title='Technical'):
    runs.outline_for(run, [{'title': title}])
    return runs.stage(run, 0, dict(section_title=title, content=text, sort_order=0))


def test_revisions_replace_generated_sections_and_preserve_edits(proposal_with_requirements):
    seed = proposal_with_requirements
    pid, uid = seed['proposal_id'], seed['user_id']
    first = runs.create(pid)
    _stage(first)
    runs.publish(first)
    original = ws.list_sections(pid, uid)[0]
    second = runs.create(pid)
    sid = _stage(second, 'Second draft')
    assert _stage(second, 'Second draft') == sid  # stable across task replay
    assert ws.list_sections(pid, uid)[0].content == 'Fresh draft'  # staged only
    runs.publish(second)
    runs.publish(second)  # completion replay is harmless
    visible = ws.list_sections(pid, uid)
    assert len(visible) == 1 and visible[0].content == 'Second draft'
    assert visible[0].id != original.id
    ws.update_section(visible[0].id, uid, 'My approved response', 'approved')
    third = runs.create(pid)
    _stage(third, 'Must not overwrite')
    runs.publish(third)
    assert [s.content for s in ws.list_sections(pid, uid)] == ['My approved response']


def test_concurrent_run_claims_and_edit_conflict(proposal_with_requirements):
    seed = proposal_with_requirements
    pid, uid = seed['proposal_id'], seed['user_id']
    def claim():
        try:
            return runs.create(pid)
        except runs.DraftConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: claim(), range(2)))
    assert sum(r is not None for r in claimed) == 1
    run = next(r for r in claimed if r)
    _stage(run)
    ws.create_section(pid, uid, 'My manual section', None)
    with pytest.raises(runs.DraftConflict, match='changed'):
        runs.publish(run)
    runs.fail(run, 'Concurrent edit')
    assert [s.title for s in ws.list_sections(pid, uid)] == ['My manual section']


def test_incomplete_revision_preserves_previous_output(proposal_with_requirements):
    seed = proposal_with_requirements
    first = runs.create(seed['proposal_id'])
    _stage(first)
    runs.publish(first)
    second = runs.create(seed['proposal_id'])
    runs.outline_for(second, [{'title': 'Missing'}])
    with pytest.raises(runs.DraftConflict, match='incomplete'):
        runs.publish(second)
    assert ws.list_sections(seed['proposal_id'], seed['user_id'])[0].content == 'Fresh draft'


def test_export_acceptance_is_durable_and_http_replay_is_idempotent(test_client, proposal_with_requirements, monkeypatch):
    from app.worker.celery_app import celery_app
    seed = proposal_with_requirements
    send = Mock(side_effect=ConnectionError('offline'))
    monkeypatch.setattr(celery_app, 'send_task', send)
    auth = {**_auth(seed['user_id']), 'Idempotency-Key': str(uuid4())}
    data = {'proposalId': seed['proposal_id'], 'format': 'pdf'}
    one = test_client.post('/exports', json=data, headers=auth)
    two = test_client.post('/exports', json=data, headers=auth)
    assert one.status_code == two.status_code == 202
    assert one.json() == two.json()
    assert send.call_count == 0  # request committed without depending on Redis
    bad = test_client.post('/exports', json={**data, 'format': 'docx'}, headers=auth)
    assert bad.status_code == 409
    jobs.dispatch_once()
    assert send.call_count == 1
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute('SELECT status,publish_failures FROM dispatch_jobs WHERE job_id=%s', (_job(one.json()['id']),))
        assert cur.fetchone() == ('queued', 1)
    conn.close()


def test_worker_replay_and_recovery_use_original_job(test_client, proposal_with_requirements, monkeypatch):
    from app.services import export_service
    seed = proposal_with_requirements
    res = test_client.post('/exports', json={'proposalId': seed['proposal_id'], 'format': 'pdf'}, headers=_auth(seed['user_id']))
    job = _job(res.json()['id'])
    render = Mock(side_effect=[RuntimeError('temporary'), {'status': 'ready'}])
    monkeypatch.setattr(export_service, 'run_export_render', render)
    assert jobs.execute(job)['status'] == 'queued'
    assert jobs.execute(job)['status'] == 'completed'
    assert jobs.execute(job)['status'] == 'completed'
    assert render.call_count == 2


def test_running_worker_lock_prevents_duplicate_execution(test_client, proposal_with_requirements, monkeypatch):
    from app.services import export_service
    seed = proposal_with_requirements
    res = test_client.post('/exports', json={'proposalId': seed['proposal_id'], 'format': 'pdf'}, headers=_auth(seed['user_id']))
    job = _job(res.json()['id'])
    render = Mock()
    monkeypatch.setattr(export_service, 'run_export_render', render)
    conn = _conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (job,))
    try:
        assert jobs.execute(job)['status'] == 'already_running'
        render.assert_not_called()
    finally:
        conn.close()  # same release PostgreSQL performs after a worker dies
    assert jobs.execute(job)['status'] == 'completed'
    render.assert_called_once()


def test_domain_and_dispatch_commit_together(test_client, proposal_with_requirements, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    seed = proposal_with_requirements
    monkeypatch.setattr(jobs, 'enqueue', Mock(side_effect=RuntimeError('outbox insert failed')))
    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.post('/exports', json={'proposalId': seed['proposal_id'], 'format': 'pdf'}, headers=_auth(seed['user_id']))
    assert res.status_code == 500
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM export_jobs WHERE proposal_id=%s', (seed['proposal_id'],))
        assert cur.fetchone()[0] == 0
    conn.close()


@mock_aws
def test_upload_replay_and_worker_pipeline(test_client, proposal_with_requirements, monkeypatch):
    from app.core.config import settings
    from app.services import ingestion
    from app.services.compliance_extractor import ComplianceMatrix, ExtractedRequirement
    from test_ingestion_pipeline import _null_summary
    seed = proposal_with_requirements
    monkeypatch.setattr(settings, 'use_localstack', False)
    monkeypatch.setattr(ingestion, 'run_extraction', AsyncMock(return_value=ComplianceMatrix(requirements=[ExtractedRequirement(section_number='C.1', requirement_text='The team shall deliver a report.', category='Technical')])) )
    monkeypatch.setattr(ingestion, 'run_solicitation_extraction', AsyncMock(return_value=_null_summary()))
    auth = {**_auth(seed['user_id']), 'Idempotency-Key': str(uuid4())}
    def upload():
        return test_client.post('/documents/upload', files={'file': ('bid.txt', b'The team shall deliver a report.', 'text/plain')}, headers=auth)
    one, two = upload(), upload()
    assert one.status_code == two.status_code == 202
    assert one.json() == two.json()
    job = _job(one.json()['rfpId'])
    assert jobs.execute(job)['status'] == 'completed'
    assert jobs.execute(job)['status'] == 'completed'
    status = test_client.get(f"/documents/{one.json()['rfpId']}", headers=auth).json()
    assert status['processingStatus'] == 'completed'
    assert status['requirementsCount'] == 1
