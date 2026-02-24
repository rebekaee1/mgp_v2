"""
Тест правок: конкретные вопросы по отелю + запрет ложных обещаний.
Сценарий: каскад до карточек → разнообразные вопросы консультации.
"""
import requests, time, json, uuid

BASE = "http://localhost:8080/api/v1/chat"

def send(conv_id, msg, label=""):
    t0 = time.time()
    try:
        r = requests.post(BASE, json={"message": msg, "conversation_id": conv_id}, timeout=180)
        elapsed = round(time.time() - t0, 1)
        data = r.json()
        reply = data.get("reply", "")
        cards = data.get("tour_cards", [])
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        reply = f"[EXCEPTION] {e}"
        cards = []
    tag = f"[{label}]" if label else ""
    print(f"\n{'='*70}")
    print(f"{tag} USER: {msg}")
    print(f"{tag} TIME: {elapsed}s | CARDS: {len(cards)} | LEN: {len(reply)}")
    print(f"{tag} BOT: {reply[:700]}")
    if len(reply) > 700:
        print(f"  ... (+{len(reply)-700} chars)")
    print(f"{'='*70}")
    return {"msg": msg, "reply": reply, "cards": len(cards), "time": elapsed, "label": label}


def run_tests():
    conv = f"test-consult-{uuid.uuid4().hex[:8]}"
    results = []

    print("\n" + "#"*70)
    print("# ТЕСТ: КОНСУЛЬТАЦИЯ (конкретные вопросы + ложные обещания)")
    print("#"*70)

    # === ФАЗА 1: Каскад до карточек ===
    cascade = [
        ("Хочу в Турцию, Сиде", "каскад-1"),
        ("Из Москвы", "каскад-2"),
        ("В начале марта на 7 ночей", "каскад-3"),
        ("Двое взрослых", "каскад-4"),
        ("5 звёзд, всё включено", "каскад-5"),
    ]
    for msg, label in cascade:
        r = send(conv, msg, label)
        results.append(r)
        time.sleep(1)

    got_cards = any(r["cards"] > 0 for r in results)
    if not got_cards:
        time.sleep(5)
        r = send(conv, "Покажите что нашли", "wait")
        results.append(r)

    # === ФАЗА 2: КОНКРЕТНЫЕ ВОПРОСЫ ПО ОТЕЛЮ (должен ответить коротко, не полное описание) ===
    print("\n" + "-"*70)
    print("ФАЗА 2: КОНКРЕТНЫЕ ВОПРОСЫ ПО ОТЕЛЮ")
    print("-"*70)

    specific_hotel = [
        ("Есть ли свой пляж у первого отеля?", "отель: пляж"),
        ("Какое питание в первом отеле?", "отель: питание"),
        ("Далеко ли до моря?", "отель: до моря"),
        ("Есть бассейн?", "отель: бассейн"),
        ("Подходит ли для детей?", "отель: дети"),
        ("Расскажи подробнее о первом отеле", "отель: ПОЛНОЕ описание"),
    ]
    for msg, label in specific_hotel:
        r = send(conv, msg, label)
        results.append(r)
        time.sleep(1)

    # === ФАЗА 3: ВОПРОСЫ ВНЕ API (должен дать номер менеджера, НЕ обещать уточнить) ===
    print("\n" + "-"*70)
    print("ФАЗА 3: ВОПРОСЫ ВНЕ API (проверка ложных обещаний)")
    print("-"*70)

    out_of_api = [
        ("Во сколько заезд и выезд?", "вне-API: заезд"),
        ("Какие экскурсии есть на курорте?", "вне-API: экскурсии"),
        ("Сколько килограмм багажа включено?", "вне-API: багаж"),
        ("Можно ли оформить рассрочку?", "вне-API: рассрочка"),
        ("Какие условия отмены тура?", "вне-API: отмена"),
        ("Какое конкретно меню в ресторане отеля?", "вне-API: меню"),
        ("Нужна ли виза в Турцию?", "FAQ: виза"),
    ]
    for msg, label in out_of_api:
        r = send(conv, msg, label)
        results.append(r)
        time.sleep(1)

    # === ФАЗА 4: ПЕРЕЛЁТ (должен ответить структурированно) ===
    print("\n" + "-"*70)
    print("ФАЗА 4: ПЕРЕЛЁТ")
    print("-"*70)

    flight = [
        ("Какой перелёт у первого тура?", "перелёт: рейсы"),
        ("Время вылета и прилёта?", "перелёт: время"),
    ]
    for msg, label in flight:
        r = send(conv, msg, label)
        results.append(r)
        time.sleep(1)

    return results


