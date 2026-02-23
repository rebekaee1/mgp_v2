"""
Тест правила 11.4 (границы консультации) + вопросы о перелётах.
Два параллельных сценария с общим отчётом.
"""
import requests
import time
import json
import uuid

BASE = "http://localhost:8080/api/v1/chat"

def send(conv_id: str, msg: str, label: str = ""):
    """Send message and return (reply, tour_cards, elapsed_sec)."""
    t0 = time.time()
    try:
        r = requests.post(BASE, json={"message": msg, "conversation_id": conv_id}, timeout=180)
        elapsed = round(time.time() - t0, 1)
        data = r.json()
        reply = data.get("reply", "")
        cards = data.get("tour_cards", [])
        status = r.status_code
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        reply = f"[EXCEPTION] {e}"
        cards = []
        status = 0

    tag = f"[{label}]" if label else ""
    print(f"\n{'='*70}")
    print(f"{tag} USER: {msg}")
    print(f"{tag} STATUS: {status} | TIME: {elapsed}s | CARDS: {len(cards)}")
    print(f"{tag} BOT: {reply[:600]}")
    if len(reply) > 600:
        print(f"  ... (+{len(reply)-600} chars)")
    print(f"{'='*70}")
    return reply, cards, elapsed


def run_scenario_boundaries():
    """Сценарий 1: довести до карточек, потом задать вопросы вне API."""
    conv = f"test-bounds-{uuid.uuid4().hex[:8]}"
    results = []

    print("\n" + "#"*70)
    print("# СЦЕНАРИЙ A: ГРАНИЦЫ КОНСУЛЬТАЦИИ (правило 11.4)")
    print("#"*70)

    # --- Фаза 1: Собрать каскад и получить карточки ---
    steps = [
        ("Хочу в Турцию", "каскад-1"),
        ("Из Москвы", "каскад-2"),
        ("В начале марта на 7 ночей", "каскад-3"),
        ("Двое взрослых", "каскад-4"),
        ("4 звезды, всё включено", "каскад-5"),
    ]

    got_cards = False
    for msg, label in steps:
        reply, cards, elapsed = send(conv, msg, f"A-{label}")
        results.append({"step": label, "msg": msg, "reply": reply, "cards": len(cards), "time": elapsed})
        if cards:
            got_cards = True
        time.sleep(1)

    if not got_cards:
        print("\n⚠️ НЕ ПОЛУЧИЛИ КАРТОЧКИ — пробуем подождать")
        time.sleep(5)
        reply, cards, elapsed = send(conv, "Покажите что нашли", "A-wait")
        results.append({"step": "wait", "msg": "Покажите что нашли", "reply": reply, "cards": len(cards), "time": elapsed})
        if cards:
            got_cards = True

    if not got_cards:
        print("\n❌ КАРТОЧКИ ТАК И НЕ ПОЛУЧЕНЫ — тестируем вопросы без карточек")

    # --- Фаза 2: Вопросы ВНЕ API (должен сказать что не может ответить) ---
    boundary_questions = [
        ("Во сколько заезд и выезд в этих отелях?", "вне-API: заезд/выезд"),
        ("Какие экскурсии есть в Анталье?", "вне-API: экскурсии"),
        ("Сколько килограмм багажа можно взять?", "вне-API: багаж"),
        ("Можно ли оформить рассрочку на этот тур?", "вне-API: рассрочка"),
        ("Какое меню в ресторане первого отеля?", "вне-API: меню ресторана"),
        ("Какие условия отмены тура?", "вне-API: условия отмены"),
    ]

    print("\n" + "-"*70)
    print("ФАЗА 2: ВОПРОСЫ ВНЕ API")
    print("-"*70)

    for msg, label in boundary_questions:
        reply, cards, elapsed = send(conv, msg, f"A-{label}")
        admits_no_data = any(phrase in reply.lower() for phrase in [
            "нет данных", "не располагаю", "не могу ответить",
            "нет информации", "у меня нет", "недоступн",
            "не имею", "к сожалению", "уточнить у менеджера",
            "не смогу", "выходит за рамки"
        ])
        results.append({
            "step": label, "msg": msg, "reply": reply,
            "cards": len(cards), "time": elapsed,
            "admits_no_data": admits_no_data
        })
        time.sleep(1)

    # --- Фаза 3: Вопрос В РАМКАХ API (должен нормально ответить) ---
    print("\n" + "-"*70)
    print("ФАЗА 3: ВОПРОСЫ В РАМКАХ API (контрольные)")
    print("-"*70)

    in_api_questions = [
        ("Расскажи подробнее о первом отеле", "в-API: info отеля"),
        ("Какая точная цена первого тура?", "в-API: цена"),
    ]

    for msg, label in in_api_questions:
        reply, cards, elapsed = send(conv, msg, f"A-{label}")
        results.append({
            "step": label, "msg": msg, "reply": reply,
            "cards": len(cards), "time": elapsed
        })
        time.sleep(1)

    return results


