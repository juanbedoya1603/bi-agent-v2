from collections.abc import Callable
from typing import Any

from agents import Agent, RunConfig, Runner
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from .config import Settings
from .database import execute_query
from .prompt import SYSTEM_PROMPT
from .tools import BiAgentContext, SqlExecutor, run_readonly_sql


def _production_model(settings: Settings) -> OpenAIResponsesModel:
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )
    return OpenAIResponsesModel(model=settings.openai_model, openai_client=client)


def build_agent(settings: Settings, *, model: Any | None = None) -> Agent[BiAgentContext]:
    return Agent[BiAgentContext](
        name="BI Agent",
        instructions=SYSTEM_PROMPT,
        model=model or _production_model(settings),
        tools=[run_readonly_sql],
    )


async def answer_question(
    question: str,
    settings: Settings,
    *,
    model: Any | None = None,
    sql_executor: SqlExecutor | None = None,
) -> tuple[str, BiAgentContext]:
    if model is None and not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY no está configurada.")

    executor: Callable[[str], dict[str, Any]] = sql_executor or (
        lambda sql: execute_query(sql, settings)
    )
    context = BiAgentContext(settings=settings, sql_executor=executor)
    result = await Runner.run(
        build_agent(settings, model=model),
        question,
        context=context,
        max_turns=8,
        run_config=RunConfig(
            tracing_disabled=True,
            trace_include_sensitive_data=False,
            workflow_name="BI question",
        ),
    )
    return str(result.final_output), context
