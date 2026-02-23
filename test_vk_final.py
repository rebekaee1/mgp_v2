#!/usr/bin/env python3
"""
Final VK real-query testing: 20 scenarios with full dialogues.
Each scenario: initial query → bot follow-ups → cards → full consultation cycle.
Consultation includes: hotel info, actualize, flight details, FAQ, direction/param change.
"""

import requests
import time
import json
import re
import sys

BASE = "http://localhost:8080/api/v1/chat"

def chat(conv_id, msg, timeout=180):
    s = time.time()
    try:
        r = requests.post(BASE, json={"message": msg, "conversation_id": conv_id}, timeout=timeout)
        d = r.json()
        return {
            "reply": d.get("reply", ""),
            "cards": d.get("tour_cards", []),
            "n_cards": len(d.get("tour_cards", [])),
            "time": round(time.time() - s, 1),
        }
    except Exception as e:
        return {"reply": f"ERROR: {e}", "cards": [], "n_cards": 0, "time": round(time.time() - s, 1)}


def detect_question_type(reply):
    r = reply.lower()

    if any(w in r for w in ["сколько взрослых", "состав", "кто едет", "сколько человек",
                             "будут ли дети", "сколько будет взрослых", "сколько путешественник"]):
        return "travelers"
    if any(w in r for w in ["звёзд", "звезд", "питан", "категори", "предпочтен",
                             "класс отел", "тип размещ"]):
        return "quality"
    if any(w in r for w in ["город вылета", "из какого города", "откуда вылет",
                             "откуда планируете", "из какого"]):
        return "departure"
    if any(w in r for w in ["когда планируете", "какие даты", "какого числа",
                             "период", "промежут", "в каком месяце",
                             "когда хотите", "на какие даты"]):
        return "dates"
    if any(w in r for w in ["сколько ночей", "на сколько ночей", "продолжительность"]):
        return "nights"
    if any(w in r for w in ["направлен", "страну", "куда хотите", "куда планируете"]):
        return "destination"
    if any(w in r for w in ["бюджет", "стоимость"]):
        return "budget"
    return "unknown"


