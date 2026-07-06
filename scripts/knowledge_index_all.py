from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.knowledge_index_capabilities import build_capability_index_preview
from scripts.knowledge_index_chat_history import count_chat_history_preview
from scripts.knowledge_index_long_term_memory import count_long_term_memory_preview
from tools.knowledge.config import DEFAULT_KNOWLEDGE_CONFIG_PATH, load_knowledge_config
from tools.knowledge.embeddings import create_embedding_model
from tools.knowledge.indexes import ensure_capability_router_collection, index_capability_router
from tools.knowledge.indexes.chat_history import index_chat_history_collection
from tools.knowledge.indexes.long_term_memory import index_long_term_memory_collection
from tools.knowledge.registry import DEFAULT_CAPABILITIES_DIR, load_capability_definitions
from tools.knowledge.stores.qdrant import create_qdrant_client


def build_index_preview(
    capabilities_dir: Path,
    chat_history_dir: Path,
    memory_path: Path,
) -> dict:
    """Return a combined dry-run preview for all local knowledge indexes."""
    capabilities = build_capability_index_preview(capabilities_dir)
    chat_history = count_chat_history_preview(chat_history_dir)
    long_term_memory = count_long_term_memory_preview(memory_path)
    return {
        "capabilities": {
            "capabilities_dir": str(capabilities_dir),
            "record_count": len(capabilities),
            "sample": capabilities[:3],
        },
        "chat_history": chat_history,
        "long_term_memory": long_term_memory,
        "total_record_count": (
            len(capabilities)
            + int(chat_history["record_count"])
            + int(long_term_memory["record_count"])
        ),
    }


def write_all_indexes(
    config_path: Path,
    capabilities_dir: Path,
    chat_history_dir: Path,
    memory_path: Path,
) -> dict[str, int]:
    """Write all local knowledge indexes to Qdrant and return indexed counts."""
    config = load_knowledge_config(config_path).qdrant
    embedding_model = create_embedding_model(config)
    client = create_qdrant_client(config)

    capabilities = load_capability_definitions(capabilities_dir)
    ensure_capability_router_collection(client, config)
    print("Indexing capability router...", file=sys.stderr, flush=True)
    capability_count = index_capability_router(
        client=client,
        config=config,
        capabilities=capabilities,
        embedding_model=embedding_model,
    )
    print(f"Indexed capability router: {capability_count}", file=sys.stderr, flush=True)

    print("Indexing chat history...", file=sys.stderr, flush=True)
    chat_history_count = index_chat_history_collection(
        client=client,
        config=config,
        root=chat_history_dir,
        embedding_model=embedding_model,
        progress=lambda count: print(
            f"Indexed chat history records: {count}",
            file=sys.stderr,
            flush=True,
        ),
    )
    print(f"Indexed chat history total: {chat_history_count}", file=sys.stderr, flush=True)

    print("Indexing long-term memory...", file=sys.stderr, flush=True)
    long_term_memory_count = index_long_term_memory_collection(
        client=client,
        config=config,
        path=memory_path,
        embedding_model=embedding_model,
        progress=lambda count: print(
            f"Indexed long-term memory batch: {count}",
            file=sys.stderr,
            flush=True,
        ),
    )
    print(
        f"Indexed long-term memory total: {long_term_memory_count}",
        file=sys.stderr,
        flush=True,
    )

    return {
        "capabilities": capability_count,
        "chat_history": chat_history_count,
        "long_term_memory": long_term_memory_count,
        "total": capability_count + chat_history_count + long_term_memory_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build or write all local knowledge Qdrant indexes. Default mode is "
            "a safe dry-run preview."
        )
    )
    parser.add_argument(
        "--capabilities-dir",
        type=Path,
        default=DEFAULT_CAPABILITIES_DIR,
        help="Directory containing capability YAML files.",
    )
    parser.add_argument(
        "--chat-history-dir",
        type=Path,
        default=Path(".agent_chat_history"),
        help="Directory containing persisted chat history files.",
    )
    parser.add_argument(
        "--memory-path",
        type=Path,
        default=Path("runtime") / "knowledge" / "memory.jsonl",
        help="Path to the persisted long-term-memory JSONL file.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_KNOWLEDGE_CONFIG_PATH,
        help="Knowledge config path used with --write-qdrant.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write dry-run preview JSON. Defaults to stdout.",
    )
    parser.add_argument(
        "--write-qdrant",
        action="store_true",
        help="Write all indexes to local Qdrant. Without this flag, only a dry-run preview is produced.",
    )
    args = parser.parse_args(argv)

    preview = build_index_preview(
        capabilities_dir=args.capabilities_dir,
        chat_history_dir=args.chat_history_dir,
        memory_path=args.memory_path,
    )
    text = json.dumps(preview, ensure_ascii=False, indent=2)
    if args.output is None:
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")

    if args.write_qdrant:
        counts = write_all_indexes(
            config_path=args.config,
            capabilities_dir=args.capabilities_dir,
            chat_history_dir=args.chat_history_dir,
            memory_path=args.memory_path,
        )
        print(
            "Indexed all local knowledge sources into Qdrant: "
            f"{json.dumps(counts, ensure_ascii=False, sort_keys=True)}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
