#!/usr/bin/env python3
"""Behavioral tests for the re-outreach FOLLOW-UP handling (prod brain, in-process).

Seeds ONE real dialogue (Turkey -> cards), snapshots handler state, then for each
scenario restores the snapshot, appends the re-outreach as the last assistant
message (as the prod fix persists it), feeds a client reply, and observes:
  - did the assistant run a fresh search_tours?  with what args (hotels= filter)?
  - did it remember params / not re-ask?
  - did it behave correctly for "no" / pivot / question / "earlier tours"?

Run from backend/ dir:
  cd backend && python3 ../.test_results/reoutreach/behavior_test.py
Creds: /tmp/mgp_e2e_creds.env (prod, funded) overrides workspace .env.
"""
import os
import sys
import json
import copy
import asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))
_CREDS = os.environ.get("MGP_E2E_CREDS", "/tmp/mgp_e2e_creds.env")
if os.path.exists(_CREDS):
    load_dotenv(_CREDS, override=True)

import logging  # noqa: E402
logging.disable(logging.WARNING)
from openai_handler import OpenAIHandler  # noqa: E402

REOUTREACH = ("Здравствуйте! Вы смотрели туры в Турцию из Москвы, 2 взрослых. "
             "Цены могли обновиться — прислать свежую подборку под ваш бюджет до 200 000 ₽?")
SEED_OPENING = ("Здравствуйте! Турция из Москвы, 2 взрослых, 4 звезды всё включено, "
                "вылет в середине августа 2026 на 7 ночей, бюджет до 200 000 рублей.")
SEED_FOLLOWUPS = ["Да, в середине августа.", "Да, запускайте поиск.", "Покажите варианты."]

SNAP = ["full_history", "input_list", "_tourid_map", "_pinned_context",
        "_pinned_search_intent", "_collected_slots", "_last_search_params",
        "_last_search_result", "_last_full_search_args", "_pending_tour_cards",
        "_last_requestid"]


def snapshot(h):
    return {k: copy.deepcopy(getattr(h, k)) for k in SNAP if hasattr(h, k)}


def restore(h, snap):
    for k, v in snap.items():
        setattr(h, k, copy.deepcopy(v))


def wrap_search(h):
    orig = h.tourvisor.search_tours
    calls = []

    async def _w(**kw):
        calls.append(kw)
        return await orig(**kw)
    h.tourvisor.search_tours = _w
    return calls, orig


async def seed(h):
    msg, fu, last = SEED_OPENING, 0, ""
    for _ in range(6):
        last = await h.chat(msg)
        if h._pending_tour_cards:
            return last
        msg = SEED_FOLLOWUPS[fu] if fu < len(SEED_FOLLOWUPS) else "На ваше усмотрение, покажите варианты."
        fu += 1
    return last


async def scenario(h, snap, name, replies, pinned=None, append_reoutreach=True):
    restore(h, snap)
    if pinned is not None:
        h._pinned_context = pinned
    if append_reoutreach:
        h.full_history.append({"role": "assistant", "content": REOUTREACH})
    h._pending_tour_cards = []
    calls, orig = wrap_search(h)
    turns = []
    for msg in replies:
        rep = await h.chat(msg)
        turns.append({"client": msg, "assistant": rep, "cards_now": len(h._pending_tour_cards)})
        if h._pending_tour_cards:
            break
    h.tourvisor.search_tours = orig
    return {
        "name": name,
        "searched": len(calls),
        "search_hotels_arg": [c.get("hotels") for c in calls],
        "search_country_arg": [c.get("country") for c in calls],
        "cards": len(h._pending_tour_cards),
        "turns": turns,
    }


def fmt(res):
    print(f"\n{'='*78}\n### {res['name']}")
    print(f"searched={res['searched']}  cards={res['cards']}  "
          f"hotels_arg={res['search_hotels_arg']}  country_arg={res['search_country_arg']}")
    for t in res["turns"]:
        print(f"  CLIENT: {t['client']}")
        print(f"  ASSIST: {(t['assistant'] or '')[:280]}")


async def main():
    h = OpenAIHandler()
    print(">>> seeding opening dialogue (Turkey -> cards)...")
    await seed(h)
    print(f"    seeded: cards={len(h._pending_tour_cards)}  tourid_map={ {k: v.get('hotelname') for k,v in (h._tourid_map or {}).items()} }")
    seed_codes = [str(v.get("hotelcode")) for v in (h._tourid_map or {}).values() if v.get("hotelcode")]
    seed_names = [v.get("hotelname") for v in (h._tourid_map or {}).values()]
    snap = snapshot(h)

    results = []
    # R1: positive -> fresh search
    results.append(await scenario(h, snap, "R1 «да, новую подборку» → ожидаем новый поиск",
                                  ["Да, покажите новую подборку, пожалуйста."]))
    # R2: refusal -> no push
    results.append(await scenario(h, snap, "R2 «нет, пока думаю» → ожидаем мягкий отказ без поиска",
                                  ["Нет, спасибо, я пока просто думаю."]))
    # R3: pivot -> new destination
    results.append(await scenario(h, snap, "R3 «а лучше Египет» → ожидаем переключение/поиск Египта",
                                  ["А давайте лучше Египет посмотрим, те же даты и бюджет.",
                                   "Да, запускайте поиск."]))
    # R4: question -> answer in context
    results.append(await scenario(h, snap, "R4 встречный вопрос → ответ в контексте",
                                  ["А подскажите, перелёт входит в стоимость тура?"]))

    # V1: Variant A — labeled pinned context with EARLIER hotels -> targeted hotels= search
    pinned = (
        "[КОНТЕКСТ: текущие показанные туры]\n(нет активной подборки)\n\n"
        "[КОНТЕКСТ: ранее показанные туры — для справки, цены могли измениться]\n"
        + "\n".join(f"- {n} (hotelcode={c})" for n, c in zip(seed_names, seed_codes))
        + "\nЕсли клиент ссылается на ранее показанные/предыдущие варианты — это ИМЕННО "
          "отели из списка выше. Чтобы показать их с АКТУАЛЬНЫМИ ценами, вызови search_tours "
          "с параметром hotels=<hotelcode этих отелей через запятую> и теми же датами/составом "
          "(НЕ делай общий поиск). Если какого-то отеля нет — честно скажи и предложи альтернативы."
    )
    results.append(await scenario(h, snap, "V1 «покажите те, что показывали ранее» → ожидаем search_tours(hotels=...)",
                                  ["А покажите, пожалуйста, те варианты, что вы показывали ранее.",
                                   "Да, именно их."],
                                  pinned=pinned))

    for r in results:
        fmt(r)

    print(f"\n\n=== SEED hotelcodes: {seed_codes} ===")
    with open(os.path.join(HERE, "behavior_report.json"), "w", encoding="utf-8") as fh:
        json.dump({"seed_codes": seed_codes, "results": results}, fh, ensure_ascii=False, indent=2)
    print("saved -> behavior_report.json")


if __name__ == "__main__":
    asyncio.run(main())
