"""Issue real revocable sessions for tenant fixtures."""
from app.core.security import create_access_token as _create_access_token
from app.services import refresh_token_service


def create_access_token(user_id):
    raw = refresh_token_service.issue(user_id)
    session = refresh_token_service.session_for_token(raw)
    return _create_access_token(str(user_id), session_id=str(session["session_id"]),
                                session_expires_at=session["session_expires_at"])
