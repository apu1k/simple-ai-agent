from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.knowledge.indexes import capability_embedding_text
from tools.knowledge.registry import DEFAULT_CAPABILITIES_DIR, load_capability_definitions


def build_capability_index_preview(capabilities_dir: Path) -> list[dict]:
    capabilities = load_capability_definitions(capabilities_dir)
    return [
        {
            "id": capability.id,
            "name": capability.name,
            "handler": capability.handler,
            "tags": capability.tags,
            "required_permissions": capability.required_permissions,
            "allow_network": capability.allow_network,
            "sensitivity": capability.sensitivity,
            "embedding_text": capability_embedding_text(capability),
        }
        for capability in capabilities
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a dry-run preview of capability texts that will later be embedded "
            "and stored in the Qdrant capability index."
        )
    )
    parser.add_argument(
        "--capabilities-dir",
        type=Path,
        default=DEFAULT_CAPABILITIES_DIR,
        help="Directory containing capability YAML files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write JSON output. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    preview = build_capability_index_preview(args.capabilities_dir)
    text = json.dumps(preview, ensure_ascii=False, indent=2)

    if args.output is None:
        print(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
