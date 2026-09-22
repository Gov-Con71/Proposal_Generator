"""QA regressions using real tenant records and PostgreSQL."""
from uuid import uuid4
from unittest.mock import Mock

import pytest

from test_workspace_rag import proposal_with_requirements, _auth, _conn


@pytest.mark.parametrize('foreign_owner', [False, True])
def test_create_rejects_requirement_outside_proposal(test_client, proposal_with_requirements, other_tenant, foreign_owner):
    seed = proposal_with_requirements
    owner = other_tenant if foreign_owner else seed['user_id']
    rfp, req = str(uuid4()), str(uuid4())
    conn = _conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key) VALUES (%s,%s,'other','k')", (rfp, owner))
            cur.execute("INSERT INTO extracted_requirements (requirement_id,rfp_id,raw_text_content) VALUES (%s,%s,'private requirement')", (req, rfp))
        auth = _auth(seed['user_id'])
        res = test_client.post(f"/proposals/{seed['proposal_id']}/sections", headers=auth, json={'title': 'Invalid', 'requirementId': req})
        assert res.status_code == 404
        assert test_client.get(f"/proposals/{seed['proposal_id']}/sections", headers=auth).json() == []
    finally:
        with conn, conn.cursor() as cur:
            cur.execute('DELETE FROM rfp_documents WHERE rfp_id=%s', (rfp,))
        conn.close()


def test_section_detail_preserves_grounding(test_client, proposal_with_requirements):
    from app.services import workspace_service as ws
    seed = proposal_with_requirements
    section = ws.create_section(seed['proposal_id'], seed['user_id'], 'Evidence', None)
    ws.save_generated_draft(section.id, 'Grounded content', .8, ['Source A'])
    auth = _auth(seed['user_id'])
    detail = test_client.get(f'/sections/{section.id}', headers=auth).json()
    listing = test_client.get(f"/proposals/{seed['proposal_id']}/sections", headers=auth).json()[0]
    assert detail['aiConfidenceScore'] == listing['aiConfidenceScore'] == .8
    assert detail['referenceTags'] == listing['referenceTags'] == ['Source A']


def test_single_section_uses_owned_proposal_scope(monkeypatch, test_client, proposal_with_requirements):
    from app.services import draft_writer
    seed = proposal_with_requirements
    search = Mock(return_value=[])
    monkeypatch.setattr(draft_writer, 'search_similar', search)
    monkeypatch.setattr(draft_writer, 'get_llm', lambda: Mock(generate_text=Mock(return_value='Our team will deliver a documented implementation and verification approach. ' * 4)))
    auth = _auth(seed['user_id'])
    req = test_client.get(f"/proposals/{seed['proposal_id']}/requirements", headers=auth).json()[0]['id']
    res = test_client.post(f"/proposals/{seed['proposal_id']}/sections/generate", headers=auth, json={'requirementId': req})
    assert res.status_code == 201, res.text
    assert str(search.call_args.kwargs.get('proposal_id')) == seed['proposal_id']
    res = test_client.post(f"/sections/{res.json()['id']}/regenerate", headers=auth)
    assert res.status_code == 200, res.text
    assert str(search.call_args.kwargs.get('proposal_id')) == seed['proposal_id']
