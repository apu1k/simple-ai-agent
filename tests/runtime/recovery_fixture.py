"""Disposable HTTP host with fake provider and scratch-only tools for crash tests."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import time

import uvicorn

from core.agent import Agent
from core.tool_registry import ToolRegistry, ToolSpec
from llm.base import LLMResponse, NativeToolCall
from runtime.server import create_server
from runtime.service import AgentRuntime
from tests.runtime_helpers import make_runtime

TOKEN = "offline-crash-fixture-" + "x" * 32


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    fixture, _ = make_runtime(args.root)
    state = fixture.state
    fixture.close()
    registry = ToolRegistry()

    def scratch_effect(mode):
        proposal, _ = state.edit_store.propose_create(args.root / "approved.txt", "approved after restart")
        if mode == "interrupt":
            with (args.root / "effects.txt").open("a", encoding="utf-8") as stream:
                stream.write("one scratch effect\n")
                stream.flush()
                os.fsync(stream.fileno())
            (args.root / "started").write_text("ready for test-owned termination", encoding="utf-8")
            time.sleep(120)
        return f"Pending proposal #{proposal.id}"

    registry.register(ToolSpec("scratch_effect", scratch_effect, "Scratch-only test effect", {"mode": "test mode"}))

    class OfflineLLM:
        supports_native_tools = True
        api_type = "chat_completions"

        def chat(self, messages, **kwargs):
            with (args.root / "provider_calls.txt").open("a", encoding="utf-8") as stream:
                stream.write("offline request\n")
            last = messages[-1]
            if last.get("role") == "user" and last.get("content") in {"propose", "interrupt"}:
                return LLMResponse(None, [NativeToolCall("scratch-call", "scratch_effect", {"mode": last["content"]})])
            return "offline final reply"

    runtime = AgentRuntime(
        state=state, llm=OfflineLLM(), persistence_path=args.root / "state.sqlite3",
        agent_factory=lambda **kwargs: Agent("offline fixture", tool_registry=registry, **kwargs),
    )
    uvicorn.run(create_server(runtime, token=TOKEN), host="127.0.0.1", port=args.port,
                access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
