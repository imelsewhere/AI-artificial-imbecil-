from __future__ import annotations

from pathlib import Path

from langchain.agents import AgentType, initialize_agent
from langchain.memory import ConversationBufferMemory

from kb_agent.config import load_settings
from kb_agent.gigachat_client import GigaChat
from kb_agent.tools import ToolContext, build_tools


def create_agent(
    *,
    project_root: Path | None = None,
    verbose: bool = True,
    max_iterations: int = 6,
):
    """
    Простая инициализация агента через `initialize_agent` (как в вашем сниппете).
    Динамическая "роль" хранится в ctx.role и может меняться через инструмент `kb_set_role`.
    """
    gigachat_settings, kb_paths = load_settings(project_root)
    runtime = GigaChat(gigachat_settings).build()
    llm = runtime.llm.with_retry(stop_after_attempt=4, wait_exponential_jitter=True)

    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

    ctx = ToolContext(kb=kb_paths, llm=llm, request_delay_s=float(gigachat_settings.request_delay_s))
    tools = build_tools(ctx=ctx)

    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
        verbose=verbose,
        memory=memory,
        handle_parsing_errors=(
            "Ошибка парсинга. Используй строго ожидаемый формат для tool-calling "
            "и верни только одно действие за шаг."
        ),
        max_iterations=max_iterations,
        early_stopping_method="generate",
    )

    return agent, {"tools": tools, "memory": memory, "kb": kb_paths, "ctx": ctx}


def create_agent_initialize_agent_style(
    *,
    project_root: Path | None = None,
    verbose: bool = True,
    max_iterations: int = 15,
):
    """
    Backward-compatible alias.
    """
    return create_agent(project_root=project_root, verbose=verbose, max_iterations=max_iterations)


