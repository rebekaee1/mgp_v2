"""Авто-возврат к ИИ после тишины менеджера (manager-handoff, MAX).

Запускается фоново планировщиком (`scheduler.py`, интервал ~60с) ВНУТРИ backend-
процесса. Если диалог в operator_mode дольше N минут (config.operator_handoff_
resume_minutes, дефолт 10) без активности менеджера — снимаем паузу:
  • operator_mode=false, handoff_state='returned';
  • шлём клиенту вежливое «снова на связи, продолжим» (RESUME_INVITE_TEXT);
  • re-emit conversation_snapshot → ЛК синхронизирует баннер.
Следующее сообщение клиента уйдёт обычному ИИ с ПОЛНОЙ памятью (гейт пропустит,
т.к. operator_mode уже false) — поэтому отдельной LLM-генерации в фоне НЕ делаем
(безопасно: ноль автономных «придуманных» ответов).

Инвариант: всё под флагом. Если operator_handoff_enabled=false или allow-list пуст —
функция мгновенно возвращает 0 (ничего не делает).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx

import manager_handoff as MH

logger = logging.getLogger("mgp_bot.operator_resume")


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _bot_token(assistant) -> str | None:
    try:
        return (
            ((assistant.runtime_metadata or {}).get("channels", {}) or {})
            .get("max", {}) or {}
        ).get("bot_token")
    except Exception:
        return None


def _max_send_text(bot_token: str, chat_id, text: str) -> bool:
    from config import settings
    base = (getattr(settings, "max_api_base_url", "") or "https://botapi.max.ru").rstrip("/")
    try:
        with httpx.Client(timeout=15.0, headers={"Authorization": bot_token}) as client:
            resp = client.post(
                f"{base}/messages", params={"chat_id": int(chat_id)}, json={"text": text}
            )
        return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.warning("operator_resume MAX send failed: %s", str(exc)[:200])
        return False


def run_operator_resume_once() -> int:
    """Один проход авто-возврата. Возвращает число возвращённых к ИИ диалогов.

    Канал-независимо (2026-06-10, widget-handoff): обрабатываем диалоги в
    operator_mode по всем включённым каналам. Доставка «снова на связи»:
    MAX — через Bot API; widget — записью в БД (виджет заберёт поллингом).
    Гейт — пер-диалог через MH.handoff_enabled (учитывает раздельные allow-list
    для MAX и widget + флаг «все виджеты»).
    """
    from config import settings
    if not bool(getattr(settings, "operator_handoff_enabled", False)):
        return 0
    enabled_channels = [
        c.strip().lower()
        for c in (getattr(settings, "operator_handoff_channels", "max") or "max").split(",")
        if c.strip()
    ] or ["max"]

    from database import get_db, is_db_available
    if not is_db_available():
        return 0
    from models import Conversation, Assistant, Message
    from dialog_sender import enqueue_conversation_snapshot

    resume_after = MH.resume_after_seconds()
    now = datetime.now(timezone.utc)
    resumed = 0

    with get_db() as db:
        if db is None:
            return 0
        convs = (
            db.query(Conversation)
            .filter(
                Conversation.operator_mode.is_(True),
                Conversation.channel.in_(enabled_channels),
            )
            .all()
        )
        for conv in convs:
            # Гейт фичи (канал-зависимый): только разрешённые ассистенты/каналы.
            if not MH.handoff_enabled(str(conv.assistant_id), getattr(conv, "channel", None)):
                continue
            base = _aware(conv.operator_last_activity_at) or _aware(conv.operator_mode_since)
            if base is None:
                continue
            elapsed = (now - base).total_seconds()
            if elapsed < resume_after:
                continue

            # Снимаем паузу: следующий ответ клиента обработает обычный ИИ.
            conv.operator_mode = False
            conv.handoff_state = MH.STATE_RETURNED
            conv.last_active_at = now

            channel = (getattr(conv, "channel", "") or "").strip().lower()
            sent = False
            if channel == "max":
                chat_id = conv.external_chat_id
                assistant = db.get(Assistant, conv.assistant_id) if conv.assistant_id else None
                token = _bot_token(assistant) if assistant else None
                if token and chat_id:
                    sent = _max_send_text(token, chat_id, MH.RESUME_INVITE_TEXT)
            elif channel == "widget":
                # Внешней отправки нет — текст доставляется записью в БД (поллинг).
                sent = True

            if sent:
                db.add(Message(
                    conversation_id=conv.id, role="assistant", content=MH.RESUME_INVITE_TEXT
                ))
                conv.message_count = (conv.message_count or 0) + 1

            if conv.assistant_id is not None:
                try:
                    db.flush()
                    enqueue_conversation_snapshot(
                        db, conversation_id=conv.id, assistant_id=conv.assistant_id
                    )
                except Exception:
                    logger.warning("operator_resume snapshot enqueue failed conv=%s", conv.id, exc_info=True)

            resumed += 1
            logger.info(
                "↩️ AI-RESUME session=%s channel=%s elapsed=%.0fs invite_sent=%s",
                (conv.session_id or "")[:8], channel, elapsed, sent,
            )

    return resumed
