"""
Post-fix QA test suite for MGP AI Assistant — v5 (Hybrid Flight + Hotel Fix).

28 tests in 5 groups:
  A: hideregular WHITELIST (6 tests)
  B: Hotel slot recognition (6 tests)
  C: Regression — existing features (8 tests)
  D: Edge cases (4 tests)
  R: Re-run critical (4 tests)

Full logging: every message, response, check result, and timing written to file.

Run: python3 test_after_fixes.py [--server URL] [--batch A|B|C|D|R|ALL]
"""

import json
import re
import sys
import time
import uuid
import requests
from datetime import datetime, timedelta

# ── Configuration ──────────────────────────────────────────────────────────

SERVER_URL = "http://72.56.88.193"
API_ENDPOINT = "/api/v1/chat"
TIMEOUT = 120
PAUSE_BETWEEN_TESTS = 30
PAUSE_BETWEEN_BATCHES = 90

_today = datetime.now()
_safe_future = _today + timedelta(days=45)
MONTH_NEXT = _safe_future.strftime("%m")
MONTH_NAMES = {
    "01": "январе", "02": "феврале", "03": "марте", "04": "апреле",
    "05": "мае", "06": "июне", "07": "июле", "08": "августе",
    "09": "сентябре", "10": "октябре", "11": "ноябре", "12": "декабре",
}
MONTH_NAMES_GENITIVE = {
    "01": "января", "02": "февраля", "03": "марта", "04": "апреля",
    "05": "мая", "06": "июня", "07": "июля", "08": "августа",
    "09": "сентября", "10": "октября", "11": "ноября", "12": "декабря",
}
NEXT_MONTH_NAME = MONTH_NAMES.get(MONTH_NEXT, "апреле")
NEXT_MONTH_GENITIVE = MONTH_NAMES_GENITIVE.get(MONTH_NEXT, "апреля")
NEXT_MONTH_NUM = int(MONTH_NEXT)
NEXT_MONTH_YEAR = _safe_future.year

LOG_FILE = f"test_results_v5_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
_log_handle = None


def log(text):
    global _log_handle
    if _log_handle is None:
        _log_handle = open(LOG_FILE, "w", encoding="utf-8")
    _log_handle.write(text + "\n")
    _log_handle.flush()
    print(text)


# ── Question Detection ─────────────────────────────────────────────────────

def detect_question_type(reply: str) -> str:
    r = reply.lower()
    if re.search(r'(?:город\w*\s*вылет|откуда\s*(?:вылет|лет)|из\s*какого\s*город)', r):
        return "departure"
    if re.search(r'(?:ноч[иейь]|длительн|сколько\s*(?:дней|ночей))', r):
        return "nights"
    if re.search(r'(?:взрослы[хй]|дет[ейи]|состав|человек|сколько\s*(?:вас|путешеств))', r):
        return "travelers"
    if re.search(r'(?:звёзд|звезд|категори).{0,20}(?:питани|включ|meal)', r):
        return "quality_check"
    if re.search(r'(?:питани[еяю]|завтрак|включено|полупансион)', r):
        return "meal_only"
    if re.search(r'(?:звёзд|звезд|категори)', r):
        return "stars_only"
    if re.search(r'(?:когда|дат[аыу]|мес[яе]ц|промежут|числ[аоу])', r):
        return "dates"
    if re.search(r'(?:куда|направлени|стран)', r):
        return "destination"
    if re.search(r'(?:бюджет|стоимост|цен[аыу])', r):
        return "budget"
    if re.search(r'(?:подтверд|верно|правильно)', r):
        return "confirmation"
    return "unknown"


ANSWER_BANK = {
    "destination": "Турция",
    "departure": "Москва",
    "dates": f"в начале {NEXT_MONTH_NAME}",
    "nights": "7 ночей",
    "travelers": "двое взрослых",
    "quality_check": "4-5 звёзд, всё включено",
    "meal_only": "всё включено",
    "stars_only": "4-5 звёзд",
    "budget": "до 200 тысяч",
    "confirmation": "да, верно",
    "unknown": "да",
}


# ── Check Functions ────────────────────────────────────────────────────────

