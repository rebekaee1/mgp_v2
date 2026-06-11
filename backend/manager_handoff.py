"""Manager-handoff — чистая логика «вход менеджера в чат» (MAX).

Модуль СОЗНАТЕЛЬНО без Flask/DB зависимостей: только `config.settings` (для
флага/allow-list) + stdlib. Тестируется изолированно. Вся интеграция (БД, HTTP,
эмиссия событий) — в app.py / dialog_sender.py / max_subscription_watchdog-стиле.

Инвариант безопасности: пока `OPERATOR_HANDOFF_ENABLED=false` ИЛИ assistant_id не
в allow-list ИЛИ канал не разрешён — `handoff_enabled()` возвращает False, и весь
остальной код фичи становится no-op. Существующие диалоги/тенанты не затрагиваются.

Контракт значений (см. docs/handoff/MANAGER_HANDOFF_CONTRACT.md):
  handoff_state : none | requested | operator | returned
  handoff_reason: manager_request | booking | contact | manual  (v3; book_click/
                  booking_intent/phrase — deprecated, не триггерят)
  operator_mode : bool (true ⇒ ИИ на паузе, только при реальном заходе менеджера)
"""
from __future__ import annotations

import re
from typing import Optional

# ── Состояния / причины (канонические значения контракта) ──
STATE_NONE = "none"
STATE_REQUESTED = "requested"
STATE_OPERATOR = "operator"
STATE_RETURNED = "returned"

# v3 (2026-06-11): причины уведомления, раздельные для приоритизации в ЛК.
REASON_MANAGER_REQUEST = "manager_request"   # клиент хочет человека/консультацию/бронь ЧЕРЕЗ менеджера
REASON_BOOKING = "booking"                   # явное само-намерение брони (без упоминания менеджера)
REASON_CONTACT = "contact"                   # оставил телефон
REASON_MANUAL = "manual"                     # ручной перехват менеджером из ЛК
# DEPRECATED (v1/v2): оставлены для обратной совместимости импортов. В v3 НЕ
# триггерят: book_click — только трекинг воронки; широкий booking_intent убран.
REASON_BOOK_CLICK = "book_click"
REASON_BOOKING_INTENT = "booking_intent"
REASON_PHRASE = "phrase"

# Семантика v3: НИ ОДИН клиентский триггер не ставит ИИ на паузу — ИИ ПРОДОЛЖАЕТ
# вести диалог; сообщение клиенту формирует промпт (контакт-first, без обещаний
# времени). Уведомление менеджеру (manager_alert) шлётся на manager_request /
# booking / contact. Пауза ИИ (operator_mode=True) — ИСКЛЮЧИТЕЛЬНО при РЕАЛЬНОМ
# заходе менеджера (ручки /api/runtime/operator/*).
ALERT_REASONS = frozenset({REASON_MANAGER_REQUEST, REASON_BOOKING, REASON_CONTACT})
HARD_REASONS = frozenset({REASON_MANAGER_REQUEST, REASON_BOOKING, REASON_CONTACT, REASON_MANUAL})
SOFT_REASONS = frozenset()

# Приоритет причин (для апгрейда reason в рамках одного цикла, без повторного
# алерта): просьба менеджера > контакт > бронь.
REASON_PRIORITY = {REASON_MANAGER_REQUEST: 3, REASON_CONTACT: 2, REASON_BOOKING: 1}


def reason_priority(reason: Optional[str]) -> int:
    return REASON_PRIORITY.get(reason or "", 0)

# DEPRECATED (модель v1): анонс при жёстком перехвате, когда ИИ сразу паузился.
# Оставлен для обратной совместимости/тестов; в модели v2 НЕ используется —
# вместо него ACK_* (ИИ продолжает) и OPERATOR_JOINED_TEXT (реальный заход).
ANNOUNCE_TEXT = (
    "Спасибо за интерес! Чтобы подобрать лучшие условия и помочь с бронированием, "
    "к диалогу подключится наш менеджер. Это займёт пару минут — пожалуйста, "
    "не закрывайте чат."
)

