"""Offline subprocess host used by network tests; never executes real tools."""
from __future__ import annotations

import argparse
from pathlib import Path
import time
from types import SimpleNamespace

import uvicorn

from runtime.server import create_server
from runtime.service import AgentRuntime
from tests.runtime_helpers import make_runtime

TOKEN = "offline-process-token-" + "x" * 32


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    runtime, agent = make_runtime(args.root)
    provider = SimpleNamespace(key="fixture", label="Fixture", default_model="fixture-model",
                               supports_model_listing=True)
    # These overrides are confined to this disposable fixture process.
    AgentRuntime.providers = property(lambda self: {"fixture": provider})
    runtime.provider_models = lambda key: ["fixture-model", "other-model"]

    def step(text):
        if text == "propose":
            target = args.root / "approved.txt"
            runtime.state.edit_store.propose_create(target, "approved from another client")
            agent.on_tool("fixture file proposal created")
            deadline = time.monotonic() + 20
            while not target.exists() and time.monotonic() < deadline:
                time.sleep(0.03)
            if not target.exists():
                raise RuntimeError("Offline fixture timed out waiting for approval")
            return "finished after initiating client disconnected"
        return f"answer: {text}"

    agent.behavior = step
    uvicorn.run(create_server(runtime, token=TOKEN), host="127.0.0.1", port=args.port,
                access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
