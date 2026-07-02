from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SEARCHABLE_SUFFIXES = {".json", ".jsonl", ".txt", ".md"}
MAX_EVIDENCE_CONTENT_CHARS = 4_000
SNIPPET_CONTEXT_CHARS = 800


class JsonChatStore:
    def __init__(self, root: Path):
        self.root = root

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        if not self.root.exists() or not self.root.is_dir():
            return []

        query_tokens = _tokens(query)
        results: list[dict] = []
        seen_content: set[str] = set()

        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SEARCHABLE_SUFFIXES:
                continue

            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        parsed = _parse_chat_line(line)
                        searchable_content = parsed["searchable_content"]
                        score = _match_score(query, query_tokens, searchable_content)
                        if score <= 0:
                            continue

                        display_content = _make_relevant_snippet(
                            parsed["display_content"],
                            query,
                            query_tokens,
                        )
                        dedupe_key = _normalize_for_dedup(display_content)
                        if dedupe_key in seen_content:
                            continue
                        seen_content.add(dedupe_key)

                        results.append(
                            {
                                "path": str(path),
                                "line": line_number,
                                "content": display_content,
                                "score": score,
                                "metadata": parsed["metadata"],
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


def _parse_chat_line(line: str) -> dict[str, Any]:
    stripped = line.strip()
    if not stripped:
        return {
            "searchable_content": "",
            "display_content": "",
            "metadata": {},
        }

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {
            "searchable_content": stripped,
            "display_content": stripped,
            "metadata": {"format": "text"},
        }

    if not isinstance(parsed, dict):
        text = str(parsed)
        return {
            "searchable_content": text,
            "display_content": text,
            "metadata": {"format": "json"},
        }

    user_text = _string_value(parsed.get("user"))
    assistant_text = _string_value(
        parsed.get("assistant_final")
        or parsed.get("assistant")
        or parsed.get("assistant_message")
    )
    content_text = _string_value(parsed.get("content") or parsed.get("text"))
    role_text = _string_value(parsed.get("role"))

    display_parts: list[str] = []
    if user_text:
        display_parts.append(f"User: {user_text}")
    if assistant_text:
        display_parts.append(f"Assistant: {assistant_text}")
    if content_text and not display_parts:
        prefix = f"{role_text.capitalize()}: " if role_text else ""
        display_parts.append(f"{prefix}{content_text}")

    display_content = "\n\n".join(display_parts) or stripped
    searchable_content = "\n".join(
        part
        for part in [user_text, assistant_text, content_text, stripped]
        if part
    )

    metadata = {
        "format": "jsonl",
        "session_id": parsed.get("session_id"),
        "turn_index": parsed.get("turn_index"),
        "source": parsed.get("source"),
        "stream": parsed.get("stream"),
        "type": parsed.get("type"),
        "created_at": parsed.get("created_at"),
    }
    metadata = {key: value for key, value in metadata.items() if value is not None}

    return {
        "searchable_content": searchable_content,
        "display_content": display_content,
        "metadata": metadata,
    }


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _make_relevant_snippet(
    content: str,
    query: str,
    query_tokens: set[str],
) -> str:
    cleaned = content.strip()
    if len(cleaned) <= MAX_EVIDENCE_CONTENT_CHARS:
        return cleaned

    lower = cleaned.lower()
    query_lower = query.lower().strip()
    match_index = lower.find(query_lower) if query_lower else -1

    if match_index < 0:
        token_positions = [lower.find(token) for token in query_tokens]
        token_positions = [position for position in token_positions if position >= 0]
        match_index = min(token_positions) if token_positions else 0

    start = max(0, match_index - SNIPPET_CONTEXT_CHARS)
    end = min(len(cleaned), match_index + len(query_lower) + SNIPPET_CONTEXT_CHARS)
    snippet = cleaned[start:end].strip()

    if start > 0:
        snippet = "…" + snippet
    if end < len(cleaned):
        snippet = snippet + "…"

    return snippet


def _normalize_for_dedup(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().lower()


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
