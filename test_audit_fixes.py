"""
Тестирование правок аудита: FAQ телефоны, hoteltypes, сезонность, горнолыжные, форс-мажор.
5 сценариев с полным логированием.
"""

import json
import re
import time
import uuid
import requests
from datetime import datetime

SERVER_URL = "http://72.56.88.193"
API_ENDPOINT = "/api/v1/chat"
TIMEOUT = 120
LOG_FILE = f"test_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
_log_handle = None


def log(text):
    global _log_handle
    if _log_handle is None:
        _log_handle = open(LOG_FILE, "w", encoding="utf-8")
    _log_handle.write(text + "\n")
    _log_handle.flush()
    print(text)


def send_message(conv_id, message):
    url = f"{SERVER_URL}{API_ENDPOINT}"
    payload = {"message": message, "conversation_id": conv_id}
    for attempt in range(3):
        t0 = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=TIMEOUT)
            elapsed = time.time() - t0
            if resp.status_code == 429:
                wait = 20 * (attempt + 1)
                log(f"    [429] Ожидание {wait}с (попытка {attempt+1}/3)")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                return {"reply": f"HTTP {resp.status_code}", "tour_cards": []}, elapsed
            data = resp.json()
            reply = data.get("response", data.get("reply", ""))
            cards = data.get("tour_cards", [])
            return {"reply": reply, "tour_cards": cards}, elapsed
        except requests.exceptions.Timeout:
            return {"reply": "TIMEOUT", "tour_cards": []}, TIMEOUT
        except Exception as e:
            return {"reply": str(e), "tour_cards": []}, 0
    return {"reply": "429 exhausted", "tour_cards": []}, 0


def run_scenario(scenario_id, name, messages, checks_fn):
    conv_id = f"audit-test-{scenario_id}-{int(time.time())}"
    log(f"\n{'='*70}")
    log(f"СЦЕНАРИЙ {scenario_id}: {name}")
    log(f"conversation_id: {conv_id}")
    log(f"{'='*70}")

    all_responses = []
    for i, msg in enumerate(messages):
        log(f"\n  >> Сообщение {i+1}: \"{msg}\"")
        resp, elapsed = send_message(conv_id, msg)
        reply_preview = resp["reply"][:500] if resp["reply"] else "(пусто)"
        cards_count = len(resp.get("tour_cards", []))
        log(f"  << Ответ ({elapsed:.1f}с, {cards_count} карточек):")
        log(f"     {reply_preview}")
        if cards_count > 0:
            for ci, card in enumerate(resp["tour_cards"][:3]):
                hotel = card.get("hotel_name", "?")
                stars = card.get("hotel_stars", "?")
                price = card.get("price", "?")
                log(f"     Карточка {ci+1}: {hotel} {stars}★ — {price} ₽")
        all_responses.append(resp)
        time.sleep(5)

    log(f"\n  --- ПРОВЕРКИ ---")
    results = checks_fn(all_responses)
    passed = 0
    failed = 0
    for check_name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        log(f"  [{status}] {check_name}: {detail}")

    verdict = "PASS" if failed == 0 else "FAIL"
    log(f"\n  ИТОГ: {verdict} ({passed} pass / {failed} fail)")
    return verdict, all_responses


# =====================================================================
# СЦЕНАРИЙ 1: FAQ — телефон менеджера
# Проверяет: правка 1.1 — новый номер +7 (499) 685-25-57
# =====================================================================
def test_1_faq_phone():
    messages = [
        "Как с вами связаться? Какой номер менеджера?"
    ]

    def checks(responses):
        r = responses[0]["reply"]
        results = []
        has_new = "+7 (499) 685-25-57" in r or "499" in r
        results.append(("Новый номер +7 (499) 685-25-57", has_new,
                        f"{'найден' if has_new else 'НЕ найден'} в ответе"))
        has_old_800 = "+7 (800) 555-35-35" in r
        results.append(("Старый номер 800 отсутствует", not has_old_800,
                        f"{'НАЙДЕН старый!' if has_old_800 else 'старого нет, ОК'}"))
        has_old_495 = "+7 (495) 822-03-67" in r
        results.append(("Старый номер 495 отсутствует", not has_old_495,
                        f"{'НАЙДЕН старый!' if has_old_495 else 'старого нет, ОК'}"))
        return results

    return run_scenario("1", "FAQ — телефон менеджера", messages, checks)


# =====================================================================
# СЦЕНАРИЙ 2: Hoteltypes маппинг — «пляжный отель»
# Проверяет: правка 1.3 — hoteltypes=beach
# =====================================================================
def test_2_hoteltypes():
    messages = [
        "Хочу пляжный отель в Турции",
        "Москва",
        "двое взрослых",
        "в середине апреля на 7 ночей",
        "4 звезды, всё включено"
    ]

    def checks(responses):
        results = []
        last = responses[-1]
        reply_all = " ".join(r["reply"] for r in responses).lower()
        has_cards = len(last.get("tour_cards", [])) > 0
        results.append(("Карточки получены", has_cards,
                        f"{len(last.get('tour_cards', []))} карточек"))
        no_error = "ошибка" not in last["reply"].lower() and "не найден" not in last["reply"].lower()
        results.append(("Нет ошибки в ответе", no_error or has_cards,
                        "ОК" if (no_error or has_cards) else "Ошибка или не найдено"))
        understood = not re.search(r"что вы имеете в виду.*пляжн", reply_all)
        results.append(("Понял 'пляжный отель' без уточнений", understood,
                        "ОК" if understood else "Переспросил"))
        return results

    return run_scenario("2", "Hoteltypes — пляжный отель", messages, checks)