# Заверение клиенту при ЖЁСТКОМ триггере (ИИ ПРОДОЛЖАЕТ вести диалог). Без
# эмодзи. Если контакт уже оставлен — не просим телефон повторно; иначе мягко
# просим номер, чтобы лид не потерялся, даже если менеджер не подключится сразу.
ACK_MANAGER_NOTIFIED = (
    "Я уже передал ваш запрос менеджеру — он подключится к чату в ближайшее "
    "время и поможет с бронированием. Я остаюсь на связи и продолжу помогать."
)
ACK_MANAGER_NOTIFIED_ASK_PHONE = (
    "Я уже передал ваш запрос менеджеру — он подключится к чату в ближайшее "
    "время. Чтобы он точно с вами связался, подскажите, пожалуйста, ваш номер "
    "телефона. Я остаюсь на связи и пока продолжу помогать."
)
# Сообщение клиенту в момент РЕАЛЬНОГО захода менеджера (перехват из ЛК).
OPERATOR_JOINED_TEXT = "Менеджер уже в чате и ответит вам здесь."

# Сообщение клиенту при авто-возврате (ИИ снова на связи после тишины менеджера).
# Без эмодзи; вежливо приглашает продолжить — следующий ответ клиента обработает
# обычный ИИ с полной памятью диалога.
RESUME_INVITE_TEXT = (
    "Спасибо за ожидание! Я снова на связи и готов помочь с подбором и "
    "бронированием. Подскажите, пожалуйста, какой вариант рассмотреть подробнее "
    "или что уточнить — продолжим."
)

# Подсказка ИИ на резюме-тёрн при авто-возврате (служебная, не показывается клиенту
# как отдельная реплика — кладётся в историю как system-инструкция перед прогоном).
RESUME_SYSTEM_HINT = (
    "[СИСТЕМА: менеджер не подключился вовремя. Продолжи диалог сам — вежливо и по "
    "сути. НЕ обещай снова, что менеджер подключится «сейчас». Ответь на последнее "
    "сообщение клиента и веди к цели (уточнить/актуализировать/оформить). Если клиент "
    "готов бронировать или просил менеджера — обязательно зафиксируй заявку "
    "(имя+телефон → submit_client_request), чтобы лид не потерялся, и скажи, что "
    "менеджер свяжется для подтверждения. Кратко и по-человечески.]"
)

# ── Фразы-триггеры v3 ──
# Раздельно: «нужен человек / консультация / бронь ЧЕРЕЗ менеджера»
# (manager_request) и «само-намерение брони» (booking). book_click и широкий
# has_booking_intent больше НЕ триггерят уведомление.
_MANAGER_REQUEST_PHRASES = (
    # прямая просьба человека
    "дайте менеджера", "дай менеджера", "нужен менеджер", "нужен живой",
    "хочу менеджера", "позовите менеджера", "позови менеджера", "вызовите менеджера",
    "контакт менеджера", "номер менеджера", "телефон менеджера",
    "связаться с менеджером", "позвонить менеджеру", "позвоните менеджеру",
    "переведите на менеджера", "переведи на менеджера",
    "соедините с менеджером", "соедини с менеджером", "соедините с человеком",
    "живой человек", "живого человека", "оператора", "позовите оператора",
    "пусть менеджер", "перезвоните", "перезвонить мне", "пусть перезвонит",
    # консультация с менеджером
    "проконсультироваться с менеджером", "консультацию менеджера",
    "консультация менеджера", "поговорить с менеджером", "пообщаться с менеджером",
    "посоветоваться с менеджером", "обсудить с менеджером", "уточнить у менеджера",
    # бронь/оформление ЧЕРЕЗ менеджера
    "через менеджера", "менеджер оформит", "менеджер забронирует",
    "менеджер поможет оформить",
)
_BOOKING_PHRASES = (
    "забронировать", "хочу забронировать", "можно забронировать",
    "как забронировать", "бронирую", "бронируем", "забронируйте", "забронируй",
    "оформить тур", "оформить", "оформляем", "давайте оформим", "давай оформим",
    "готов оформить", "готовы оформить", "хочу оформить", "оформите",
    "оформить первый", "оформить второй", "оформить этот",
    "готов оплатить", "готовы оплатить", "хочу оплатить",
    "беру этот", "берем этот", "берём этот", "беру первый", "беру второй",
    "хочу этот вариант", "хочу первый вариант", "хочу второй вариант", "хочу этот",
    "мне понравился первый вариант", "мне понравился этот вариант",
)
_MANAGER_REQUEST_PHRASES_NORM = tuple(p.lower().replace("ё", "е") for p in _MANAGER_REQUEST_PHRASES)
_BOOKING_PHRASES_NORM = tuple(p.lower().replace("ё", "е") for p in _BOOKING_PHRASES)