def analyze(results):
    lines = []
    lines.append("# Отчёт: тест правок консультации\n")
    lines.append(f"**Дата:** {time.strftime('%Y-%m-%d %H:%M')}\n")

    # --- Каскад ---
    cascade_r = [r for r in results if "каскад" in r["label"] or r["label"] == "wait"]
    lines.append("\n## Каскад\n")
    lines.append("| Шаг | Время | Карточки |")
    lines.append("|---|---|---|")
    for r in cascade_r:
        lines.append(f"| {r['label']} | {r['time']}с | {r['cards']} |")
    got = any(r["cards"] > 0 for r in cascade_r)
    lines.append(f"\n**Карточки:** {'Да' if got else 'НЕТ'}\n")

    # --- Конкретные вопросы по отелю ---
    hotel_r = [r for r in results if "отель:" in r["label"]]
    lines.append("\n## Конкретные вопросы по отелю\n")
    lines.append("| Вопрос | Время | Длина | Короткий ответ? | Ответ |")
    lines.append("|---|---|---|---|---|")
    for r in hotel_r:
        is_general = "ПОЛНОЕ" in r["label"]
        is_short = len(r["reply"]) < 400
        if is_general:
            mark = "Полный (ожидаемо)" if len(r["reply"]) > 300 else "Короткий (ОШИБКА!)"
        else:
            mark = "Да (корректно)" if is_short else "НЕТ — слишком длинный!"
        short = r["reply"][:250].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['msg']} | {r['time']}с | {len(r['reply'])} | {mark} | {short} |")

    # --- Вопросы вне API ---
    api_r = [r for r in results if "вне-API:" in r["label"] or "FAQ:" in r["label"]]
    lines.append("\n## Вопросы вне API\n")
    lines.append("| Вопрос | Время | Телефон менеджера? | Ложное обещание? | Ответ |")
    lines.append("|---|---|---|---|---|")
    for r in api_r:
        has_phone = "+7" in r["reply"] or "555-35-35" in r["reply"] or "телефон" in r["reply"].lower()
        false_promise = any(p in r["reply"].lower() for p in [
            "могу уточнить", "свяжусь с менеджером", "могу связаться",
            "запрошу у оператора", "переведу менеджеру", "могу запросить",
            "уточню у менеджера", "обращусь к менеджеру"
        ])
        phone_mark = "Да" if has_phone else "НЕТ"
        promise_mark = "ДА — ОШИБКА!" if false_promise else "Нет (корректно)"
        short = r["reply"][:250].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['msg']} | {r['time']}с | {phone_mark} | {promise_mark} | {short} |")

    # --- Перелёт ---
    flight_r = [r for r in results if "перелёт:" in r["label"]]
    lines.append("\n## Перелёт\n")
    lines.append("| Вопрос | Время | Ошибка? | Ответ |")
    lines.append("|---|---|---|---|")
    for r in flight_r:
        is_err = any(p in r["reply"].lower() for p in ["ошибка", "error", "произошла", "временная"])
        mark = "ДА" if is_err else "Нет"
        short = r["reply"][:300].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['msg']} | {r['time']}с | {mark} | {short} |")

    # --- Полные ответы ---
    lines.append("\n## Полные ответы\n")
    for r in results:
        if "каскад" in r["label"] or r["label"] == "wait":
            continue
        lines.append(f"### {r['label']}: «{r['msg']}»")
        lines.append(f"Время: {r['time']}с | Длина: {len(r['reply'])} символов\n")
        lines.append(f"```\n{r['reply']}\n```\n")

    return "\n".join(lines)


if __name__ == "__main__":
    print(f"Запуск: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    results = run_tests()
    report = analyze(results)
    with open("TEST_CONSULTATION_REPORT.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n\nОтчёт: TEST_CONSULTATION_REPORT.md")
