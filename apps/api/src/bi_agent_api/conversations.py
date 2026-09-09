import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus
from uuid import uuid4

from agents import SQLiteSession
from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Unicode,
    UnicodeText,
    create_engine,
    delete,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

from .config import get_settings
from .usage import AgentUsage, estimate_cost_usd


class ConversationNotFoundError(LookupError):
    pass


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str


class ConversationMessage(BaseModel):
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    data: dict[str, Any] | None = None
    created_at: str
    metadata: "MessageMetadata | None" = None


class MessageMetadata(BaseModel):
    duration_ms: float
    model_name: str | None = None
    llm_requests: int | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: Decimal | None = None


metadata = MetaData()
identity_type = BigInteger().with_variant(Integer, "sqlite")
APP_DB_SCHEMA = "biAgent"

conversations = Table(
    "app_conversations",
    metadata,
    Column("conversation_id", String(36), primary_key=True),
    Column(
        "user_id",
        identity_type,
        ForeignKey(f"{APP_DB_SCHEMA}.app_users.user_id"),
        nullable=True,
        index=True,
    ),
    Column("title", Unicode(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    schema=APP_DB_SCHEMA,
)

messages = Table(
    "app_messages",
    metadata,
    Column("message_id", identity_type, primary_key=True, autoincrement=True),
    Column(
        "conversation_id",
        String(36),
        ForeignKey(f"{APP_DB_SCHEMA}.app_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("role", String(16), nullable=False),
    Column("content", UnicodeText, nullable=False),
    Column("data_json", UnicodeText),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_app_messages_conversation", "conversation_id", "message_id"),
    CheckConstraint("role IN ('user', 'assistant')", name="ck_app_messages_role"),
    schema=APP_DB_SCHEMA,
)

audit_turns = Table(
    "app_audit_turns",
    metadata,
    Column("audit_id", identity_type, primary_key=True, autoincrement=True),
    Column(
        "user_id",
        identity_type,
        ForeignKey(f"{APP_DB_SCHEMA}.app_users.user_id"),
        nullable=True,
        index=True,
    ),
    Column(
        "conversation_id",
        String(36),
        ForeignKey(f"{APP_DB_SCHEMA}.app_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("sql_attempt_count", Integer, nullable=False),
    Column("success", Boolean, nullable=False),
    Column("error", Unicode(200)),
    Column(
        "assistant_message_id",
        identity_type,
        ForeignKey(f"{APP_DB_SCHEMA}.app_messages.message_id"),
        nullable=True,
    ),
    Column("model_name", Unicode(100)),
    Column("llm_requests", Integer),
    Column("input_tokens", BigInteger),
    Column("cached_input_tokens", BigInteger),
    Column("output_tokens", BigInteger),
    Column("reasoning_tokens", BigInteger),
    Column("total_tokens", BigInteger),
    Column("estimated_cost_usd", Numeric(19, 8)),
    Index("ix_app_audit_turns_conversation", "conversation_id", "timestamp"),
    CheckConstraint(
        "(llm_requests IS NULL OR llm_requests >= 0)"
        " AND (input_tokens IS NULL OR input_tokens >= 0)"
        " AND (cached_input_tokens IS NULL OR cached_input_tokens >= 0)"
        " AND (output_tokens IS NULL OR output_tokens >= 0)"
        " AND (reasoning_tokens IS NULL OR reasoning_tokens >= 0)"
        " AND (total_tokens IS NULL OR total_tokens >= 0)"
        " AND (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)",
        name="CK_app_audit_turns_usage_nonnegative",
    ),
    schema=APP_DB_SCHEMA,
)

Index(
    "UX_app_audit_turns_assistant_message",
    audit_turns.c.assistant_message_id,
    unique=True,
    sqlite_where=audit_turns.c.assistant_message_id.is_not(None),
    mssql_where=audit_turns.c.assistant_message_id.is_not(None),
)

audit_sql_attempts = Table(
    "app_audit_sql_attempts",
    metadata,
    Column("attempt_id", identity_type, primary_key=True, autoincrement=True),
    Column(
        "audit_id",
        identity_type,
        ForeignKey(f"{APP_DB_SCHEMA}.app_audit_turns.audit_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("attempt_number", Integer, nullable=False),
    Column("sql_text", UnicodeText, nullable=False),
    Column("guard_passed", Boolean, nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("row_count", Integer),
    Column("truncated", Boolean),
    Column("success", Boolean, nullable=False),
    Column("error", Unicode(1000)),
    Index("ix_app_audit_sql_attempts_audit", "audit_id", "attempt_number"),
    schema=APP_DB_SCHEMA,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class ConversationStore:
    """Historial visible y auditoría en la App DB; Sessions permanecen en SQLite."""

    def __init__(
        self,
        database: Engine | str | Path,
        session_db_path: str | Path | None = None,
        *,
        initialize: bool = True,
    ):
        if isinstance(database, Engine):
            self.engine = database
        elif isinstance(database, Path):
            self.engine = create_engine(f"sqlite:///{database}")
            session_db_path = session_db_path or database
        elif database.startswith("sqlite:"):
            self.engine = create_engine(database)
        else:
            odbc_connect = quote_plus(database)
            self.engine = create_engine(f"mssql+pyodbc:///?odbc_connect={odbc_connect}")

        if self.engine.dialect.name == "sqlite":
            self.engine = self.engine.execution_options(
                schema_translate_map={APP_DB_SCHEMA: None}
            )

        self.session_db_path = Path(session_db_path or "tmp/bi_agent_sessions.sqlite3")
        self.session_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        if initialize:
            # Import registers the auth tables in this shared metadata.
            from . import auth as _auth  # noqa: F401

            metadata.create_all(self.engine)

    @staticmethod
    def _summary(row: Any) -> ConversationSummary:
        return ConversationSummary(
            conversation_id=row.conversation_id,
            title=row.title,
            created_at=_isoformat(row.created_at),
            updated_at=_isoformat(row.updated_at),
        )

    def create_conversation(self, user_id: int) -> ConversationSummary:
        conversation_id = str(uuid4())
        timestamp = _now()
        with self.engine.begin() as connection:
            connection.execute(
                insert(conversations).values(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    title="Nueva conversación",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return ConversationSummary(
            conversation_id=conversation_id,
            title="Nueva conversación",
            created_at=timestamp.isoformat(),
            updated_at=timestamp.isoformat(),
        )

    def list_conversations(
        self, user_id: int, search: str | None = None
    ) -> list[ConversationSummary]:
        statement = select(conversations).where(conversations.c.user_id == user_id)
        if search and (term := search.strip()):
            statement = statement.where(func.lower(conversations.c.title).contains(term.lower()))
        statement = statement.order_by(conversations.c.updated_at.desc())
        with self.engine.connect() as connection:
            rows = connection.execute(statement).fetchall()
        return [self._summary(row) for row in rows]

    def get_conversation(self, conversation_id: str, user_id: int) -> ConversationSummary:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(conversations).where(
                    conversations.c.conversation_id == conversation_id,
                    conversations.c.user_id == user_id,
                )
            ).first()
        if row is None:
            raise ConversationNotFoundError(conversation_id)
        return self._summary(row)

    def get_messages(self, conversation_id: str, user_id: int) -> list[ConversationMessage]:
        self.get_conversation(conversation_id, user_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    messages,
                    audit_turns.c.assistant_message_id.label("audit_assistant_message_id"),
                    audit_turns.c.duration_ms.label("audit_duration_ms"),
                    audit_turns.c.model_name,
                    audit_turns.c.llm_requests,
                    audit_turns.c.input_tokens,
                    audit_turns.c.cached_input_tokens,
                    audit_turns.c.output_tokens,
                    audit_turns.c.reasoning_tokens,
                    audit_turns.c.total_tokens,
                    audit_turns.c.estimated_cost_usd,
                )
                .outerjoin(
                    audit_turns,
                    audit_turns.c.assistant_message_id == messages.c.message_id,
                )
                .where(messages.c.conversation_id == conversation_id)
                .order_by(messages.c.message_id)
            ).fetchall()
        return [self._message(row) for row in rows]

    @staticmethod
    def _message(row: Any) -> ConversationMessage:
        message_metadata = None
        if getattr(row, "audit_assistant_message_id", None) is not None:
            message_metadata = MessageMetadata(
                duration_ms=row.audit_duration_ms,
                model_name=row.model_name,
                llm_requests=row.llm_requests,
                input_tokens=row.input_tokens,
                cached_input_tokens=row.cached_input_tokens,
                output_tokens=row.output_tokens,
                reasoning_tokens=row.reasoning_tokens,
                total_tokens=row.total_tokens,
                estimated_cost_usd=row.estimated_cost_usd,
            )
        return ConversationMessage(
            message_id=row.message_id,
            role=row.role,
            content=row.content,
            data=json.loads(row.data_json) if row.data_json else None,
            created_at=_isoformat(row.created_at),
            metadata=message_metadata,
        )

    def rename_conversation(
        self, conversation_id: str, user_id: int, title: str
    ) -> ConversationSummary:
        timestamp = _now()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(conversations)
                .where(
                    conversations.c.conversation_id == conversation_id,
                    conversations.c.user_id == user_id,
                )
                .values(title=title, updated_at=timestamp)
            )
            if result.rowcount == 0:
                raise ConversationNotFoundError(conversation_id)
        return self.get_conversation(conversation_id, user_id)

    def delete_conversation(self, conversation_id: str, user_id: int) -> None:
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(conversations.c.conversation_id).where(
                    conversations.c.conversation_id == conversation_id,
                    conversations.c.user_id == user_id,
                )
            ).first()
            if exists is None:
                raise ConversationNotFoundError(conversation_id)
            audit_ids = select(audit_turns.c.audit_id).where(
                audit_turns.c.conversation_id == conversation_id
            )
            connection.execute(delete(audit_sql_attempts).where(
                audit_sql_attempts.c.audit_id.in_(audit_ids)
            ))
            connection.execute(
                delete(audit_turns).where(audit_turns.c.conversation_id == conversation_id)
            )
            connection.execute(
                delete(messages).where(messages.c.conversation_id == conversation_id)
            )
            connection.execute(
                delete(conversations).where(conversations.c.conversation_id == conversation_id)
            )
        self._conversation_locks.pop(conversation_id, None)

    async def delete_conversation_with_session(
        self, conversation_id: str, user_id: int
    ) -> None:
        self.delete_conversation(conversation_id, user_id)
        session = SQLiteSession(conversation_id, self.session_db_path)
        try:
            await session.clear_session()
        finally:
            session.close()

    def check_app_db(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()

    def add_turn(
        self,
        conversation_id: str,
        user_id: int,
        user_content: str,
        assistant_content: str,
        data: dict[str, Any] | None,
        *,
        duration_ms: float,
        sql_history: Iterable[dict[str, Any]],
        sql_durations_ms: Iterable[float],
        audit_success: bool = True,
        audit_error: str | None = None,
        model_name: str | None = None,
        usage: AgentUsage | None = None,
    ) -> tuple[ConversationMessage, ConversationMessage]:
        timestamp = _now()
        attempts = list(sql_history)
        durations = list(sql_durations_ms)
        with self.engine.begin() as connection:
            conversation = connection.execute(
                select(conversations).where(
                    conversations.c.conversation_id == conversation_id,
                    conversations.c.user_id == user_id,
                )
            ).first()
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            title = conversation.title
            if title == "Nueva conversación":
                title = " ".join(user_content.split())[:64] or title
            user_message_id = connection.execute(
                insert(messages).values(
                    conversation_id=conversation_id,
                    role="user",
                    content=user_content,
                    data_json=None,
                    created_at=timestamp,
                )
            ).inserted_primary_key[0]
            assistant_id = connection.execute(
                insert(messages).values(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_content,
                    data_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
                    created_at=timestamp,
                )
            ).inserted_primary_key[0]
            connection.execute(
                update(conversations)
                .where(conversations.c.conversation_id == conversation_id)
                .values(title=title, updated_at=timestamp)
            )
            self._insert_audit(
                connection,
                conversation_id,
                user_id,
                timestamp,
                duration_ms,
                attempts,
                durations,
                assistant_message_id=assistant_id,
                model_name=model_name,
                usage=usage,
                success=audit_success,
                error=audit_error[:200] if audit_error else None,
            )
        return (
            ConversationMessage(
                message_id=user_message_id,
                role="user",
                content=user_content,
                created_at=timestamp.isoformat(),
            ),
            ConversationMessage(
                message_id=assistant_id,
                role="assistant",
                content=assistant_content,
                data=data,
                created_at=timestamp.isoformat(),
                metadata=MessageMetadata(
                    duration_ms=duration_ms,
                    model_name=model_name,
                    llm_requests=usage.requests if usage else None,
                    input_tokens=usage.input_tokens if usage else None,
                    cached_input_tokens=usage.cached_input_tokens if usage else None,
                    output_tokens=usage.output_tokens if usage else None,
                    reasoning_tokens=usage.reasoning_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                    estimated_cost_usd=(
                        estimate_cost_usd(model_name, usage)
                        if model_name is not None and usage is not None
                        else None
                    ),
                ),
            ),
        )

    def add_failed_audit(
        self,
        conversation_id: str,
        user_id: int,
        *,
        duration_ms: float,
        sql_history: Iterable[dict[str, Any]] = (),
        sql_durations_ms: Iterable[float] = (),
        error: str,
    ) -> None:
        timestamp = _now()
        attempts = list(sql_history)
        with self.engine.begin() as connection:
            exists = connection.execute(
                select(conversations.c.conversation_id).where(
                    conversations.c.conversation_id == conversation_id,
                    conversations.c.user_id == user_id,
                )
            ).first()
            if exists is None:
                raise ConversationNotFoundError(conversation_id)
            self._insert_audit(
                connection,
                conversation_id,
                user_id,
                timestamp,
                duration_ms,
                attempts,
                list(sql_durations_ms),
                assistant_message_id=None,
                model_name=None,
                usage=None,
                success=False,
                error=error[:200],
            )

    @staticmethod
    def _insert_audit(
        connection: Any,
        conversation_id: str,
        user_id: int,
        timestamp: datetime,
        duration_ms: float,
        attempts: list[dict[str, Any]],
        durations: list[float],
        *,
        assistant_message_id: int | None,
        model_name: str | None,
        usage: AgentUsage | None,
        success: bool,
        error: str | None,
    ) -> None:
        estimated_cost = (
            estimate_cost_usd(model_name, usage)
            if model_name is not None and usage is not None
            else None
        )
        audit_id = connection.execute(
            insert(audit_turns).values(
                conversation_id=conversation_id,
                user_id=user_id,
                timestamp=timestamp,
                duration_ms=duration_ms,
                sql_attempt_count=len(attempts),
                success=success,
                error=error,
                assistant_message_id=assistant_message_id,
                model_name=model_name,
                llm_requests=usage.requests if usage else None,
                input_tokens=usage.input_tokens if usage else None,
                cached_input_tokens=usage.cached_input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                reasoning_tokens=usage.reasoning_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                estimated_cost_usd=estimated_cost,
            )
        ).inserted_primary_key[0]
        for index, attempt in enumerate(attempts):
            result = attempt.get("result") or {}
            attempt_error = result.get("error") or {}
            connection.execute(
                insert(audit_sql_attempts).values(
                    audit_id=audit_id,
                    attempt_number=index + 1,
                    sql_text=attempt.get("sql", ""),
                    guard_passed=bool(attempt.get("guard_passed")),
                    duration_ms=durations[index] if index < len(durations) else 0.0,
                    row_count=result.get("row_count"),
                    truncated=result.get("truncated"),
                    success=bool(result.get("ok")),
                    error=(str(attempt_error.get("message"))[:1000] if attempt_error else None),
                )
            )

    def sdk_session(self, conversation_id: str, user_id: int) -> SQLiteSession:
        self.get_conversation(conversation_id, user_id)
        return SQLiteSession(conversation_id, self.session_db_path)

    async def lock_for(self, conversation_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._conversation_locks.setdefault(conversation_id, asyncio.Lock())


@lru_cache
def get_conversation_store() -> ConversationStore:
    settings = get_settings()
    return ConversationStore(
        settings.app_database_connection_string(),
        settings.session_db_path,
        initialize=False,
    )