def run_scenario_flights():
    """Сценарий 2: довести до карточек, потом спросить про перелёты."""
    conv = f"test-flights-{uuid.uuid4().hex[:8]}"
    results = []

    print("\n" + "#"*70)
    print("# СЦЕНАРИЙ B: ВОПРОСЫ О ПЕРЕЛЁТАХ")
    print("#"*70)

    steps = [
        ("Хочу в Египет, Хургада", "каскад-1"),
        ("Из Санкт-Петербурга", "каскад-2"),
        ("В середине марта, 10 ночей", "каскад-3"),
        ("Вдвоём", "каскад-4"),
        ("5 звёзд, всё включено", "каскад-5"),
    ]

    got_cards = False
    for msg, label in steps:
        reply, cards, elapsed = send(conv, msg, f"B-{label}")
        results.append({"step": label, "msg": msg, "reply": reply, "cards": len(cards), "time": elapsed})
        if cards:
            got_cards = True
        time.sleep(1)

    if not got_cards:
        time.sleep(5)
        reply, cards, elapsed = send(conv, "Покажите результаты", "B-wait")
        results.append({"step": "wait", "msg": "Покажите результаты", "reply": reply, "cards": len(cards), "time": elapsed})
        if cards:
            got_cards = True

    if not got_cards:
        print("\n❌ КАРТОЧКИ НЕ ПОЛУЧЕНЫ — тестируем перелёты без карточек")

    # --- Вопросы о перелётах ---
    flight_questions = [
        ("Какой перелёт у первого тура? Хочу узнать рейсы", "перелёт-1: рейсы"),
        ("Время вылета и прилёта?", "перелёт-2: время"),
        ("Есть прямой рейс или с пересадкой?", "перелёт-3: пересадки"),
        ("Какая авиакомпания?", "перелёт-4: авиакомпания"),
        ("А обратный рейс когда?", "перелёт-5: обратный"),
    ]

    print("\n" + "-"*70)
    print("ФАЗА 2: ВОПРОСЫ О ПЕРЕЛЁТАХ")
    print("-"*70)

    for msg, label in flight_questions:
        reply, cards, elapsed = send(conv, msg, f"B-{label}")
        is_error = any(phrase in reply.lower() for phrase in [
            "ошибка", "error", "traceback", "exception",
            "произошла", "не удалось", "попробуйте ещё",
            "временная", "техническая"
        ])
        results.append({
            "step": label, "msg": msg, "reply": reply,
            "cards": len(cards), "time": elapsed,
            "is_error": is_error
        })
        time.sleep(1)

    return results


