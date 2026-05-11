"""End-to-end runner для проверки safety-net BUDGET-FLOOR + AUTO-RETRY.

Перед запуском:
  1) docker compose up -d (mgp-local-backend-1 healthy на :8080)
  2) В БД должен быть seeded assistant с slug=mgp-tour

Запуск:
  python3 .test_results/budget_upper_floor/run_tests.py [scenario_id ...]

Если scenario_id не указаны — прогоняется весь набор (13 сценариев + warmup).
Результаты складываются в JSON-файлы рядом со скриптом.

Что фиксируем для каждого сценария:
  - response payload (reply, tour_cards, crm_submitted)
  - SQL-snapshot tour_searches для этого conversation_id (price_from / price_to / tours_found / min_price)
  - выдержку из docker logs (BUDGET-FLOOR / AUTO-RETRY BUDGET-FLOOR / SAFETY-NET P7)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import urllib.request

API_URL = os.environ.get("CHAT_API_URL", "http://localhost:8080/api/v1/chat")
PG_CONTAINER = os.environ.get("MGP_PG_CONTAINER", "mgp-local-postgres-1")
BACKEND_CONTAINER = os.environ.get("MGP_BACKEND_CONTAINER", "mgp-local-backend-1")
OUTDIR = Path(__file__).resolve().parent

REQUEST_TIMEOUT_S = 120  # search_tours + actualize могут быть медленные
PER_SCENARIO_LOG_WINDOW = "5m"
MAX_STEPS = 4  # макс. сообщений на сценарий, если LLM переспрашивает

ASSISTANT_SLUG = "mgp-tour"


@dataclass
class Scenario:
    sid: str
    description: str
    budget_phrase: str  # фраза про бюджет в тексте клиенту
    direction: str
    departure: str = "Москва"
    dates: str = "с 03.06.2026"
    nights: int = 7
    composition: str = "2 взрослых"
    qc: str = "4 звезды, всё включено"
    expected_pricefrom: Optional[int] = None
    expected_priceto: Optional[int] = None
    expects_floor_applied: bool = True
    expects_auto_retry: bool = False  # будем смотреть в логи post factum
    note: str = ""

    def build_prompt(self) -> str:
        return (
            f"Привет! Подбери тур из {self.departure} в {self.direction} для {self.composition}, "
            f"вылет {self.dates}, на {self.nights} ночей. Бюджет {self.budget_phrase}. "
            f"{self.qc}."
        )


SCENARIOS: list[Scenario] = [
    # Основные сценарии: «до X» с разными бюджетами и направлениями
    Scenario(
        sid="S01_turkey_100k",
        description="Турция, июнь 2026, 7 ночей, 2 взр, бюджет до 100к",
        budget_phrase="до 100 000 рублей",
        direction="Турцию",
        dates="03.06.2026",
        expected_pricefrom=70_000,
        expected_priceto=100_000,
    ),
    Scenario(
        sid="S02_turkey_200k_kid",
        description="Турция, июль 2026, 10 ночей, 2 взр + ребёнок 8 лет, до 200к",
        budget_phrase="до 200к",
        direction="Турцию",
        dates="05.07.2026",
        nights=10,
        composition="2 взрослых и ребёнок 8 лет",
        expected_pricefrom=130_000,
        expected_priceto=200_000,
    ),
    Scenario(
        sid="S03_turkey_300k",
        description="Турция, август, 7 ночей, 2 взр, до 300к",
        budget_phrase="до 300к",
        direction="Турцию",
        dates="04.08.2026",
        expected_pricefrom=195_000,
        expected_priceto=300_000,
    ),
    Scenario(
        sid="S04_egypt_150k",
        description="Египет, сентябрь, 7 ночей, 2 взр, до 150к",
        budget_phrase="до 150к",
        direction="Египет",
        dates="07.09.2026",
        expected_pricefrom=105_000,
        expected_priceto=150_000,
    ),
    Scenario(
        sid="S05_uae_400k",
        description="ОАЭ, ноябрь, 7 ночей, 2 взр, до 400к",
        budget_phrase="до 400к",
        direction="ОАЭ",
        dates="03.11.2026",
        expected_pricefrom=260_000,
        expected_priceto=400_000,
    ),
    Scenario(
        sid="S06_greece_250k",
        description="Греция, август, 10 ночей, 2 взр, до 250к",
        budget_phrase="до 250к",
        direction="Грецию",
        dates="08.08.2026",
        nights=10,
        expected_pricefrom=162_500,
        expected_priceto=250_000,
    ),
    Scenario(
        sid="S07_maldives_600k",
        description="Мальдивы, февраль 2027, 10 ночей, 2 взр, до 600к — ожидается AUTO-RETRY",
        budget_phrase="до 600к",
        direction="Мальдивы",
        dates="05.02.2027",
        nights=10,
        qc="5 звёзд, всё включено",
        expected_pricefrom=390_000,
        expected_priceto=600_000,
        expects_auto_retry=True,
        note="Мальдивы — дорогое направление, в верхнем слоте часто мало туров",
    ),
    Scenario(
        sid="S08_thailand_500k",
        description="Таиланд, январь 2027, 10 ночей, 2 взр, до 500к",
        budget_phrase="до 500к",
        direction="Таиланд",
        dates="10.01.2027",
        nights=10,
        expected_pricefrom=325_000,
        expected_priceto=500_000,
    ),
    Scenario(
        sid="S07b_maldives_350k_retry",
        description="Мальдивы, март 2027, 10 ночей, 2 взр, до 350к — заведомо < 3 туров → AUTO-RETRY",
        budget_phrase="до 350к",
        direction="Мальдивы",
        dates="05.03.2027",
        nights=10,
        qc="5 звёзд, всё включено",
        expected_pricefrom=227_500,
        expected_priceto=350_000,
        expects_auto_retry=True,
        note="Бюджет заведомо узкий для Мальдив — проверяем что AUTO-RETRY срабатывает и LLM передаёт _warning",
    ),
    # Синонимы триггер-фразы
    Scenario(
        sid="S09_turkey_not_more_250k",
        description="Турция, июнь, 2 взр, «не более 250к»",
        budget_phrase="не более 250к",
        direction="Турцию",
        dates="10.06.2026",
        expected_pricefrom=162_500,
        expected_priceto=250_000,
    ),
    Scenario(
        sid="S10_turkey_max_200k",
        description="Турция, июнь, 2 взр, «максимум 200к»",
        budget_phrase="максимум 200к",
        direction="Турцию",
        dates="12.06.2026",
        expected_pricefrom=130_000,
        expected_priceto=200_000,
    ),
    # Негативные кейсы: safety-net НЕ должен срабатывать
    Scenario(
        sid="S11_turkey_range_150_300",
        description="Турция, июнь, 2 взр, диапазон «150-300к» (safety-net НЕ срабатывает)",
        budget_phrase="150-300к",
        direction="Турцию",
        dates="15.06.2026",
        expected_pricefrom=150_000,  # LLM сам положит
        expected_priceto=300_000,
        expects_floor_applied=False,
        note="LLM сам кладёт оба значения, safety-net BUDGET-FLOOR не должен трогать",
    ),
    Scenario(
        sid="S12_turkey_about_200k",
        description="Турция, июнь, 2 взр, «около 200к» — должен сработать existing safety-net «около»",
        budget_phrase="около 200к",
        direction="Турцию",
        dates="20.06.2026",
        expected_pricefrom=160_000,  # 0.8 × 200000
        expected_priceto=240_000,    # 1.2 × 200000
        expects_floor_applied=False,
        note="Срабатывает existing SAFETY-NET P7 «около», а не BUDGET-FLOOR",
    ),
    Scenario(
        sid="S13_turkey_any_budget",
        description="Турция, июнь, 2 взр, «любой бюджет» — skip, ничего не срабатывает",
        budget_phrase="без ограничения",
        direction="Турцию",
        dates="25.06.2026",
        expected_pricefrom=None,  # ожидаем NULL/0
        expected_priceto=None,
        expects_floor_applied=False,
        note="Skip-фраза: LLM не передаёт ни pricefrom, ни priceto",
    ),
    Scenario(
        sid="S14_uae_120k_retry_success",
        description="ОАЭ октябрь, 7 ночей, 2 взр, до 120к — в верхнем слоте нет → AUTO-RETRY должен найти варианты + _warning",
        budget_phrase="до 120к",
        direction="ОАЭ",
        dates="01.10.2026",
        nights=7,
        qc="4 звезды, завтрак",
        expected_pricefrom=84_000,
        expected_priceto=120_000,
        expects_auto_retry=True,
        note="ОАЭ за 120к на 7 ночей — обычно от 110-130к, в слоте 84-120k часто пусто",
    ),
    Scenario(
        sid="S15_turkey_60k_retry_success",
        description="Турция, июнь, 7 ночей, 2 взр, до 60к — узкий бюджет, в слоте 30-60k мало; ожидается AUTO-RETRY + _warning",
        budget_phrase="до 60к",
        direction="Турцию",
        dates="08.06.2026",
        nights=7,
        qc="3 звезды, завтрак",
        expected_pricefrom=30_000,  # MIN_WINDOW сработает: 60k - 30k = 30k (граница)
        expected_priceto=60_000,
        expects_auto_retry=True,
        note="Дешёвый бюджет: в слоте 30-60k обычно пусто, но без floor от 50-80k найдётся",
    ),
]


def http_post(url: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Assistant-Id": body.get("assistant_id", ""),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw}
        return e.code, parsed
    except Exception as e:
        return 0, {"error": f"transport: {e}"}


def get_assistant_id(slug: str) -> str:
    out = subprocess.run(
        [
            "docker", "exec", PG_CONTAINER, "psql", "-U", "mgp", "-d", "mgp",
            "-t", "-A", "-c",
            f"SELECT a.id FROM assistants a JOIN companies c ON c.id=a.company_id WHERE c.slug='{slug}' LIMIT 1;",
        ],
        capture_output=True, text=True, check=True,
    )
    aid = out.stdout.strip()
    if not aid:
        raise RuntimeError(f"assistant for slug={slug!r} not found")
    return aid


def fetch_tour_searches(conv_id: str) -> list[dict]:
    sql = (
        "SELECT id, price_from, price_to, country, adults, children, "
        "       nights_from, nights_to, hotels_found, tours_found, min_price, "
        "       to_char(created_at AT TIME ZONE 'Europe/Moscow', 'YYYY-MM-DD HH24:MI:SS') "
        f"FROM tour_searches WHERE conversation_id = '{conv_id}' ORDER BY created_at ASC;"
    )
    out = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "mgp", "-d", "mgp",
         "-t", "-A", "-F", "|", "-c", sql],
        capture_output=True, text=True, check=True,
    )
    rows = []
    for line in out.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 12:
            continue
        rows.append({
            "id": int(parts[0]) if parts[0].isdigit() else parts[0],
            "price_from": int(parts[1]) if parts[1] else None,
            "price_to": int(parts[2]) if parts[2] else None,
            "country": int(parts[3]) if parts[3] else None,
            "adults": int(parts[4]) if parts[4] else None,
            "children": int(parts[5]) if parts[5] else None,
            "nights_from": int(parts[6]) if parts[6] else None,
            "nights_to": int(parts[7]) if parts[7] else None,
            "hotels_found": int(parts[8]) if parts[8] else None,
            "tours_found": int(parts[9]) if parts[9] else None,
            "min_price": int(parts[10]) if parts[10] else None,
            "created_at_msk": parts[11],
        })
    return rows


def fetch_backend_logs(since: str = PER_SCENARIO_LOG_WINDOW) -> str:
    out = subprocess.run(
        ["docker", "logs", BACKEND_CONTAINER, "--since", since],
        capture_output=True, text=True, check=False,
    )
    return (out.stdout or "") + "\n" + (out.stderr or "")


def grep_marker_lines(text: str, marker: str) -> list[str]:
    return [ln for ln in text.split("\n") if marker in ln]


def call_chat(conv_id: str, assistant_id: str, message: str) -> dict[str, Any]:
    return http_post(API_URL, {
        "message": message,
        "conversation_id": conv_id,
        "assistant_id": assistant_id,
    })


def run_scenario(scn: Scenario, assistant_id: str) -> dict[str, Any]:
    conv_id = str(uuid.uuid4())
    t0 = time.time()
    print(f"\n=== {scn.sid} — {scn.description}")
    print(f"    conv_id={conv_id}")

    messages_sent: list[str] = []
    responses: list[dict[str, Any]] = []

    msg = scn.build_prompt()
    messages_sent.append(msg)
    print(f"    >>> client: {msg}")
    status, payload = call_chat(conv_id, assistant_id, msg)
    responses.append({"status": status, "payload": payload})
    print(f"    <<< status={status}  cards={len(payload.get('tour_cards') or [])}  reply_len={len(payload.get('reply') or '')}")

    # Если LLM ничего не нашёл и переспрашивает (без tour_cards) — ткнём ещё 1-2 раза
    step = 1
    while step < MAX_STEPS and not (payload.get("tour_cards") or "").__class__ is list:
        break  # sentinel — placeholder; полноценно расширим если понадобится
    while step < MAX_STEPS and not payload.get("tour_cards"):
        reply = (payload.get("reply") or "").lower()
        # эвристика: что отвечать
        followup = "Запускай поиск, все параметры я уже указал — посмотрим что есть."
        if "сколько" in reply or "город" in reply:
            followup = "Из Москвы, 2 взрослых, на 7 ночей, " + scn.budget_phrase + "."
        if "звёзд" in reply or "звезд" in reply or "питани" in reply:
            followup = scn.qc + "."
        messages_sent.append(followup)
        print(f"    >>> client (step {step+1}): {followup}")
        status, payload = call_chat(conv_id, assistant_id, followup)
        responses.append({"status": status, "payload": payload})
        print(f"    <<< status={status}  cards={len(payload.get('tour_cards') or [])}  reply_len={len(payload.get('reply') or '')}")
        step += 1

    # дать backend время дописать tour_searches в БД
    time.sleep(1)

    elapsed = time.time() - t0
    rows = fetch_tour_searches(conv_id)
    logs = fetch_backend_logs(since="3m")
    floor_lines = grep_marker_lines(logs, "BUDGET-FLOOR:")
    retry_lines = grep_marker_lines(logs, "AUTO-RETRY BUDGET-FLOOR:")
    about_lines = grep_marker_lines(logs, "SAFETY-NET P7:")

    # сузим до тех что относятся к conv_id (best-effort: смотрим в окно 3 минуты)
    return {
        "scenario": {
            "sid": scn.sid,
            "description": scn.description,
            "budget_phrase": scn.budget_phrase,
            "direction": scn.direction,
            "departure": scn.departure,
            "dates": scn.dates,
            "nights": scn.nights,
            "composition": scn.composition,
            "qc": scn.qc,
            "expected_pricefrom": scn.expected_pricefrom,
            "expected_priceto": scn.expected_priceto,
            "expects_floor_applied": scn.expects_floor_applied,
            "expects_auto_retry": scn.expects_auto_retry,
            "note": scn.note,
        },
        "runtime": {
            "elapsed_s": round(elapsed, 2),
            "steps": len(messages_sent),
            "conv_id": conv_id,
        },
        "messages_sent": messages_sent,
        "final_payload": responses[-1]["payload"] if responses else {},
        "tour_searches": rows,
        "marker_lines": {
            "BUDGET-FLOOR": floor_lines[-3:],
            "AUTO-RETRY BUDGET-FLOOR": retry_lines[-6:],
            "SAFETY-NET P7": about_lines[-3:],
        },
    }


def main(argv: list[str]) -> int:
    assistant_id = get_assistant_id(ASSISTANT_SLUG)
    print(f"assistant_id({ASSISTANT_SLUG}) = {assistant_id}")

    if len(argv) > 1:
        wanted = set(argv[1:])
        selected = [s for s in SCENARIOS if s.sid in wanted]
        if not selected:
            print(f"No scenarios match: {wanted}", file=sys.stderr)
            return 2
    else:
        selected = SCENARIOS

    results: list[dict] = []
    for scn in selected:
        try:
            result = run_scenario(scn, assistant_id)
        except Exception as e:
            print(f"!!! {scn.sid} crashed: {e}")
            result = {
                "scenario": {"sid": scn.sid, "description": scn.description},
                "error": str(e),
            }
        results.append(result)
        outfile = OUTDIR / f"{scn.sid}.json"
        outfile.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    saved → {outfile.name}")

    summary_file = OUTDIR / "_all_runs.json"
    summary_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAll {len(results)} scenarios done → {summary_file.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
