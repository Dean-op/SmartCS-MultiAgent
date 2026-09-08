from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from ecommerce_ai_agent.workflow import build_chat_workflow
from tests.integration.conftest import IntegrationDatabase


class GeneralModel:
    def __init__(self, response: str) -> None:
        self.response = response

    async def generate_structured(self, system_prompt, user_prompt, schema_type):
        return schema_type(route="general")

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return self.response


class UnusedTools:
    async def run(self, name: str, arguments: str) -> str:
        raise AssertionError("general route must not execute tools")


class UnusedKnowledge:
    async def search(self, question: str) -> list:
        raise AssertionError("general route must not retrieve knowledge")


def checkpoint_dsn(database: IntegrationDatabase) -> str:
    return database.database.engine.url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


@pytest.mark.asyncio
async def test_async_postgres_saver_restores_state_after_new_connection(
    test_database: IntegrationDatabase,
) -> None:
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    dsn = checkpoint_dsn(test_database)

    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        first_graph = build_chat_workflow(
            GeneralModel("first answer"),
            UnusedTools(),
            UnusedKnowledge(),
            checkpointer=saver,
        )
        await first_graph.ainvoke(
            {"messages": [{"role": "user", "content": "first message"}]},
            config,
        )

    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        second_graph = build_chat_workflow(
            GeneralModel("second answer"),
            UnusedTools(),
            UnusedKnowledge(),
            checkpointer=saver,
        )
        state = await second_graph.ainvoke(
            {"messages": [{"role": "user", "content": "second message"}]},
            config,
        )
        checkpoint = await saver.aget_tuple(config)

    user_messages = [
        message["content"] for message in state["messages"] if message["role"] == "user"
    ]
    assert user_messages == ["first message", "second message"]
    assert checkpoint is not None
    assert checkpoint.config["configurable"]["thread_id"] == thread_id