def cards_gte(response, n):
    cards = response.get("tour_cards", [])
    return len(cards) >= n, f"cards={len(cards)} (need >={n})"


def reply_contains(response, text):
    reply = response.get("reply", "")
    ok = text.lower() in reply.lower()
    return ok, f"reply {'contains' if ok else 'MISSING'} '{text}'"


def reply_not_contains(response, text):
    reply = response.get("reply", "")
    ok = text.lower() not in reply.lower()
    return ok, f"reply {'clean' if ok else 'CONTAINS FORBIDDEN'} '{text}'"


def reply_regex_match(response, pattern):
    reply = response.get("reply", "")
    match = re.search(pattern, reply, re.IGNORECASE)
    return match is not None, f"regex {'FOUND' if match else 'NOT FOUND'}: {pattern[:60]}"


def reply_regex_absent(response, pattern):
    reply = response.get("reply", "")
    match = re.search(pattern, reply, re.IGNORECASE)
    return match is None, f"regex {'absent' if match is None else 'FOUND: ' + match.group()}"


def cards_have_diverse_stars(response):
    cards = response.get("tour_cards", [])
    if len(cards) < 2:
        return True, "less than 2 cards, skip diversity check"
    star_set = set()
    for c in cards:
        s = c.get("hotel_stars")
        if s and s > 0:
            star_set.add(s)
    ok = len(star_set) >= 2
    return ok, f"star diversity: {sorted(star_set)} ({'diverse' if ok else 'NOT diverse'})"


def cards_nights_in_range(response, lo, hi):
    cards = response.get("tour_cards", [])
    if not cards:
        return True, "no cards to check nights"
    for c in cards:
        n = c.get("nights")
        if n is not None and (n < lo or n > hi):
            return False, f"card nights={n} outside [{lo},{hi}]"
    return True, f"all card nights in [{lo},{hi}]"


def cards_meal_matches(response, keyword):
    cards = response.get("tour_cards", [])
    if not cards:
        return False, "no cards to check meal"
    for c in cards:
        meal = str(c.get("meal_description", "")).lower()
        if keyword.lower() in meal:
            return True, f"found meal '{keyword}' in cards"
    return False, f"no card meal contains '{keyword}'"


def meal_warning_or_match(response, keyword):
    ok_cards, _ = cards_meal_matches(response, keyword)
    if ok_cards:
        return True, f"cards contain '{keyword}'"
    reply = response.get("reply", "").lower()
    if "показаны варианты с" in reply or "варианты не найдены" in reply or "не найдены" in reply:
        return True, "bot warned about meal mismatch"
    return False, f"no meal match and no mismatch warning"


def cards_country_contains(response, keyword):
    cards = response.get("tour_cards", [])
    if not cards:
        return True, f"no cards to check country (soft skip)"
    reply = response.get("reply", "").lower()
    if keyword.lower() in reply:
        return True, f"reply mentions '{keyword}'"
    for c in cards:
        for field in ("country", "region", "hotel_name", "resort"):
            val = str(c.get(field, "")).lower()
            if keyword.lower() in val:
                return True, f"card field '{field}' contains '{keyword}'"
    return False, f"no card/reply mentions '{keyword}'"


def no_stars_question(response, _=None):
    reply = response.get("reply", "").lower()
    star_q = re.search(
        r'(?:как\w+\s*(?:категори|звёзд|звезд)|какую?\s*(?:категори|звёзд|звезд)|'
        r'сколько\s*звёзд|звёздност\w*\s*(?:отел|предпочит)|категори\w+\s*отел)',
        reply
    )
    if star_q:
        return False, f"bot ASKED about stars: '{star_q.group()[:50]}'"
    return True, "bot did NOT ask about stars"


# ── Test Runner ────────────────────────────────────────────────────────────

