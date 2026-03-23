from __future__ import annotations

from typing import Iterable, List, Sequence


_INTERNAL_USER_PREFIXES = (
    "СИСТЕМНАЯ ОШИБКА:",
    "Пожалуйста, продолжи",
    "Продолжи обработку",
    "Ответь клиенту нормальным текстом",
)


def is_internal_runtime_user_message(role: str | None, content: str | None) -> bool:
    if role != "user":
        return False
    text = (content or "").strip()
    return any(text.startswith(prefix) for prefix in _INTERNAL_USER_PREFIXES)


def filter_runtime_snapshot_entries(entries: Sequence[dict]) -> List[dict]:
    filtered: List[dict] = []
    for entry in entries:
        role = entry.get("role")
        content = entry.get("content") or ""
        if is_internal_runtime_user_message(role, content):
            if filtered and filtered[-1].get("role") == "assistant":
                filtered.pop()
            continue
        filtered.append(entry)
    return filtered


def filter_runtime_message_rows(rows: Iterable[object]) -> List[object]:
    filtered: List[object] = []
    for row in rows:
        role = getattr(row, "role", None)
        content = getattr(row, "content", None)
        if is_internal_runtime_user_message(role, content):
            if filtered and getattr(filtered[-1], "role", None) == "assistant":
                filtered.pop()
            continue
        filtered.append(row)
    return filtered