SCENARIOS = [
    {
        "id": "vk01",
        "name": "Египет из Казани, 7 ночей",
        "initial": "Здравствуйте, хочу в Египет из Казани, 28 марта на 7 ночей",
        "followups": {
            "travelers": "двое взрослых",
            "quality": "4 звезды, все включено",
            "dates": "28 марта на 7 ночей",
            "departure": "из Казани",
            "destination": "Египет",
        },
        "consult_extra": {"type": "change_params", "msg": "А если посмотреть 5 звёзд с тем же питанием?"},
    },
    {
        "id": "vk02",
        "name": "Мальдивы из Москвы, 10 ночей",
        "initial": "Здравствуйте, хотел бы уехать на Мальдивы из Москвы, 14 июня на 10 ночей, двое взрослых, 5 звёзд, всё включено",
        "followups": {},
        "consult_extra": {"type": "faq", "msg": "Нужна ли виза на Мальдивы?"},
    },
    {
        "id": "vk03",
        "name": "ОАЭ из Москвы, 6 ночей",
        "initial": "ОАЭ из Москвы, 14 апреля на 6 ночей, двое взрослых",
        "followups": {"quality": "4 звезды, завтрак"},
        "consult_extra": {"type": "change_dir", "msg": "А посмотрите такое же в Египте?"},
    },
    {
        "id": "vk04",
        "name": "Сейшелы из Москвы, 7 ночей",
        "initial": "Сейшелы из Москвы, середина мая, 7 ночей, двое взрослых, 5 звёзд, всё включено",
        "followups": {"dates": "15 мая"},
        "consult_extra": {"type": "faq", "msg": "Что обычно входит в стоимость тура?"},
    },
    {
        "id": "vk05",
        "name": "ОАЭ из Екатеринбурга, 5 ночей",
        "initial": "Здравствуйте, ОАЭ из Екатеринбурга, конец апреля на 5 ночей, двое взрослых",
        "followups": {
            "quality": "4 звезды, полупансион",
            "dates": "25 апреля",
        },
        "consult_extra": {"type": "change_params", "msg": "А если все включено вместо полупансиона?"},
    },
    {
        "id": "vk06",
        "name": "Египет, семья с ребёнком, 10 ночей",
        "initial": "Добрый вечер, хотели бы подобрать тур: Египет конец мая, из Москвы, 2 взрослых + ребёнок 7 лет, 10 ночей, 5 звёзд, всё включено",
        "followups": {
            "quality": "5 звёзд, всё включено",
            "dates": "25 мая на 10 ночей",
            "travelers": "2 взрослых и ребенок 7 лет",
        },
        "consult_extra": {"type": "change_dir", "msg": "А в Турцию с такими же параметрами?"},
    },
    {
        "id": "vk07",
        "name": "Таиланд, бюджет 250т",
        "initial": "Тайланд, после 15 марта, на 7 дней, 2 взрослых и ребенок 5 лет, бюджет до 250 тысяч, из Москвы",
        "followups": {
            "quality": "4 звезды, все включено",
            "departure": "из Москвы",
            "dates": "17 марта",
        },
        "consult_extra": {"type": "faq", "msg": "Включён ли трансфер из аэропорта?"},
    },
    {
        "id": "vk08",
        "name": "Мальдивы из СПб, семья",
        "initial": "Подскажите варианты на Мальдивы, вылет 28 марта на 7 дней из Санкт-Петербурга, 2 взрослых и 2 ребёнка 9 лет",
        "followups": {"quality": "5 звёзд, всё включено"},
        "consult_extra": {"type": "change_params", "msg": "А если на 10 ночей вместо 7?"},
    },
    {
        "id": "vk09",
        "name": "Турция Алания, бюджет 80 тыс",
        "initial": "Добрый день! Турция Алания, даты вылета 18-20 июня, 5-6 ночей, всё включено, 2 взрослых, из Москвы",
        "followups": {
            "quality": "4 звезды, всё включено",
            "dates": "18 июня на 6 ночей",
        },
        "consult_extra": {"type": "change_dir", "msg": "А в Египте с такими же параметрами?"},
    },
    {
        "id": "vk10",
        "name": "Таиланд Пхукет, 10 дней",
        "initial": "Здравствуйте! Интересует Таиланд, Пхукет, вылет из Москвы 26 марта на 10 дней, 2 взрослых",
        "followups": {"quality": "4 звезды, завтрак"},
        "consult_extra": {"type": "faq", "msg": "Какой сейчас сезон в Таиланде в марте?"},
    },
    {
        "id": "vk11",
        "name": "Вьетнам, прямой рейс, 11 ночей",
        "initial": "Подскажите туры во Вьетнам с прямыми рейсами из Москвы на 11 ночей, 2 взрослых и ребёнок 10 лет, вылет 18-21 августа",
        "followups": {
            "quality": "4 звезды, завтрак",
            "dates": "18 августа на 11 ночей",
        },
        "consult_extra": {"type": "change_params", "msg": "А если без ограничения на прямой рейс?"},
    },
    {
        "id": "vk12",
        "name": "Египет Шарм, большая семья",
        "initial": "Нам нужна путевка в Египет, Шарм, с 20 июля на 8 ночей, 3 взрослых и 2 ребёнка — 1 год и 8 лет, вылет из Казани, всё включено, 4 или 5 звёзд",
        "followups": {
            "departure": "из Казани",
            "dates": "20 июля на 8 ночей",
        },
        "consult_extra": {"type": "faq", "msg": "Насколько жарко в Египте в июле?"},
    },
    {
        "id": "vk13",
        "name": "Турция на неделю, бюджетно",
        "initial": "Турция на неделю двое взрослых. Бюджетно",
        "followups": {
            "departure": "из Москвы",
            "dates": "начало июня на 7 ночей",
            "quality": "3 звезды, все включено",
        },
        "consult_extra": {"type": "change_dir", "msg": "А в Египет с такими же параметрами?"},
    },
    {
        "id": "vk14",
        "name": "Турция из Нижнего, 1 взр + ребёнок",
        "initial": "Здравствуйте, мне надо подобрать тур Турция, один взрослый и один ребенок 9 лет, все включено, 5 звезд, вылет из Нижнего Новгорода, 15 июля на 7 ночей",
        "followups": {},
        "consult_extra": {"type": "change_params", "msg": "А если 4 звезды вместо 5?"},
    },
    {
        "id": "vk15",
        "name": "Горящие путёвки в Турцию",
        "initial": "Здравствуйте, есть горящие путёвки в Турцию из Москвы? Семья — 2 взрослых и двое детей 11 лет и 3 года",
        "followups": {},
        "consult_extra": {"type": "faq", "msg": "А горящие туры можно вернуть если передумаем?"},
    },
    {
        "id": "vk16",
        "name": "Египет, 2 взр + 2 детей, конец августа",
        "initial": "Хотелось бы подобрать тур из Москвы в Египет, последние числа августа, 2 взрослых и 2 детей — 10 лет и 15 лет, всё включено, на 10 ночей",
        "followups": {
            "quality": "4 звезды, все включено",
            "dates": "25 августа на 10 ночей",
        },
        "consult_extra": {"type": "change_dir", "msg": "А в Турцию с такими же параметрами?"},
    },
    {
        "id": "vk17",
        "name": "ОАЭ Дубай из СПб, семья",
        "initial": "Посмотрите пожалуйста предложения в Дубай, с 16 июня, из СПб, 2 взрослых и 2 детей — 2 года и 6 лет, на 5 ночей",
        "followups": {"quality": "4 звезды, завтрак"},
        "consult_extra": {"type": "change_params", "msg": "А если полупансион вместо завтрака?"},
    },
    {
        "id": "vk18",
        "name": "Вьетнам из Тюмени, 10 ночей",
        "initial": "Вьетнам из Тюмени, 10 марта на 10 ночей, двое взрослых",
        "followups": {"quality": "4 звезды, завтрак"},
        "consult_extra": {"type": "faq", "msg": "Нужна ли виза во Вьетнам?"},
    },
    {
        "id": "vk19",
        "name": "Турция, семья, 300тр, сентябрь",
        "initial": "Здравствуйте, ищу тур в Турцию, 2 взрослых и дети 15 лет и 10 лет, на 8-10 ночей, с 25 сентября, бюджет около 300 тысяч, из Москвы, 4 звезды, все включено",
        "followups": {"dates": "25 сентября на 10 ночей"},
        "consult_extra": {"type": "change_dir", "msg": "А в ОАЭ с такими же параметрами?"},
    },
    {
        "id": "vk20",
        "name": "Таиланд, бюджетный, 1 взр + ребёнок",
        "initial": "Здравствуйте, интересует тур в Таиланд в апреле, до 10 дней, один взрослый и ребёнок 3 года, бюджет ограничен, можно хорошую тройку, из Москвы",
        "followups": {
            "quality": "3 звезды, завтрак",
            "dates": "10 апреля на 10 ночей",
        },
        "consult_extra": {"type": "change_params", "msg": "А если посмотреть 4 звезды?"},
    },
]


