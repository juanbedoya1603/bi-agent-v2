from contextlib import asynccontextmanager
from io import BytesIO
from time import perf_counter
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from .agent import answer_question
from .config import get_settings
from .conversations import (
    ConversationMessage,
    ConversationNotFoundError,
    ConversationStore,
    ConversationSummary,
    get_conversation_store,
)
from .excel_export import build_excel

ConversationStoreDependency = Annotated[ConversationStore, Depends(get_conversation_store)]


def app_db_is_available() -> bool:
    try:
        get_conversation_store().check_app_db()
    except Exception:
        return False
    return True


AppDbHealthDependency = Annotated[bool, Depends(app_db_is_available)]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    answer: str
    data: dict[str, Any] | None = None


class ConversationMessagesResponse(BaseModel):
    conversation: ConversationSummary
    messages: list[ConversationMessage]


class ConversationChatResponse(ChatResponse):
    conversation_id: str
    user_message: ConversationMessage
    message: ConversationMessage


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("El título no puede estar vacío.")
        return title


class ExcelExportRequest(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=100)
    rows: list[list[Any]] = Field(max_length=200)
    row_count: int = Field(ge=0, le=200)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_visible_table(self) -> "ExcelExportRequest":
        if self.row_count != len(self.rows):
            raise ValueError("row_count debe coincidir con las filas visibles.")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Todas las filas deben coincidir con las columnas.")
        return self


@asynccontextmanager
async def lifespan(_: FastAPI):
    # El SDK queda sin tracing para evitar capturar prompt, SQL o resultados sensibles.
    yield


app = FastAPI(title="BI Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/health", responses={503: {"description": "App DB no disponible"}})
async def health(app_db_available: AppDbHealthDependency) -> JSONResponse:
    if not app_db_available:
        return JSONResponse(status_code=503, content={"status": "degraded"})
    return JSONResponse(content={"status": "ok"})


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        answer, context = await answer_question(request.message, get_settings())
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="No fue posible completar la consulta analítica.",
        ) from error
    data = (
        context.latest_result if context.latest_result and context.latest_result.get("ok") else None
    )
    return ChatResponse(answer=answer, data=data)


@app.post("/api/v1/conversations", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    store: ConversationStoreDependency,
) -> ConversationSummary:
    return store.create_conversation()


@app.get("/api/v1/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    store: ConversationStoreDependency,
    search: str | None = Query(default=None, max_length=200),
) -> list[ConversationSummary]:
    return store.list_conversations(search)


@app.patch("/api/v1/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    request: RenameConversationRequest,
    store: ConversationStoreDependency,
) -> ConversationSummary:
    try:
        return store.rename_conversation(conversation_id, request.title)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error


@app.delete("/api/v1/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    store: ConversationStoreDependency,
) -> Response:
    try:
        await store.delete_conversation_with_session(conversation_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error
    return Response(status_code=204)


@app.post("/api/v1/exports/excel")
async def export_excel(request: ExcelExportRequest) -> StreamingResponse:
    content = build_excel(request.columns, request.rows)
    headers = {"Content-Disposition": 'attachment; filename="datos-bi.xlsx"'}
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
async def get_conversation_messages(
    conversation_id: str,
    store: ConversationStoreDependency,
) -> ConversationMessagesResponse:
    try:
        return ConversationMessagesResponse(
            conversation=store.get_conversation(conversation_id),
            messages=store.get_messages(conversation_id),
        )
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error


@app.post(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=ConversationChatResponse,
)
async def send_conversation_message(
    conversation_id: str,
    request: ChatRequest,
    store: ConversationStoreDependency,
) -> ConversationChatResponse:
    started_at = perf_counter()
    context = None
    try:
        conversation_lock = await store.lock_for(conversation_id)
        async with conversation_lock:
            session = store.sdk_session(conversation_id)
            try:
                session_item_count = len(await session.get_items())
                answer, context = await answer_question(
                    request.message,
                    get_settings(),
                    session=session,
                )
                data = (
                    context.latest_result
                    if context.latest_result and context.latest_result.get("ok")
                    else None
                )
                duration_ms = (perf_counter() - started_at) * 1000
                latest_error = (
                    (context.latest_result.get("error") or {}).get("type")
                    if context.latest_result and not context.latest_result.get("ok")
                    else None
                )
                try:
                    user_message, message = store.add_turn(
                        conversation_id,
                        request.message,
                        answer,
                        data,
                        duration_ms=duration_ms,
                        sql_history=getattr(context, "sql_history", ()),
                        sql_durations_ms=getattr(context, "sql_durations_ms", ()),
                        audit_success=latest_error is None,
                        audit_error=latest_error,
                    )
                except Exception:
                    items_added = max(0, len(await session.get_items()) - session_item_count)
                    for _ in range(items_added):
                        await session.pop_item()
                    raise
            finally:
                session.close()
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error
    except ValueError as error:
        store.add_failed_audit(
            conversation_id,
            duration_ms=(perf_counter() - started_at) * 1000,
            sql_history=getattr(context, "sql_history", ()),
            sql_durations_ms=getattr(context, "sql_durations_ms", ()),
            error="configuration_error",
        )
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        store.add_failed_audit(
            conversation_id,
            duration_ms=(perf_counter() - started_at) * 1000,
            sql_history=getattr(context, "sql_history", ()),
            sql_durations_ms=getattr(context, "sql_durations_ms", ()),
            error="agent_error",
        )
        raise HTTPException(
            status_code=502,
            detail="No fue posible completar la consulta analítica.",
        ) from error
    return ConversationChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        data=data,
        user_message=user_message,
        message=message,
    )
