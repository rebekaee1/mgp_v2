"""Unit-sanity для канальной атрибуции (фаза A, backend-only).

Проверяет логику нормализации значений `channel` и `external_user_id`,
зеркально к коду в backend/app.py:_log_chat_to_db. Не запускает реальный
backend / Postgres — чистая логика.

Запуск:
    python3 .test_results/channel_attribution/test_sanity.py
"""
from __future__ import annotations

import sys


# Тот же contract что и в backend/app.py:_log_chat_to_db
ALLOWED_CHANNELS = {"widget", "max"}
DEFAULT_CHANNEL = "widget"
MAX_EXT_UID_LEN = 64


def normalize_channel(value: str | None) -> str:
    if value is None:
        return DEFAULT_CHANNEL
    v = (value or "").strip().lower()
    if v not in ALLOWED_CHANNELS:
        return DEFAULT_CHANNEL
    return v


def normalize_external_user_id(value: str | None) -> str | None:
    if value is None:
        return None
    v = (value or "").strip()
    if not v:
        return None
    if len(v) > MAX_EXT_UID_LEN:
        v = v[:MAX_EXT_UID_LEN]
    return v


CHANNEL_CASES: list[tuple[str | None, str, str]] = [
    # (input, expected, description)
    (None, "widget", "no header"),
    ("", "widget", "empty string"),
    ("   ", "widget", "whitespace only"),
    ("widget", "widget", "normal widget"),
    ("max", "max", "normal max"),
    ("MAX", "max", "uppercase max"),
    ("  Max  ", "max", "padded max"),
    ("telegram", "widget", "future channel (not in enum) → fallback widget"),
    ("malicious; DROP TABLE", "widget", "injection-like garbage → fallback"),
    ("max\n", "max", "trailing newline"),
]


EXT_UID_CASES: list[tuple[str | None, str | None, str]] = [
    (None, None, "no header"),
    ("", None, "empty string"),
    ("   ", None, "whitespace only"),
    ("213771498", "213771498", "MAX numeric user_id"),
    ("a" * 65, "a" * 64, "over-length truncated to 64"),
    ("  99887766  ", "99887766", "trimmed"),
    ("99887766\n", "99887766", "newline trimmed"),
]


def run() -> int:
    failed = 0
    for inp, expected, desc in CHANNEL_CASES:
        got = normalize_channel(inp)
        ok = got == expected
        marker = "ok " if ok else "FAIL"
        print(f"  channel  [{marker}] {desc:<48s} in={inp!r:<25} → {got!r:<10} (exp {expected!r})")
        if not ok:
            failed += 1

    for inp, expected, desc in EXT_UID_CASES:
        got = normalize_external_user_id(inp)
        ok = got == expected
        marker = "ok " if ok else "FAIL"
        in_repr = (inp[:25] + "...") if inp and len(inp) > 25 else repr(inp)
        out_repr = (got[:25] + "...") if got and len(got) > 25 else repr(got)
        exp_repr = (expected[:25] + "...") if expected and len(expected) > 25 else repr(expected)
        print(f"  ext_uid  [{marker}] {desc:<48s} in={in_repr:<25} → {out_repr:<28} (exp {exp_repr})")
        if not ok:
            failed += 1

    total = len(CHANNEL_CASES) + len(EXT_UID_CASES)
    print()
    if failed:
        print(f"FAIL — {failed}/{total} checks failed")
        return 1
    print(f"OK — {total} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