def generate_report(bounds_results, flight_results):
    """Generate markdown report."""
    lines = []
    lines.append("# Отчёт: Тест правила 11.4 + Перелёты\n")
    lines.append(f"**Дата:** {time.strftime('%Y-%m-%d %H:%M')}\n")

    # --- СЦЕНАРИЙ A ---
    lines.append("\n## Сценарий A: Границы консультации (правило 11.4)\n")

    cascade = [r for r in bounds_results if "каскад" in r["step"] or r["step"] == "wait"]
    boundary = [r for r in bounds_results if "вне-API" in r["step"]]
    in_api = [r for r in bounds_results if "в-API" in r["step"]]

    lines.append("### Каскад (до карточек)\n")
    lines.append("| Шаг | Сообщение | Время | Карточки |")
    lines.append("|---|---|---|---|")
    for r in cascade:
        lines.append(f"| {r['step']} | {r['msg']} | {r['time']}с | {r['cards']} |")

    got_cards = any(r["cards"] > 0 for r in cascade)
    lines.append(f"\n**Карточки получены:** {'Да' if got_cards else 'НЕТ'}\n")

    lines.append("### Вопросы ВНЕ API (ожидание: ассистент признаёт отсутствие данных)\n")
    lines.append("| Вопрос | Время | Признал отсутствие данных? | Ответ (первые 200 символов) |")
    lines.append("|---|---|---|---|")
    pass_count = 0
    for r in boundary:
        admits = r.get("admits_no_data", False)
        mark = "✅ Да" if admits else "❌ Нет"
        if admits:
            pass_count += 1
        short = r["reply"][:200].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['msg']} | {r['time']}с | {mark} | {short} |")

    total_boundary = len(boundary)
    lines.append(f"\n**Результат:** {pass_count}/{total_boundary} вопросов — ассистент признал отсутствие данных\n")

    lines.append("### Контрольные вопросы В РАМКАХ API\n")
    lines.append("| Вопрос | Время | Ответ (первые 200 символов) |")
    lines.append("|---|---|---|")
    for r in in_api:
        short = r["reply"][:200].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['msg']} | {r['time']}с | {short} |")

    # --- СЦЕНАРИЙ B ---
    lines.append("\n## Сценарий B: Вопросы о перелётах\n")

    cascade_b = [r for r in flight_results if "каскад" in r["step"] or r["step"] == "wait"]
    flights = [r for r in flight_results if "перелёт" in r["step"]]

    lines.append("### Каскад (до карточек)\n")
    lines.append("| Шаг | Сообщение | Время | Карточки |")
    lines.append("|---|---|---|---|")
    for r in cascade_b:
        lines.append(f"| {r['step']} | {r['msg']} | {r['time']}с | {r['cards']} |")

    got_cards_b = any(r["cards"] > 0 for r in cascade_b)
    lines.append(f"\n**Карточки получены:** {'Да' if got_cards_b else 'НЕТ'}\n")

    lines.append("### Вопросы о перелётах (ожидание: нормальный ответ без ошибок)\n")
    lines.append("| Вопрос | Время | Ошибка? | Ответ (первые 300 символов) |")
    lines.append("|---|---|---|---|")
    error_count = 0
    for r in flights:
        is_err = r.get("is_error", False)
        mark = "❌ Да" if is_err else "✅ Нет"
        if is_err:
            error_count += 1
        short = r["reply"][:300].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['msg']} | {r['time']}с | {mark} | {short} |")

    total_flights = len(flights)
    lines.append(f"\n**Результат:** {total_flights - error_count}/{total_flights} без ошибок\n")

    # --- ИТОГО ---
    lines.append("\n## Итоговая сводка\n")
    lines.append("| Метрика | Значение |")
    lines.append("|---|---|")
    lines.append(f"| Правило 11.4: корректных ответов | {pass_count}/{total_boundary} |")
    lines.append(f"| Перелёты: без ошибок | {total_flights - error_count}/{total_flights} |")

    all_times = [r["time"] for r in bounds_results + flight_results]
    avg_time = round(sum(all_times) / len(all_times), 1) if all_times else 0
    max_time = max(all_times) if all_times else 0
    lines.append(f"| Среднее время ответа | {avg_time}с |")
    lines.append(f"| Макс. время ответа | {max_time}с |")

    # Детальные ответы
    lines.append("\n## Полные ответы\n")
    
    lines.append("### Сценарий A: Все ответы\n")
    for r in bounds_results:
        lines.append(f"#### {r['step']}: «{r['msg']}»")
        lines.append(f"- Время: {r['time']}с | Карточки: {r['cards']}")
        if "admits_no_data" in r:
            lines.append(f"- Признал отсутствие данных: {'Да' if r['admits_no_data'] else 'Нет'}")
        lines.append(f"\n```\n{r['reply']}\n```\n")

    lines.append("### Сценарий B: Все ответы\n")
    for r in flight_results:
        lines.append(f"#### {r['step']}: «{r['msg']}»")
        lines.append(f"- Время: {r['time']}с | Карточки: {r['cards']}")
        if "is_error" in r:
            lines.append(f"- Ошибка: {'Да' if r['is_error'] else 'Нет'}")
        lines.append(f"\n```\n{r['reply']}\n```\n")

    return "\n".join(lines)


if __name__ == "__main__":
    print("🚀 Запуск тестов: правило 11.4 + перелёты")
    print(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    bounds_results = run_scenario_boundaries()
    flight_results = run_scenario_flights()

    report = generate_report(bounds_results, flight_results)
    report_path = "TEST_BOUNDARIES_FLIGHTS_REPORT.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n\n📄 Отчёт записан: {report_path}")
    print("✅ Тестирование завершено")
