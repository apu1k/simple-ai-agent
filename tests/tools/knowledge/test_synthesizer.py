from types import SimpleNamespace

import pytest

from llm.base import LLMResponse, NativeToolCall
from runtime.state import ModelConfig
from tools.knowledge.config import KnowledgeSynthesisConfig
from tools.knowledge.models import EvidenceBundle, EvidenceItem, KnowledgeSearchResult
from tools.knowledge.synthesizer import KnowledgeSynthesizer


class FakeStructuredClient:
    supports_native_tools = True
    api_type = "responses"

    def __init__(self, payload):
        self.payload = payload
        self.messages = None
        self.tools = None
        self.tool_choice = None

    def chat(self, messages, tools=None, tool_choice=None):
        self.messages = messages
        self.tools = tools
        self.tool_choice = tool_choice
        return LLMResponse(
            content=None,
            tool_calls=[
                NativeToolCall(
                    id="call-1",
                    name="submit_knowledge_synthesis",
                    arguments=self.payload,
                )
            ],
        )


def _state():
    return SimpleNamespace(
        model_config=ModelConfig(
            provider_key="test",
            provider_label="Test Provider",
            model="large-model",
            api_key="test-key",
            base_url="http://localhost:1234/v1",
            api_type="responses",
        )
    )


def _result():
    return KnowledgeSearchResult(
        query="What was decided?",
        selected_capabilities=[],
        evidence_bundles=[
            EvidenceBundle(
                capability_id="search.test",
                source="test_source",
                status="success",
                confidence=0.9,
                items=[
                    EvidenceItem(
                        type="memory",
                        source="memory",
                        title="decision.md:4",
                        content="The team selected Qdrant.",
                        confidence=0.9,
                        metadata={"path": "decision.md", "line": 4},
                    )
                ],
            )
        ],
    )


def test_synthesizer_uses_strict_structured_output_and_returns_citation_catalog():
    payload = {
        "answer": "The team selected Qdrant [E1].",
        "key_facts": [
            {"statement": "Qdrant was selected.", "citations": ["E1"]}
        ],
        "conflicts": [],
        "missing_information": [],
    }
    client = FakeStructuredClient(payload)
    captured = {}

    def client_factory(provider, model):
        captured["provider"] = provider
        captured["model"] = model
        return client

    synthesizer = KnowledgeSynthesizer(
        KnowledgeSynthesisConfig(model="gpt-5.6-luna"),
        client_factory=client_factory,
    )

    output = synthesizer.synthesize(_result(), _state())

    assert captured["model"] == "gpt-5.6-luna"
    assert captured["provider"].default_model == "gpt-5.6-luna"
    assert client.tools[0]["name"] == "submit_knowledge_synthesis"
    assert client.tools[0]["strict"] is True
    assert client.tool_choice == {
        "type": "function",
        "name": "submit_knowledge_synthesis",
    }
    assert output["synthesis"] == payload
    assert output["citations"] == [
        {
            "id": "E1",
            "type": "memory",
            "source": "memory",
            "title": "decision.md:4",
            "confidence": 0.9,
            "metadata": {"path": "decision.md", "line": 4},
        }
    ]


def test_synthesizer_rejects_unknown_citation_ids():
    client = FakeStructuredClient(
        {
            "answer": "Unsupported claim [E99].",
            "key_facts": [],
            "conflicts": [],
            "missing_information": [],
        }
    )
    synthesizer = KnowledgeSynthesizer(
        KnowledgeSynthesisConfig(),
        client_factory=lambda provider, model: client,
    )

    with pytest.raises(ValueError, match="unknown citation IDs"):
        synthesizer.synthesize(_result(), _state())
