"""Google Gemini client using Vertex AI and Application Default Credentials."""

from __future__ import annotations

from typing import Any

from llm.providers import ProviderConfig


class GeminiVertexClient:
    """Gemini text client authenticated through Google Cloud ADC.

    Tool calls currently use the agent's provider-neutral JSON protocol. This
    keeps tool execution compatible while Vertex/Gemini support is introduced
    without storing an API key in the application.
    """

    def __init__(self, provider: ProviderConfig):
        if not provider.project:
            raise ValueError("Gemini Vertex provider requires a Google Cloud project ID.")
        if not provider.location:
            raise ValueError("Gemini Vertex provider requires a Google Cloud location.")

        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "Gemini support requires the 'google-genai' package. "
                "Install it with: python -m pip install google-genai"
            ) from exc

        self.model = provider.default_model
        self._client = genai.Client(
            vertexai=True,
            project=provider.project,
            location=provider.location,
        )

    @property
    def supports_native_tools(self) -> bool:
        return False

    @property
    def supports_native_tool_outputs(self) -> bool:
        return False

    @property
    def api_type(self) -> str:
        return "gemini_vertex"

    def submit_tool_outputs(self, tool_outputs):
        raise NotImplementedError(
            "Gemini Vertex currently continues tool calls through the textual protocol."
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> str:
        del tools, tool_choice

        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for message in messages:
            role = message.get("role", "user")
            text = str(message.get("content") or "")
            if role == "system":
                system_parts.append(text)
                continue

            gemini_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"][0]["text"] += f"\n\n{text}"
            else:
                contents.append({
                    "role": gemini_role,
                    "parts": [{"text": text}],
                })

        config = None
        if system_parts:
            config = {"system_instruction": "\n\n".join(system_parts)}

        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return getattr(response, "text", None) or ""