# =====================================================================
# СЦЕНАРИЙ 3: Сезонность — Доминикана
# Проверяет: правка 1.7 — новые строки сезонности
# =====================================================================
def test_3_seasonality():
    messages = [
        "Когда лучше ехать в Доминикану?"
    ]

    def checks(responses):
        r = responses[0]["reply"].lower()
        results = []
        has_season = any(w in r for w in ["ноябр", "декабр", "январ", "феврал", "март", "апрел"])
        results.append(("Указан лучший сезон (нояб-апрель)", has_season,
                        f"{'найден' if has_season else 'НЕ найден'}"))
        has_warning = any(w in r for w in ["ураган", "дожд", "не рекоменд", "сезон дождей", "май", "октябр"])
        results.append(("Указан неблагоприятный период", has_warning,
                        f"{'найден' if has_warning else 'НЕ найден'}"))
        not_empty = len(r) > 30
        results.append(("Ответ содержательный (>30 символов)", not_empty,
                        f"{len(r)} символов"))
        return results

    return run_scenario("3", "Сезонность — Доминикана", messages, checks)


# =====================================================================
# СЦЕНАРИЙ 4: Горнолыжные туры (D1)
# Проверяет: секция 15.1 — горнолыжные направления + tourtype
# =====================================================================
def test_4_ski_tours():
    messages = [
        "Хочу горнолыжный отдых, куда можно поехать?"
    ]

    def checks(responses):
        r = responses[0]["reply"].lower()
        results = []
        has_ski_dest = any(w in r for w in ["улудаг", "красная поляна", "андорра", "горнолыж",
                                             "турция", "россия", "лыж", "сноуборд"])
        results.append(("Предложены горнолыжные направления", has_ski_dest,
                        f"{'найдены' if has_ski_dest else 'НЕ найдены'}"))
        has_season = any(w in r for w in ["декабр", "январ", "феврал", "март", "зим"])
        results.append(("Указан сезон (декабрь-март)", has_season,
                        f"{'найден' if has_season else 'НЕ найден'}"))
        no_beach = "пляж" not in r
        results.append(("Не предложил пляжный отдых", no_beach,
                        f"{'ОК' if no_beach else 'ПРЕДЛОЖИЛ ПЛЯЖ'}"))
        return results

    return run_scenario("4", "Горнолыжные туры (D1)", messages, checks)


# =====================================================================
# СЦЕНАРИЙ 5: Форс-мажор / безопасность (G3)
# Проверяет: секция 25 — правило безопасности, МИД
# =====================================================================
def test_5_force_majeure():
    messages = [
        "Насколько безопасно сейчас лететь в Египет? Какая там обстановка?"
    ]

    def checks(responses):
        r = responses[0]["reply"].lower()
        results = []
        has_mid = any(w in r for w in ["мид", "mid.ru"])
        results.append(("Упоминание МИД / mid.ru", has_mid,
                        f"{'найдено' if has_mid else 'НЕ найдено'}"))
        has_manager = any(w in r for w in ["менеджер", "499", "685-25-57"])
        results.append(("Ссылка на менеджера", has_manager,
                        f"{'найдена' if has_manager else 'НЕ найдена'}"))
        not_definitive = not any(w in r for w in ["абсолютно безопасно", "полностью безопасно",
                                                   "опасно лететь", "нельзя лететь"])
        results.append(("Не даёт категоричных утверждений", not_definitive,
                        f"{'ОК' if not_definitive else 'КАТЕГОРИЧНОЕ утверждение!'}"))
        return results

    return run_scenario("5", "Форс-мажор / безопасность (G3)", messages, checks)


# =====================================================================
# MAIN
# =====================================================================
def main():
    log(f"{'='*70}")
    log(f"  ТЕСТИРОВАНИЕ ПРАВОК АУДИТА — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Сервер: {SERVER_URL}")
    log(f"  Лог: {LOG_FILE}")
    log(f"{'='*70}")

    tests = [
        ("1", test_1_faq_phone),
        ("2", test_2_hoteltypes),
        ("3", test_3_seasonality),
        ("4", test_4_ski_tours),
        ("5", test_5_force_majeure),
    ]

    verdicts = {}
    for tid, fn in tests:
        try:
            verdict, _ = fn()
            verdicts[tid] = verdict
        except Exception as e:
            log(f"\n  ОШИБКА в сценарии {tid}: {e}")
            verdicts[tid] = "ERROR"
        time.sleep(10)

    log(f"\n{'='*70}")
    log(f"  ИТОГОВЫЙ ОТЧЁТ")
    log(f"{'='*70}")
    for tid, v in verdicts.items():
        log(f"  Сценарий {tid}: {v}")
    total_pass = sum(1 for v in verdicts.values() if v == "PASS")
    total = len(verdicts)
    log(f"\n  ВСЕГО: {total_pass}/{total} PASS")
    log(f"{'='*70}")

    if _log_handle:
        _log_handle.close()


if __name__ == "__main__":
    main()