# ── Устойчивый матч просьбы менеджера (v3.1, 2026-06-11) ──
# Литеральные фразы ломаются вставками («соедините МЕНЯ с менеджером» ≠
# «соедините с менеджером»). Поэтому дополнительно матчим ПАРУ
# «глагол-просьба … персона» с зазором до 4 слов в нормализованном тексте.
# Персона: менеджер/оператор/консультант/специалист/человек (живой).
_MANAGER_REQUEST_RE = tuple(re.compile(p) for p in (
    # соединить/связать/переключить/перевести/позвать/вызвать + персона
    r"(?:соедин|свяж|связа|переключ|перевед|переведи|позов|вызов)\w*"
    r"(?:\s+\S+){0,4}?\s+(?:с\s+|на\s+)?(?:менеджер|оператор|консультант|специалист|человек)\w*",
    # дать/нужен/хочу/можно/прошу + персона
    r"(?:дай|дайте|нужен|нужна|нужно|хочу|хотим|можно|давайте|прошу|просьба)"
    r"(?:\s+\S+){0,3}?\s+(?:менеджер|оператор|консультант|живого\s+человека|живой\s+человек)\w*",
    # поговорить/пообщаться/посоветоваться/обсудить/проконсультироваться/уточнить/спросить + персона
    r"(?:поговор|пообща|посоветова|обсуд|проконсультир|консультац|уточн|спрос)\w*"
    r"(?:\s+\S+){0,4}?\s+(?:с\s+|у\s+)?(?:менеджер|оператор|специалист|консультант|человек)\w*",
    # персона-вперёд: «менеджера можно/позовите/дайте/нужен»
    r"(?:менеджер|оператор)\w*(?:\s+\S+){0,2}?\s+(?:можно|нужен|нужна|позов|дай|соедин|свяж|пригласи)\w*",
))

# Телефон РФ: 10–11 цифр, начинается на 7/8/9 (строго, чтобы не ловить длинные ID
# из служебных блоков [ИСТОЧНИК:…]). Зеркалит логику leads-аудита.
_PHONE_CANDIDATE_RE = re.compile(r"\+?[\d][\d\s\-()]{8,}\d")
_SRC_BLOCK_RE = re.compile(r"\[(ИСТОЧНИК|КОНТЕКСТ)\s*:[^\]]*\]")


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def handoff_enabled(assistant_id: Optional[str], channel: Optional[str]) -> bool:
    """Активна ли фича для данного (assistant_id, channel).

    Гейт по каналам (раздельно MAX и widget):
      • глобальный флаг ON И канал ∈ operator_handoff_channels;
      • канал MAX     → assistant_id ∈ operator_handoff_assistant_ids;
      • канал widget  → operator_handoff_widget_all_tenants (все виджеты) ИЛИ
                        assistant_id ∈ operator_handoff_widget_assistant_ids.
    Любая осечка → False (фича инертна). Никаких исключений наружу.
    """
    try:
        from config import settings
    except Exception:
        return False
    if not bool(getattr(settings, "operator_handoff_enabled", False)):
        return False
    if not assistant_id:
        return False
    ch = (channel or "widget").strip().lower()
    channels = set(_split_csv(getattr(settings, "operator_handoff_channels", "max"))) or {"max"}
    if ch not in channels:
        return False
    if ch == "widget":
        if bool(getattr(settings, "operator_handoff_widget_all_tenants", False)):
            return True
        widget_allow = set(_split_csv(getattr(settings, "operator_handoff_widget_assistant_ids", "")))
        return str(assistant_id) in widget_allow
    # MAX (и любой иной канал из списка) — основной allow-list
    allow = set(_split_csv(getattr(settings, "operator_handoff_assistant_ids", "")))
    return str(assistant_id) in allow


