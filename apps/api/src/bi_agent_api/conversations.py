import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from agents import SQLiteSession
from pydantic import BaseModel

from .config import get_settings


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


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ConversationStore:
    """Minimal UI history alongside the Agents SDK SQLite session tables."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ui_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ui_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    data_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id)
                        REFERENCES ui_conversations (conversation_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_ui_messages_conversation
                    ON ui_messages (conversation_id, message_id);
                """
            )

    def create_conversation(self) -> ConversationSummary:
        conversation_id = str(uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ui_conversations
                    (conversation_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, "Nueva conversación", timestamp, timestamp),
            )
        return ConversationSummary(
            conversation_id=conversation_id,
            title="Nueva conversación",
            created_at=timestamp,
            updated_at=timestamp,
        )

    def list_conversations(self) -> list[ConversationSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT conversation_id, title, created_at, updated_at
                FROM ui_conversations
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [ConversationSummary(**dict(row)) for row in rows]

    def get_conversation(self, conversation_id: str) -> ConversationSummary:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT conversation_id, title, created_at, updated_at
                FROM ui_conversations
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise ConversationNotFoundError(conversation_id)
        return ConversationSummary(**dict(row))

    def get_messages(self, conversation_id: str) -> list[ConversationMessage]:
        self.get_conversation(conversation_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT message_id, role, content, data_json, created_at
                FROM ui_messages
                WHERE conversation_id = ?
                ORDER BY message_id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [
            ConversationMessage(
                message_id=row["message_id"],
                role=row["role"],
                content=row["content"],
                data=json.loads(row["data_json"]) if row["data_json"] else None,
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def add_message(
        self,
        conversation_id: str,
        role: Literal["user", "assistant"],
        content: str,
        data: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        conversation = self.get_conversation(conversation_id)
        timestamp = _now()
        title = conversation.title
        if role == "user" and title == "Nueva conversación":
            title = " ".join(content.split())[:64] or title

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ui_messages
                    (conversation_id, role, content, data_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    json.dumps(data, ensure_ascii=False) if data is not None else None,
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE ui_conversations
                SET title = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (title, timestamp, conversation_id),
            )
            message_id = cursor.lastrowid
        if message_id is None:
            raise RuntimeError("No fue posible guardar el mensaje.")
        return ConversationMessage(
            message_id=message_id,
            role=role,
            content=content,
            data=data,
            created_at=timestamp,
        )

    def sdk_session(self, conversation_id: str) -> SQLiteSession:
        self.get_conversation(conversation_id)
        return SQLiteSession(conversation_id, self.db_path)

    async def lock_for(self, conversation_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._conversation_locks.setdefault(conversation_id, asyncio.Lock())


@lru_cache
def get_conversation_store() -> ConversationStore:
    return ConversationStore(get_settings().session_db_path)
