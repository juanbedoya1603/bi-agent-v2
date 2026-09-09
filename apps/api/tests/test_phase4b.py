from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

from bi_agent_api.auth import (
    AuthStore,
    get_auth_store,
    user_sessions,
    users,
    verify_password,
)
from bi_agent_api.config import Settings
from bi_agent_api.conversations import (
    ConversationStore,
    audit_turns,
    conversations,
    get_conversation_store,
)
from bi_agent_api.main import app


def stores(tmp_path: Path) -> tuple[ConversationStore, AuthStore]:
    conversations_store = ConversationStore(
        tmp_path / "app.sqlite3", tmp_path / "sessions.sqlite3"
    )
    auth_store = AuthStore(conversations_store.engine)
    app.dependency_overrides[get_conversation_store] = lambda: conversations_store
    app.dependency_overrides[get_auth_store] = lambda: auth_store
    return conversations_store, auth_store


def login(client: TestClient, username: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def test_argon2_login_cookie_logout_and_no_plaintext(tmp_path: Path) -> None:
    conversation_store, auth = stores(tmp_path)
    user = auth.create_user(
        "  JUAN  ", "Juan", "secret-pass-123", must_change_password=False
    )
    with conversation_store.engine.connect() as connection:
        row = connection.execute(select(users).where(users.c.user_id == user.user_id)).one()
    assert row.username == "juan"
    assert row.password_hash.startswith("$argon2id$")
    assert "secret-pass-123" not in row.password_hash
    assert verify_password(row.password_hash, "secret-pass-123")

    try:
        with TestClient(app) as client:
            response = login(client, " JUAN ", "secret-pass-123")
            assert response.status_code == 200
            assert "bi_agent_session=" in response.headers["set-cookie"]
            assert "HttpOnly" in response.headers["set-cookie"]
            assert "SameSite=lax" in response.headers["set-cookie"]
            token = client.cookies["bi_agent_session"]
            with conversation_store.engine.connect() as connection:
                session = connection.execute(select(user_sessions)).one()
            assert token not in session.session_token_hash
            assert len(session.session_token_hash) == 64
            assert client.get("/api/v1/auth/me").status_code == 200
            assert client.post("/api/v1/auth/logout").status_code == 204
            assert client.get("/api/v1/auth/me").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_production_cookie_is_secure(tmp_path: Path, monkeypatch: Any) -> None:
    _, auth = stores(tmp_path)
    auth.create_user("secure", "Secure", "secure-password", must_change_password=False)
    monkeypatch.setattr(
        "bi_agent_api.main.get_settings",
        lambda: Settings(_env_file=None, app_env="production"),
    )
    try:
        with TestClient(app) as client:
            response = login(client, "secure", "secure-password")
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
    finally:
        app.dependency_overrides.clear()


def test_lockout_expiry_inactive_and_must_change_password(tmp_path: Path) -> None:
    conversation_store, auth = stores(tmp_path)
    user = auth.create_user("juan", "Juan", "temporary-123")
    try:
        with TestClient(app) as client:
            for _ in range(5):
                assert login(client, "juan", "wrong-password").status_code == 401
            assert login(client, "juan", "temporary-123").status_code == 401
            with conversation_store.engine.begin() as connection:
                connection.execute(
                    update(users)
                    .where(users.c.user_id == user.user_id)
                    .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
                )
            assert login(client, "juan", "temporary-123").status_code == 200
            blocked = client.post("/api/v1/conversations")
            assert blocked.status_code == 403
            changed = client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "temporary-123",
                    "new_password": "permanent-123",
                },
            )
            assert changed.status_code == 200
            assert changed.json()["must_change_password"] is False
            assert client.post("/api/v1/conversations").status_code == 201

            with conversation_store.engine.begin() as connection:
                connection.execute(
                    update(user_sessions).values(
                        expires_at=datetime.now(UTC) - timedelta(seconds=1)
                    )
                )
            assert client.get("/api/v1/auth/me").status_code == 401
            auth.set_active(user.user_id, False)
            assert login(client, "juan", "permanent-123").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_bootstrap_is_idempotent_and_assigns_legacy_rows(tmp_path: Path) -> None:
    conversation_store, auth = stores(tmp_path)
    timestamp = datetime.now(UTC)
    with conversation_store.engine.begin() as connection:
        connection.execute(
            insert(conversations).values(
                conversation_id="legacy",
                user_id=None,
                title="Legacy",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        connection.execute(
            insert(audit_turns).values(
                conversation_id="legacy",
                user_id=None,
                timestamp=timestamp,
                duration_ms=1,
                sql_attempt_count=0,
                success=True,
                error=None,
            )
        )
    settings = Settings(
        _env_file=None,
        bootstrap_admin_username=" ADMIN ",
        bootstrap_admin_password="bootstrap-123",
        bootstrap_admin_display_name="Administrador",
    )
    admin = auth.bootstrap_admin(settings)
    assert admin and admin.is_admin and admin.username == "admin"
    assert admin.must_change_password is True
    assert auth.bootstrap_admin(settings) is None
    with conversation_store.engine.connect() as connection:
        assert connection.scalar(select(conversations.c.user_id)) == admin.user_id
        assert connection.scalar(select(audit_turns.c.user_id)) == admin.user_id
        assert len(connection.execute(select(users)).fetchall()) == 1
    app.dependency_overrides.clear()


def test_admin_crud_role_checks_revocation_and_last_admin(tmp_path: Path) -> None:
    conversation_store, auth = stores(tmp_path)
    admin = auth.create_user(
        "admin", "Admin", "admin-password", is_admin=True, must_change_password=False
    )
    auth.create_user("member", "Member", "member-password", must_change_password=False)
    try:
        with TestClient(app) as client:
            login(client, "member", "member-password")
            assert client.get("/api/v1/admin/users").status_code == 403
            login(client, "admin", "admin-password")
            created = client.post(
                "/api/v1/admin/users",
                json={
                    "username": " NEWUSER ",
                    "display_name": "New User",
                    "temporary_password": "temporary-456",
                    "is_admin": False,
                },
            )
            assert created.status_code == 201
            user_id = created.json()["user_id"]
            edited = client.patch(
                f"/api/v1/admin/users/{user_id}",
                json={"username": "renamed", "display_name": "Renamed User"},
            )
            assert edited.json()["username"] == "renamed"

            member_client = TestClient(app)
            login(member_client, "renamed", "temporary-456")
            assert member_client.get("/api/v1/auth/me").status_code == 200
            reset = client.post(
                f"/api/v1/admin/users/{user_id}/reset-password",
                json={"temporary_password": "replacement-456"},
            )
            assert reset.json()["must_change_password"] is True
            assert member_client.get("/api/v1/auth/me").status_code == 401
            login(member_client, "renamed", "replacement-456")
            assert client.post(f"/api/v1/admin/users/{user_id}/deactivate").status_code == 200
            assert member_client.get("/api/v1/auth/me").status_code == 401
            activated = client.post(f"/api/v1/admin/users/{user_id}/activate")
            assert activated.status_code == 200
            assert activated.json()["is_active"] is True
            assert client.post(
                f"/api/v1/admin/users/{admin.user_id}/deactivate"
            ).status_code == 409
            member_client.close()
    finally:
        app.dependency_overrides.clear()


def test_all_conversation_endpoints_are_isolated_and_audit_has_owner(
    tmp_path: Path,
) -> None:
    conversation_store, auth = stores(tmp_path)
    first = auth.create_user("first", "First", "first-password", must_change_password=False)
    auth.create_user("second", "Second", "second-password", must_change_password=False)
    try:
        with TestClient(app) as first_client, TestClient(app) as second_client:
            login(first_client, "first", "first-password")
            login(second_client, "second", "second-password")
            created = first_client.post("/api/v1/conversations")
            conversation_id = created.json()["conversation_id"]
            assert second_client.get("/api/v1/conversations").json() == []
            assert second_client.get(
                f"/api/v1/conversations/{conversation_id}/messages"
            ).status_code == 404
            assert second_client.patch(
                f"/api/v1/conversations/{conversation_id}", json={"title": "Intrusión"}
            ).status_code == 404
            assert second_client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={"message": "No permitido"},
            ).status_code == 404
            assert second_client.delete(
                f"/api/v1/conversations/{conversation_id}"
            ).status_code == 404

            conversation_store.add_turn(
                conversation_id,
                first.user_id,
                "Pregunta",
                "Respuesta",
                None,
                duration_ms=1,
                sql_history=[],
                sql_durations_ms=[],
            )
            with conversation_store.engine.connect() as connection:
                audit = connection.execute(select(audit_turns)).one()
            assert audit.user_id == first.user_id
    finally:
        app.dependency_overrides.clear()


def test_only_health_and_login_are_public(tmp_path: Path) -> None:
    stores(tmp_path)
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code in {200, 503}
            assert login(client, "missing", "not-a-password").status_code == 401
            assert client.get("/api/v1/auth/me").status_code == 401
            assert client.post("/api/v1/auth/logout").status_code == 401
            assert client.post("/api/v1/chat", json={"message": "Ventas"}).status_code == 401
            assert client.post("/api/v1/exports/excel", json={}).status_code == 401
            assert client.get("/api/v1/conversations").status_code == 401
            assert client.get("/api/v1/admin/users").status_code == 401
    finally:
        app.dependency_overrides.clear()
