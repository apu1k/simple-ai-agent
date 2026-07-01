from __future__ import annotations

import json
import re
from pathlib import Path


SEARCHABLE_SUFFIXES = {".json", ".jsonl", ".txt", ".md"}


class JsonChatStore:
    def __init__(self, root: Path):
        self.root = root

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        if not self.root.exists() or not self.root.is_dir():
            return []

        query_tokens = _tokens(query)
        results: list[dict] = []

        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SEARCHABLE_SUFFIXES:
                continue

            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        score = _match_score(query, query_tokens, line)
                        if score <= 0:
                            continue

                        results.append(
                            {
                                "path": str(path),
                                "line": line_number,
                                "content": line.strip(),
                                "score": score,
                            }
                        )
            except OSError:
                continue

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:max_results]


class SimpleMemoryStore:
    def __init__(self, path: Path):
        self.path = path

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        if not self.path.exists() or not self.path.is_file():
            return []

        query_tokens = _tokens(query)
        results: list[dict] = []

        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue

            content = line
            metadata = {}

            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    content = str(
                        parsed.get("content")
                        or parsed.get("text")
                        or parsed.get("memory")
                        or line
                    )
                    metadata = {
                        key: value
                        for key, value in parsed.items()
                        if key not in {"content", "text", "memory"}
                    }
            except json.JSONDecodeError:
                pass

            score = _match_score(query, query_tokens, content)
            if score <= 0:
                continue

            results.append(
                {
                    "path": str(self.path),
                    "line": line_number,
                    "content": content.strip(),
                    "metadata": metadata,
                    "score": score,
                }
            )

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:max_results]


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_äöüÄÖÜß-]+", text.lower())
        if len(token) >= 2
    }


def _match_score(query: str, query_tokens: set[str], text: str) -> float:
    text_lower = text.lower()
    query_lower = query.lower().strip()

    if not query_lower:
        return 0.0

    if query_lower in text_lower:
        return 1.0

    text_tokens = _tokens(text)
    if not query_tokens:
        return 0.0

    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)
