from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.knowledge.config import DEFAULT_KNOWLEDGE_CONFIG_PATH, load_knowledge_config
from tools.knowledge.embeddings import create_embedding_model
from tools.knowledge.indexes.chat_history import index_chat_history_collection
from tools.knowledge.stores.qdrant import create_qdrant_client


def count_chat_history_preview(chat_history_dir: Path) -> dict:
    """Return a small dry-run preview for chat-history evidence indexing."""
    from tools.knowledge.indexes.chat_history import iter_chat_history_records

    records = list(iter_chat_history_records(chat_history_dir))
    return {
        "chat_history_dir": str(chat_history_dir),
        "record_count": len(records),
        "sample": records[:3],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Index local chat history into the normal Qdrant evidence collection. "
            "Default mode is a safe dry-run preview."
        )
    )
    parser.add_argument(
        "--chat-history-dir",
        type=Path,
        default=Path(".agent_chat_history"),
        help="Directory containing persisted chat history files.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_KNOWLEDGE_CONFIG_PATH,
        help="Knowledge config path.",
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
        help="Write to local Qdrant. Without this flag, only a dry-run preview is produced.",
    )
    args = parser.parse_args(argv)

    preview = count_chat_history_preview(args.chat_history_dir)
    text = json.dumps(preview, ensure_ascii=False, indent=2)
    if args.output is None:
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")

    if args.write_qdrant:
        config = load_knowledge_config(args.config).qdrant
        embedding_model = create_embedding_model(config)
        client = create_qdrant_client(config)
        indexed_count = index_chat_history_collection(
            client=client,
            config=config,
            root=args.chat_history_dir,
            embedding_model=embedding_model,
        )
        print(
            f"Indexed {indexed_count} chat-history records into "
            f"{config.data_collections['chat_history'].collection!r}.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
