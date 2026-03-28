"""Unit tests for graph building, state construction, and code generation."""

from __future__ import annotations

import pytest

from backend.graph_builder import build_graph, filter_output, generate_code, _build_state_type
from backend.schema import GraphDef, StateFieldDef, NodeDef, EdgeDef
from backend.tests.conftest import make_graph


class TestBuildStateType:
    def test_basic_fields(self):
        fields = [
            StateFieldDef(name="input"),
            StateFieldDef(name="output"),
        ]
        state_type = _build_state_type(fields)
        annotations = state_type.__annotations__
        assert "input" in annotations
        assert "output" in annotations
        assert "messages" in annotations  # always added

    def test_messages_always_present(self):
        state_type = _build_state_type([StateFieldDef(name="x")])
        assert "messages" in state_type.__annotations__


class TestBuildGraph:
    def test_simple_graph_compiles(self, simple_graph_def):
        compiled = build_graph(simple_graph_def)
        assert compiled is not None

    def test_rag_graph_compiles(self, rag_graph_def):
        compiled = build_graph(rag_graph_def)
        assert compiled is not None

    def test_router_graph_compiles(self, router_graph_def):
        compiled = build_graph(router_graph_def)
        assert compiled is not None

    def test_missing_start_edge_raises(self):
        graph = make_graph(
            nodes=[{"id": "n1", "type": "llm", "writes_to": "output", "config": {}}],
            edges=[{"id": "e1", "source": "n1", "target": "__end__"}],
        )
        with pytest.raises(ValueError, match="START"):
            build_graph(graph)

    def test_missing_end_edge_raises(self):
        graph = make_graph(
            nodes=[{"id": "n1", "type": "llm", "writes_to": "output", "config": {}}],
            edges=[{"id": "e1", "source": "__start__", "target": "n1"}],
        )
        with pytest.raises(ValueError, match="END"):
            build_graph(graph)

    def test_multi_node_chain_compiles(self):
        graph = make_graph(
            nodes=[
                {"id": "n1", "type": "llm", "writes_to": "step1", "config": {"endpoint": "test"}},
                {"id": "n2", "type": "llm", "writes_to": "output", "config": {"endpoint": "test"}},
            ],
            edges=[
                {"id": "e1", "source": "__start__", "target": "n1"},
                {"id": "e2", "source": "n1", "target": "n2"},
                {"id": "e3", "source": "n2", "target": "__end__"},
            ],
            state_fields=[
                {"name": "input", "type": "str", "description": "", "sub_fields": []},
                {"name": "step1", "type": "str", "description": "", "sub_fields": []},
                {"name": "output", "type": "str", "description": "", "sub_fields": []},
            ],
        )
        compiled = build_graph(graph)
        assert compiled is not None


class TestGenerateCode:
    def test_produces_valid_python(self, simple_graph_def):
        code = generate_code(simple_graph_def)
        assert isinstance(code, str)
        assert len(code) > 0
        # Should be syntactically valid Python
        compile(code, "<test>", "exec")

    def test_contains_state_fields(self, simple_graph_def):
        code = generate_code(simple_graph_def)
        assert "input" in code
        assert "output" in code

    def test_router_graph_code(self, router_graph_def):
        code = generate_code(router_graph_def)
        compile(code, "<test>", "exec")
        assert "router" in code.lower() or "conditional" in code.lower()


class TestFilterOutput:
    def test_no_output_fields_returns_all_state_fields(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            state_fields=[StateFieldDef(name="input"), StateFieldDef(name="output")],
        )
        result = {"input": "hello", "output": "world", "extra": "val", "messages": []}
        output_text, state = filter_output(result, graph_def)
        import json
        parsed = json.loads(output_text)
        assert parsed == {"input": "hello", "output": "world"}
        # State always has everything
        assert "extra" in state
        assert "messages" not in state

    def test_no_output_fields_single_state_field_unwrapped(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            state_fields=[StateFieldDef(name="input")],
        )
        result = {"input": "hello", "messages": []}
        output_text, state = filter_output(result, graph_def)
        assert output_text == "hello"

    def test_single_selected_field_unwrapped(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            state_fields=[StateFieldDef(name="input"), StateFieldDef(name="summary")],
            output_fields=["summary"],
        )
        result = {"input": "hello", "summary": "a summary", "messages": []}
        output_text, state = filter_output(result, graph_def)
        assert output_text == "a summary"
        # State always returns everything (for debugging)
        assert state == {"input": "hello", "summary": "a summary"}

    def test_multiple_selected_fields_returns_json(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            state_fields=[StateFieldDef(name="a"), StateFieldDef(name="b")],
            output_fields=["a", "b"],
        )
        result = {"a": "first", "b": "second", "messages": []}
        output_text, state = filter_output(result, graph_def)
        import json
        parsed = json.loads(output_text)
        assert parsed == {"a": "first", "b": "second"}

    def test_dotted_subfield_resolved(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            state_fields=[StateFieldDef(name="verdict", type="structured")],
            output_fields=["verdict.is_funny", "verdict.reasoning"],
        )
        result = {
            "verdict": '{"is_funny": false, "reasoning": "not great"}',
            "messages": [],
        }
        output_text, state = filter_output(result, graph_def)
        import json
        parsed = json.loads(output_text)
        assert parsed == {"is_funny": False, "reasoning": "not great"}
        assert state == {"verdict": '{"is_funny": false, "reasoning": "not great"}'}

    def test_mixed_toplevel_and_subfield(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            state_fields=[
                StateFieldDef(name="verdict", type="structured"),
                StateFieldDef(name="rewrite", type="structured"),
            ],
            output_fields=["verdict.is_funny", "rewrite"],
        )
        result = {
            "verdict": '{"is_funny": true, "reasoning": "good one"}',
            "rewrite": '{"critique": "meh", "rewritten_joke": "A better joke"}',
            "messages": [],
        }
        output_text, state = filter_output(result, graph_def)
        import json
        parsed = json.loads(output_text)
        assert parsed == {
            "is_funny": True,
            "rewrite": {"critique": "meh", "rewritten_joke": "A better joke"},
        }

    def test_empty_when_nothing_available(self):
        graph_def = GraphDef(
            nodes=[], edges=[],
            output_fields=["missing"],
        )
        result = {"messages": []}
        output_text, state = filter_output(result, graph_def)
        assert output_text == ""
