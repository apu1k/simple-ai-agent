import importlib
import json
from types import SimpleNamespace

from core.tool_registry import registry
from runtime.prompt import build_system_prompt
from tools.knowledge.models import EvidenceBundle, EvidenceItem, KnowledgeSearchResult


knowledge_tool_module = importlib.import_module("tools.knowledge.tool")


class FakeEngine:
    def search(self, request):
        return KnowledgeSearchResult(
            query=request.query,
            selected_capabilities=[],
            evidence_bundles=[
                EvidenceBundle(
                    capability_id="search.test",
                    source="memory",
                    status="success",
                    confidence=0.8,
                    items=[
                        EvidenceItem(
                            type="memory",
                            source="memory",
                            content="Raw evidence",
                            title="memory.jsonl:1",
                            confidence=0.8,
                        )
                    ],
                )
            ],
        )


class FakeSynthesizer:
    def synthesize(self, result, state):
        return {
            "synthesis": {
                "answer": "Synthesized answer [E1].",
                "key_facts": [
                    {"statement": "A fact.", "citations": ["E1"]}
                ],
                "conflicts": [],
                "missing_information": [],
            },
            "citations": [{"id": "E1", "source": "memory"}],
        }


class FailingSynthesizer:
    def synthesize(self, result, state):
        raise ValueError("invalid structured response")


def _state(tmp_path):
    return SimpleNamespace(cwd=tmp_path)


def _configure(monkeypatch, synthesizer, *, fallback_to_raw=True):
    monkeypatch.setattr(knowledge_tool_module, "_ENGINE", FakeEngine())
    monkeypatch.setattr(knowledge_tool_module, "_SYNTHESIZER", synthesizer)
    monkeypatch.setattr(
        knowledge_tool_module,
        "_CONFIG",
        SimpleNamespace(
            synthesis=SimpleNamespace(
                enabled=True,
                fallback_to_raw=fallback_to_raw,
            )
        ),
    )


def test_response_mode_schema_and_prompt_prefer_synthesized():
    spec = registry.get("knowledge_search")
    assert spec is not None
    response_mode = spec.parameters["response_mode"]
    assert isinstance(response_mode, dict)
    assert response_mode["enum"] == ["synthesized", "raw", "both"]
    assert "only when the user explicitly requests both" in response_mode["description"]

    prompt = build_system_prompt(use_native_tools=True)
    assert 'Use response_mode="synthesized" for ordinary knowledge searches.' in prompt
    assert 'Never use "both" merely to increase confidence' in prompt
    assert 'always choose "synthesized"' in prompt


def test_raw_mode_does_not_call_synthesizer(monkeypatch, tmp_path):
    class UnexpectedSynthesizer:
        def synthesize(self, result, state):
            raise AssertionError("raw mode must not call the synthesis model")

    _configure(monkeypatch, UnexpectedSynthesizer())

    output = json.loads(
        knowledge_tool_module.knowledge_search(
            _state(tmp_path),
            "test query",
            response_mode="raw",
        )
    )

    assert output["response_mode"] == "raw"
    assert output["evidence"][0]["content"] == "Raw evidence"
    assert "synthesis" not in output


def test_synthesized_mode_omits_raw_evidence(monkeypatch, tmp_path):
    _configure(monkeypatch, FakeSynthesizer())

    output = json.loads(
        knowledge_tool_module.knowledge_search(
            _state(tmp_path),
            "test query",
            response_mode="synthesized",
        )
    )

    assert output["response_mode"] == "synthesized"
    assert output["synthesis"]["answer"] == "Synthesized answer [E1]."
    assert output["citations"][0]["id"] == "E1"
    assert "evidence" not in output
    assert "raw" not in output


def test_both_mode_includes_synthesis_and_raw_evidence(monkeypatch, tmp_path):
    _configure(monkeypatch, FakeSynthesizer())

    output = json.loads(
        knowledge_tool_module.knowledge_search(
            _state(tmp_path),
            "test query",
            response_mode="both",
        )
    )

    assert output["response_mode"] == "both"
    assert output["synthesis"]["answer"] == "Synthesized answer [E1]."
    assert output["raw"]["evidence"][0]["content"] == "Raw evidence"


def test_synthesis_failure_falls_back_to_raw(monkeypatch, tmp_path):
    _configure(monkeypatch, FailingSynthesizer(), fallback_to_raw=True)

    output = json.loads(
        knowledge_tool_module.knowledge_search(
            _state(tmp_path),
            "test query",
            response_mode="synthesized",
        )
    )

    assert output["response_mode"] == "raw"
    assert output["requested_response_mode"] == "synthesized"
    assert output["synthesis_error"] == "invalid structured response"
    assert output["evidence"][0]["content"] == "Raw evidence"
