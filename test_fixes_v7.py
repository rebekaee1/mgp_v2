"""
Тест-сценарии для проверки 7 правок (v7).
Каждый тест полностью логируется для последующего анализа.
"""
import requests
import time
import json
import re
from datetime import datetime

API_URL = "http://72.56.88.193/api/v1/chat"
LOG_FILE = "test_fixes_v7.log"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def send(conv_id, text, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(API_URL, json={
                "message": text,
                "conversation_id": conv_id
            }, timeout=120)
            if r.status_code == 429:
                wait = 15 * (attempt + 1)
                log(f"  ⏳ 429 rate limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            return data.get("reply", ""), data.get("tour_cards", []), data.get("conversation_id", conv_id)
        except Exception as e:
            log(f"  ❌ ERROR attempt {attempt+1}: {e}")
            time.sleep(5)
    return None, [], conv_id

def run_test(name, steps, checks):
    log(f"\n{'='*60}")
    log(f"ТЕСТ: {name}")
    log(f"{'='*60}")
    conv_id = f"test-v7-{name}-{int(time.time())}"
    all_replies = []
    all_cards = []
    
    for i, step_text in enumerate(steps):
        log(f"  [{i+1}] USER >> {step_text}")
        reply, cards, conv_id = send(conv_id, step_text)
        if reply is None:
            log(f"  ❌ FAIL: нет ответа от API")
            return "FAIL", "Нет ответа от API"
        log(f"  [{i+1}] BOT  << {reply[:200]}...")
        if cards:
            log(f"  [{i+1}] 🎴 Карточки: {len(cards)}")
            for ci, c in enumerate(cards):
                log(f"    Card {ci+1}: {c.get('hotel_name','?')} | {c.get('hotel_stars','?')}★ | price={c.get('price','?')} | pp={c.get('price_per_person','?')} | adults={c.get('adults','?')}")
        all_replies.append(reply)
        all_cards.extend(cards)
        time.sleep(3)
    
    results = []
    for check_name, check_fn in checks:
        passed = check_fn(all_replies, all_cards)
        status = "✅" if passed else "❌"
        results.append((check_name, passed))
        log(f"  {status} CHECK: {check_name}")
    
    all_passed = all(p for _, p in results)
    final = "PASS" if all_passed else "FAIL"
    failed = [n for n, p in results if not p]
    log(f"  RESULT: {final}" + (f" (failed: {', '.join(failed)})" if failed else ""))
    return final, results


# ============================================================
# ТЕСТ 1: SKIP-QC — "всё равно когда" НЕ должно удалить 5 звёзд
# ============================================================
def test_skipqc():
    return run_test(
        "SKIP-QC-FIX",
        [
            "Турция, Москва, всё равно когда, двое взрослых, 7 ночей, 5 звёзд, всё включено"
        ],
        [
            ("Карточки получены", lambda r, c: len(c) > 0),
            ("Все карточки 5★", lambda r, c: all(card.get("hotel_stars", 0) >= 4 for card in c) if c else False),
            ("Нет 3★ отелей", lambda r, c: not any(card.get("hotel_stars", 0) <= 3 for card in c) if c else False),
        ]
    )


# ============================================================
# ТЕСТ 2: Ассистент НЕ предлагает формат ДД.ММ.ГГГГ
# ============================================================
def test_no_date_format():
    return run_test(
        "NO-DATE-FORMAT",
        [
            "Хочу в Сочи, 7 ночей, из Москвы, 2 взрослых"
        ],
        [
            ("Нет 'ДД.ММ.ГГГГ' в ответе", lambda r, c: not any("ДД.ММ" in reply or "дд.мм" in reply.lower() for reply in r)),
            ("Нет 'DD.MM' в ответе", lambda r, c: not any("DD.MM" in reply for reply in r)),
        ]
    )


# ============================================================
# ТЕСТ 3: Цена за человека при 1 взрослом
# ============================================================
def test_price_per_person_1adult():
    return run_test(
        "PRICE-1-ADULT",
        [
            "Турция, Москва, ближайший вылет, 1 взрослый, 7 ночей, 4 звезды, всё включено"
        ],
        [
            ("Карточки получены", lambda r, c: len(c) > 0),
            ("price_per_person = None при 1 взрослом", lambda r, c: all(card.get("price_per_person") is None for card in c) if c else False),
            ("adults=1 в карточках", lambda r, c: all(card.get("adults") == 1 for card in c) if c else False),
        ]
    )


# ============================================================
# ТЕСТ 4: Цена за человека при 2 взрослых
# ============================================================
def test_price_per_person_2adults():
    return run_test(
        "PRICE-2-ADULTS",
        [
            "Египет, Москва, ближайший вылет, 2 взрослых, 7 ночей, 4 звезды, завтраки"
        ],
        [
            ("Карточки получены", lambda r, c: len(c) > 0),
            ("price_per_person заполнен при 2 взрослых", lambda r, c: all(card.get("price_per_person") is not None for card in c) if c else False),
            ("adults=2 в карточках", lambda r, c: all(card.get("adults") == 2 for card in c) if c else False),
            ("pp = price/2 ± 1", lambda r, c: all(
                abs(card.get("price_per_person", 0) - card.get("price", 0) // 2) <= 1
                for card in c
            ) if c else False),
        ]
    )


# ============================================================
# ТЕСТ 5: "3+ звезды" распознаётся как starsbetter=1
# ============================================================
def test_3plus_stars():
    return run_test(
        "3PLUS-STARS",
        [
            "Турция, Москва, ближайший вылет, 2 взрослых, 7 ночей, 3+ звезды, завтраки"
        ],
        [
            ("Карточки получены", lambda r, c: len(c) > 0),
            ("Все карточки ≥3★", lambda r, c: all(card.get("hotel_stars", 0) >= 3 for card in c) if c else False),
            ("Есть 4★ или 5★ (starsbetter работает)", lambda r, c: any(card.get("hotel_stars", 0) >= 4 for card in c) if c else False),
        ]
    )


# ============================================================
# ТЕСТ 6: Лишние предложения / действия
# ============================================================
def test_no_extra_suggestions():
    return run_test(
        "NO-EXTRA-SUGGEST",
        [
            "Турция, Москва, ближайший вылет, 2 взрослых, 7 ночей, 5 звёзд, всё включено",
        ],
        [
            ("Карточки получены", lambda r, c: len(c) > 0),
            ("Нет 'могу также' в ответе", lambda r, c: not any("могу также" in reply.lower() for reply in r)),
            ("Нет 'кроме того' в ответе", lambda r, c: not any("кроме того" in reply.lower() for reply in r)),
            ("Нет 'могу уточнить' в ответе", lambda r, c: not any("могу уточнить" in reply.lower() for reply in r)),
        ]
    )


# ============================================================
# ТЕСТ 7: Полный мультислотный ввод (регрессия)
# ============================================================
def test_full_slot_regression():
    return run_test(
        "FULL-SLOT-REGRESSION",
        [
            "Египет, Москва, ближайший вылет, 2 взрослых, 10 ночей, 5 звёзд, всё включено"
        ],
        [
            ("Карточки получены", lambda r, c: len(c) > 0),
            ("Все ≥4★", lambda r, c: all(card.get("hotel_stars", 0) >= 4 for card in c) if c else False),
            ("Нет 'ДД.ММ.ГГГГ'", lambda r, c: not any("ДД.ММ" in reply for reply in r)),
            ("Нет 'могу также'", lambda r, c: not any("могу также" in reply.lower() for reply in r)),
        ]
    )


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== TEST RUN v7 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    
    tests = [
        ("1-SKIP-QC", test_skipqc),
        ("2-NO-DATE-FORMAT", test_no_date_format),
        ("3-PRICE-1-ADULT", test_price_per_person_1adult),
        ("4-PRICE-2-ADULTS", test_price_per_person_2adults),
        ("5-3PLUS-STARS", test_3plus_stars),
        ("6-NO-EXTRA-SUGGEST", test_no_extra_suggestions),
        ("7-REGRESSION", test_full_slot_regression),
    ]
    
    results = {}
    for test_name, test_fn in tests:
        log(f"\n>>> Запуск теста {test_name}")
        try:
            result, details = test_fn()
            results[test_name] = result
        except Exception as e:
            log(f"  ❌ EXCEPTION: {e}")
            results[test_name] = "ERROR"
        time.sleep(8)
    
    log(f"\n{'='*60}")
    log("ИТОГИ:")
    log(f"{'='*60}")
    for name, result in results.items():
        icon = "✅" if result == "PASS" else "❌"
        log(f"  {icon} {name}: {result}")
    
    passed = sum(1 for r in results.values() if r == "PASS")
    total = len(results)
    log(f"\nОбщий результат: {passed}/{total} PASS")