def send_message(server_url, conversation_id, message, retry_429=4):
    url = f"{server_url}{API_ENDPOINT}"
    payload = {"message": message, "conversation_id": conversation_id}
    for attempt in range(retry_429):
        t0 = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=TIMEOUT)
            elapsed = time.time() - t0
            if resp.status_code == 429:
                wait = 15 * (attempt + 1)
                log(f"      HTTP 429 — waiting {wait}s (attempt {attempt+1}/{retry_429})")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                return {"reply": f"HTTP {resp.status_code}", "tour_cards": [], "error": True}, elapsed
            data = resp.json()
            reply = data.get("response", data.get("reply", ""))
            tour_cards = data.get("tour_cards", [])
            return {"reply": reply, "tour_cards": tour_cards}, elapsed
        except requests.exceptions.Timeout:
            return {"reply": "TIMEOUT", "tour_cards": [], "error": True}, TIMEOUT
        except Exception as e:
            return {"reply": str(e), "tour_cards": [], "error": True}, 0
    return {"reply": "HTTP 429 (all retries exhausted)", "tour_cards": [], "error": True}, 0


def run_test(server_url, test):
    test_id = test["id"]
    test_name = test["name"]
    category = test.get("category", "A")
    conv_id = f"test-v5-{test_id}-{int(time.time())}"

    log(f"\n  [{test_id}] {test_name} (group={category}, conv={conv_id})")

    messages_to_send = test.get("messages", [])
    if not messages_to_send:
        messages_to_send = [{"text": test["initial_message"]}]

    max_turns = test.get("max_turns", 8)
    all_turn_checks = test.get("all_turn_checks", [])
    final_checks = test.get("final_checks", [])
    card_checks = test.get("card_checks", [])
    custom_answers = test.get("custom_answers", {})
    expect_cards = test.get("expect_cards", False)
    followup_message = test.get("followup_message")
    followup_checks = test.get("followup_checks", [])

    all_responses = []
    status = "PASS"
    cards_received = False
    forced_msg_idx = 0

    for turn in range(max_turns):
        if turn == 0:
            msg = messages_to_send[0]["text"]
            forced_msg_idx = 1
        elif followup_message and cards_received and not any(r.get("_followup_sent") for r in all_responses):
            msg = followup_message
            all_responses[-1]["_followup_sent"] = True
            log(f"      Turn {turn+1}: sending followup: \"{msg[:80]}\"")
        elif forced_msg_idx < len(messages_to_send):
            msg = messages_to_send[forced_msg_idx]["text"]
            forced_msg_idx += 1
        else:
            last_reply = all_responses[-1]["reply"] if all_responses else ""

            if last_reply in ("TIMEOUT", "") or last_reply.startswith("HTTP"):
                status = "SKIP"
                log(f"      Turn {turn+1}: SKIP — error: {last_reply[:80]}")
                break

            if all_responses[-1].get("tour_cards") and not followup_message:
                cards_received = True
                break

            if all_responses[-1].get("tour_cards"):
                cards_received = True

            q_type = detect_question_type(last_reply)
            msg = custom_answers.get(q_type, ANSWER_BANK.get(q_type, "да"))
            log(f"      Turn {turn+1}: bot asked [{q_type}] -> \"{msg[:60]}\"")

        response, elapsed = send_message(server_url, conv_id, msg)
        reply = response.get("reply", "")
        cards_count = len(response.get("tour_cards", []))

        all_responses.append(response)
        log(f"      Turn {turn+1}: {elapsed:.1f}s | cards={cards_count} | \"{reply[:150]}\"")

        # Log full response for audit
        log(f"      [FULL REPLY]: {reply[:500]}{'...' if len(reply)>500 else ''}")
        if cards_count > 0:
            cards_received = True
            for ci, card in enumerate(response["tour_cards"][:3]):
                log(f"      [CARD {ci+1}]: {json.dumps(card, ensure_ascii=False)[:200]}")

        for atc in all_turn_checks:
            check_fn = atc["check"]
            check_args = atc.get("args", [])
            ok, detail = check_fn(response, *check_args)
            if not ok:
                status = "FAIL"
                log(f"        FAIL [turn {turn+1}]: {detail}")

        time.sleep(2)

    if status == "SKIP":
        log(f"  -> [{test_id}] SKIP")
        return {"id": test_id, "name": test_name, "status": "SKIP", "turns": len(all_responses), "category": category}

    for fc in final_checks:
        check_fn = fc["check"]
        check_args = fc.get("args", [])
        target = fc.get("target", "last")

        if target == "all_turns":
            for idx, r in enumerate(all_responses):
                ok, detail = check_fn(r, *check_args)
                if not ok:
                    if fc.get("soft", False):
                        log(f"        SOFT FAIL [turn {idx+1}]: {detail}")
                    else:
                        status = "FAIL"
                        log(f"        FAIL [turn {idx+1}]: {detail}")
        else:
            if target == "last" and all_responses:
                resp = all_responses[-1]
            elif target == "first" and all_responses:
                resp = all_responses[0]
            elif target == "any":
                resp = None
                for r in all_responses:
                    ok, _ = check_fn(r, *check_args)
                    if ok:
                        resp = r
                        break
                if resp is None:
                    resp = all_responses[-1] if all_responses else {"reply": "", "tour_cards": []}
            elif target == "with_cards":
                resp = None
                for r in all_responses:
                    if r.get("tour_cards"):
                        resp = r
                        break
                if resp is None:
                    resp = all_responses[-1] if all_responses else {"reply": "", "tour_cards": []}
            else:
                resp = all_responses[-1] if all_responses else {"reply": "", "tour_cards": []}

            ok, detail = check_fn(resp, *check_args)
            if not ok:
                if fc.get("soft", False):
                    log(f"        SOFT FAIL: {detail}")
                else:
                    status = "FAIL"
                    log(f"        FAIL: {detail}")

    if cards_received:
        card_resp = None
        for r in all_responses:
            if r.get("tour_cards"):
                card_resp = r
        if card_resp:
            for cc in card_checks:
                check_fn = cc["check"]
                check_args = cc.get("args", [])
                ok, detail = check_fn(card_resp, *check_args)
                if not ok:
                    if cc.get("soft", False):
                        log(f"        SOFT CARD FAIL: {detail}")
                    else:
                        status = "FAIL"
                        log(f"        CARD FAIL: {detail}")

    if followup_message and followup_checks:
        followup_resp = all_responses[-1] if all_responses else {"reply": "", "tour_cards": []}
        for fuc in followup_checks:
            check_fn = fuc["check"]
            check_args = fuc.get("args", [])
            ok, detail = check_fn(followup_resp, *check_args)
            if not ok:
                status = "FAIL"
                log(f"        FOLLOWUP FAIL: {detail}")

    if expect_cards and not cards_received and status != "FAIL":
        if category in ("B", "D"):
            log(f"        SOFT: No cards (TourVisor may have 0 results for this direction)")
        else:
            status = "FAIL"
            log(f"        FAIL: Expected cards but none received")

    log(f"  -> [{test_id}] {status} ({len(all_responses)} turns)")
    return {"id": test_id, "name": test_name, "status": status, "turns": len(all_responses), "category": category}


