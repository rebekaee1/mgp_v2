#!/usr/bin/env python3
"""«Тёплый добив» — проактивный нудж клиенту, который замолчал на подборке.

Запускается ВНУТРИ backend-контейнера (нужны БД + модели + Redis + MAX-токен).
Идея: большинство клиентов не пишут «подумаю» — они просто молчат после показа
карточек. Через ~15 минут тишины ассистент мягко переспрашивает («понравился
какой-то вариант?») и предлагает мониторинг (кнопка 🔔). Это «тёплый» этап
воронки ПЕРЕД 20-часовым re-outreach (Фича 1) и опциональным мониторингом
(Фича 2). После ответа клиента диалог оживает из БД с ПОЛНОЙ памятью
(_restore_handler_from_db поднимает историю + _tourid_map показанных туров),
поэтому ассистент консультирует как обычно — контекст не теряется.

Бизнес-правила (согласовано):
  • триггер     — последнее сообщение в диалоге = подборка (assistant с
                  tour_cards), после неё клиент НЕ ответил, прошло 15–MAX минут;
  • бюджет      — только премиум-лиды: пиковый бюджет (max tour_searches.price_to)
                  ≥ MIN_BUDGET; <200к — НЕ добиваем (его подхватит Фича 1);
  • частота     — один раз за диалог (conversations.warm_nudge_sent_at);
  • стоп        — opt-out (do-not-contact), уже активная подписка (мониторинг
                  сам ведёт клиента), клиент ответил после подборки.

Безопасность: DRY-RUN по умолчанию; реально шлёт только с --send; --max-send
ограничивает объём. Окно отправки 10:00–20:00 локально (как у монитора/Ф.1).

Примеры (на сервере):
  docker exec mgp-backend-1 python /app/backend/warm_nudge_monitor.py            # dry-run
  docker exec mgp-backend-1 python /app/backend/warm_nudge_monitor.py --send --ignore-timing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta

import subscription_monitor as SM  # reuse proven helpers (repoint/evict/token/slug)
import subscription_store as ST

# Тенанты с включённым «тёплым добивом» (старт — тест-бот «Навылет! AI»;
# после пилота сюда добавится AnyTour). Для остальных джоб ничего не делает.
WARM_NUDGE_ASSISTANT_IDS = {
    "593471b7-42da-4ae0-8499-904dcedd6a4b",  # «Навылет! AI» (mgp-tour MAX, тест/пилот)
    "64fea0d3-2605-4c4c-be67-62258ebfa7a9",  # AnyTour (Павел)
}

MIN_BUDGET = 200000            # премиум-гейт (как у кнопки подписки)
NUDGE_AFTER_MIN_DEFAULT = 15   # шлём после N минут тишины на подборке
NUDGE_MAX_MIN_DEFAULT = 120    # и не позже M минут (не добиваем «протухшие»/бэклог)

# Кнопка 🔔: payload ДОЛЖЕН совпадать с renderers.SUBSCRIPTION_BUTTON_PAYLOAD,
# т.к. system_prompt матчит именно эту фразу и вызывает subscribe_tours.
SUBSCRIPTION_BUTTON_PAYLOAD = (
    "Хочу подписаться на мониторинг — пишите, когда появится подходящий "
    "или подешевеет тур"
)
SUBSCRIPTION_KEYBOARD = {
    "type": "inline_keyboard",
    "payload": {"buttons": [[{
        "type": "message",
        "text": "🔔 Подписаться на мониторинг",
        "payload": SUBSCRIPTION_BUTTON_PAYLOAD,
    }]]},
}

NUDGE_TEXT = (
    "Подскажите, какой-то из вариантов приглянулся? 🙂 "
    "Если ещё выбираете — расскажу подробнее по любому из показанных, подберу "
    "похожие, либо подпишу на мониторинг: сам напишу сюда, как появится более "
    "выгодный вариант по вашему запросу (от вас ничего не нужно)."
)

log = SM.log


def should_nudge(*, last_role, last_has_cards, minutes_since_cards, peak_budget,
                 opted_out, has_active_sub, already_nudged,
                 after_min=NUDGE_AFTER_MIN_DEFAULT, max_min=NUDGE_MAX_MIN_DEFAULT,
                 min_budget=MIN_BUDGET):
    """Чистое решение (без БД) — добивать ли диалог. Возвращает (ok, reason)."""
    if already_nudged:
        return False, "already_nudged"
    if opted_out:
        return False, "optout"
    if has_active_sub:
        return False, "subscribed"
    if last_role != "assistant" or not last_has_cards:
        return False, "not_podborka_tail"
    if minutes_since_cards is None:
        return False, "no_podborka"
    if minutes_since_cards < after_min:
        return False, "too_soon"
    if minutes_since_cards > max_min:
        return False, "too_old"
    if not peak_budget or int(peak_budget) < min_budget:
        return False, "below_budget"
    return True, "ok"


def max_send_with_kb(token: str, chat_id: str, text: str, keyboard: dict) -> dict:
    url = f"{SM.MAX_API}/messages?chat_id={chat_id}"
    body = json.dumps({"text": text, "format": "markdown",
                       "attachments": [keyboard]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def run(args) -> int:
    import database
    database.init_db(os.environ.get("DATABASE_URL", "postgresql://mgp:mgp@postgres:5432/mgp"))
    from database import get_db
    from models import Conversation, Message, TourSearch
    from sqlalchemy import func

    aids = [uuid.UUID(a) for a in WARM_NUDGE_ASSISTANT_IDS]
    now = datetime.now(timezone.utc)
    m = Counter()
    samples = []
    sent = 0
    token_by_aid: dict = {}
    slug_by_aid: dict = {}
    handoffs = []  # (uid, slug, session_id, assistant_id) — repoint/evict after commit

    with get_db() as db:
        # Префильтр по БД: max-канал, включённый тенант, ещё не добивали,
        # последняя активность 15..MAX минут назад (подборка-хвост уточняем ниже).
        lo = now - timedelta(minutes=args.max_min)
        hi = now - timedelta(minutes=args.after_min)
        convs = (db.query(Conversation)
                 .filter(Conversation.channel == "max",
                         Conversation.assistant_id.in_(aids),
                         Conversation.external_user_id.isnot(None),
                         Conversation.warm_nudge_sent_at.is_(None),
                         Conversation.last_active_at >= lo,
                         Conversation.last_active_at <= hi)
                 .order_by(Conversation.last_active_at.asc())
                 .all())
        log(f"prefilter candidates: {len(convs)}")

        for conv in convs:
            m["candidates"] += 1
            aid = conv.assistant_id
            uid = str(conv.external_user_id or "")

            # Последнее сообщение должно быть подборкой (assistant + tour_cards).
            last_msg = (db.query(Message)
                        .filter(Message.conversation_id == conv.id)
                        .order_by(Message.created_at.desc(), Message.id.desc())
                        .first())
            last_role = getattr(last_msg, "role", None)
            last_cards = bool(getattr(last_msg, "tour_cards", None))
            minutes_since = None
            if last_msg is not None and last_msg.created_at is not None:
                minutes_since = (now - _aware(last_msg.created_at)).total_seconds() / 60.0

            peak_budget = (db.query(func.max(TourSearch.price_to))
                           .filter(TourSearch.conversation_id == conv.id).scalar())

            opted_out = ST.is_opted_out(db, aid, uid) if uid else True
            has_sub = ST.get_active_for_user(db, aid, uid) is not None if uid else False
            already = conv.warm_nudge_sent_at is not None

            ok, reason = should_nudge(
                last_role=last_role, last_has_cards=last_cards,
                minutes_since_cards=minutes_since, peak_budget=peak_budget,
                opted_out=opted_out, has_active_sub=has_sub, already_nudged=already,
                after_min=args.after_min, max_min=args.max_min,
            )
            if not ok:
                m[f"skip_{reason}"] += 1
                continue

            # Окно отправки (по городу вылета последнего поиска; дефолт МСК).
            dep = (db.query(TourSearch.departure)
                   .filter(TourSearch.conversation_id == conv.id)
                   .order_by(TourSearch.created_at.desc()).limit(1).scalar())
            if not args.ignore_timing and not SM.send_window_ok(dep):
                m["skip_send_window"] += 1
                continue

            m["would_nudge"] += 1
            if len(samples) < args.samples:
                samples.append({"conv": str(conv.id), "uid": uid,
                                "budget": peak_budget, "mins": round(minutes_since, 1)})

            if not args.send:
                continue
            if sent >= args.max_send:
                m["capped"] += 1
                continue

            chat_id = conv.external_chat_id or uid
            if not chat_id:
                m["no_chat_id"] += 1
                continue
            try:
                if aid not in token_by_aid:
                    token_by_aid[aid] = SM.fetch_bot_token(db, aid)
                max_send_with_kb(token_by_aid[aid], str(chat_id), NUDGE_TEXT,
                                 SUBSCRIPTION_KEYBOARD)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200]
                undeliverable = any(k in body.lower() for k in
                                    ("block", "forbidden", "denied", "suspend",
                                     "not found", "chat.not"))
                if e.code in (400, 403, 404) and undeliverable:
                    ST.add_optout(db, aid, uid, reason="blocked", source="warm_nudge")
                    m["undeliverable"] += 1
                else:
                    m["send_error"] += 1
                    log(f"SEND ERROR conv={conv.id} http={e.code} {body}")
                continue
            except Exception as e:  # noqa: BLE001
                m["send_error"] += 1
                log(f"SEND ERROR conv={conv.id} {e}")
                continue

            # Успех: запись в историю + отметка «добит» (один раз за диалог).
            try:
                SM.persist_teaser(db, conv.id, NUDGE_TEXT)
            except Exception as e:  # noqa: BLE001
                log(f"POST-SEND WARN conv={conv.id} (sent ok, persist failed): {e}")
            conv.warm_nudge_sent_at = datetime.now(timezone.utc)
            sent += 1
            m["sent"] += 1

            sid = getattr(conv, "session_id", None)
            if sid:
                if aid not in slug_by_aid:
                    slug_by_aid[aid] = SM.fetch_tenant_slug(db, aid)
                handoffs.append((uid, slug_by_aid[aid], sid, aid))
            time.sleep(args.throttle_sec)

    # Хэндофф после коммита: ответ клиента оживит ЭТОТ диалог (полная память) и
    # «холодно» восстановит хендлер (подборка + _tourid_map в контексте).
    for uid, slug, sid, aid in handoffs:
        if slug and uid:
            SM.repoint_bridge_session(uid, slug, sid)
        SM.evict_backend_session(sid, aid)
    if handoffs:
        log(f"handoff done for {len(handoffs)} session(s): repoint+evict")

    summary = {"mode": "SEND" if args.send else "DRY-RUN",
               "metrics": dict(m), "sent": sent}
    log("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    if samples:
        print("\n=== SAMPLE TARGETS ===")
        for s in samples:
            print(f"  conv={s['conv'][:8]} uid={s['uid']} budget={s['budget']} "
                  f"mins_silent={s['mins']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually send (else dry-run)")
    ap.add_argument("--ignore-timing", action="store_true",
                    help="bypass send-window (testing)")
    ap.add_argument("--after-min", type=int, default=NUDGE_AFTER_MIN_DEFAULT)
    ap.add_argument("--max-min", type=int, default=NUDGE_MAX_MIN_DEFAULT)
    ap.add_argument("--max-send", type=int, default=10)
    ap.add_argument("--throttle-sec", type=float, default=2.0)
    ap.add_argument("--samples", type=int, default=6)
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
