#!/usr/bin/env python3
"""
Test script for context limit warning feature.
Tests 3 scenarios against the live API at http://72.56.88.193/api/v1/chat

Each scenario tracks:
- User messages sent
- Assistant responses received
- When soft warning (stage 1, ~60 msgs) appears
- When hard warning (stage 2, ~72 msgs) appears
- Whether context is maintained correctly
"""
import requests
import json
import time
import uuid
import sys

BASE_URL = "http://72.56.88.193"
API_URL = f"{BASE_URL}/api/v1/chat"
RESET_URL = f"{BASE_URL}/api/reset"

SOFT_WARNING_MARKER = "Наш диалог уже достаточно длинный"
HARD_WARNING_MARKER = "Диалог подходит к завершению"
DATA_SUMMARY_MARKER = "Вот данные из нашего разговора"


def send_message(conversation_id: str, message: str, timeout: int = 120) -> dict:
    """Send a message and return the full response dict."""
    resp = requests.post(API_URL, json={
        "message": message,
        "conversation_id": conversation_id,
    }, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def reset_session(conversation_id: str):
    """Reset a chat session."""
    try:
        requests.post(RESET_URL, json={"session_id": conversation_id}, timeout=10)
    except Exception:
        pass


def check_warnings(reply: str) -> tuple:
    """Return (has_soft, has_hard, has_summary)."""
    return (
        SOFT_WARNING_MARKER in reply,
        HARD_WARNING_MARKER in reply,
        DATA_SUMMARY_MARKER in reply,
    )


def run_test(test_name: str, messages: list, conversation_id: str = None):
    """Run a test scenario, printing results as we go."""
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())

    reset_session(conversation_id)
    time.sleep(1)

    print(f"\n{'='*70}")
    print(f"  TEST: {test_name}")
    print(f"  conversation_id: {conversation_id}")
    print(f"  Total messages to send: {len(messages)}")
    print(f"{'='*70}")

    user_count = 0
    assistant_count = 0
    soft_warning_at = None
    hard_warning_at = None
    tour_cards_total = 0
    errors = []

    for i, msg in enumerate(messages, 1):
        user_count += 1
        print(f"\n--- Message {i}/{len(messages)} ---")
        print(f"  USER: {msg[:80]}{'...' if len(msg) > 80 else ''}")

        try:
            t0 = time.time()
            result = send_message(conversation_id, msg)
            elapsed = time.time() - t0

            reply = result.get("reply", "")
            cards = result.get("tour_cards", [])
            tour_cards_total += len(cards)
            assistant_count += 1

            has_soft, has_hard, has_summary = check_warnings(reply)

            reply_preview = reply[:150].replace('\n', ' ')
            print(f"  ASSISTANT ({elapsed:.1f}s): {reply_preview}{'...' if len(reply) > 150 else ''}")
            if cards:
                print(f"  TOUR CARDS: {len(cards)}")
            if has_soft and soft_warning_at is None:
                soft_warning_at = user_count
                print(f"  >>> SOFT WARNING DETECTED at user message #{user_count}")
            if has_hard and hard_warning_at is None:
                hard_warning_at = user_count
                print(f"  >>> HARD WARNING DETECTED at user message #{user_count}")
            if has_summary:
                summary_start = reply.find(DATA_SUMMARY_MARKER)
                print(f"  >>> DATA SUMMARY: {reply[summary_start:summary_start+200]}")

            time.sleep(3)

        except Exception as e:
            errors.append((i, str(e)))
            print(f"  ERROR: {e}")
            time.sleep(5)

    print(f"\n{'='*70}")
    print(f"  RESULTS: {test_name}")
    print(f"{'='*70}")
    print(f"  User messages sent:    {user_count}")
    print(f"  Assistant responses:   {assistant_count}")
    print(f"  Tour cards shown:      {tour_cards_total}")
    print(f"  Soft warning at msg:   {soft_warning_at or 'NOT SHOWN'}")
    print(f"  Hard warning at msg:   {hard_warning_at or 'NOT SHOWN'}")
    print(f"  Errors:                {len(errors)}")
    if errors:
        for msg_num, err in errors:
            print(f"    - Message {msg_num}: {err[:100]}")
    print(f"{'='*70}\n")

    return {
        "test_name": test_name,
        "user_messages": user_count,
        "assistant_responses": assistant_count,
        "tour_cards_total": tour_cards_total,
        "soft_warning_at": soft_warning_at,
        "hard_warning_at": hard_warning_at,
        "errors": errors,
    }