def run_scenario(sc):
    sid = sc["id"]
    print(f"\n{'═'*70}")
    print(f"  СЦЕНАРИЙ {sid}: {sc['name']}")
    print(f"{'═'*70}", flush=True)

    steps = []
    got_cards = False
    card_names = []
    got_cards_extra = False

    msg = sc["initial"]
    print(f"\n  👤 [{sid}] Клиент: {msg}", flush=True)
    result = chat(sid, msg)
    steps.append({"step": 1, "user": msg, "phase": "cascade", **result})
    print(f"  🤖 [{sid}] Бот ({result['time']}s, {result['n_cards']} карт): {result['reply'][:500]}", flush=True)

    if result['n_cards'] > 0:
        got_cards = True
        card_names = [c.get("hotel_name", c.get("hotelname", "?")) for c in result['cards'][:5]]
        print(f"  🎴 Карточки: {card_names}", flush=True)

    for attempt in range(6):
        if got_cards:
            break
        if not result['reply']:
            break

        qtype = detect_question_type(result['reply'])
        followup = sc.get("followups", {}).get(qtype)

        if not followup:
            if qtype == "travelers":
                followup = "двое взрослых"
            elif qtype == "departure":
                followup = "из Москвы"
            elif qtype == "quality":
                followup = "4 звезды, все включено"
            elif qtype == "dates":
                followup = "в начале июня на 7 ночей"
            elif qtype == "nights":
                followup = "7 ночей"
            elif qtype == "destination":
                followup = "Турция"
            else:
                followup = "да, подберите пожалуйста"

        msg = followup
        print(f"\n  👤 [{sid}] Клиент: {msg}", flush=True)
        result = chat(sid, msg)
        steps.append({"step": len(steps) + 1, "user": msg, "phase": "cascade", **result})
        print(f"  🤖 [{sid}] Бот ({result['time']}s, {result['n_cards']} карт): {result['reply'][:500]}", flush=True)

        if result['n_cards'] > 0:
            got_cards = True
            card_names = [c.get("hotel_name", c.get("hotelname", "?")) for c in result['cards'][:5]]
            print(f"  🎴 Карточки: {card_names}", flush=True)

    # ─── CONSULTATION PHASE ──────────────────────────────────────────────
    if got_cards:
        # 1. Hotel info
        msg = "Расскажите подробнее о первом отеле"
        print(f"\n  👤 [{sid}] Клиент: {msg}", flush=True)
        result = chat(sid, msg)
        steps.append({"step": len(steps) + 1, "user": msg, "phase": "hotel_info", **result})
        print(f"  🤖 [{sid}] Бот ({result['time']}s): {result['reply'][:600]}", flush=True)

        # 2. Actualize
        msg = "Актуализируйте цену первого варианта"
        print(f"\n  👤 [{sid}] Клиент: {msg}", flush=True)
        result = chat(sid, msg)
        steps.append({"step": len(steps) + 1, "user": msg, "phase": "actualize", **result})
        print(f"  🤖 [{sid}] Бот ({result['time']}s): {result['reply'][:600]}", flush=True)

        # 3. Flight details
        msg = "Покажите детали рейса"
        print(f"\n  👤 [{sid}] Клиент: {msg}", flush=True)
        result = chat(sid, msg)
        steps.append({"step": len(steps) + 1, "user": msg, "phase": "flight", **result})
        print(f"  🤖 [{sid}] Бот ({result['time']}s): {result['reply'][:600]}", flush=True)

        # 4. Extra consultation (FAQ / direction change / param change)
        extra = sc.get("consult_extra", {})
        if extra:
            msg = extra["msg"]
            print(f"\n  👤 [{sid}] Клиент: {msg}", flush=True)
            result = chat(sid, msg)
            steps.append({"step": len(steps) + 1, "user": msg, "phase": extra["type"], **result})
            print(f"  🤖 [{sid}] Бот ({result['time']}s, {result['n_cards']} карт): {result['reply'][:600]}", flush=True)

            if result['n_cards'] > 0:
                got_cards_extra = True
                extra_cards = [c.get("hotel_name", c.get("hotelname", "?")) for c in result['cards'][:5]]
                print(f"  🎴 Новые карточки: {extra_cards}", flush=True)

            if extra["type"] in ("change_dir", "change_params"):
                if result['n_cards'] == 0 and "ERROR" not in result['reply']:
                    for wait_attempt in range(3):
                        time.sleep(2)
                        if result['n_cards'] > 0:
                            break

    # ─── ANALYSIS ────────────────────────────────────────────────────────
    issues = []
    total_time = sum(s['time'] for s in steps)

    if not got_cards:
        issues.append("КРИТИЧНО: НЕ получены карточки")

    for s in steps:
        phase = s.get("phase", "")
        if phase == "hotel_info" and len(s["reply"]) < 50:
            issues.append(f"Консультация слишком короткая: {len(s['reply'])} символов")
        if phase == "actualize" and len(s["reply"]) < 30:
            issues.append(f"Актуализация слишком короткая: {len(s['reply'])} символов")
        if phase == "flight" and len(s["reply"]) < 30:
            issues.append(f"Детали рейса слишком короткие: {len(s['reply'])} символов")

    for s in steps:
        reply_lower = s["reply"].lower()
        if any(w in reply_lower for w in ["вы выбрали:", "вы указали:", "ваш запрос:", "подведу итог"]):
            issues.append(f"Step {s['step']}: Эхо параметров")

    for s in steps:
        reply = s["reply"]
        if '{"' in reply or "```json" in reply or "function_call" in reply:
            issues.append(f"Step {s['step']}: Утечка JSON/reasoning")

    for s in steps:
        if s["n_cards"] > 0 and len(s["reply"]) > 500:
            issues.append(f"Step {s['step']}: Возможное дублирование карточек ({len(s['reply'])} символов)")

    for s in steps:
        if "ERROR" in s["reply"]:
            issues.append(f"Step {s['step']}: {s['reply'][:100]}")

    extra_info = sc.get("consult_extra", {})
    extra_type = extra_info.get("type", "")
    extra_ok = True
    if extra_type in ("change_dir", "change_params") and got_cards:
        extra_step = [s for s in steps if s.get("phase") == extra_type]
        if extra_step and extra_step[0]["n_cards"] == 0 and "ERROR" not in extra_step[0]["reply"]:
            if "не удалось" not in extra_step[0]["reply"].lower() and "не найдено" not in extra_step[0]["reply"].lower():
                pass
            extra_ok = False
            issues.append(f"Смена ({extra_type}): карточки не получены (может быть каскадный вопрос)")

    return {
        "id": sid,
        "name": sc["name"],
        "got_cards": got_cards,
        "got_cards_extra": got_cards_extra,
        "card_names": card_names,
        "total_steps": len(steps),
        "total_time": round(total_time, 1),
        "issues": issues,
        "steps": steps,
        "extra_type": extra_type,
    }