def resume_after_seconds() -> int:
    """Через сколько секунд тишины менеджера ИИ продолжает диалог сам."""
    try:
        from config import settings
        return max(60, int(getattr(settings, "operator_handoff_resume_minutes", 10)) * 60)
    except Exception:
        return 600


def _clean(text: str) -> str:
    return _SRC_BLOCK_RE.sub(" ", text or "")


def has_contact(text: str) -> bool:
    """Есть ли в тексте реальный телефон РФ (после вычистки служебных блоков)."""
    cleaned = _clean(text)
    for m in _PHONE_CANDIDATE_RE.finditer(cleaned):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) == 11 and digits[0] in "78" and digits[1] == "9":
            return True
        if len(digits) == 10 and digits[0] == "9":
            return True
    return False


def has_manager_request(text: str) -> bool:
    """Клиент явно хочет человека: менеджер/оператор/консультация/через менеджера.

    Два слоя (v3.1): литеральные фразы (быстро, точно) + регэкспы пары
    «глагол-просьба … персона» с зазором до 4 слов — устойчиво к вставкам
    («соедините МЕНЯ ПОЖАЛУЙСТА с менеджером», «позовите МНЕ менеджера»).
    """
    t = _clean(text).lower().replace("ё", "е")
    if any(p in t for p in _MANAGER_REQUEST_PHRASES_NORM):
        return True
    return any(rx.search(t) for rx in _MANAGER_REQUEST_RE)


def has_booking_phrase(text: str) -> bool:
    """Явное само-намерение брони (без упоминания менеджера)."""
    t = _clean(text).lower().replace("ё", "е")
    return any(p in t for p in _BOOKING_PHRASES_NORM)


def has_hard_phrase(text: str) -> bool:
    """Back-compat: любой явный триггер (просьба менеджера ИЛИ бронь)."""
    return has_manager_request(text) or has_booking_phrase(text)


def classify_user_trigger(text: str) -> Optional[str]:
    """Классифицировать триггер из реплики клиента (v3).

    Приоритет: manager_request > contact > booking. book_click и широкая
    эвристика booking_intent больше НЕ триггерят. Возвращает reason или None.
    «Оформить через менеджера» → manager_request (есть упоминание менеджера),
    «хочу забронировать» → booking, «+79161234567» → contact.
    """
    if has_manager_request(text):
        return REASON_MANAGER_REQUEST
    if has_contact(text):
        return REASON_CONTACT
    if has_booking_phrase(text):
        return REASON_BOOKING
    return None


def is_hard(reason: Optional[str]) -> bool:
    """Жёсткий ли триггер (пауза ИИ + анонс), или мягкий (только алерт)."""
    return reason in HARD_REASONS


def alert_preview(text: str, limit: int = 200) -> str:
    """Короткое превью последнего сообщения клиента для уведомления менеджеру."""
    t = " ".join((_clean(text) or "").split())
    return t[:limit]


def request_ack_text(contact_known: bool) -> str:
    """Текст заверения клиенту при жёстком триггере (ИИ продолжает диалог).

    Если контакт уже оставлен (reason=contact или телефон встречался в диалоге)
    — не просим номер повторно.
    """
    return ACK_MANAGER_NOTIFIED if contact_known else ACK_MANAGER_NOTIFIED_ASK_PHONE


def deep_link(conversation_id) -> str:
    """Относительная ссылка на диалог в ЛК (источник = уведомление)."""
    return f"/conversations/{conversation_id}?src=alert"