# ── Test 1: Simple consultation (no searches) ──
TEST1_MESSAGES = [
    "Привет! Хочу поехать отдохнуть, но пока не определился куда",
    "Какие направления сейчас популярны?",
    "А что насчет Турции? Какие курорты там хорошие?",
    "А в Египте какие курорты лучше?",
    "Чем отличается Хургада от Шарм-эль-Шейха?",
    "А какое питание лучше выбрать - все включено или завтраки?",
    "Сколько примерно стоит тур в Турцию на двоих?",
    "А в Египет дешевле или дороже?",
    "Какой месяц лучше для поездки в Турцию?",
    "А в ОАЭ когда лучше ехать?",
    "Мне нужен отель с хорошим пляжем, посоветуй",
    "А какие отели в Турции самые лучшие для семьи с детьми?",
    "Нам нужен аквапарк в отеле, это возможно?",
    "Какие документы нужны для поездки в Турцию?",
    "А виза в Египет нужна?",
    "Спасибо за информацию! А можно подробнее про Анталию?",
    "Какие экскурсии есть в Анталии?",
    "А трансфер из аэропорта обычно включен?",
    "Сколько лететь до Анталии из Москвы?",
    "А до Хургады?",
    "Какой бюджет лучше заложить на экскурсии?",
    "А на питание вне отеля?",
    "Хорошо, я подумаю. А можно узнать про Мальдивы?",
    "Сколько стоит тур на Мальдивы?",
    "А когда лучшее время для Мальдив?",
    "Какие отели на Мальдивах самые лучшие?",
    "Понятно, дорого. А есть что-то бюджетное но красивое?",
    "А что скажешь про Тунис?",
    "Какое море в Тунисе?",
    "Окей, давай все-таки подберем что-нибудь в Турцию",
]

# ── Test 2: Two searches (Turkey + Egypt) + consultation ──
TEST2_MESSAGES = [
    "Хочу в Турцию из Москвы",
    "2 взрослых, вылет в начале апреля",
    "7 ночей, 4-5 звезд, все включено",
    # After cards appear, ask questions
    "Расскажи подробнее про первый отель",
    "А какой перелет?",
    "Хорошо, а теперь покажи мне варианты в Египет",
    "Тоже из Москвы, 2 взрослых, начало апреля",
    "7 ночей, 5 звезд, все включено",
    # After cards, more questions
    "Какой из этих отелей лучше?",
    "А пляж там хороший?",
    "Сравни Турцию и Египет по цене",
    "А по качеству отелей?",
    "Хорошо, я склоняюсь к Турции. Можно забронировать первый вариант?",
    "А есть ли скидки?",
    "Какие условия отмены бронирования?",
]

# ── Test 3: Maximum load - 4 searches across destinations ──
TEST3_MESSAGES = [
    # Search 1: Turkey
    "Хочу в Турцию из Москвы, 2 взрослых",
    "Начало апреля, 7 ночей, 5 звезд, все включено",
    "Расскажи про первый вариант",
    "Какой там перелет?",
    # Search 2: Egypt
    "А теперь покажи Египет, те же параметры",
    "7 ночей, 5 звезд, все включено из Москвы",
    "Что скажешь про первый отель?",
    # Search 3: UAE
    "Хочу посмотреть ОАЭ тоже",
    "Из Москвы, 2 взрослых, апрель, 5 ночей, 4-5 звезд",
    "Какой отель лучший из предложенных?",
    "А пляж хороший?",
    # Search 4: Thailand
    "И покажи еще Таиланд пожалуйста",
    "Из Москвы, 2 взрослых, апрель, 10 ночей, 4-5 звезд",
    "Расскажи подробнее про лучший вариант",
    # Consultation across all
    "Сравни все 4 направления по цене",
    "А по качеству пляжей?",
    "Какое направление лучше для пляжного отдыха?",
    "А для экскурсий?",
    "Хорошо, склоняюсь к Турции. Напомни что ты мне показывал",
    "А Египет какие были варианты?",
    "Спасибо! Хочу забронировать тур в Турцию",
]


def main():
    test_num = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    results = []

    if test_num == 0 or test_num == 1:
        r = run_test("Test 1: Простая консультация (без поисков)", TEST1_MESSAGES)
        results.append(r)

    if test_num == 0 or test_num == 2:
        r = run_test("Test 2: Два поиска (Турция + Египет)", TEST2_MESSAGES)
        results.append(r)

    if test_num == 0 or test_num == 3:
        r = run_test("Test 3: Максимальная нагрузка (4 направления)", TEST3_MESSAGES)
        results.append(r)

    print("\n" + "="*70)
    print("  SUMMARY")
    print("="*70)
    for r in results:
        print(f"\n  {r['test_name']}:")
        print(f"    User msgs:        {r['user_messages']}")
        print(f"    Assistant msgs:   {r['assistant_responses']}")
        print(f"    Tour cards:       {r['tour_cards_total']}")
        print(f"    Soft warning:     msg #{r['soft_warning_at']}" if r['soft_warning_at'] else f"    Soft warning:     NOT TRIGGERED")
        print(f"    Hard warning:     msg #{r['hard_warning_at']}" if r['hard_warning_at'] else f"    Hard warning:     NOT TRIGGERED")
        print(f"    Errors:           {len(r['errors'])}")


if __name__ == "__main__":
    main()
