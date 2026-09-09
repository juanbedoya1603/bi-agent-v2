import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Unicode,
    func,
    insert,
    select,
    true,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .conversations import (
    APP_DB_SCHEMA,
    audit_turns,
    conversations,
    get_conversation_store,
    identity_type,
    metadata,
)

SESSION_DAYS = 7
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
password_hasher = PasswordHasher()
DUMMY_PASSWORD_HASH = password_hasher.hash("invalid-password-placeholder")

users = Table(
    "app_users",
    metadata,
    Column("user_id", identity_type, primary_key=True, autoincrement=True),
    Column("username", Unicode(100), nullable=False),
    Column("username_normalized", Unicode(100), nullable=False, unique=True),
    Column("display_name", Unicode(200), nullable=False),
    Column("password_hash", Unicode(512), nullable=False),
    Column("is_admin", Boolean, nullable=False),
    Column("is_active", Boolean, nullable=False),
    Column("must_change_password", Boolean, nullable=False),
    Column("failed_login_attempts", Integer, nullable=False),
    Column("locked_until", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_login_at", DateTime(timezone=True)),
    schema=APP_DB_SCHEMA,
)

user_sessions = Table(
    "app_user_sessions",
    metadata,
    Column("session_id", identity_type, primary_key=True, autoincrement=True),
    Column(
        "user_id",
        identity_type,
        ForeignKey(f"{APP_DB_SCHEMA}.app_users.user_id"),
        nullable=False,
    ),
    Column("session_token_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Index("ix_app_user_sessions_user", "user_id", "expires_at"),
    schema=APP_DB_SCHEMA,
)


class AuthError(ValueError):
    pass


class DuplicateUsernameError(ValueError):
    pass


class LastAdminError(ValueError):
    pass


class UserNotFoundError(LookupError):
    pass


class User(BaseModel):
    user_id: int
    username: str
    display_name: str
    is_admin: bool
    is_active: bool
    must_change_password: bool


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_password(password: str) -> None:
    if len(password) < 10:
        raise ValueError("La contraseña debe tener al menos 10 caracteres.")


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _active_session_user_query(token_hash: str, timestamp: datetime) -> Any:
    return (
        select(users)
        .join(user_sessions, user_sessions.c.user_id == users.c.user_id)
        .where(
            user_sessions.c.session_token_hash == token_hash,
            user_sessions.c.revoked_at.is_(None),
            user_sessions.c.expires_at > timestamp,
            users.c.is_active == true(),
        )
    )


def _active_admin_count_query() -> Any:
    return (
        select(func.count())
        .select_from(users)
        .where(users.c.is_admin == true(), users.c.is_active == true())
    )


class AuthStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _user(row: Any) -> User:
        return User(
            user_id=row.user_id,
            username=row.username,
            display_name=row.display_name,
            is_admin=bool(row.is_admin),
            is_active=bool(row.is_active),
            must_change_password=bool(row.must_change_password),
        )

    def create_user(
        self,
        username: str,
        display_name: str,
        password: str,
        *,
        is_admin: bool = False,
        must_change_password: bool = True,
    ) -> User:
        normalized = normalize_username(username)
        display = display_name.strip()
        if not normalized or not display:
            raise ValueError("Username y nombre son obligatorios.")
        timestamp = _now()
        try:
            with self.engine.begin() as connection:
                user_id = connection.execute(
                    insert(users).values(
                        username=normalized,
                        username_normalized=normalized,
                        display_name=display,
                        password_hash=hash_password(password),
                        is_admin=is_admin,
                        is_active=True,
                        must_change_password=must_change_password,
                        failed_login_attempts=0,
                        locked_until=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                        last_login_at=None,
                    )
                ).inserted_primary_key[0]
        except IntegrityError as error:
            raise DuplicateUsernameError("El username ya existe.") from error
        return self.get_user(user_id)

    def list_users(self) -> list[User]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(users).order_by(users.c.username)).fetchall()
        return [self._user(row) for row in rows]

    def get_user(self, user_id: int) -> User:
        with self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.user_id == user_id)).first()
        if row is None:
            raise UserNotFoundError(user_id)
        return self._user(row)

    def authenticate(self, username: str, password: str) -> User:
        normalized = normalize_username(username)
        timestamp = _now()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(users).where(users.c.username_normalized == normalized)
            ).first()
            if row is None:
                # Keep unknown usernames on the same expensive verification path.
                verify_password(DUMMY_PASSWORD_HASH, password)
                raise AuthError("Credenciales incorrectas.")
            if not row.is_active:
                raise AuthError("Credenciales incorrectas.")
            if row.locked_until and _aware(row.locked_until) > timestamp:
                raise AuthError("Credenciales incorrectas.")
            password_is_valid = verify_password(row.password_hash, password)
            if not password_is_valid:
                attempts = row.failed_login_attempts + 1
                locked_until = (
                    timestamp + timedelta(minutes=LOCK_MINUTES)
                    if attempts >= MAX_FAILED_LOGINS
                    else None
                )
                connection.execute(
                    update(users)
                    .where(users.c.user_id == row.user_id)
                    .values(
                        failed_login_attempts=attempts,
                        locked_until=locked_until,
                        updated_at=timestamp,
                    )
                )
            else:
                connection.execute(
                    update(users)
                    .where(users.c.user_id == row.user_id)
                    .values(
                        failed_login_attempts=0,
                        locked_until=None,
                        updated_at=timestamp,
                        last_login_at=timestamp,
                    )
                )
        if not password_is_valid:
            raise AuthError("Credenciales incorrectas.")
        return self.get_user(row.user_id)

    def create_session(self, user_id: int) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(48)
        timestamp = _now()
        expires_at = timestamp + timedelta(days=SESSION_DAYS)
        with self.engine.begin() as connection:
            connection.execute(
                insert(user_sessions).values(
                    user_id=user_id,
                    session_token_hash=_token_hash(token),
                    created_at=timestamp,
                    expires_at=expires_at,
                    last_seen_at=timestamp,
                    revoked_at=None,
                )
            )
        return token, expires_at

    def user_for_session(self, token: str | None) -> User | None:
        if not token:
            return None
        timestamp = _now()
        with self.engine.begin() as connection:
            row = connection.execute(
                _active_session_user_query(_token_hash(token), timestamp)
            ).first()
            if row:
                connection.execute(
                    update(user_sessions)
                    .where(user_sessions.c.session_token_hash == _token_hash(token))
                    .values(last_seen_at=timestamp)
                )
        return self._user(row) if row else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self.engine.begin() as connection:
            connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.session_token_hash == _token_hash(token),
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )

    def revoke_user_sessions(self, user_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.user_id == user_id,
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )

    def change_password(self, user_id: int, current_password: str, new_password: str) -> User:
        with self.engine.begin() as connection:
            row = connection.execute(select(users).where(users.c.user_id == user_id)).one()
            if not verify_password(row.password_hash, current_password):
                raise AuthError("La contraseña actual es incorrecta.")
            connection.execute(
                update(users)
                .where(users.c.user_id == user_id)
                .values(
                    password_hash=hash_password(new_password),
                    must_change_password=False,
                    failed_login_attempts=0,
                    locked_until=None,
                    updated_at=_now(),
                )
            )
        return self.get_user(user_id)

    def edit_user(self, user_id: int, username: str, display_name: str) -> User:
        normalized = normalize_username(username)
        display = display_name.strip()
        if not normalized or not display:
            raise ValueError("Username y nombre son obligatorios.")
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(users)
                    .where(users.c.user_id == user_id)
                    .values(
                        username=normalized,
                        username_normalized=normalized,
                        display_name=display,
                        updated_at=_now(),
                    )
                )
                if result.rowcount == 0:
                    raise UserNotFoundError(user_id)
        except IntegrityError as error:
            raise DuplicateUsernameError("El username ya existe.") from error
        return self.get_user(user_id)

    def set_active(self, user_id: int, active: bool) -> User:
        with self.engine.begin() as connection:
            row = connection.execute(select(users).where(users.c.user_id == user_id)).first()
            if row is None:
                raise UserNotFoundError(user_id)
            if not active and row.is_admin and row.is_active:
                active_admins = connection.scalar(_active_admin_count_query())
                if active_admins <= 1:
                    raise LastAdminError("Debe existir al menos un administrador activo.")
            connection.execute(
                update(users)
                .where(users.c.user_id == user_id)
                .values(is_active=active, updated_at=_now())
            )
            if not active:
                connection.execute(
                    update(user_sessions)
                    .where(
                        user_sessions.c.user_id == user_id,
                        user_sessions.c.revoked_at.is_(None),
                    )
                    .values(revoked_at=_now())
                )
        return self.get_user(user_id)

    def reset_password(self, user_id: int, temporary_password: str) -> User:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(users)
                .where(users.c.user_id == user_id)
                .values(
                    password_hash=hash_password(temporary_password),
                    must_change_password=True,
                    failed_login_attempts=0,
                    locked_until=None,
                    updated_at=_now(),
                )
            )
            if result.rowcount == 0:
                raise UserNotFoundError(user_id)
            connection.execute(
                update(user_sessions)
                .where(
                    user_sessions.c.user_id == user_id,
                    user_sessions.c.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )
        return self.get_user(user_id)

    def bootstrap_admin(self, settings: Settings) -> User | None:
        configured = (
            settings.bootstrap_admin_username,
            settings.bootstrap_admin_password,
            settings.bootstrap_admin_display_name,
        )
        if not all(configured):
            return None
        normalized = normalize_username(settings.bootstrap_admin_username)
        display_name = settings.bootstrap_admin_display_name.strip()
        if not normalized or not display_name:
            return None
        timestamp = _now()
        try:
            with self.engine.begin() as connection:
                if connection.scalar(select(func.count()).select_from(users)):
                    return None
                user_id = connection.execute(
                    insert(users).values(
                        username=normalized,
                        username_normalized=normalized,
                        display_name=display_name,
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        is_admin=True,
                        is_active=True,
                        must_change_password=True,
                        failed_login_attempts=0,
                        locked_until=None,
                        created_at=timestamp,
                        updated_at=timestamp,
                        last_login_at=None,
                    )
                ).inserted_primary_key[0]
                connection.execute(
                    update(conversations)
                    .where(conversations.c.user_id.is_(None))
                    .values(user_id=user_id)
                )
                connection.execute(
                    update(audit_turns)
                    .where(audit_turns.c.user_id.is_(None))
                    .values(user_id=user_id)
                )
        except IntegrityError:
            # Another application worker completed the same one-time bootstrap.
            return None
        return self.get_user(user_id)


@lru_cache
def get_auth_store() -> AuthStore:
    return AuthStore(get_conversation_store().engine)
