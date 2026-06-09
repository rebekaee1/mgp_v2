"""Manager-handoff — чистая логика «вход менеджера в чат» (MAX).

Модуль СОЗНАТЕЛЬНО без Flask/DB зависимостей: только `config.settings` (для
флага/allow-list) + stdlib. Тестируется изолированно. Вся интеграция (БД, HTTP,
эмиссия событий) — в app.py / dialog_sender.py / max_subscription_watchdog-стиле.

Инвариант безопасности: пока `OPERATOR_HANDOFF_ENABLED=false` ИЛИ assistant_id не
в allow-list ИЛИ канал не разрешён — `handoff_enabled()` возвращает False, и весь
остальной код фичи становится no-op. Существующие диалоги/тенанты не затрагиваются.

Контракт значений (см. docs/handoff/MANAGER_HANDOFF_CONTRACT.md):
  handoff_state : none | requested | operator | returned
  handoff_reason: book_click | booking_intent | phrase | contact | manual
  operator_mode : bool (true ⇒ ИИ на паузе)
"""
from __future__ import annotations

import re
from typing import Optional

# ── Состояния / причины (канонические значения контракта) ──
STATE_NONE = "none"
STATE_REQUESTED = "requested"
STATE_OPERATOR = "operator"
STATE_RETURNED = "returned"

REASON_BOOK_CLICK = "book_click"
REASON_BOOKING_INTENT = "booking_intent"
REASON_PHRASE = "phrase"
REASON_CONTACT = "contact"
REASON_MANUAL = "manual"

# Жёсткие триггеры → пауза ИИ + анонс клиенту + manager_alert.
# Мягкий триггер (booking_intent) → ТОЛЬКО manager_alert, ИИ продолжает.
HARD_REASONS = frozenset({REASON_BOOK_CLICK, REASON_PHRASE, REASON_CONTACT, REASON_MANUAL})
SOFT_REASONS = frozenset({REASON_BOOKING_INTENT})

# Анонс клиенту (без эмодзи, вежливо, без имени менеджера — по согласованию).
ANNOUNCE_TEXT = (
    "Спасибо за интерес! Чтобы подобрать лучшие условия и помочь с бронированием, "
    "к диалогу подключится наш менеджер. Это займёт пару минут — пожалуйста, "
    "не закрывайте чат."
)

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

# ── Жёсткие фразы (явная готовность бронировать / просьба менеджера) ──
# Подмножество _BOOKING_PHRASES из app.py: только то, что означает «оформляю сейчас»
# или «дайте менеджера». Широкий has_booking_intent остаётся мягким триггером.
_HARD_PHRASES = (
    "забронировать", "хочу забронировать", "можно забронировать",
    "как забронировать", "бронирую", "бронируем",
    "оформить тур", "оформляем", "давайте оформим", "давай оформим",
    "готов оформить", "готовы оформить", "хочу оформить",
    "готов оплатить", "готовы оплатить", "хочу оплатить",
    "беру этот", "берем этот", "берём этот", "хочу этот вариант",
    "контакт менеджера", "номер менеджера", "телефон менеджера",
    "связаться с менеджером", "позвонить менеджеру", "дайте менеджера",
    "переведите на менеджера", "переведи на менеджера",
    "соедините с менеджером", "соедини с менеджером",
    "пусть менеджер", "перезвоните",
)
_HARD_PHRASES_NORM = tuple(p.lower().replace("ё", "е") for p in _HARD_PHRASES)

# Телефон РФ: 10–11 цифр, начинается на 7/8/9 (строго, чтобы не ловить длинные ID
# из служебных блоков [ИСТОЧНИК:…]). Зеркалит логику leads-аудита.
_PHONE_CANDIDATE_RE = re.compile(r"\+?[\d][\d\s\-()]{8,}\d")
_SRC_BLOCK_RE = re.compile(r"\[(ИСТОЧНИК|КОНТЕКСТ)\s*:[^\]]*\]")


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def handoff_enabled(assistant_id: Optional[str], channel: Optional[str]) -> bool:
    """Активна ли фича для данного (assistant_id, channel).

    True только если: глобальный флаг ON И assistant_id ∈ allow-list И канал
    разрешён. Любая осечка → False (фича инертна). Никаких исключений наружу.
    """
    try:
        from config import settings
    except Exception:
        return False
    if not bool(getattr(settings, "operator_handoff_enabled", False)):
        return False
    if not assistant_id:
        return False
    allow = set(_split_csv(getattr(settings, "operator_handoff_assistant_ids", "")))
    if str(assistant_id) not in allow:
        return False
    channels = set(_split_csv(getattr(settings, "operator_handoff_channels", "max"))) or {"max"}
    if (channel or "widget").strip().lower() not in channels:
        return False
    return True


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


def has_hard_phrase(text: str) -> bool:
    """Явная фраза «оформляю/дайте менеджера» (жёсткий триггер)."""
    t = _clean(text).lower().replace("ё", "е")
    return any(p in t for p in _HARD_PHRASES_NORM)


def classify_user_trigger(text: str, *, booking_intent: bool) -> Optional[str]:
    """Классифицировать триггер из реплики клиента.

    Приоритет: contact > phrase > booking_intent(мягкий). Возвращает reason или None.
    `booking_intent` — результат существующего has_booking_intent (широкий).
    """
    if has_contact(text):
        return REASON_CONTACT
    if has_hard_phrase(text):
        return REASON_PHRASE
    if booking_intent:
        return REASON_BOOKING_INTENT
    return None


def is_hard(reason: Optional[str]) -> bool:
    """Жёсткий ли триггер (пауза ИИ + анонс), или мягкий (только алерт)."""
    return reason in HARD_REASONS


def alert_preview(text: str, limit: int = 200) -> str:
    """Короткое превью последнего сообщения клиента для уведомления менеджеру."""
    t = " ".join((_clean(text) or "").split())
    return t[:limit]


def deep_link(conversation_id) -> str:
    """Относительная ссылка на диалог в ЛК (источник = уведомление)."""
    return f"/conversations/{conversation_id}?src=alert"