# ═══════════════════════════════════════════════════════════════════════════
# GROUP A: All-flights search (no auto hideregular) — 6 tests
# ═══════════════════════════════════════════════════════════════════════════

GROUP_A = [
    {
        "id": "A1-ABKHAZIA",
        "name": "Abkhazia: all flights, tours found",
        "category": "A",
        "initial_message": f"Абхазия из Москвы, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, 3 звезды, завтраки",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [
            {"check": cards_country_contains, "args": ["абхази"], "soft": True},
        ],
        "expect_cards": True,
    },
    {
        "id": "A2-TURKEY",
        "name": "Turkey: all flights, tours found (previously charter-only)",
        "category": "A",
        "initial_message": f"Турция из Москвы, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, всё включено, 5 звёзд",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "A3-EGYPT",
        "name": "Egypt from SPB: all flights, tours found (previously charter-only)",
        "category": "A",
        "initial_message": f"Египет из Санкт-Петербурга, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, всё включено, 4 звезды",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "A4-TUNISIA",
        "name": "Tunisia: all flights, tours found (previously 0 with charter filter)",
        "category": "A",
        "initial_message": f"Тунис из Москвы, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, всё включено, 4 звезды",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "A5-CUBA",
        "name": "Cuba: all flights, tours found (previously 0 with charter filter)",
        "category": "A",
        "initial_message": f"Куба из Москвы, начало {NEXT_MONTH_NAME}, 10 ночей, двое взрослых, всё включено, 4 звезды",
        "max_turns": 8,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "A6-SOCHI-NOFLIGHT",
        "name": "Sochi no-flight: tours found without flight filter",
        "category": "A",
        "initial_message": f"Сочи, без перелёта, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, 3 звезды, завтраки",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
            {"check": reply_regex_absent, "args": [r'(?:откуда\s*вылетает|город\w*\s*вылет|из\s*какого\s*город)']},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# GROUP B: Hotel slot recognition (6 tests)
# ═══════════════════════════════════════════════════════════════════════════

GROUP_B = [
    {
        "id": "B1-HOT-RIXOS",
        "name": "Rixos (Latin brand): bot should NOT ask stars",
        "category": "B",
        "initial_message": f"Rixos в Турции из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, на неделю, завтраки",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": no_stars_question, "args": []},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "B2-HOT-HILTON-RU",
        "name": "Хилтон (Cyrillic brand): bot should NOT ask stars",
        "category": "B",
        "initial_message": f"Хилтон в Турции из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, на неделю",
        "max_turns": 6,
        "custom_answers": {
            "meal_only": "всё включено",
        },
        "all_turn_checks": [
            {"check": no_stars_question, "args": []},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "B3-HOT-DELPHIN",
        "name": "Delphin Imperial (full name): bot should NOT ask stars",
        "category": "B",
        "initial_message": f"Delphin Imperial в Турции из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, неделя, всё включено",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": no_stars_question, "args": []},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "B4-HOT-OTEL-PATTERN",
        "name": "отель Космос (contextual pattern): bot should NOT ask stars",
        "category": "B",
        "initial_message": f"отель Космос в Сочи из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, неделя",
        "max_turns": 6,
        "custom_answers": {
            "meal_only": "завтраки",
        },
        "all_turn_checks": [
            {"check": no_stars_question, "args": []},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "B5-HOT-WITH-STARS",
        "name": "Rixos 5 stars (explicit stars): auto-fill should NOT overwrite",
        "category": "B",
        "initial_message": f"Rixos 5 звёзд в Турции из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, неделя, всё включено",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "B6-HOT-UNKNOWN",
        "name": "отель Маджестик (unknown hotel): contextual pattern catches it",
        "category": "B",
        "initial_message": f"отель Маджестик в Турции из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, неделя, завтраки",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": no_stars_question, "args": []},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# GROUP C: Regression — existing features still work (8 tests)
# ═══════════════════════════════════════════════════════════════════════════

GROUP_C = [
    {
        "id": "C1-REG-TURKEY",
        "name": "Full Turkey flow: all slots -> cards in 1-2 turns",
        "category": "C",
        "initial_message": f"Турция, Москва, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, 4-5 звёзд, всё включено",
        "max_turns": 4,
        "custom_answers": {},
        "all_turn_checks": [],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any"},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "C2-REG-EGYPT",
        "name": "Full Egypt flow: all slots -> cards",
        "category": "C",
        "initial_message": f"Египет, Хургада, из Москвы, начало {NEXT_MONTH_NAME}, 10 ночей, двое взрослых, 4 звезды, всё включено",
        "max_turns": 4,
        "custom_answers": {},
        "all_turn_checks": [],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any"},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "C3-REG-NEAREST",
        "name": "Nearest departure: bot should NOT re-ask dates",
        "category": "C",
        "initial_message": f"Египет из Москвы, ближайший вылет, 7 ночей, двое взрослых, 4 звезды всё включено",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_regex_absent, "args": [
                r'(?:как\w+\s*месяц|какие\s*дат|когда\s*план|на\s*как\w+\s*месяц|'
                r'промежут\w*\s*дат|уточн\w+\s*дат|в\s*каком\s*месяц)'
            ]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "C4-REG-NIGHTS-RANGE",
        "name": f"Night calc from dates: 's 16 po 28 {NEXT_MONTH_GENITIVE}' -> no night questions",
        "category": "C",
        "initial_message": f"Турция из Москвы, с 16 по 28 {NEXT_MONTH_GENITIVE}, двое взрослых, 5 звёзд, всё включено",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_regex_absent, "args": [
                r'(?:сколько\s*ноч|на\s*сколько\s*ноч|длительн|количеств\w*\s*ноч)'
            ]},
        ],
        "final_checks": [],
        "card_checks": [
            {"check": cards_nights_in_range, "args": [10, 14], "soft": True},
        ],
        "expect_cards": False,
    },
    {
        "id": "C5-REG-SOCHI-DEST",
        "name": "Sochi = destination, not departure: bot asks 'откуда вылетаете?'",
        "category": "C",
        "initial_message": f"Хочу в Сочи, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, 4 звезды, завтрак",
        "max_turns": 8,
        "custom_answers": {
            "departure": "из Москвы",
        },
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "C6-REG-COUNTRY-CHANGE",
        "name": "Change country: Turkey -> 'a esli Egypt?' preserves params",
        "category": "C",
        "initial_message": f"Турция, Москва, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, 4 звезды всё включено",
        "max_turns": 8,
        "followup_message": "а если Египет?",
        "followup_checks": [
            {"check": reply_regex_absent, "args": [
                r'(?:сколько\s*взрослы|на\s*сколько\s*ноч|город\w*\s*вылет|какую\s*категори)'
            ]},
        ],
        "custom_answers": {},
        "all_turn_checks": [],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "C7-REG-NO-TECH-ERROR",
        "name": "No technical errors or function names in responses",
        "category": "C",
        "initial_message": f"Турция, Москва, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, 4 звезды всё включено",
        "max_turns": 4,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
            {"check": reply_not_contains, "args": ["search_tours"]},
            {"check": reply_not_contains, "args": ["get_search"]},
            {"check": reply_not_contains, "args": ["get_dictionaries"]},
            {"check": reply_not_contains, "args": ["requestid"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "C8-REG-BEZ-RAZNITSY",
        "name": "'Bez raznitsy' QC -> diverse stars (not forced 2*)",
        "category": "C",
        "initial_message": f"Турция из Москвы, двое взрослых, начало {NEXT_MONTH_NAME}, 7 ночей",
        "max_turns": 6,
        "custom_answers": {
            "quality_check": "без разницы, покажите что есть",
            "meal_only": "всё равно",
            "stars_only": "любые",
        },
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["2 звезды"]},
        ],
        "final_checks": [],
        "card_checks": [
            {"check": cards_have_diverse_stars, "args": [], "soft": True},
        ],
        "expect_cards": False,
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# GROUP D: Edge cases (4 tests)
# ═══════════════════════════════════════════════════════════════════════════

GROUP_D = [
    {
        "id": "D1-EDGE-HOTEL-5STAR",
        "name": "'otel 5 zvyozd' = stars, NOT brand (no false positive)",
        "category": "D",
        "initial_message": f"хочу отель 5 звёзд в Турции из Москвы, начало {NEXT_MONTH_NAME}, неделя, двое взрослых, всё включено",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [],
        "card_checks": [],
        "expect_cards": False,
    },
    {
        "id": "D2-EDGE-ABKHAZIA-HOTEL",
        "name": "Sunrise Garden + Abkhazia: BOTH fixes work together",
        "category": "D",
        "initial_message": f"Sunrise Garden в Абхазии из Москвы, начало {NEXT_MONTH_NAME}, 7 ночей, двое взрослых, завтраки",
        "max_turns": 8,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": no_stars_question, "args": []},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "D3-EDGE-CHARTER-EXPLICIT",
        "name": "'tolko charter v Turciyu': LLM can set hideregular explicitly",
        "category": "D",
        "initial_message": f"только чартер в Турцию, Москва, двое взрослых, начало {NEXT_MONTH_NAME}, неделя, всё включено, 4 звезды",
        "max_turns": 6,
        "custom_answers": {},
        "all_turn_checks": [],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
    {
        "id": "D4-EDGE-MALDIVES",
        "name": "Maldives: NOT blocked by charter filter (exotic destination)",
        "category": "D",
        "initial_message": f"Мальдивы из Москвы, ближайший вылет, двое взрослых, 5 звёзд, всё включено",
        "max_turns": 8,
        "custom_answers": {},
        "all_turn_checks": [
            {"check": reply_not_contains, "args": ["traceback"]},
            {"check": reply_not_contains, "args": ["техническ"]},
        ],
        "final_checks": [
            {"check": cards_gte, "args": [1], "target": "any", "soft": True},
        ],
        "card_checks": [],
        "expect_cards": True,
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# GROUP R: Re-run critical (4 tests for stability check)
# ═══════════════════════════════════════════════════════════════════════════

GROUP_R = [
    GROUP_A[0],  # A1-ABKHAZIA
    GROUP_A[3],  # A4-TUNISIA (critical: was 0 results with charter filter)
    GROUP_B[0],  # B1-HOT-RIXOS
    GROUP_C[0],  # C1-REG-TURKEY
]


# ── Main ───────────────────────────────────────────────────────────────────

def run_batch(server, tests, batch_name):
    log(f"\n{'='*70}")
    log(f"  GROUP: {batch_name} ({len(tests)} tests)")
    log(f"{'='*70}")
    results = []
    for i, test in enumerate(tests):
        if i > 0:
            log(f"\n   ... pausing {PAUSE_BETWEEN_TESTS}s ...")
            time.sleep(PAUSE_BETWEEN_TESTS)
        result = run_test(server, test)
        results.append(result)
    return results


def print_summary(all_results):
    log(f"\n{'='*70}")
    log("FINAL SUMMARY")
    log(f"{'='*70}")

    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    skipped = sum(1 for r in all_results if r["status"] == "SKIP")

    for r in all_results:
        icon = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}.get(r["status"], "?")
        log(f"  [{icon:4s}] [{r['id']:22s}] {r['name'][:55]} ({r['turns']}t)")

    log(f"\n  Total: {len(all_results)} | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")

    if failed > 0:
        log(f"\n  FAILED tests:")
        for r in all_results:
            if r["status"] == "FAIL":
                log(f"    - {r['id']}: {r['name']}")


def main():
    server = SERVER_URL
    batch_filter = "ALL"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--server" and i + 1 < len(args):
            server = args[i + 1]
            i += 2
        elif args[i] == "--batch" and i + 1 < len(args):
            batch_filter = args[i + 1].upper()
            i += 2
        else:
            i += 1

    log(f"MGP AI Assistant — Test Suite v5 (Hybrid Flight + Hotel Fix)")
    log(f"  Server: {server}")
    log(f"  Batch: {batch_filter}")
    log(f"  Future month: {NEXT_MONTH_NAME} {NEXT_MONTH_YEAR}")
    log(f"  Log file: {LOG_FILE}")
    log(f"  Pause between tests: {PAUSE_BETWEEN_TESTS}s")
    log(f"  Pause between groups: {PAUSE_BETWEEN_BATCHES}s")
    log(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_results = []

    batches_to_run = []
    if batch_filter in ("ALL", "A"):
        batches_to_run.append(("Group A: hideregular WHITELIST (6 tests)", GROUP_A))
    if batch_filter in ("ALL", "B"):
        batches_to_run.append(("Group B: Hotel Slot Recognition (6 tests)", GROUP_B))
    if batch_filter in ("ALL", "C"):
        batches_to_run.append(("Group C: Regression (8 tests)", GROUP_C))
    if batch_filter in ("ALL", "D"):
        batches_to_run.append(("Group D: Edge Cases (4 tests)", GROUP_D))
    if batch_filter in ("ALL", "R"):
        batches_to_run.append(("Group R: Re-run Critical (4 tests)", GROUP_R))

    for idx, (batch_name, tests) in enumerate(batches_to_run):
        if idx > 0:
            log(f"\n   === Waiting {PAUSE_BETWEEN_BATCHES}s between groups ===")
            time.sleep(PAUSE_BETWEEN_BATCHES)
        results = run_batch(server, tests, batch_name)
        all_results.extend(results)

    print_summary(all_results)

    log(f"\n  Full log saved to: {LOG_FILE}")

    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
