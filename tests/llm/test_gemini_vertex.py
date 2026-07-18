"""Tests for the Vertex AI Gemini adapter."""

from types import SimpleNamespace

from llm.gemini_vertex import GeminiVertexClient


class _Models:
    def __init__(self):
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text="Gemini reply")


def test_chat_maps_system_and_conversation_roles():
    client = GeminiVertexClient.__new__(GeminiVertexClient)
    client.model = "gemini-2.5-flash"
    models = _Models()
    client._client = SimpleNamespace(models=models)

    result = client.chat([
        {"role": "system", "content": "Follow instructions."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Continue"},
    ])

    assert result == "Gemini reply"
    assert models.kwargs == {
        "model": "gemini-2.5-flash",
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {"role": "model", "parts": [{"text": "Hi"}]},
            {"role": "user", "parts": [{"text": "Continue"}]},
        ],
        "config": {"system_instruction": "Follow instructions."},
    }


def test_chat_coalesces_adjacent_messages_with_same_gemini_role():
    client = GeminiVertexClient.__new__(GeminiVertexClient)
    client.model = "gemini-2.5-flash"
    models = _Models()
    client._client = SimpleNamespace(models=models)

    client.chat([
        {"role": "user", "content": "Tool result one"},
        {"role": "tool", "content": "Tool result two"},
    ])

    assert models.kwargs["contents"] == [
        {
            "role": "user",
            "parts": [{"text": "Tool result one\n\nTool result two"}],
        }
    ]
