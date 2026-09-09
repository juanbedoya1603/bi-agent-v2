from contextlib import asynccontextmanager
from io import BytesIO
from time import perf_counter
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from .agent import answer_question
from .auth import (
    AuthError,
    AuthStore,
    DuplicateUsernameError,
    LastAdminError,
    User,
    UserNotFoundError,
    get_auth_store,
)
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
AuthStoreDependency = Annotated[AuthStore, Depends(get_auth_store)]
SESSION_COOKIE = "bi_agent_session"


def current_user(request: Request, auth_store: AuthStoreDependency) -> User:
    user = auth_store.user_for_session(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    return user


CurrentUserDependency = Annotated[User, Depends(current_user)]


def agent_user(user: CurrentUserDependency) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Debes cambiar tu contraseña para continuar.")
    return user


AgentUserDependency = Annotated[User, Depends(agent_user)]


def admin_user(user: AgentUserDependency) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Se requieren permisos de administrador.")
    return user


AdminUserDependency = Annotated[User, Depends(admin_user)]


def app_db_is_available() -> bool:
    try:
        get_conversation_store().check_app_db()
    except Exception:
        return False
    return True


AppDbHealthDependency = Annotated[bool, Depends(app_db_is_available)]


def try_add_failed_audit(
    store: ConversationStore,
    conversation_id: str,
    user_id: int,
    *,
    started_at: float,
    context: Any,
    error: str,
) -> None:
    try:
        store.add_failed_audit(
            conversation_id,
            user_id,
            duration_ms=(perf_counter() - started_at) * 1000,
            sql_history=getattr(context, "sql_history", ()),
            sql_durations_ms=getattr(context, "sql_durations_ms", ()),
            error=error,
        )
    except Exception:
        # La auditoría es best-effort y nunca debe ocultar el error original.
        return


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)


class ChatResponse(BaseModel):
    answer: str
    data: dict[str, Any] | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1000)
    new_password: str = Field(min_length=10, max_length=1000)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    temporary_password: str = Field(min_length=10, max_length=1000)
    is_admin: bool = False


class EditUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)


class ResetPasswordRequest(BaseModel):
    temporary_password: str = Field(min_length=10, max_length=1000)


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
    get_auth_store().bootstrap_admin(get_settings())
    yield


app = FastAPI(
    title="BI Agent API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/health", responses={503: {"description": "App DB no disponible"}})
async def health(app_db_available: AppDbHealthDependency) -> JSONResponse:
    if not app_db_available:
        return JSONResponse(status_code=503, content={"status": "degraded"})
    return JSONResponse(content={"status": "ok"})


@app.post("/api/v1/auth/login", response_model=User)
async def login(
    request: LoginRequest,
    response: Response,
    auth_store: AuthStoreDependency,
) -> User:
    try:
        user = auth_store.authenticate(request.username, request.password)
    except AuthError as error:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.") from error
    token, _ = auth_store.create_session(user.user_id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=get_settings().app_env.lower() == "production",
        samesite="lax",
        path="/",
    )
    return user


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    _: CurrentUserDependency,
    auth_store: AuthStoreDependency,
) -> Response:
    auth_store.revoke_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax")
    response.status_code = 204
    return response


@app.get("/api/v1/auth/me", response_model=User)
async def me(user: CurrentUserDependency) -> User:
    return user


@app.post("/api/v1/auth/change-password", response_model=User)
async def change_password(
    request: ChangePasswordRequest,
    user: CurrentUserDependency,
    auth_store: AuthStoreDependency,
) -> User:
    try:
        return auth_store.change_password(
            user.user_id, request.current_password, request.new_password
        )
    except (AuthError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/v1/admin/users", response_model=list[User])
async def list_users(_: AdminUserDependency, auth_store: AuthStoreDependency) -> list[User]:
    return auth_store.list_users()


@app.post("/api/v1/admin/users", response_model=User, status_code=201)
async def create_user(
    request: CreateUserRequest,
    _: AdminUserDependency,
    auth_store: AuthStoreDependency,
) -> User:
    try:
        return auth_store.create_user(
            request.username,
            request.display_name,
            request.temporary_password,
            is_admin=request.is_admin,
        )
    except (DuplicateUsernameError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.patch("/api/v1/admin/users/{user_id}", response_model=User)
async def edit_user(
    user_id: int,
    request: EditUserRequest,
    _: AdminUserDependency,
    auth_store: AuthStoreDependency,
) -> User:
    try:
        return auth_store.edit_user(user_id, request.username, request.display_name)
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail="El usuario no existe.") from error
    except DuplicateUsernameError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/v1/admin/users/{user_id}/activate", response_model=User)
async def activate_user(
    user_id: int, _: AdminUserDependency, auth_store: AuthStoreDependency
) -> User:
    try:
        return auth_store.set_active(user_id, True)
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail="El usuario no existe.") from error


@app.post("/api/v1/admin/users/{user_id}/deactivate", response_model=User)
async def deactivate_user(
    user_id: int, _: AdminUserDependency, auth_store: AuthStoreDependency
) -> User:
    try:
        return auth_store.set_active(user_id, False)
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail="El usuario no existe.") from error
    except LastAdminError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/v1/admin/users/{user_id}/reset-password", response_model=User)
async def reset_user_password(
    user_id: int,
    request: ResetPasswordRequest,
    _: AdminUserDependency,
    auth_store: AuthStoreDependency,
) -> User:
    try:
        return auth_store.reset_password(user_id, request.temporary_password)
    except UserNotFoundError as error:
        raise HTTPException(status_code=404, detail="El usuario no existe.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _: AgentUserDependency) -> ChatResponse:
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
    user: AgentUserDependency,
) -> ConversationSummary:
    return store.create_conversation(user.user_id)


@app.get("/api/v1/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    store: ConversationStoreDependency,
    user: AgentUserDependency,
    search: str | None = Query(default=None, max_length=200),
) -> list[ConversationSummary]:
    return store.list_conversations(user.user_id, search)


@app.patch("/api/v1/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    request: RenameConversationRequest,
    store: ConversationStoreDependency,
    user: AgentUserDependency,
) -> ConversationSummary:
    try:
        return store.rename_conversation(conversation_id, user.user_id, request.title)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error


@app.delete("/api/v1/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    store: ConversationStoreDependency,
    user: AgentUserDependency,
) -> Response:
    try:
        await store.delete_conversation_with_session(conversation_id, user.user_id)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=404, detail="La conversación no existe.") from error
    return Response(status_code=204)


@app.post("/api/v1/exports/excel")
async def export_excel(
    request: ExcelExportRequest, _: AgentUserDependency
) -> StreamingResponse:
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
    user: AgentUserDependency,
) -> ConversationMessagesResponse:
    try:
        return ConversationMessagesResponse(
            conversation=store.get_conversation(conversation_id, user.user_id),
            messages=store.get_messages(conversation_id, user.user_id),
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
    user: AgentUserDependency,
) -> ConversationChatResponse:
    started_at = perf_counter()
    context = None
    try:
        conversation_lock = await store.lock_for(conversation_id)
        async with conversation_lock:
            session = store.sdk_session(conversation_id, user.user_id)
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
                        user.user_id,
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
        try_add_failed_audit(
            store,
            conversation_id,
            user.user_id,
            started_at=started_at,
            context=context,
            error="configuration_error",
        )
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        try_add_failed_audit(
            store,
            conversation_id,
            user.user_id,
            started_at=started_at,
            context=context,
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
