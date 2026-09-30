"""Password guidance and error contracts without external services."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import auth
from app.core.config import settings
from app.core.deps import get_current_user_id


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_current_user_id] = lambda: 'user-1'
    with TestClient(app) as client:
        yield client


def test_policy_is_public_and_uses_configured_minimum(client, monkeypatch):
    monkeypatch.setattr(settings, 'password_min_length', 16)
    response = client.get('/auth/password-policy')
    assert response.status_code == 200
    assert response.json() == {'minLength': 16, 'maxBytes': 72, 'minDistinctCharacters': 5}


def test_wrong_current_password_has_a_distinct_error(client, monkeypatch):
    def reject(*args):
        raise auth.users.InvalidCredentialsError()

    monkeypatch.setattr(auth.users, 'change_password', reject)
    response = client.post('/auth/password', json={
        'currentPassword': 'wrong', 'newPassword': 'trombone-marmalade-97',
    })
    assert response.status_code == 401
    assert response.json()['detail'] == {
        'code': 'incorrect_current_password',
        'message': 'Your current password is incorrect.',
    }


def test_expired_session_does_not_use_password_error_code(client):
    def expired():
        raise auth.HTTPException(401, 'Session expired.')

    client.app.dependency_overrides[get_current_user_id] = expired
    response = client.post('/auth/password', json={
        'currentPassword': 'wrong', 'newPassword': 'trombone-marmalade-97',
    })
    assert response.status_code == 401
    assert response.json()['detail'] == 'Session expired.'


@pytest.mark.parametrize('password', ['short', 'password1234', 'aaaaaaaaaaaa', ' leading-space'])
def test_password_change_returns_readable_policy_error(client, password):
    response = client.post('/auth/password', json={
        'currentPassword': 'old', 'newPassword': password,
    })
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], str)


def test_successful_change_still_revokes_sessions(client, monkeypatch):
    revoked = []
    monkeypatch.setattr(auth.users, 'change_password', lambda *args: None)
    monkeypatch.setattr(auth.refresh_tokens, 'revoke_all_for_user', lambda user_id: revoked.append(user_id) or 1)
    response = client.post('/auth/password', json={
        'currentPassword': 'old', 'newPassword': 'trombone-marmalade-97',
    })
    assert response.status_code == 200
    assert revoked == ['user-1']
    assert response.json()['message'] == 'Password updated. Sign in again to continue.'


@pytest.mark.parametrize('password,expected', [
    ('short', 'at least'),
    ('password1234', 'common words'),
    ('bartholomew-spring-2026', 'name'),
    ('uniquealias-spring-2026', 'email address'),
])
def test_registration_explains_rejections(client, monkeypatch, password, expected):
    monkeypatch.setattr(auth.rate_limit, 'check', lambda *args: None)
    response = client.post('/auth/register', json={
        'email': 'uniquealias@example.com', 'password': password,
        'firstName': 'Bartholomew', 'lastName': 'Smith',
    })
    assert response.status_code == 422
    assert expected in response.json()['detail']
