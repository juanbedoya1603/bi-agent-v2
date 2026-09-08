from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import answer_question
from .config import get_settings
from .conversations import (
    ConversationMessage,
    ConversationNotFoundError,
    ConversationStore,
    ConversationSummary,
    get_conversation_store,
)

ConversationStoreDependency = Annotated[ConversationStore, Depends(get_conversation_store)]


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
    message: ConversationMessage


@asynccontextmanager
async def lifespan(_: FastAPI):
    # El SDK queda sin tracing para evitar capturar prompt, SQL o resultados sensibles.
    yield


app = FastAPI(title="BI Agent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
) -> list[ConversationSummary]:
    return store.list_conversations()


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
    try:
        conversation_lock = await store.lock_for(conversation_id)
        async with conversation_lock:
            store.add_message(conversation_id, "user", request.message)
            session = store.sdk_session(conversation_id)
            try:
                answer, context = await answer_question(
                    request.message,
                    get_settings(),
                    session=session,
                )
            finally:
                session.close()
            data = (
                context.latest_result
                if context.latest_result and context.latest_result.get("ok")
                else None
            )
            message = store.add_message(conversation_id, "assistant", answer, data)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="No fue posible completar la consulta analítica.",
        ) from error
    return ConversationChatResponse(
        conversation_id=conversation_id,
        answer=answer,
        data=data,
        message=message,
    )
