from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent import answer_question
from .config import get_settings


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    answer: str
    data: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    # El SDK queda sin tracing para evitar capturar prompt, SQL o resultados sensibles.
    yield


app = FastAPI(title="BI Agent API", version="0.1.0", lifespan=lifespan)


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
