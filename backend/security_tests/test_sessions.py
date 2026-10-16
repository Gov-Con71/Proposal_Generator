"""Regression coverage for real database locking, revocation and HTTP contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import UUID, uuid4

import jwt
import psycopg2
import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.config import Settings, settings
from app.core.security import decode_access_claims, create_two_factor_challenge_token
from app.core.secret_encryption import decrypt_secret
from app.services import refresh_token_service as tokens, user_service as users, totp_service as totp

PASSWORD = "trombone-marmalade-97"
NEW_PASSWORD = "accordion-cantaloupe-83"


def register(client):
    response = client.post('/auth/register', json={
        'email': f'{uuid4().hex}@example.com', 'password': PASSWORD,
        'firstName': 'Ada', 'lastName': 'Lovelace'})
    assert response.status_code == 201, response.text
    return response.json(), client.cookies.get(settings.refresh_cookie_name)


def bearer(session):
    return {'Authorization': f"Bearer {session['accessToken']}"}


def sql(dsn, statement, params=()):
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchall() if cur.description else None


def test_logout_invalidates_access_immediately(security_client):
    session, raw = register(security_client)
    assert security_client.get('/auth/me', headers=bearer(session)).status_code == 200
    assert security_client.post('/auth/logout').status_code == 200
    assert security_client.get('/auth/me', headers=bearer(session)).status_code == 401
    with pytest.raises(tokens.InvalidRefreshTokenError):
        tokens.rotate(raw)


def test_password_change_invalidates_access_and_all_devices(security_client):
    session, first = register(security_client)
    other = security_client.post('/auth/login', json={'email': session['user']['email'], 'password': PASSWORD}).json()
    second = security_client.cookies.get(settings.refresh_cookie_name)
    response = security_client.post('/auth/password', headers=bearer(session), json={
        'currentPassword': PASSWORD, 'newPassword': NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert 'Max-Age=0' in response.headers['set-cookie']
    for token_session in (session, other):
        assert security_client.get('/auth/me', headers=bearer(token_session)).status_code == 401
    for raw in (first, second):
        with pytest.raises(tokens.InvalidRefreshTokenError):
            tokens.rotate(raw)


def test_refresh_preserves_session_id_and_old_access(security_client):
    session, _ = register(security_client)
    response = security_client.post('/auth/refresh')
    assert response.status_code == 200, response.text
    assert decode_access_claims(response.json()['accessToken'])['sid'] == decode_access_claims(session['accessToken'])['sid']
    assert security_client.get('/auth/me', headers=bearer(session)).status_code == 200
    listed = security_client.get('/auth/sessions', headers=bearer(response.json())).json()
    assert len(listed) == 1 and listed[0]['isCurrent']


def test_concurrent_refresh_does_not_revoke_winner(security_client):
    session, raw = register(security_client)
    def rotate():
        try:
            return tokens.rotate(raw)
        except tokens.ConcurrentRefreshError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: rotate(), range(2)))
    assert outcomes.count('conflict') == 1
    winner = next(o for o in outcomes if o != 'conflict')
    assert tokens.is_active_session(UUID(session['user']['id']), tokens.session_for_token(winner[1])['session_id'])


def test_conflict_has_no_cookie_header(security_client):
    _, raw = register(security_client)
    tokens.rotate(raw)
    response = security_client.post('/auth/refresh', headers={'Cookie': f'{settings.refresh_cookie_name}={raw}'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'refresh_in_progress'
    assert 'set-cookie' not in response.headers


def test_replay_after_grace_revokes_sessions(security_client, monkeypatch):
    session, raw = register(security_client)
    _, successor = tokens.rotate(raw)
    monkeypatch.setattr(settings, 'refresh_concurrency_seconds', 0)
    with pytest.raises(tokens.InvalidRefreshTokenError):
        tokens.rotate(raw)
    assert not tokens.is_active_session(UUID(session['user']['id']), tokens.session_for_token(successor)['session_id'])
    assert security_client.get('/auth/me', headers=bearer(session)).status_code == 401


def test_logout_using_predecessor_revokes_current_successor(security_client):
    session, raw = register(security_client)
    _, successor = tokens.rotate(raw)
    tokens.revoke(raw)
    assert not tokens.is_active_session(UUID(session['user']['id']), tokens.session_for_token(successor)['session_id'])


def test_insert_failure_rolls_back_rotation(security_client, monkeypatch):
    session, raw = register(security_client)
    def fail(*args):
        raise RuntimeError('synthetic insertion failure')
    monkeypatch.setattr(tokens, '_insert', fail)
    with pytest.raises(RuntimeError):
        tokens.rotate(raw)
    assert tokens.is_active_session(UUID(session['user']['id']), tokens.session_for_token(raw)['session_id'])


def test_password_change_waits_for_rotation_then_revokes_successor(security_client, monkeypatch):
    session, raw = register(security_client)
    insert = tokens._insert
    entered, release = Event(), Event()
    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return insert(*args)
    monkeypatch.setattr(tokens, '_insert', delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rotation = pool.submit(tokens.rotate, raw)
        assert entered.wait(5)
        password = pool.submit(users.change_password, UUID(session['user']['id']), PASSWORD, NEW_PASSWORD)
        release.set()
        _, successor = rotation.result(timeout=5)
        password.result(timeout=5)
    assert not tokens.is_active_session(UUID(session['user']['id']), tokens.session_for_token(successor)['session_id'])


def test_stale_password_check_cannot_open_session_after_change(security_client):
    session, _ = register(security_client)
    authenticated = users.authenticate(session['user']['email'], PASSWORD)
    users.change_password(UUID(authenticated['id']), PASSWORD, NEW_PASSWORD)
    with pytest.raises(tokens.InvalidRefreshTokenError):
        tokens.issue(UUID(authenticated['id']), expected_auth_version=authenticated['auth_version'])


def test_absolute_expiry_caps_refresh_and_access(security_client, db):
    session, raw = register(security_client)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=2)
    sql(db, 'UPDATE refresh_tokens SET session_expires_at = %s WHERE user_id = %s', (deadline, session['user']['id']))
    response = security_client.post('/auth/refresh')
    assert response.status_code == 200
    assert decode_access_claims(response.json()['accessToken'])['exp'] <= deadline.timestamp()
    assert int(response.headers['set-cookie'].split('Max-Age=')[1].split(';')[0]) <= 120
    assert sql(db, 'SELECT MAX(expires_at) FROM refresh_tokens WHERE revoked_at IS NULL')[0][0] == deadline
    sql(db, "UPDATE refresh_tokens SET session_expires_at = NOW() - INTERVAL '1 second'")
    assert security_client.post('/auth/refresh').status_code == 401
    assert security_client.get('/auth/me', headers=bearer(session)).status_code == 401


def test_rejected_refresh_deletes_cookie(security_client):
    security_client.cookies.set(settings.refresh_cookie_name, 'invalid-token')
    response = security_client.post('/auth/refresh')
    assert response.status_code == 401
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert 'HttpOnly' in response.headers['set-cookie']


@pytest.mark.parametrize('path', ['/auth/refresh', '/auth/logout'])
def test_cookie_endpoints_require_csrf_header(security_client, path):
    security_client.headers.pop('X-CSRF-Protection')
    assert security_client.post(path).status_code == 403


@pytest.mark.parametrize('path', ['/auth/refresh', '/auth/logout', '/auth/login', '/auth/register'])
def test_hostile_origin_is_rejected(security_client, path):
    assert security_client.post(path, headers={'Origin': 'https://hostile.example'}).status_code == 403


def test_allowed_origin_is_accepted(security_client):
    assert security_client.post('/auth/logout', headers={'Origin': settings.cors_origin_list[0]}).status_code == 200


def test_device_revocation_is_owner_scoped_and_immediate(security_client):
    first, _ = register(security_client)
    login = security_client.post('/auth/login', json={'email': first['user']['email'], 'password': PASSWORD}).json()
    other, _ = register(security_client)
    sid = decode_access_claims(first['accessToken'])['sid']
    assert security_client.delete('/auth/sessions/' + sid, headers=bearer(other)).status_code == 404
    assert security_client.delete('/auth/sessions/' + sid, headers=bearer(login)).status_code == 200
    assert security_client.get('/auth/me', headers=bearer(first)).status_code == 401
    assert security_client.get('/auth/me', headers=bearer(login)).status_code == 200


def test_validation_does_not_echo_or_log_passwords(security_client, caplog):
    secret = 'synthetic-password-do-not-log'
    response = security_client.post('/auth/login', json={'password': secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert 'input' not in response.json()['detail'][0]
    assert secret not in caplog.text
    assert all(secret not in str(getattr(record, 'validation_errors', '')) for record in caplog.records)


def test_totp_is_encrypted_and_codes_cannot_be_replayed(security_client, db):
    session, _ = register(security_client)
    setup = security_client.post('/auth/2fa/setup', headers=bearer(session)).json()
    stored = sql(db, 'SELECT totp_secret FROM users WHERE user_id = %s', (session['user']['id'],))[0][0]
    assert stored.startswith('fernet:') and stored != setup['secret']
    assert decrypt_secret(stored) == setup['secret']
    code = pyotp.TOTP(setup['secret']).now()
    assert security_client.post('/auth/2fa/verify', headers=bearer(session), json={'code': code}).status_code == 200
    assert not totp.verify_login_code(UUID(session['user']['id']), code, 1)
    # Future valid window is a fresh step, then consumed globally.
    future_code = pyotp.TOTP(setup['secret']).at(datetime.now(timezone.utc) + timedelta(seconds=30))
    challenge = security_client.post('/auth/login', json={'email': session['user']['email'], 'password': PASSWORD}).json()
    response = security_client.post('/auth/2fa/login', json={'challengeToken': challenge['challengeToken'], 'code': future_code})
    assert response.status_code == 200, response.text
    assert security_client.post('/auth/2fa/login', json={'challengeToken': challenge['challengeToken'], 'code': future_code}).status_code == 401


def test_password_change_invalidates_pending_two_factor_challenge(security_client, db):
    session, _ = register(security_client)
    user_id = UUID(session['user']['id'])
    secret, _ = totp.start_enrollment(user_id, session['user']['email'])
    totp.confirm_enrollment(user_id, pyotp.TOTP(secret).now())
    challenge = create_two_factor_challenge_token(str(user_id), 1)
    users.change_password(user_id, PASSWORD, NEW_PASSWORD)
    code = pyotp.TOTP(secret).at(datetime.now(timezone.utc) + timedelta(seconds=30))
    assert security_client.post('/auth/2fa/login', json={'challengeToken': challenge, 'code': code}).status_code == 401


class FakeRedis:
    def __init__(self):
        self.count = 0
    def eval(self, script, key_count, key, window):
        self.count += 1
        return self.count, window


@pytest.mark.parametrize('path,payload', [
    ('/auth/password', {'currentPassword': 'wrong', 'newPassword': NEW_PASSWORD}),
    ('/auth/2fa/disable', {'password': 'wrong'}),
    ('/auth/2fa/verify', {'code': '000000'}),
])
def test_sensitive_actions_are_throttled(security_client, monkeypatch, path, payload):
    from app.core import rate_limit
    session, _ = register(security_client)
    fake = FakeRedis()
    monkeypatch.setattr(settings, 'rate_limit_enabled', True)
    monkeypatch.setattr(settings, 'sensitive_max_attempts', 2)
    monkeypatch.setattr(rate_limit, '_redis', lambda: fake)
    for _ in range(2):
        assert security_client.post(path, headers=bearer(session), json=payload).status_code in (400, 401)
    response = security_client.post(path, headers=bearer(session), json=payload)
    assert response.status_code == 429 and 'retry-after' in response.headers


def test_sensitive_actions_fail_closed_without_redis(security_client, monkeypatch):
    from app.core import rate_limit
    session, _ = register(security_client)
    monkeypatch.setattr(settings, 'rate_limit_enabled', True)
    def unavailable():
        raise ConnectionError()
    monkeypatch.setattr(rate_limit, '_redis', unavailable)
    response = security_client.post('/auth/password', headers=bearer(session), json={
        'currentPassword': PASSWORD, 'newPassword': NEW_PASSWORD})
    assert response.status_code == 503
    assert security_client.get('/auth/me', headers=bearer(session)).status_code == 200


def test_legacy_access_token_is_rejected(security_client):
    session, _ = register(security_client)
    legacy = jwt.encode({'sub': session['user']['id'], 'exp': datetime.now(timezone.utc) + timedelta(minutes=15), 'type': 'access'}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert security_client.get('/auth/me', headers={'Authorization': 'Bearer ' + legacy}).status_code == 401


def test_migration_encrypts_existing_secrets_and_revokes_existing_tokens(auth_schema):
    _, engine, migration = auth_schema
    from sqlalchemy import text
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
        connection.execute(text("TRUNCATE users, companies CASCADE"))
        user_id = str(uuid4())
        connection.execute(text("INSERT INTO users(user_id,email,password_hash,totp_secret) VALUES (:id,'legacy@example.com','hash','BASE32SECRET')"), {'id': user_id})
        connection.execute(text("INSERT INTO refresh_tokens(user_id,token_hash,expires_at) VALUES (:id,:hash,NOW() + INTERVAL '30 days')"), {'id': user_id, 'hash': 'a' * 64})
        migration.upgrade()
        stored = connection.execute(text("SELECT totp_secret FROM users WHERE user_id = :id"), {'id': user_id}).scalar_one()
        assert decrypt_secret(stored) == 'BASE32SECRET'
        assert connection.execute(text("SELECT revoked_at IS NOT NULL FROM refresh_tokens")).scalar_one()


@pytest.mark.parametrize('overrides', [
    {'JWT_SECRET': 'dev-insecure-change-me'},
    {'JWT_SECRET': 'change-me-to-a-long-random-string'},
    {'COOKIE_SECURE': False}, {'TOTP_ENCRYPTION_KEY': ''}, {'CORS_ORIGINS': '*'},
])
def test_production_rejects_insecure_auth_configuration(overrides):
    config = {'ENVIRONMENT': 'production', 'JWT_SECRET': 'a' * 64,
              'COOKIE_SECURE': True, 'TOTP_ENCRYPTION_KEY': Fernet.generate_key().decode(),
              'CORS_ORIGINS': 'https://app.example.com'}
    config.update(overrides)
    with pytest.raises(ValueError):
        Settings(_env_file=None, **config)


def test_production_accepts_secure_auth_configuration():
    Settings(_env_file=None, ENVIRONMENT='production', JWT_SECRET='a' * 64,
             COOKIE_SECURE=True, TOTP_ENCRYPTION_KEY=Fernet.generate_key().decode(),
             CORS_ORIGINS='https://app.example.com')


def test_admin_deactivation_is_immediate_and_self_deactivation_is_rejected(security_client, db):
    admin, _ = register(security_client)
    target, raw = register(security_client)
    sql(db, "UPDATE users SET role = 'admin' WHERE user_id = %s", (admin['user']['id'],))
    assert security_client.patch('/auth/users/' + admin['user']['id'] + '/active',
        headers=bearer(admin), json={'isActive': False}).status_code == 400
    response = security_client.patch('/auth/users/' + target['user']['id'] + '/active',
        headers=bearer(admin), json={'isActive': False})
    assert response.status_code == 200
    assert security_client.get('/auth/me', headers=bearer(target)).status_code == 401
    with pytest.raises(tokens.InvalidRefreshTokenError):
        tokens.rotate(raw)
    assert security_client.patch('/auth/users/not-a-uuid/active', headers=bearer(admin),
        json={'isActive': False}).status_code == 422
