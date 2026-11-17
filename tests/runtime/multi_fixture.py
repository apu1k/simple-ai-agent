"""Disposable multi-chat host; all side effects are confined to its scratch root."""
from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import time

import uvicorn

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from llm.base import LLMResponse, NativeToolCall
from runtime.chat_store import ChatStore
from runtime.conversations import ConversationManager
from runtime.server import create_server
from runtime.service import AgentRuntime
from runtime.state import AgentState, ModelConfig, ModelSettings
from tests.runtime.recovery_fixture import TOKEN


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    history = ChatStore(args.root / "history")

    def factory(identity, store, source):
        state = AgentState(
            cwd=args.root, chat_store=history, chat_session_id=identity,
            model_config=ModelConfig("fixture", "Fixture", "fixture-model", None, None, "chat_completions"),
            model_settings=replace(source.model_settings) if source else ModelSettings(),
        )
        registry = ToolRegistry()

        def scratch_effect(mode):
            proposal, _ = state.edit_store.propose_create(args.root / f"approved-{identity}.txt", identity)
            if mode == "hold":
                with (args.root / f"effects-{identity}.txt").open("a", encoding="utf-8") as stream:
                    stream.write("one scratch effect\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                (args.root / f"started-{identity}").write_text("ready", encoding="utf-8")
                time.sleep(120)
            return f"Pending proposal #{proposal.id}"

        registry.register(ToolSpec("scratch_effect", scratch_effect, "Scratch-only fixture", {"mode": "test mode"}))

        class OfflineLLM:
            supports_native_tools = True
            api_type = "chat_completions"

            def chat(self, messages, **kwargs):
                with (args.root / f"calls-{identity}.txt").open("a", encoding="utf-8") as stream:
                    stream.write("offline request\n")
                last = messages[-1]
                if last.get("role") == "user" and last.get("content") in {"propose", "hold"}:
                    return LLMResponse(None, [NativeToolCall("scratch-call", "scratch_effect", {"mode": last["content"]})])
                return f"offline final reply for {identity}"

        return AgentRuntime(
            state=state, llm=OfflineLLM(), persistence_store=store,
            agent_factory=lambda **kwargs: Agent("offline multi-chat fixture", tool_registry=registry, **kwargs),
        )

    manager = ConversationManager(history=history, runtime_factory=factory,
                                  persistence_path=args.root / "state.sqlite3")
    uvicorn.run(create_server(manager, token=TOKEN), host="127.0.0.1", port=args.port,
                access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
