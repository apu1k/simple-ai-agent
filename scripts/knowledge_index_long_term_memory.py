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
from tools.knowledge.indexes.long_term_memory import index_long_term_memory_collection
from tools.knowledge.stores.qdrant import create_qdrant_client


def count_long_term_memory_preview(memory_path: Path) -> dict:
    """Return a small dry-run preview for long-term-memory evidence indexing."""
    from tools.knowledge.indexes.long_term_memory import iter_long_term_memory_records

    records = list(iter_long_term_memory_records(memory_path))
    return {
        "memory_path": str(memory_path),
        "record_count": len(records),
        "sample": records[:3],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Index local long-term memory into the normal Qdrant evidence collection. "
            "Default mode is a safe dry-run preview."
        )
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

    preview = count_long_term_memory_preview(args.memory_path)
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
        indexed_count = index_long_term_memory_collection(
            client=client,
            config=config,
            path=args.memory_path,
            embedding_model=embedding_model,
        )
        print(
            f"Indexed {indexed_count} long-term-memory records into "
            f"{config.data_collections['long_term_memory'].collection!r}.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
