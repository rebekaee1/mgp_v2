#!/usr/bin/env python3
"""Local smoke tests for the new Moscow / Подмосковье / hotline office logic.

Targets local backend at http://localhost:8080/api/v1/chat with assistant_id
read from environment ASSISTANT_ID (default: the only active local assistant).

Six scenarios per the task spec; outputs JSON per test + builds a summary table.
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

BASE = "http://localhost:8080/api/v1/chat"
ASSISTANT_ID = os.environ.get("ASSISTANT_ID", "8f38186c-444f-45ad-9cad-734bd1481a59")
OUT_DIR = Path(__file__).parent

SCENARIOS = [
    {
        "id": "T1",
        "title": "Москва без района — 5-7 адресов",
        "history": [
            "Хочу подъехать в офис лично",
            "В Москве",
        ],
        "must_have": ["м. ", "Москв"],
        "must_not_have": ["нет офиса", "офиса нет", "не нашли"],
        "min_metro_mentions": 4,
    },
    {
        "id": "T2",
        "title": "Москва, метро Чистые Пруды (нет точного офиса)",
        "history": ["Дайте адрес офиса в Москве у метро Чистые пруды"],
        "should_have_any": ["Курск", "Красн", "Земляной", "Садов"],
        "must_not_have": [
            "Чистые пруды | ",
            "м. Чистые пруды | (",
        ],
    },
    {
        "id": "T3",
        "title": "Калининград (офиса нет)",
        "history": ["А офис в Калининграде есть?"],
        "must_have": ["нет", "Калининград"],
        "should_have_any": ["8 800 100-99-77", "горячая", "онлайн", "online@mgp.ru"],
    },
    {
        "id": "T4",
        "title": "Санкт-Петербург — много офисов",
        "history": ["Где ваш офис в СПб?"],
        "must_have": ["санкт"],
        "spb_office_keywords": ["купчин", "ладож", "гатчин", "пушкин", "старая деревн", "большевиков", "парк побед"],
        "min_spb_offices": 3,
    },
    {
        "id": "T5",
        "title": "Главный телефон — горячая линия",
        "history": ["Какой у вас главный телефон?"],
        "must_have": ["8 800 100-99-77"],
        "should_have_any": ["+7 (499) 685-25-57", "499) 685-25-57"],
    },
    {
        "id": "T6",
        "title": "Юго-западная Москва",
        "history": ["Я живу на юго-западе Москвы, где ваш ближайший офис?"],
        "should_have_any": ["Калужская", "Обручева", "Пражская", "Кировоградская"],
        "must_not_have": ["нет офиса в Москве", "офиса в Москве нет"],
    },
]


def send(conv_id: str, message: str) -> dict:
    body = {
        "message": message,
        "conversation_id": conv_id,
        "assistant_id": ASSISTANT_ID,
    }
    body_json = json.dumps(body, ensure_ascii=False).encode("utf-8")
    cmd = [
        "curl", "-sS", "-m", "120", "-X", "POST", BASE,
        "-H", "Content-Type: application/json",
        "-H", f"X-Assistant-Id: {ASSISTANT_ID}",
        "--data-binary", "@-",
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, input=body_json, capture_output=True, timeout=140)
    dt = time.time() - t0
    raw = proc.stdout.decode("utf-8", "replace") or proc.stderr.decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"_error": "non-json", "_raw": raw[:400], "elapsed": dt}
    data["_elapsed"] = round(dt, 1)
    return data


def _norm(s: str) -> str:
    """Normalize unicode dashes / NBSP / case so substring checks are robust to LLM whim."""
    return (
        s.lower()
        .replace("\u2011", "-")  # non-breaking hyphen
        .replace("\u2013", "-")  # en dash
        .replace("\u2014", "-")  # em dash
        .replace("\u00a0", " ")  # nbsp
        .replace("ё", "е")
    )


def check(reply: str, scenario: dict) -> dict:
    fails = []
    passes = []
    r = _norm(reply)
    for needle in scenario.get("must_have", []):
        if _norm(needle) in r:
            passes.append(f"has '{needle}'")
        else:
            fails.append(f"MISSING '{needle}'")
    for needle in scenario.get("must_not_have", []):
        if _norm(needle) in r:
            fails.append(f"FORBIDDEN '{needle}' present")
        else:
            passes.append(f"no '{needle}' (ok)")
    if scenario.get("should_have_any"):
        if any(_norm(n) in r for n in scenario["should_have_any"]):
            passes.append(f"any-of {scenario['should_have_any'][:2]}…")
        else:
            fails.append(f"NONE of {scenario['should_have_any']}")
    if scenario.get("min_metro_mentions"):
        cnt = len(re.findall(r"м\.\s*[А-ЯЁA-Z][а-яёa-z\- ]+", reply))
        if cnt >= scenario["min_metro_mentions"]:
            passes.append(f"metro-mentions={cnt} (≥{scenario['min_metro_mentions']})")
        else:
            fails.append(f"metro-mentions={cnt} (<{scenario['min_metro_mentions']})")
    if scenario.get("min_spb_offices"):
        cnt = sum(1 for kw in scenario["spb_office_keywords"] if kw in r)
        if cnt >= scenario["min_spb_offices"]:
            passes.append(f"spb-offices={cnt} (≥{scenario['min_spb_offices']})")
        else:
            fails.append(f"spb-offices={cnt} (<{scenario['min_spb_offices']})")
    return {"pass": not fails, "passes": passes, "fails": fails}


def main():
    print(f"Backend: {BASE}")
    print(f"Assistant: {ASSISTANT_ID}\n")
    summary = []
    for sc in SCENARIOS:
        print(f"=== {sc['id']}: {sc['title']} ===")
        conv_id = str(uuid.uuid4())
        out_file = OUT_DIR / f"{sc['id']}.json"
        history_records = []
        final_reply = ""
        for i, msg in enumerate(sc["history"], 1):
            print(f"  → [{i}] {msg!r}")
            resp = send(conv_id, msg)
            reply = resp.get("reply", "") or resp.get("_raw", "")
            history_records.append({"user": msg, "assistant": reply, "elapsed": resp.get("_elapsed")})
            final_reply = reply
        verdict = check(final_reply, sc)
        record = {
            "id": sc["id"],
            "title": sc["title"],
            "conversation_id": conv_id,
            "turns": history_records,
            "final_reply": final_reply,
            "verdict": verdict,
        }
        out_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        status = "PASS" if verdict["pass"] else "FAIL"
        print(f"  ← reply ({len(final_reply)} chars): {final_reply[:140]!r}")
        print(f"  → {status}: {' | '.join(verdict['passes'][:3])}")
        if verdict["fails"]:
            print(f"     FAILS: {verdict['fails']}")
        print()
        summary.append({"id": sc["id"], "title": sc["title"], "status": status, "fails": verdict["fails"]})

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for s in summary if s["status"] == "PASS")
    print(f"=== TOTAL: {passed}/{len(summary)} PASS ===")
    sys.exit(0 if passed == len(summary) else 1)


if __name__ == "__main__":
    main()
