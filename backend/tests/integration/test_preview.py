"""Integration tests for full graph preview — end-to-end execution."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.schema import GraphDef, StateFieldDef, NodeDef, EdgeDef

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    return TestClient(app)


def _consume_sse(resp) -> tuple[str, list[dict]]:
    """Drain an SSE response into the deltas plus the terminal event.

    Returns ``(joined_delta_text, [non_delta_events])``. The terminal event
    is the last item in the list (``done`` / ``interrupt`` / ``error``).
    """
    deltas: list[str] = []
    other: list[dict] = []
    for line in resp.iter_lines():
        if not line or not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        if event.get("type") == "delta":
            deltas.append(event.get("text", ""))
        else:
            other.append(event)
    return "".join(deltas), other


class TestPreviewIntegration:
    def test_simple_llm_graph(self, client, llm_endpoint):
        graph = GraphDef(
            nodes=[
                NodeDef(id="llm_1", type="llm", writes_to="output", config={
                    "endpoint": llm_endpoint,
                    "system_prompt": "Reply with exactly one word.",
                    "temperature": 0.1,
                }),
            ],
            edges=[
                EdgeDef(id="e1", source="__start__", target="llm_1"),
                EdgeDef(id="e2", source="llm_1", target="__end__"),
            ],
            state_fields=[
                StateFieldDef(name="input"),
                StateFieldDef(name="output"),
            ],
        )
        with client.stream("POST", "/api/graph/preview", json={
            "graph": graph.model_dump(),
            "input_message": "Hello",
        }) as resp:
            assert resp.status_code == 200
            streamed_text, events = _consume_sse(resp)

        assert events[-1]["type"] == "done"
        assert len(events[-1]["output"]) > 0
        # Streaming actually streamed something (LLM endpoints support deltas).
        assert streamed_text

    def test_rag_graph(self, client, llm_endpoint, vs_index_name, vs_endpoint_name):
        graph = GraphDef(
            nodes=[
                NodeDef(id="vs_1", type="vector_search", writes_to="context", config={
                    "query_from": "input",
                    "index_name": vs_index_name,
                    "endpoint_name": vs_endpoint_name,
                    "columns": "note_id,department,text",
                    "num_results": 2,
                    "enable_reranker": "false",
                }),
                NodeDef(id="llm_1", type="llm", writes_to="output", config={
                    "endpoint": llm_endpoint,
                    "system_prompt": "Answer based on context: {context}",
                    "temperature": 0.1,
                }),
            ],
            edges=[
                EdgeDef(id="e1", source="__start__", target="vs_1"),
                EdgeDef(id="e2", source="vs_1", target="llm_1"),
                EdgeDef(id="e3", source="llm_1", target="__end__"),
            ],
            state_fields=[
                StateFieldDef(name="input"),
                StateFieldDef(name="context"),
                StateFieldDef(name="output"),
            ],
        )
        with client.stream("POST", "/api/graph/preview", json={
            "graph": graph.model_dump(),
            "input_message": "Tell me about cardiology patients",
        }) as resp:
            assert resp.status_code == 200
            _, events = _consume_sse(resp)

        assert events[-1]["type"] == "done"
        assert len(events[-1]["output"]) > 0

    def test_multi_turn_preserves_thread(self, client, llm_endpoint):
        graph = GraphDef(
            nodes=[
                NodeDef(id="llm_1", type="llm", writes_to="output", config={
                    "endpoint": llm_endpoint,
                    "system_prompt": "You are a helpful assistant. Be brief.",
                    "temperature": 0.1,
                    "conversational": "true",
                }),
            ],
            edges=[
                EdgeDef(id="e1", source="__start__", target="llm_1"),
                EdgeDef(id="e2", source="llm_1", target="__end__"),
            ],
            state_fields=[
                StateFieldDef(name="input"),
                StateFieldDef(name="output"),
            ],
        )
        # First message
        with client.stream("POST", "/api/graph/preview", json={
            "graph": graph.model_dump(),
            "input_message": "My name is Alice.",
        }) as resp:
            _, events1 = _consume_sse(resp)
        terminal1 = events1[-1]
        assert terminal1["type"] == "done"
        thread_id = terminal1["thread_id"]
        assert thread_id is not None

        # Second message with same thread
        with client.stream("POST", "/api/graph/preview", json={
            "graph": graph.model_dump(),
            "input_message": "What is my name?",
            "thread_id": thread_id,
        }) as resp:
            _, events2 = _consume_sse(resp)
        terminal2 = events2[-1]
        assert terminal2["type"] == "done"
        # The LLM should remember Alice from the first turn
        assert "alice" in terminal2["output"].lower()