# ═══ MAIN ═══
print("╔══════════════════════════════════════════════════════════════════════╗")
print("║  ТЕСТИРОВАНИЕ ПОСЛЕ ОПТИМИЗАЦИИ — 20 VK сценариев (полный цикл)   ║")
print("╚══════════════════════════════════════════════════════════════════════╝")
sys.stdout.flush()

all_results = []
t_start = time.time()

for sc in SCENARIOS:
    result = run_scenario(sc)
    all_results.append(result)
    sys.stdout.flush()

total_elapsed = round(time.time() - t_start, 1)

# ═══ SUMMARY ═══
print(f"\n\n{'═'*70}")
print("  ИТОГОВЫЙ ОТЧЁТ")
print(f"{'═'*70}")

passed = sum(1 for r in all_results if not r["issues"])
failed = sum(1 for r in all_results if r["issues"])
cards_ok = sum(1 for r in all_results if r["got_cards"])
extra_ok = sum(1 for r in all_results if r["got_cards_extra"])

print(f"\n  Всего сценариев:        {len(all_results)}")
print(f"  Карточки получены:      {cards_ok}/{len(all_results)}")
print(f"  Без ошибок (автотест):  {passed}")
print(f"  С замечаниями:          {failed}")
print(f"  Смена направления/парам (новые карточки): {extra_ok}")
print(f"  Общее время:            {total_elapsed}s ({total_elapsed/60:.1f} мин)")
print(f"  Среднее время/сценарий: {total_elapsed/len(all_results):.1f}s")

if failed > 0:
    print(f"\n  {'─'*60}")
    print("  ЗАМЕЧАНИЯ:")
    for r in all_results:
        if r["issues"]:
            print(f"\n  ⚠️  {r['id']}: {r['name']}")
            for issue in r["issues"]:
                print(f"     • {issue}")

print(f"\n  {'─'*60}")
print("  ДЕТАЛИ:")
for r in all_results:
    status = "✅" if not r["issues"] else "⚠️"
    cards_info = f"{len(r['card_names'])} карт" if r["got_cards"] else "0 карт"
    extra_info = ""
    if r["extra_type"]:
        extra_info = f" | {r['extra_type']}: {'✅ карт' if r['got_cards_extra'] else '⚠️ без карт'}"
    print(f"  {status} {r['id']}: {r['name']} — {r['total_steps']} шагов, {r['total_time']}s, {cards_info}{extra_info}")
    if r["got_cards"] and r["card_names"]:
        print(f"     Отели: {', '.join(r['card_names'][:3])}")

print(f"\n{'═'*70}")
print("  ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print(f"{'═'*70}")
sys.stdout.flush()
