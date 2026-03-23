"""
Web UI для чата с AI-менеджером турагентства
Flask + Server-Sent Events для streaming
"""

import asyncio
import hashlib
import hmac
import ipaddress
import os
import time
import uuid
import logging
from flask import Flask, request, Response, jsonify, stream_with_context, g, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
def _import_handler_class():
    """Import handler class based on LLM_PROVIDER env variable."""
    from dotenv import load_dotenv as _ld
    _ld()
    provider = os.getenv("LLM_PROVIDER", "yandex").lower().strip()
    if provider == "openai":
        try:
            from openai_handler import OpenAIHandler
            return OpenAIHandler, "openai"
        except ImportError:
            from backend.openai_handler import OpenAIHandler
            return OpenAIHandler, "openai"
    else:
        try:
            from yandex_handler import YandexGPTHandler
            return YandexGPTHandler, "yandex"
        except ImportError:
            from backend.yandex_handler import YandexGPTHandler
            return YandexGPTHandler, "yandex"

_HandlerClass, _llm_provider = _import_handler_class()
import json
import queue
import threading

app = Flask(__name__, template_folder='templates', static_folder='static')

_cors_origins = os.getenv("CORS_ORIGINS", "").strip()
_allowed_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()] if _cors_origins else ["*"]

CORS(app, resources={
    r"/api/v1/chat": {"origins": "*"},
    r"/api/*": {"origins": _allowed_origins},
}, supports_credentials=False)

from dashboard_api import auth_bp, dash_bp
from provisioning_api import provisioning_bp
from reconciliation_api import reconciliation_bp
from runtime_message_filters import filter_runtime_message_rows, filter_runtime_snapshot_entries
app.register_blueprint(auth_bp)
app.register_blueprint(dash_bp)
app.register_blueprint(provisioning_bp)
app.register_blueprint(reconciliation_bp)

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

_MAX_MESSAGE_LENGTH = 2000
_MAX_SESSIONS = 500
_RUNTIME_MODE = os.getenv("RUNTIME_MODE", "backend-only").strip().lower()

# === ИНИЦИАЛИЗАЦИЯ ИНФРАСТРУКТУРЫ (PostgreSQL, Redis) ===
_infra_lock = threading.Lock()
_infra_done = False

def _backfill_booking_intent():
    """One-time backfill: scan existing conversations for booking intent."""
    try:
        from database import get_db, is_db_available
        if not is_db_available():
            return
        from models import Conversation, Message
        with get_db() as db:
            if db is None:
                return
            convs = db.query(Conversation).filter(
                Conversation.has_booking_intent == False  # noqa: E712
            ).all()
            updated = 0
            for conv in convs:
                user_msgs = [
                    m.content for m in db.query(Message.content).filter(
                        Message.conversation_id == conv.id,
                        Message.role == "user",
                    ).all()
                ]
                if check_conversation_booking_intent(user_msgs):
                    conv.has_booking_intent = True
                    updated += 1
            if updated:
                logging.getLogger("mgp_bot").info(
                    "Backfill: marked %d conversations with booking intent", updated
                )
    except Exception as e:
        logging.getLogger("mgp_bot").debug("Booking intent backfill: %s", e)


def _init_infrastructure():
    """Инициализация БД и Redis при первом запросе (lazy init, thread-safe)."""
    global _infra_done
    if _infra_done:
        return
    with _infra_lock:
        if _infra_done:
            return
        try:
            from config import settings
            from database import init_db
            from cache import init_cache
            init_db(settings.database_url)
            init_cache(settings.redis_url)
            _backfill_booking_intent()
            from scheduler import init_scheduler
            init_scheduler(app)
        except Exception as e:
            logging.getLogger("mgp_bot").warning("Infrastructure init: %s", e)
        _infra_done = True

# === ЛОГИРОВАНИЕ ===
from datetime import datetime as _dt

# Директория для логов
_LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
try:
    os.makedirs(_LOGS_DIR, exist_ok=True)
except OSError:
    _LOGS_DIR = "/tmp"

# Файл диалогового лога (человекочитаемый markdown)
_DIALOGUE_LOG_PATH = os.path.join(
    _LOGS_DIR,
    f"dialogue_{_dt.now().strftime('%Y%m%d_%H%M%S')}.md"
)


def _write_dialogue_log(session_id: str, direction: str, content: str):
    """
    Пишет в человекочитаемый диалоговый лог (markdown).
    direction: 'USER', 'ASSISTANT', 'FUNC_CALL', 'FUNC_RESULT', 'API_RAW', 'ERROR', 'SYSTEM'
    """
    ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    sid = session_id[:8] if session_id else "--------"
    icons = {
        "USER": "👤", "ASSISTANT": "🤖", "FUNC_CALL": "🔧",
        "FUNC_RESULT": "📦", "API_RAW": "🌐", "ERROR": "❌", "SYSTEM": "⚙️",
        "TOUR_CARDS": "🎴"
    }
    icon = icons.get(direction, "📝")
    try:
        with open(_DIALOGUE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n### [{ts}] {icon} {direction} (session: {sid})\n")
            f.write(f"```\n{content}\n```\n")
    except Exception:
        pass  # лог не должен ломать приложение


def _setup_logging() -> logging.Logger:
    """
    Единая настройка логирования в консоль + файл.
    Управление:
      - LOG_LEVEL=DEBUG|INFO|WARNING|ERROR (по умолчанию INFO)
    """
    logger = logging.getLogger("mgp_bot")

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- Console handler ---
    if logger.handlers:
        handler = logger.handlers[0]
    else:
        handler = logging.StreamHandler()
        logger.addHandler(handler)

    handler.setLevel(level)
    handler.setFormatter(formatter)

    # --- File handler (полный лог с DEBUG) ---
    file_log_path = os.path.join(
        _LOGS_DIR,
        f"server_{_dt.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    file_handler = logging.FileHandler(file_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    # WerkZeug: по умолчанию скрываем access-логи (они дублируют наши -> / <-).
    # При необходимости можно включить обратно через WERKZEUG_LOG_LEVEL=INFO.
    werk_logger = logging.getLogger("werkzeug")
    werk_level_name = os.getenv("WERKZEUG_LOG_LEVEL", "WARNING").upper()
    werk_level = getattr(logging, werk_level_name, logging.WARNING)
    werk_logger.setLevel(werk_level)
    if not werk_logger.handlers:
        werk_logger.addHandler(handler)
        werk_logger.addHandler(file_handler)
    else:
        # на случай, если handler уже был, приведём его к одному формату
        for h in werk_logger.handlers:
            h.setLevel(werk_level)
            h.setFormatter(formatter)

    logger.info("📁 Server log: %s", file_log_path)
    logger.info("📁 Dialogue log: %s", _DIALOGUE_LOG_PATH)

    return logger


logger = _setup_logging()

# Записываем заголовок диалогового лога
try:
    with open(_DIALOGUE_LOG_PATH, "w", encoding="utf-8") as _f:
        _f.write(f"# 📝 Диалоговый лог AI-Турменеджера МГП\n")
        _f.write(f"**Дата:** {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        _f.write(f"---\n")
except OSError:
    pass


def log(msg: str, level: str = "INFO"):
    """Совместимость со старым логгером (level=INFO/OK/WARN/ERROR/MSG/FUNC)."""
    level_map = {
        "INFO": logging.INFO,
        "OK": logging.INFO,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "MSG": logging.INFO,
        "FUNC": logging.DEBUG,
    }
    py_level = level_map.get(level, logging.INFO)
    logger.log(py_level, f"[{level}] {msg}")

# === УПРАВЛЕНИЕ СЕССИЯМИ ===
# Thread-safe хранилище сессий с автоочисткой
_handlers_lock = threading.Lock()
_handlers: dict[str, dict] = {}  # cache_key → {"handler": Handler, "last_active": float}
SESSION_TTL_SECONDS = 30 * 60  # 30 минут неактивности → удаление

# Per-session mutexes to prevent concurrent request processing (double messages)
_session_chat_locks: dict[str, threading.Lock] = {}
_session_chat_locks_guard = threading.Lock()

# Per-session message debounce (blocks identical messages within a short window)
_debounce_lock = threading.Lock()
_session_last_user_msg: dict = {}       # session_id -> (text, timestamp)
_session_last_assistant_at: dict = {}   # session_id -> timestamp
_DEBOUNCE_WINDOW_SEC = 3


def _is_duplicate_user_message(session_id: str, text: str) -> bool:
    now = time.time()
    with _debounce_lock:
        last = _session_last_user_msg.get(session_id)
        last_asst = _session_last_assistant_at.get(session_id, 0)
        _session_last_user_msg[session_id] = (text, now)
        if last is None:
            return False
        prev_text, prev_ts = last
        if prev_text != text or now - prev_ts > _DEBOUNCE_WINDOW_SEC:
            return False
        if last_asst > prev_ts:
            return False
        return True


def _mark_assistant_responded(session_id: str):
    with _debounce_lock:
        _session_last_assistant_at[session_id] = time.time()


def _session_cache_key(session_id: str, assistant_id: str = None) -> str:
    return f"{assistant_id or 'default'}::{session_id}"


_DEPARTURE_CITY_NAMES = {
    1: "Москва",
    2: "Пермь",
    3: "Екатеринбург",
    4: "Уфа",
    5: "Санкт-Петербург",
    6: "Челябинск",
    7: "Самара",
    8: "Нижний Новгород",
    9: "Новосибирск",
    10: "Казань",
    11: "Краснодар",
    12: "Красноярск",
    18: "Ростов-на-Дону",
    56: "Сочи",
    99: "Без перелёта",
}


def _assistant_uuid_or_none(raw_value):
    if not raw_value:
        return None
    try:
        return uuid.UUID(str(raw_value))
    except (ValueError, TypeError, AttributeError):
        return None


def _restore_handler_from_db(handler, session_id: str, assistant_id: str = None) -> bool:
    """Restore saved conversation state into a fresh handler instance."""
    try:
        from database import get_db, is_db_available
        from models import Conversation, Message, TourSearch

        if not is_db_available():
            return False

        assistant_uuid = _assistant_uuid_or_none(assistant_id)
        with get_db() as db:
            if db is None:
                return False

            conv_query = db.query(Conversation).filter(
                Conversation.session_id == session_id
            )
            if assistant_uuid is not None:
                conv_query = conv_query.filter(Conversation.assistant_id == assistant_uuid)
            conv = conv_query.first()
            if conv is None and assistant_uuid is not None:
                conv = db.query(Conversation).filter(
                    Conversation.session_id == session_id
                ).first()
            if conv is None:
                return False

            messages = db.query(Message).filter(
                Message.conversation_id == conv.id
            ).order_by(Message.created_at.asc(), Message.id.asc()).all()

            handler.reset()

            restored_history = []
            latest_tour_cards = None
            for msg in messages:
                if msg.role not in ("user", "assistant", "tool"):
                    continue
                entry = {
                    "role": msg.role,
                    "content": msg.content or "",
                }
                if msg.tool_calls:
                    entry["tool_calls"] = msg.tool_calls
                if msg.tool_call_id:
                    entry["tool_call_id"] = msg.tool_call_id
                if msg.tokens_prompt is not None:
                    entry["tokens_prompt"] = int(msg.tokens_prompt)
                if msg.tokens_completion is not None:
                    entry["tokens_completion"] = int(msg.tokens_completion)
                restored_history.append(entry)
                if msg.tour_cards:
                    latest_tour_cards = list(msg.tour_cards)

            if not restored_history:
                return False

            handler.full_history = restored_history
            handler.input_list = []
            handler._pending_tour_cards = []
            handler._last_message_usage = None
            if hasattr(handler, "_search_awaiting_results"):
                handler._search_awaiting_results = False

            if hasattr(handler, "_update_collected_slots"):
                if hasattr(handler, "_collected_slots"):
                    handler._collected_slots.clear()
                for entry in restored_history:
                    if entry.get("role") == "user" and entry.get("content"):
                        handler._update_collected_slots(entry["content"])
                # After restoration, remove potentially stale child-related slots
                # that were extracted from historical messages -- the authoritative
                # source is _last_search_params from the DB, not regex over old text.
                if hasattr(handler, "_collected_slots"):
                    for _stale_key in ("Дети", "Возраст ребёнка"):
                        handler._collected_slots.pop(_stale_key, None)

            latest_search = db.query(TourSearch).filter(
                TourSearch.conversation_id == conv.id
            ).order_by(TourSearch.created_at.desc(), TourSearch.id.desc()).first()

            if latest_search is not None:
                params = {}
                if latest_search.departure is not None:
                    params["departure"] = latest_search.departure
                    handler._last_departure_city = _DEPARTURE_CITY_NAMES.get(
                        latest_search.departure,
                        getattr(handler, "_last_departure_city", "Москва"),
                    )
                if latest_search.country is not None:
                    params["country"] = latest_search.country
                    params["_country"] = latest_search.country
                if latest_search.regions:
                    params["regions"] = latest_search.regions
                    params["_regions"] = latest_search.regions
                if latest_search.date_from:
                    params["datefrom"] = latest_search.date_from
                if latest_search.date_to:
                    params["dateto"] = latest_search.date_to
                if latest_search.nights_from is not None:
                    params["nightsfrom"] = latest_search.nights_from
                if latest_search.nights_to is not None:
                    params["nightsto"] = latest_search.nights_to
                if latest_search.adults is not None:
                    params["adults"] = latest_search.adults
                if latest_search.children is not None:
                    params["child"] = latest_search.children
                if latest_search.stars is not None:
                    params["stars"] = latest_search.stars
                if latest_search.meal is not None:
                    params["meal"] = latest_search.meal
                if latest_search.price_from is not None:
                    params["pricefrom"] = latest_search.price_from
                if latest_search.price_to is not None:
                    params["priceto"] = latest_search.price_to

                handler._last_search_params = params
                handler._last_requestid = latest_search.requestid or None
                handler._last_search_result = {
                    "requestid": latest_search.requestid,
                    "hotels_found": latest_search.hotels_found,
                    "tours_found": latest_search.tours_found,
                    "min_price": latest_search.min_price,
                    "duration_ms": latest_search.duration_ms,
                }

                _param_labels = {
                    "departure": "Город вылета", "country": "Страна",
                    "datefrom": "Дата от", "dateto": "Дата до",
                    "nightsfrom": "Ночей от", "nightsto": "Ночей до",
                    "adults": "Взрослых", "child": "Детей",
                    "stars": "Звёзды", "meal": "Питание",
                }
                _summary_lines = []
                for k, label in _param_labels.items():
                    v = params.get(k)
                    if v is not None:
                        _summary_lines.append(f"- {label}: {v}")
                if _summary_lines and hasattr(handler, "full_history"):
                    handler.full_history.append({
                        "role": "system",
                        "content": (
                            "[ВОССТАНОВЛЕННАЯ СЕССИЯ] Параметры предыдущего поиска:\n"
                            + "\n".join(_summary_lines)
                            + "\nНЕ переспрашивай эти параметры. Используй их для контекста."
                        )
                    })

            if latest_tour_cards:
                handler._tourid_map = {}
                for idx, card in enumerate(latest_tour_cards, 1):
                    tour_id = str(card.get("tourid") or "").strip()
                    if not tour_id:
                        continue
                    handler._tourid_map[idx] = {
                        "tourid": tour_id,
                        "hotelcode": card.get("hotelcode"),
                        "hotelname": card.get("hotel_name") or card.get("hotelname") or "",
                    }

                if getattr(handler, "_tourid_map", None) and hasattr(handler, "_pinned_context"):
                    lines = ["[КОНТЕКСТ: текущие показанные туры]"]
                    for pos, entry in sorted(handler._tourid_map.items()):
                        lines.append(
                            f"{pos}. {entry.get('hotelname', '?')} "
                            f"(tourid={entry['tourid']}, hotelcode={entry.get('hotelcode', '?')})"
                        )
                    handler._pinned_context = "\n".join(lines)

            logger.info(
                "♻️ Restored session %s from DB (%d messages, assistant=%s)",
                session_id[:8],
                len(restored_history),
                assistant_id or "-",
            )
            return True
    except Exception:
        logger.warning(
            "Session restore failed for session_id=%s assistant=%s",
            session_id,
            assistant_id or "-",
            exc_info=True,
        )
        return False


def _build_conversation_history_payload(db, assistant_id: str, conversation_id: str) -> dict:
    from models import Conversation, Message

    assistant_uuid = _assistant_uuid_or_none(assistant_id)
    conv_query = db.query(Conversation).filter(
        Conversation.session_id == conversation_id
    )
    if assistant_uuid is not None:
        conv_query = conv_query.filter(Conversation.assistant_id == assistant_uuid)
    conv = conv_query.first()
    if conv is None and assistant_uuid is not None:
        conv = db.query(Conversation).filter(
            Conversation.session_id == conversation_id
        ).first()
    if conv is None:
        return {"conversation_id": conversation_id, "messages": []}

    rows = db.query(Message).filter(
        Message.conversation_id == conv.id
    ).order_by(Message.created_at.asc(), Message.id.asc()).all()
    rows = filter_runtime_message_rows(rows)

    visible = []
    for row in rows:
        if row.role not in ("user", "assistant"):
            continue
        content = (row.content or "").strip()
        tour_cards = list(row.tour_cards or [])
        if row.role == "assistant" and not content and not tour_cards:
            continue
        if row.role == "user" and not content:
            continue
        visible.append({
            "role": row.role,
            "content": content,
            "tour_cards": tour_cards,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return {
        "conversation_id": conversation_id,
        "messages": visible[-50:],
    }


def _build_handler(assistant_id: str = None):
    from runtime_config import resolve_runtime_config

    runtime_config = resolve_runtime_config(assistant_id=assistant_id)
    provider = (runtime_config.llm_provider or _llm_provider or "openai").strip().lower()

    if provider == "openai":
        try:
            from openai_handler import OpenAIHandler as handler_cls
        except ImportError:
            from backend.openai_handler import OpenAIHandler as handler_cls
    else:
        try:
            from yandex_handler import YandexGPTHandler as handler_cls
        except ImportError:
            from backend.yandex_handler import YandexGPTHandler as handler_cls

    return handler_cls(runtime_config=runtime_config), runtime_config, provider


def get_handler(session_id: str, assistant_id: str = None):
    """Получить или создать handler для сессии (thread-safe, assistant-aware)."""
    cache_key = _session_cache_key(session_id, assistant_id)
    with _handlers_lock:
        if cache_key in _handlers:
            _handlers[cache_key]["last_active"] = time.time()
            return _handlers[cache_key]["handler"]
        handler, runtime_config, provider = _build_handler(assistant_id=assistant_id)
        # Подключаем диалоговый лог
        handler._dialogue_log_callback = lambda direction, content: _write_dialogue_log(session_id, direction, content)
        restored = _restore_handler_from_db(handler, session_id, assistant_id=assistant_id)
        _handlers[cache_key] = {
            "handler": handler,
            "last_active": time.time(),
            "session_id": session_id,
            "assistant_id": assistant_id,
            "provider": provider,
        }
        logger.info(
            "🆕 New session %s  (provider: %s, assistant: %s, source: %s, restored=%s, total sessions: %d)",
            session_id[:8],
            provider,
            assistant_id or "-",
            getattr(runtime_config, "source", "env-default"),
            "yes" if restored else "no",
            len(_handlers),
        )
        _write_dialogue_log(
            session_id,
            "SYSTEM",
            f"New session created (provider: {provider}, model: {handler.model}, assistant_id: {assistant_id or '-'}, config_source: {getattr(runtime_config, 'source', 'env-default')}, restored={'yes' if restored else 'no'})",
        )
        return handler


def _cleanup_stale_sessions():
    """Удалить сессии, неактивные дольше SESSION_TTL_SECONDS"""
    now = time.time()
    _stale_session_ids: list[str] = []
    with _handlers_lock:
        stale = [cache_key for cache_key, info in _handlers.items()
                 if now - info["last_active"] > SESSION_TTL_SECONDS]
        for cache_key in stale:
            handler = _handlers[cache_key]["handler"]
            parts = cache_key.split("::", 1)
            if len(parts) == 2:
                _stale_session_ids.append(parts[1])
            try:
                handler.close_sync()
            except Exception:
                logger.debug("close_sync failed for session %s", cache_key[:24], exc_info=True)
            del _handlers[cache_key]
        if stale:
            logger.info("🧹 Cleaned up %d stale sessions (remaining: %d)", len(stale), len(_handlers))
    if _stale_session_ids:
        with _session_chat_locks_guard:
            for sid in _stale_session_ids:
                _session_chat_locks.pop(sid, None)
        with _debounce_lock:
            for sid in _stale_session_ids:
                _session_last_user_msg.pop(sid, None)
                _session_last_assistant_at.pop(sid, None)


# === BOOKING INTENT DETECTION ===

_BOOKING_PHRASES = [
    "забронировать", "бронирую", "бронируем", "бронируй", "бронируйте",
    "хочу бронь", "оформить бронь", "оформить тур", "оформляем", "оформляй",
    "оформляйте", "оформите", "давайте оформим", "давай оформим",
    "купить тур", "покупаю", "покупаем", "хочу купить",
    "беру этот", "берем этот", "берём этот", "возьмем", "возьмём", "возьму",
    "этот вариант беру", "этот тур беру", "давайте этот", "хочу этот",
    "выбираю этот", "выбрал этот", "выбрали этот",
    "останавливаюсь на", "решили брать", "решил брать",
    "как забронировать", "как оформить", "как купить", "как заказать",
    "условия бронирования", "процесс бронирования",
    "можно забронировать", "можно оформить", "можно ли забронировать",
    "можно ли оформить", "хочу забронировать",
    "контакт менеджера", "номер менеджера",
    "связаться с менеджером", "позвонить менеджеру",
    "переведите на менеджера", "переведи на менеджера",
    "соедините с менеджером", "соедини с менеджером",
    "нас устраивает", "нам подходит", "подходит идеально",
    "нравится этот вариант", "нравится этот тур",
    "готовы оплатить", "готовы оформить", "готов оплатить", "готов оформить",
    "можно оплатить", "хочу оплатить",
    "давайте бронируем", "давай бронируем", "бронируем этот",
    "оформляем этот", "берем этот тур", "берём этот тур",
    "хотим забронировать", "хотим оформить", "хотим купить",
    "заказать тур", "заказать этот",
    "оплатить тур", "оплатить этот",
    "давайте закажем", "давай закажем",
    "запишите нас", "запиши нас",
    "бронь", "бронирование",
]

_BOOKING_PHRASES_NORMALIZED = [
    p.lower().replace("ё", "е") for p in _BOOKING_PHRASES
]


def has_booking_intent(text: str) -> bool:
    """Check if a single message text contains booking intent."""
    if not text:
        return False
    t = text.lower().replace("ё", "е")
    return any(phrase in t for phrase in _BOOKING_PHRASES_NORMALIZED)


def check_conversation_booking_intent(user_messages: list) -> bool:
    """Check if any user message in a conversation shows booking intent."""
    return any(has_booking_intent(msg) for msg in user_messages if msg)


# === DB LOGGING (полный путь диалога для аналитики и личного кабинета) ===

def _log_chat_to_db(session_id: str, user_message: str, reply: str,
                     tour_cards: list, latency_ms: int = None,
                     model_name: str = "unknown",
                     llm_provider: str = None,
                     ip_address: str = None, user_agent: str = None,
                     history_snapshot: list = None,
                     assistant_id: str = None,
                     search_result: dict = None,
                     api_calls_log: list = None,
                     final_message_usage: dict = None):
    """
    Записать в PostgreSQL клиентски-видимую историю:
    - все обычные записи из history_snapshot (user, assistant, tool)
    - исключая внутренние runtime nudges/self-repair подсказки
    - Последний assistant enriched с tour_cards + latency_ms
    - Safety net: если handler.chat() вернул reply без append в history,
      финальный ответ добавляется отдельно
    """
    try:
        from database import get_db, is_db_available
        if not is_db_available():
            return
        from models import Conversation, Message

        with get_db() as db:
            if db is None:
                return

            _aid = None
            if assistant_id:
                try:
                    _aid = uuid.UUID(assistant_id) if isinstance(assistant_id, str) else assistant_id
                except (ValueError, AttributeError):
                    _aid = None

            conv_query = db.query(Conversation).filter(
                Conversation.session_id == session_id
            )
            if _aid is not None:
                conv_query = conv_query.filter(Conversation.assistant_id == _aid)
            conv = conv_query.first()

            if conv is None:
                ip_addr = ip_address
                ua = user_agent
                if ip_addr is None:
                    try:
                        ip_addr = request.remote_addr
                        ua = request.headers.get('User-Agent', '')[:500]
                    except RuntimeError:
                        pass
                conv = Conversation(
                    session_id=session_id,
                    llm_provider=llm_provider or _llm_provider,
                    model=model_name,
                    ip_address=ip_addr,
                    user_agent=ua,
                    assistant_id=_aid,
                )
                db.add(conv)
                db.flush()

            msg_count = 0
            final_reply_in_snapshot = False
            tool_outputs_by_call_id = {}
            snapshot_entries = list(history_snapshot or [])

            if snapshot_entries:
                # Some handler flows can return a snapshot that already contains tool/final
                # assistant entries but omits the current user turn. Persist it explicitly
                # so LK snapshots and analytics do not lose the latest user message.
                has_current_user_in_snapshot = any(
                    entry.get("role") == "user" and (entry.get("content") or "") == user_message
                    for entry in snapshot_entries
                )
                if user_message and not has_current_user_in_snapshot:
                    last_user_idx = -1
                    for idx, entry in enumerate(snapshot_entries):
                        if entry.get("role") == "user":
                            last_user_idx = idx
                    snapshot_entries.insert(last_user_idx + 1, {
                        "role": "user",
                        "content": user_message,
                    })
                snapshot_entries = filter_runtime_snapshot_entries(snapshot_entries)

            if snapshot_entries:
                for entry in snapshot_entries:
                    if entry.get("role") != "tool":
                        continue
                    tool_call_id = entry.get("tool_call_id")
                    if not tool_call_id:
                        continue
                    try:
                        parsed_output = json.loads(entry.get("content") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        parsed_output = None
                    if isinstance(parsed_output, dict):
                        tool_outputs_by_call_id[tool_call_id] = parsed_output

            if snapshot_entries:
                last_reply_idx = -1
                for idx, entry in enumerate(snapshot_entries):
                    if (
                        entry.get("role") == "assistant"
                        and not entry.get("tool_calls")
                        and (entry.get("content") or "") == reply
                    ):
                        last_reply_idx = idx

                for i, entry in enumerate(snapshot_entries):
                    role = entry.get("role", "")
                    content = entry.get("content") or ""
                    tc_data = entry.get("tool_calls")
                    tc_id = entry.get("tool_call_id")

                    is_final_reply = (
                        i == last_reply_idx and role == "assistant"
                        and not tc_data and content == reply
                    )

                    msg = Message(
                        conversation_id=conv.id,
                        role=role,
                        content=content[:10000] if role != "tool" else content[:5000],
                    )
                    if tc_data:
                        msg.tool_calls = tc_data
                    if tc_id:
                        msg.tool_call_id = tc_id
                    tokens_prompt = entry.get("tokens_prompt")
                    tokens_completion = entry.get("tokens_completion")
                    if tokens_prompt is not None:
                        msg.tokens_prompt = int(tokens_prompt)
                    if tokens_completion is not None:
                        msg.tokens_completion = int(tokens_completion)

                    if is_final_reply:
                        if tour_cards:
                            msg.tour_cards = tour_cards
                        msg.latency_ms = latency_ms
                        if final_message_usage:
                            prompt_tokens = final_message_usage.get("tokens_prompt")
                            completion_tokens = final_message_usage.get("tokens_completion")
                            if prompt_tokens is not None:
                                msg.tokens_prompt = int(prompt_tokens)
                            if completion_tokens is not None:
                                msg.tokens_completion = int(completion_tokens)
                        final_reply_in_snapshot = True

                    db.add(msg)
                    msg_count += 1

                    if tc_data:
                        _log_tour_searches(
                            db,
                            conv.id,
                            tc_data,
                            tour_cards=tour_cards,
                            search_result=search_result,
                            tool_outputs=tool_outputs_by_call_id,
                        )

            if not final_reply_in_snapshot:
                if not snapshot_entries:
                    db.add(Message(
                        conversation_id=conv.id,
                        role="user",
                        content=user_message,
                    ))
                    msg_count += 1
                fallback_msg = Message(
                    conversation_id=conv.id,
                    role="assistant",
                    content=reply,
                    latency_ms=latency_ms,
                )
                if tour_cards:
                    fallback_msg.tour_cards = tour_cards
                if final_message_usage:
                    prompt_tokens = final_message_usage.get("tokens_prompt")
                    completion_tokens = final_message_usage.get("tokens_completion")
                    if prompt_tokens is not None:
                        fallback_msg.tokens_prompt = int(prompt_tokens)
                    if completion_tokens is not None:
                        fallback_msg.tokens_completion = int(completion_tokens)
                db.add(fallback_msg)
                msg_count += 1

            conv.message_count = (conv.message_count or 0) + msg_count
            if tour_cards:
                conv.tour_cards_shown = (conv.tour_cards_shown or 0) + len(tour_cards)

            search_call_count = 0
            if snapshot_entries:
                for entry in snapshot_entries:
                    for tc in (entry.get("tool_calls") or []):
                        fn = tc.get("function", {}).get("name", "")
                        if fn in ("search_tours", "get_hot_tours"):
                            search_call_count += 1
            if search_call_count > 0:
                conv.search_count = (conv.search_count or 0) + search_call_count

            if not conv.has_booking_intent:
                user_texts = [
                    m.content for m in db.query(Message.content).filter(
                        Message.conversation_id == conv.id,
                        Message.role == "user",
                    ).all()
                ]
                if check_conversation_booking_intent(user_texts):
                    conv.has_booking_intent = True

            if api_calls_log:
                try:
                    from models import ApiCall
                    for ac in api_calls_log:
                        db.add(ApiCall(
                            conversation_id=conv.id,
                            service=ac.get("service", "unknown"),
                            endpoint=ac.get("endpoint", ""),
                            response_code=ac.get("response_code"),
                            response_bytes=ac.get("response_bytes"),
                            tokens_used=ac.get("tokens_used"),
                            latency_ms=ac.get("latency_ms", 0),
                            error=ac.get("error"),
                        ))
                except Exception:
                    pass

            db.flush()

            if _aid is not None:
                try:
                    from dialog_sender import enqueue_conversation_snapshot
                    enqueue_conversation_snapshot(db, conversation_id=conv.id, assistant_id=_aid)
                except Exception:
                    logger.warning(
                        "Dialog sender enqueue failed for conversation=%s assistant=%s",
                        conv.id,
                        _aid,
                        exc_info=True,
                    )

    except Exception as e:
        logger.warning("DB logging failed (non-critical): %s", e)


def _log_tour_searches(db, conv_id, tool_calls_data, tour_cards=None, search_result=None, tool_outputs=None):
    """Извлечь параметры поисков туров из tool_calls и записать в tour_searches."""
    try:
        from models import TourSearch
        for tc in tool_calls_data:
            func = tc.get("function", {})
            name = func.get("name", "")
            if name not in ("search_tours", "get_hot_tours"):
                continue
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue

            def _int(val):
                if val is None or val == "":
                    return None
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return None

            def _csv_first_int(val):
                if val is None or val == "":
                    return None
                if isinstance(val, (list, tuple)):
                    return _csv_first_int(val[0] if val else None)
                if isinstance(val, int):
                    return val
                raw = str(val).strip()
                if not raw:
                    return None
                return _int(raw.split(",")[0].strip())

            def _csv_text(val):
                if val is None or val == "":
                    return None
                if isinstance(val, (list, tuple)):
                    items = [str(item).strip() for item in val if str(item).strip()]
                    return ",".join(items) or None
                return str(val).strip() or None

            tours_found = None
            hotels_found = None
            min_price = None
            if tour_cards:
                tours_found = len(tour_cards)
                hotel_names = {c.get("hotel_name") for c in tour_cards if c.get("hotel_name")}
                hotels_found = len(hotel_names) if hotel_names else None
                prices = [c.get("price") for c in tour_cards if c.get("price")]
                min_price = min(prices) if prices else None

            if name == "get_hot_tours":
                stype = "hot"
            elif _int(args.get("departure")) == 99:
                stype = "without_flight"
            elif args.get("hotels"):
                stype = "hotel"
            else:
                stype = "regular"

            search = TourSearch(
                conversation_id=conv_id,
                search_type=stype,
                departure=_int(args.get("departure") or args.get("city")),
                country=_csv_first_int(args.get("country") or args.get("countries")),
                regions=_csv_text(args.get("regions")),
                date_from=args.get("datefrom"),
                date_to=args.get("dateto"),
                nights_from=_int(args.get("nightsfrom")),
                nights_to=_int(args.get("nightsto") or (args.get("maxdays") if stype != "hot" else None)),
                adults=_int(args.get("adults")),
                children=_int(args.get("child")),
                stars=_int(args.get("stars")),
                meal=_int(args.get("meal")),
                price_from=_int(args.get("pricefrom")),
                price_to=_int(args.get("priceto")),
                tours_found=tours_found,
                hotels_found=hotels_found,
                min_price=min_price,
            )
            if search_result:
                search.hotels_found = search_result.get("hotels_found")
                search.tours_found = search_result.get("tours_found")
                search.min_price = search_result.get("min_price")
                search.requestid = search_result.get("requestid") or search.requestid
                search.duration_ms = search_result.get("duration_ms")
            tc_id = tc.get("id")
            tool_output = (tool_outputs or {}).get(tc_id) if tc_id else None
            if name == "search_tours" and isinstance(tool_output, dict):
                search.requestid = (
                    tool_output.get("requestid")
                    or ((tool_output.get("result") or {}).get("requestid") if isinstance(tool_output.get("result"), dict) else None)
                    or search.requestid
                )
            if not search.requestid:
                search.requestid = args.get("requestid")
            db.add(search)
    except Exception as e:
        logger.warning("_log_tour_searches failed: %s", e)


# Dashboard SPA is built into the backend image and served directly by Flask.
_DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_dist"))


def _is_internal_request() -> bool:
    """Check if request comes from localhost or Docker internal network."""
    ip = request.remote_addr or ""
    return ip in ("127.0.0.1", "::1", "172.18.0.1") or ip.startswith("172.") or ip.startswith("10.")


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _ip_matches_trusted_cidrs(ip: str, raw_cidrs: str) -> bool:
    if not ip or not raw_cidrs:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False

    for item in _split_csv(raw_cidrs):
        try:
            if "/" in item:
                if ip_obj in ipaddress.ip_network(item, strict=False):
                    return True
            elif ip == item:
                return True
        except ValueError:
            logger.warning("Invalid trusted CIDR/IP ignored: %s", item)
    return False


def _compute_service_signature(secret: str, service_id: str, timestamp: str,
                               method: str, path: str, body: bytes) -> str:
    payload = b"\n".join([
        service_id.encode("utf-8"),
        timestamp.encode("utf-8"),
        method.upper().encode("utf-8"),
        path.encode("utf-8"),
        body or b"",
    ])
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _build_service_auth_headers(assistant_id: str = None) -> dict:
    from config import settings

    secret = ""
    if assistant_id:
        try:
            from runtime_config import resolve_runtime_config
            runtime_config = resolve_runtime_config(assistant_id=assistant_id)
            secret = (runtime_config.runtime_service_auth_secret or "").strip()
        except Exception:
            logger.warning("Failed to resolve runtime auth secret for assistant=%s", assistant_id, exc_info=True)
            secret = ""

    if not secret:
        secret = (settings.runtime_service_auth_secret or "").strip()
    if not secret:
        return {}

    return {
        "X-MGP-Service-Token": secret,
    }


def _resolve_request_assistant_id() -> str:
    assistant_id = (request.headers.get("X-Assistant-Id") or "").strip()
    if assistant_id:
        return assistant_id

    assistant_id = (request.args.get("assistant_id") or "").strip()
    if assistant_id:
        return assistant_id

    payload = request.get_json(silent=True) or {}
    return str(payload.get("assistant_id") or "").strip()


def _resolve_request_runtime_secret() -> tuple[str, str]:
    from config import settings
    from runtime_config import resolve_runtime_config

    assistant_id = _resolve_request_assistant_id()
    if assistant_id:
        runtime_config = resolve_runtime_config(assistant_id=assistant_id)
        assistant_secret = (runtime_config.runtime_service_auth_secret or "").strip()
        if assistant_secret:
            return assistant_secret, "assistant"

    return (settings.runtime_service_auth_secret or "").strip(), "env"


def _evaluate_runtime_auth(path: str = None) -> dict:
    from config import settings

    mode = (settings.runtime_service_auth_mode or "monitor").strip().lower()
    ip = request.remote_addr or ""
    trusted_ip = _ip_matches_trusted_cidrs(ip, settings.runtime_trusted_proxy_cidrs)
    trusted_service_ids = set(_split_csv(settings.runtime_trusted_service_ids))
    assistant_id = _resolve_request_assistant_id()
    secret, secret_source = _resolve_request_runtime_secret()
    service_id = (request.headers.get("X-MGP-Service-Id") or "").strip()
    timestamp = (request.headers.get("X-MGP-Timestamp") or "").strip()
    signature = (request.headers.get("X-MGP-Signature") or "").strip().lower()
    token_header = (request.headers.get("X-MGP-Service-Token") or "").strip()
    auth_header = (request.headers.get("Authorization") or "").strip()
    bearer_token = ""
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()

    present = any([service_id, timestamp, signature, token_header, bearer_token])
    service_allowed = not trusted_service_ids or not service_id or service_id in trusted_service_ids

    token_valid = bool(secret) and (
        (token_header and hmac.compare_digest(token_header, secret))
        or (bearer_token and hmac.compare_digest(bearer_token, secret))
    )

    signature_valid = False
    skew_ok = False
    if secret and service_allowed and service_id and timestamp and signature:
        try:
            ts = int(timestamp)
            skew_ok = abs(int(time.time()) - ts) <= int(settings.runtime_service_auth_max_skew_seconds)
        except ValueError:
            skew_ok = False

        if skew_ok:
            expected = _compute_service_signature(
                secret,
                service_id,
                timestamp,
                request.method,
                path or request.path,
                request.get_data(cache=True) or b"",
            )
            signature_valid = hmac.compare_digest(signature, expected)

    reason = "missing"
    valid = False
    if mode == "off":
        reason = "disabled"
    elif not secret and not settings.runtime_trusted_proxy_cidrs:
        reason = "not_configured"
    elif trusted_ip and settings.runtime_allow_trusted_proxy_bypass:
        valid = True
        reason = "trusted_proxy"
    elif not service_allowed:
        reason = "untrusted_service"
    elif signature and service_id and timestamp:
        valid = signature_valid
        reason = "hmac" if signature_valid else ("timestamp_skew" if not skew_ok else "invalid_hmac")
    elif token_header or bearer_token:
        valid = token_valid
        reason = "token" if token_valid else "invalid_token"

    would_reject = mode == "enforce" and mode != "off" and not valid

    return {
        "mode": mode,
        "ip": ip,
        "present": present,
        "valid": valid,
        "trusted_ip": trusted_ip,
        "service_id": service_id or None,
        "assistant_id": assistant_id or None,
        "secret_source": secret_source,
        "reason": reason,
        "would_reject": would_reject,
    }


def _runtime_auth_log_label(outcome: dict) -> str:
    if outcome.get("valid"):
        return outcome.get("reason", "ok")
    if outcome.get("present"):
        return outcome.get("reason", "invalid")
    return "missing"


def _runtime_auth_error_response(conversation_id: str = None, stream: bool = False):
    outcome = getattr(g, "runtime_auth", None) or {}
    if not outcome.get("would_reject"):
        return None

    logger.warning(
        "🚫 SERVICE AUTH rejected path=%s ip=%s mode=%s service=%s assistant_id=%s secret_source=%s reason=%s",
        request.path,
        outcome.get("ip"),
        outcome.get("mode"),
        outcome.get("service_id") or "-",
        outcome.get("assistant_id") or "-",
        outcome.get("secret_source") or "-",
        outcome.get("reason"),
    )

    if request.path == "/api/v1/chat":
        return jsonify({
            "error": "Forbidden",
            "reply": "Доступ к runtime временно запрещён.",
            "tour_cards": [],
            "conversation_id": conversation_id or str(uuid.uuid4()),
        }), 403

    if stream:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"error": "Forbidden"}), 403


def _runtime_control_plane_forbidden():
    return None


def _dashboard_file_response(path: str):
    rel_path = (path or "").lstrip("/")
    if not rel_path:
        return None
    full_path = os.path.abspath(os.path.join(_DASHBOARD_DIR, rel_path))
    if not full_path.startswith(_DASHBOARD_DIR + os.sep):
        return None
    if not os.path.isfile(full_path):
        return None
    return send_from_directory(_DASHBOARD_DIR, rel_path)


def _dashboard_index_response():
    index_path = os.path.join(_DASHBOARD_DIR, "index.html")
    if not os.path.isfile(index_path):
        logger.error("Dashboard bundle is missing: %s", index_path)
        return "Dashboard bundle is not available", 503
    return send_from_directory(_DASHBOARD_DIR, "index.html")


@app.route('/test_widget.html')
def test_widget():
    """Serve the standalone test widget page for local testing."""
    _widget_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_widget.html"))
    if os.path.isfile(_widget_path):
        return send_from_directory(os.path.dirname(_widget_path), "test_widget.html")
    return "test_widget.html not found", 404


@app.route('/favicon.ico')
def favicon():
    """Чтобы не засорять логи 404-ками от браузера."""
    return ("", 204)

_last_cleanup = [0.0]  # mutable container for nonlocal access

@app.before_request
def _log_request_start():
    _init_infrastructure()
    g._req_start = time.perf_counter()
    g.request_id = uuid.uuid4().hex[:8]
    logger.info("-> %s %s rid=%s ip=%s", request.method, request.path, g.request_id, request.remote_addr)

    try:
        from cache import rate_limit_check
        from config import settings
        ip = request.remote_addr or "unknown"

        if request.path in ('/api/auth/login', '/api/auth/refresh'):
            auth_key = f"rl:auth:{ip}:{int(time.time()) // 300}"
            if not rate_limit_check(auth_key, 10, 300):
                return jsonify({"error": "Too many login attempts. Try again in 5 minutes."}), 429

        if request.path.startswith(('/api/chat', '/api/v1/chat')):
            ip_key = f"rl:ip:{ip}:{int(time.time()) // 60}"
            if not rate_limit_check(ip_key, settings.rate_limit_per_ip, 60):
                logger.warning("🚫 RATE LIMIT ip=%s path=%s", ip, request.path)
                return jsonify({"error": "Rate limit exceeded", "reply": "Слишком много запросов — подождите минутку и повторите!"}), 429
    except Exception:
        pass

    if request.path in ('/api/v1/chat', '/api/runtime/history'):
        try:
            g.runtime_auth = _evaluate_runtime_auth()
            outcome = g.runtime_auth
            if outcome.get("mode") != "off":
                label = _runtime_auth_log_label(outcome)
                log_level = logging.INFO if outcome.get("valid") or label == "not_configured" else logging.WARNING
                logger.log(
                    log_level,
                    "🔐 SERVICE AUTH path=%s mode=%s result=%s ip=%s service=%s",
                    request.path,
                    outcome.get("mode"),
                    label,
                    outcome.get("ip"),
                    outcome.get("service_id") or "-",
                )
        except Exception:
            logger.warning("Runtime auth evaluation failed for %s", request.path, exc_info=True)

    # Периодическая очистка устаревших сессий (каждые 5 минут)
    now = time.time()
    if now - _last_cleanup[0] > 300:
        _last_cleanup[0] = now
        _cleanup_stale_sessions()


@app.after_request
def _log_request_end(response):
    try:
        duration_ms = int((time.perf_counter() - getattr(g, "_req_start", time.perf_counter())) * 1000)
    except Exception:
        duration_ms = -1
    rid = getattr(g, "request_id", "-")
    logger.info("<- %s %s %s %dms rid=%s", request.method, request.path, response.status_code, duration_ms, rid)
    # удобно дергать request-id из фронта при разборе багов
    response.headers["X-Request-Id"] = rid
    if request.path in ('/api/v1/chat', '/api/runtime/history'):
        outcome = getattr(g, "runtime_auth", None)
        if outcome:
            response.headers["X-Runtime-Auth-Mode"] = outcome.get("mode", "off")
    return response


@app.errorhandler(Exception)
def _handle_unexpected_error(e: Exception):
    # не ломаем штатные HTTP ошибки (404/405 и т.п.)
    if isinstance(e, HTTPException):
        return e

    rid = getattr(g, "request_id", "-")
    logger.exception("Unhandled exception rid=%s path=%s", rid, request.path)
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e), "request_id": rid}), 500
    return "Internal Server Error", 500


@app.route('/api/chat', methods=['POST'])
def chat():
    """Обычный chat без streaming"""
    data = request.json or {}
    message = data.get('message', '').strip()
    session_id = data.get('session_id', 'default')
    assistant_id = data.get('assistant_id') or request.headers.get('X-Assistant-Id')
    auth_error = _runtime_auth_error_response(conversation_id=session_id)
    if auth_error:
        return auth_error
    
    if not message:
        return jsonify({'error': 'Empty message'}), 400
    if len(message) > _MAX_MESSAGE_LENGTH:
        return jsonify({'error': 'Message too long'}), 400
    
    handler = get_handler(session_id, assistant_id=assistant_id)
    
    try:
        _hist_before = len(handler.full_history)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(handler.chat(message))
        loop.close()
        _new_entries = handler.full_history[_hist_before:]

        tour_cards = list(handler._pending_tour_cards)
        handler._pending_tour_cards = []
        _api_calls_snapshot = list(getattr(handler, '_pending_api_calls', []))
        if hasattr(handler, '_pending_api_calls'):
            handler._pending_api_calls.clear()

        # ── Enrich cards with addpayments from prefetch cache (no extra API calls) ──
        if tour_cards and hasattr(handler, '_tour_details_cache'):
            _sp = getattr(handler, '_last_search_params', {}) or {}
            _adults = _sp.get('adults', 2)
            _children = _sp.get('child', 0)
            _total_people = _adults + _children

            _first_tid = tour_cards[0].get("id", "")
            _prefetch_tids = getattr(handler, '_prefetch_tids', set())
            _failed = getattr(handler, '_prefetch_failed', set())
            if _first_tid and _first_tid in _prefetch_tids and _first_tid not in handler._tour_details_cache:
                import time as _t
                _t0 = _t.time()
                while _t.time() - _t0 < 2.0:
                    if _first_tid in handler._tour_details_cache or _first_tid in _failed:
                        break
                    _t.sleep(0.2)

            _enriched_count = 0
            for card in tour_cards:
                tid = card.get("id", "")
                cached = handler._tour_details_cache.get(tid)
                if cached and isinstance(cached, dict):
                    tourinfo = cached.get("tourinfo", {})
                    addpayments = tourinfo.get("addpayments", [])
                    if addpayments:
                        total_pp = sum(ap.get("amount", 0) for ap in addpayments)
                        card["addpayments_per_person"] = total_pp
                        card["addpayments_total"] = total_pp * _total_people
                        card["addpayments_details"] = [
                            {"name": ap.get("name", ""), "amount": ap.get("amount", 0)}
                            for ap in addpayments
                        ]
                        _enriched_count += 1
            if _enriched_count:
                logger.info("💊 ADDPAYMENTS enriched %d/%d cards from prefetch cache", _enriched_count, len(tour_cards))

        _latency_ms = int((time.perf_counter() - g._req_start) * 1000) if hasattr(g, '_req_start') else None
        _log_chat_to_db(session_id, message, response, tour_cards,
                        _latency_ms, model_name=getattr(handler, 'model', 'unknown'),
                        llm_provider=getattr(getattr(handler, 'runtime_config', None), 'llm_provider', _llm_provider),
                        history_snapshot=_new_entries,
                        assistant_id=assistant_id,
                        search_result=getattr(handler, '_last_search_result', None),
                        api_calls_log=_api_calls_snapshot,
                        final_message_usage=getattr(handler, '_last_message_usage', None))
        
        return jsonify({'response': response})
    except Exception as e:
        logger.exception("chat error session_id=%s", session_id)
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/chat', methods=['POST'])
def chat_v1():
    """
    Новый API для чат-виджета.
    Принимает: { message, conversation_id }
    Возвращает: { reply, tour_cards, conversation_id }
    
    Ключевое отличие от /api/chat/stream:
    - Один JSON-ответ (не SSE stream)
    - tour_cards — массив структурированных объектов для визуальных карточек
    - reply — текстовый ответ ассистента (без Markdown-карточек)
    """
    data = request.json or {}
    message = data.get('message', '').strip()
    conversation_id = data.get('conversation_id', str(uuid.uuid4()))
    assistant_id = data.get('assistant_id') or request.headers.get('X-Assistant-Id')
    auth_error = _runtime_auth_error_response(conversation_id=conversation_id)
    if auth_error:
        return auth_error

    if not message:
        return jsonify({
            'error': 'Empty message',
            'reply': '',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 400

    if len(message) > _MAX_MESSAGE_LENGTH:
        return jsonify({
            'error': 'Message too long',
            'reply': f'Сообщение слишком длинное (макс. {_MAX_MESSAGE_LENGTH} символов).',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 400

    # conversation_id → session_id
    session_id = conversation_id

    if _is_duplicate_user_message(session_id, message):
        logger.warning("🚫 DEBOUNCE: duplicate message from session %s, rejecting", session_id[:8])
        return jsonify({
            'error': 'Duplicate message',
            'reply': 'Подождите, обрабатываю ваш запрос...',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 429

    # Session count limit
    with _handlers_lock:
        if _session_cache_key(session_id, assistant_id) not in _handlers and len(_handlers) >= _MAX_SESSIONS:
            logger.warning("🚫 SESSION LIMIT reached (%d), rejecting new session", _MAX_SESSIONS)
            return jsonify({
                'error': 'Server busy',
                'reply': 'Сейчас много обращений — попробуйте через минутку!',
                'tour_cards': [],
                'conversation_id': conversation_id
            }), 503

    log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "INFO")
    log(f"📨 [v1] Новое сообщение от {session_id[:8]}...", "MSG")
    log(f"   └─ \"{message[:100]}{'...' if len(message) > 100 else ''}\"", "MSG")

    # Acquire per-session lock to prevent concurrent processing (double messages)
    with _session_chat_locks_guard:
        if session_id not in _session_chat_locks:
            _session_chat_locks[session_id] = threading.Lock()
        _chat_lock = _session_chat_locks[session_id]

    if not _chat_lock.acquire(blocking=False):
        logger.warning("🚫 DOUBLE-REQUEST: session %s already processing, rejecting", session_id[:8])
        return jsonify({
            'error': 'Request already in progress',
            'reply': 'Подождите, обрабатываю предыдущий запрос...',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 429

    _write_dialogue_log(session_id, "USER", message)

    handler = get_handler(session_id, assistant_id=assistant_id)

    try:
        _hist_before = len(handler.full_history)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reply = loop.run_until_complete(handler.chat(message))
        loop.close()
        _new_entries = handler.full_history[_hist_before:]

        tour_cards = list(handler._pending_tour_cards)
        handler._pending_tour_cards = []
        _api_calls_snapshot = list(getattr(handler, '_pending_api_calls', []))
        if hasattr(handler, '_pending_api_calls'):
            handler._pending_api_calls.clear()

        # ── Enrich cards with addpayments from prefetch cache (no extra API calls) ──
        if tour_cards and hasattr(handler, '_tour_details_cache'):
            _sp = getattr(handler, '_last_search_params', {}) or {}
            _adults = _sp.get('adults', 2)
            _children = _sp.get('child', 0)
            _total_people = _adults + _children

            _first_tid = tour_cards[0].get("id", "")
            _prefetch_tids = getattr(handler, '_prefetch_tids', set())
            _failed = getattr(handler, '_prefetch_failed', set())
            if _first_tid and _first_tid in _prefetch_tids and _first_tid not in handler._tour_details_cache:
                import time as _t
                _t0 = _t.time()
                while _t.time() - _t0 < 2.0:
                    if _first_tid in handler._tour_details_cache or _first_tid in _failed:
                        break
                    _t.sleep(0.2)

            _enriched_count = 0
            for card in tour_cards:
                tid = card.get("id", "")
                cached = handler._tour_details_cache.get(tid)
                if cached and isinstance(cached, dict):
                    tourinfo = cached.get("tourinfo", {})
                    addpayments = tourinfo.get("addpayments", [])
                    if addpayments:
                        total_pp = sum(ap.get("amount", 0) for ap in addpayments)
                        card["addpayments_per_person"] = total_pp
                        card["addpayments_total"] = total_pp * _total_people
                        card["addpayments_details"] = [
                            {"name": ap.get("name", ""), "amount": ap.get("amount", 0)}
                            for ap in addpayments
                        ]
                        _enriched_count += 1
            if _enriched_count:
                logger.info("💊 ADDPAYMENTS enriched %d/%d cards from prefetch cache", _enriched_count, len(tour_cards))

        _write_dialogue_log(session_id, "ASSISTANT", reply)

        if tour_cards:
            cards_summary_lines = []
            for i, card in enumerate(tour_cards, 1):
                cards_summary_lines.append(
                    f"  {i}. {card.get('hotel_name', '?')} {'⭐' * card.get('hotel_stars', 0)}\n"
                    f"     📍 {card.get('country', '')} / {card.get('resort', '')}\n"
                    f"     💰 {card.get('price', '?'):,} ₽ {'(за чел.)' if card.get('price_per_person') else '(за тур)'}\n"
                    f"     📅 {card.get('date_from', '?')} → {card.get('date_to', '?')} ({card.get('nights', '?')} ночей)\n"
                    f"     🍽 {card.get('meal_description', card.get('food_type', '?'))}\n"
                    f"     🏨 {card.get('room_type', '?')}\n"
                    f"     ✈️ Из: {card.get('departure_city', '?')} | Перелёт: {'Да' if card.get('flight_included') else 'Нет'}\n"
                    f"     🏢 Оператор: {card.get('operator', '?')}\n"
                    f"     🔗 {card.get('hotel_link', '')}"
                )
            cards_text = f"Показано {len(tour_cards)} карточек:\n" + "\n".join(cards_summary_lines)
            _write_dialogue_log(session_id, "TOUR_CARDS", cards_text)

        log(f"✅ [v1] Ответ: {len(reply)} символов, {len(tour_cards)} карточек", "OK")

        _latency_ms = int((time.perf_counter() - g._req_start) * 1000) if hasattr(g, '_req_start') else None
        _log_chat_to_db(session_id, message, reply, tour_cards, _latency_ms,
                        model_name=getattr(handler, 'model', 'unknown'),
                        llm_provider=getattr(getattr(handler, 'runtime_config', None), 'llm_provider', _llm_provider),
                        history_snapshot=_new_entries,
                        assistant_id=assistant_id,
                        search_result=getattr(handler, '_last_search_result', None),
                        api_calls_log=_api_calls_snapshot,
                        final_message_usage=getattr(handler, '_last_message_usage', None))

        _mark_assistant_responded(session_id)

        return jsonify({
            'reply': reply,
            'tour_cards': tour_cards,
            'conversation_id': conversation_id
        })

    except Exception as e:
        logger.exception("[v1] chat error session_id=%s", session_id)
        _write_dialogue_log(session_id, "ERROR", str(e))
        return jsonify({
            'error': str(e),
            'reply': 'Что-то пошло не так — попробуйте ещё раз!',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 500

    finally:
        _chat_lock.release()


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """Chat со streaming через SSE"""
    data = request.json or {}
    message = data.get('message', '').strip()
    session_id = data.get('conversation_id') or data.get('session_id', 'default')
    _stream_assistant_id = data.get('assistant_id') or request.headers.get('X-Assistant-Id')
    auth_error = _runtime_auth_error_response(conversation_id=session_id, stream=True)
    if auth_error:
        return auth_error

    if not message:
        return jsonify({'error': 'Empty message'}), 400
    if len(message) > _MAX_MESSAGE_LENGTH:
        return jsonify({'error': 'Message too long'}), 400

    if _is_duplicate_user_message(session_id, message):
        logger.warning("🚫 DEBOUNCE: duplicate stream message from session %s, rejecting", session_id[:8])
        return jsonify({'error': 'Duplicate message'}), 429

    log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "INFO")
    log(f"📨 Новое сообщение от {session_id[:8]}...", "MSG")
    log(f"   └─ \"{message[:100]}{'...' if len(message) > 100 else ''}\"", "MSG")
    
    # Логируем входящее сообщение пользователя
    _write_dialogue_log(session_id, "USER", message)
    
    handler = get_handler(session_id, assistant_id=_stream_assistant_id)
    _stream_ip = request.remote_addr
    _stream_ua = request.headers.get('User-Agent', '')[:500]
    _stream_start = time.perf_counter()
    log(f"📊 Модель: {handler.model}", "INFO")
    log(f"📊 История: {len(handler.input_list)} сообщений", "INFO")
    
    def generate():
        with _session_chat_locks_guard:
            if session_id not in _session_chat_locks:
                _session_chat_locks[session_id] = threading.Lock()
            _chat_lock = _session_chat_locks[session_id]

        if not _chat_lock.acquire(blocking=False):
            logger.warning("🚫 DOUBLE-REQUEST: stream session %s already processing, rejecting", session_id[:8])
            yield f"data: {json.dumps({'type': 'error', 'content': 'Подождите, обрабатываю предыдущий запрос...'})}\n\n"
            return

        try:
            token_queue = queue.Queue()
            result = {'response': '', 'error': None}
            token_count = [0]
            accumulated_text = ['']
            first_line = [None]
            dedup_active = [False]

            def on_token(token):
                accumulated_text[0] += token

                if first_line[0] is None:
                    nl_idx = accumulated_text[0].find('\n')
                    if nl_idx > 10:
                        first_line[0] = accumulated_text[0][:nl_idx].strip()

                if first_line[0] and len(accumulated_text[0]) > len(first_line[0]) + 50:
                    second = accumulated_text[0].find(first_line[0], len(first_line[0]) + 1)
                    if second > 0 and not dedup_active[0]:
                        dedup_active[0] = True
                        logger.debug("🧹 STREAM DEDUP: duplicate detected at char %d, stopping token emission", second)

                if not dedup_active[0]:
                    token_queue.put(('token', token))
                    token_count[0] += 1

            def run_chat():
                try:
                    _hist_before = len(handler.full_history)
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    log("🚀 Отправляю запрос в LLM...", "INFO")
                    response = loop.run_until_complete(
                        handler.chat_stream(message, on_token=on_token)
                    )
                    loop.close()
                    _new_entries = handler.full_history[_hist_before:]
                    _tour_cards = getattr(handler, '_pending_tour_cards', []) or []
                    handler._pending_tour_cards = []
                    _stream_api_calls = list(getattr(handler, '_pending_api_calls', []))
                    if hasattr(handler, '_pending_api_calls'):
                        handler._pending_api_calls.clear()
                    result['response'] = response
                    result['tour_cards'] = _tour_cards
                    log(f"✅ Ответ получен: {len(response)} символов, {token_count[0]} токенов", "OK")
                    log(f"   └─ \"{response[:150]}{'...' if len(response) > 150 else ''}\"", "OK")
                    _write_dialogue_log(session_id, "ASSISTANT", response)
                    _stream_latency = int((time.perf_counter() - _stream_start) * 1000)
                    _log_chat_to_db(session_id, message, response, _tour_cards,
                                    latency_ms=_stream_latency,
                                    model_name=getattr(handler, 'model', 'unknown'),
                                    llm_provider=getattr(getattr(handler, 'runtime_config', None), 'llm_provider', _llm_provider),
                                    ip_address=_stream_ip, user_agent=_stream_ua,
                                    history_snapshot=_new_entries,
                                    assistant_id=_stream_assistant_id,
                                    search_result=getattr(handler, '_last_search_result', None),
                                    api_calls_log=_stream_api_calls,
                                    final_message_usage=getattr(handler, '_last_message_usage', None))
                    _mark_assistant_responded(session_id)
                    token_queue.put(('done', response))
                except Exception as e:
                    result['error'] = str(e)
                    logger.exception("stream chat error session_id=%s", session_id)
                    log(f"❌ ОШИБКА: {e}", "ERROR")
                    _write_dialogue_log(session_id, "ERROR", str(e))
                    token_queue.put(('error', str(e)))

            thread = threading.Thread(target=run_chat)
            thread.start()

            while True:
                try:
                    event_type, data = token_queue.get(timeout=60)

                    if event_type == 'token':
                        yield f"data: {json.dumps({'type': 'token', 'content': data})}\n\n"
                    elif event_type == 'done':
                        yield f"data: {json.dumps({'type': 'done', 'content': data})}\n\n"
                        break
                    elif event_type == 'error':
                        yield f"data: {json.dumps({'type': 'error', 'content': data})}\n\n"
                        break
                except queue.Empty:
                    log("⏳ Таймаут ожидания...", "WARN")
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"

            thread.join()
        finally:
            _chat_lock.release()
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/reset', methods=['POST'])
def reset():
    """Сбросить историю диалога"""
    data = request.json or {}
    session_id = data.get('session_id', 'default')
    
    with _handlers_lock:
        if session_id in _handlers:
            _handlers[session_id]["handler"].reset()
            log(f"🔄 Сессия {session_id[:8]}... сброшена", "WARN")
            _write_dialogue_log(session_id, "SYSTEM", "=== SESSION RESET ===")
    
    return jsonify({'status': 'ok'})


def _build_health_payload() -> dict:
    checks = {"status": "ok"}
    try:
        from database import check_health as db_health
        checks["postgres"] = "ok" if db_health() else "unavailable"
    except Exception:
        checks["postgres"] = "unavailable"
    try:
        from cache import check_health as cache_health
        checks["redis"] = "ok" if cache_health() else "unavailable"
    except Exception:
        checks["redis"] = "unavailable"
    with _handlers_lock:
        checks["active_sessions"] = len(_handlers)
    return checks


@app.route('/api/health')
def health():
    """Health check для Docker healthcheck и мониторинга."""
    checks = _build_health_payload()
    all_ok = checks.get("postgres") == "ok" and checks.get("redis") == "ok"
    return jsonify(checks), 200 if all_ok else 503


@app.route('/api/runtime/metadata')
def runtime_metadata():
    """Runtime metadata for control-plane and tenant provisioning."""
    denied = _runtime_control_plane_forbidden()
    if denied:
        return denied

    from config import settings
    from runtime_config import resolve_runtime_config

    assistant_id = request.args.get("assistant_id") or request.headers.get("X-Assistant-Id")
    runtime = resolve_runtime_config(assistant_id=assistant_id)
    service_ids = _split_csv(settings.runtime_trusted_service_ids)
    reporting = dict((runtime.runtime_metadata or {}).get("reporting") or {})
    reporting_auth = dict(reporting.get("auth") or {})

    return jsonify({
        "runtime_instance_id": settings.runtime_instance_id or os.getenv("HOSTNAME") or "mgp-runtime",
        "runtime_mode": _RUNTIME_MODE,
        "public_base_url": settings.runtime_public_base_url or request.host_url.rstrip("/"),
        "config_source": getattr(runtime, "source", "env-default"),
        "tenant": {
            "assistant_id": runtime.assistant_id,
            "assistant_name": runtime.assistant_name,
            "company_id": runtime.company_id,
            "company_name": runtime.company_name,
            "company_slug": runtime.company_slug,
            "company_logo_url": runtime.company_logo_url,
            "allowed_domains": runtime.allowed_domains,
            "bot_server_url": runtime.bot_server_url,
            "branding": {
                "title": (runtime.widget_config or {}).get("title"),
                "subtitle": (runtime.widget_config or {}).get("subtitle"),
                "primary_color": (runtime.widget_config or {}).get("primary_color"),
                "logo_url": (runtime.widget_config or {}).get("logo_url") or runtime.company_logo_url,
            },
        },
        "llm": {
            "provider": runtime.llm_provider,
            "model": runtime.llm_model or runtime.yandex_model,
        },
        "security": {
            "auth_mode": settings.runtime_service_auth_mode,
            "trusted_service_ids": service_ids,
            "trusted_proxy_configured": bool(settings.runtime_trusted_proxy_cidrs),
            "allow_trusted_proxy_bypass": settings.runtime_allow_trusted_proxy_bypass,
        },
        "reporting": {
            "mode": reporting.get("mode") or ("batch_snapshot" if settings.runtime_report_url else "none"),
            "contract_version": reporting.get("contract_version"),
            "endpoint_url": reporting.get("endpoint_url") or settings.runtime_report_url or "",
            "accepted_event_types": reporting.get("accepted_event_types") or ["conversation_snapshot"],
            "auth": {
                "type": reporting_auth.get("type") or "shared_secret",
                "header_name": reporting_auth.get("header_name") or "X-MGP-Service-Token",
                "secret_configured": bool(reporting_auth.get("secret") or settings.runtime_report_token),
            },
        },
        "capabilities": {
            "chat_v1": True,
            "chat_stream": True,
            "health": True,
            "runtime_metadata": True,
            "runtime_status": True,
            "dialog_sender": True,
        },
    })


@app.route('/api/runtime/history')
def runtime_history():
    """Internal runtime conversation history for widget restoration."""
    _init_infrastructure()
    from database import get_db

    conversation_id = (request.args.get("conversation_id") or request.args.get("cid") or "").strip()
    assistant_id = _resolve_request_assistant_id()
    auth_error = _runtime_auth_error_response(conversation_id=conversation_id)
    if auth_error:
        return auth_error
    if not conversation_id:
        return jsonify({"conversation_id": "", "messages": []})

    with get_db() as db:
        if db is None:
            return jsonify({"conversation_id": conversation_id, "messages": []}), 503
        return jsonify(_build_conversation_history_payload(db, assistant_id, conversation_id))


@app.route('/api/runtime/status')
def runtime_status():
    """Control-plane friendly runtime status snapshot."""
    denied = _runtime_control_plane_forbidden()
    if denied:
        return denied

    from config import settings
    from database import get_db
    from dialog_sender import collect_delivery_metrics
    from models import Assistant
    from runtime_config import resolve_runtime_config

    assistant_id = request.args.get("assistant_id") or request.headers.get("X-Assistant-Id")
    runtime = resolve_runtime_config(assistant_id=assistant_id)
    reporting = dict((runtime.runtime_metadata or {}).get("reporting") or {})
    reporting_enabled = bool(reporting.get("endpoint_url") or settings.runtime_report_url)

    checks = _build_health_payload()
    checks["runtime_mode"] = _RUNTIME_MODE
    checks["runtime_instance_id"] = settings.runtime_instance_id or os.getenv("HOSTNAME") or "mgp-runtime"
    checks["service_auth_mode"] = settings.runtime_service_auth_mode
    checks["trusted_proxy_configured"] = bool(settings.runtime_trusted_proxy_cidrs)
    checks["reporting_enabled"] = reporting_enabled
    checks["dialog_sender_enabled"] = bool(settings.runtime_dialog_sender_enabled)
    checks["dialog_sender_backlog"] = {"pending": 0, "retrying": 0, "failed": 0}
    checks["oldest_undelivered_event_age_sec"] = None
    checks["last_successful_delivery_at"] = None
    checks["estimated_delivery_lag_sec"] = 0
    checks["delivery_pipeline_status"] = "disabled" if not checks["dialog_sender_enabled"] else "ok"
    checks["dialog_sender_alert_thresholds"] = {
        "normal_lag_sec": int(settings.runtime_dialog_sender_normal_lag_threshold_seconds),
        "oldest_undelivered_alert_sec": int(settings.runtime_dialog_sender_oldest_pending_alert_seconds),
        "failed_backlog_alert_count": int(settings.runtime_dialog_sender_failed_backlog_alert_threshold),
    }
    try:
        with get_db() as db:
            if db is not None:
                if not reporting_enabled:
                    assistant_rows = db.query(Assistant.runtime_metadata).filter(Assistant.runtime_metadata.isnot(None)).all()
                    reporting_enabled = any(
                        isinstance(row[0], dict)
                        and isinstance(row[0].get("reporting"), dict)
                        and bool((row[0].get("reporting") or {}).get("endpoint_url"))
                        for row in assistant_rows
                    )
                    checks["reporting_enabled"] = reporting_enabled
                checks.update(
                    collect_delivery_metrics(
                        db,
                        reporting_enabled=reporting_enabled,
                        dialog_sender_enabled=bool(checks["dialog_sender_enabled"]),
                    )
                )
    except Exception:
        logger.warning("Failed to collect dialog sender backlog", exc_info=True)
    all_ok = checks.get("postgres") == "ok" and checks.get("redis") == "ok"
    return jsonify(checks), 200 if all_ok else 503


@app.route('/api/status')
def status():
    """Статус сервера (только внутренние IP)."""
    if not _is_internal_request():
        return jsonify({"error": "Forbidden"}), 403
    with _handlers_lock:
        session_count = len(_handlers)
    return jsonify({
        'status': 'running',
        'sessions': session_count
    })


@app.route('/api/metrics')
def get_metrics():
    """
    Возвращает агрегированные метрики по всем активным сессиям.
    Доступно только с внутренних IP.
    """
    if not _is_internal_request():
        return jsonify({"error": "Forbidden"}), 403
    with _handlers_lock:
        aggregated = {
            "total_sessions": len(_handlers),
            "promised_search_detections": 0,
            "cascade_incomplete_detections": 0,
            "dateto_corrections": 0,
            "total_searches": 0,
            "total_messages": 0,
        }
        
        for session_data in _handlers.values():
            handler = session_data["handler"]
            metrics = handler.get_metrics()
            for key in ["promised_search_detections", "cascade_incomplete_detections", 
                        "dateto_corrections", "total_searches", "total_messages"]:
                aggregated[key] += metrics.get(key, 0)
        
        return jsonify(aggregated)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def dashboard_spa(path):
    """Serve the admin dashboard SPA from the backend bundle."""
    if path.startswith(("api/", "static/", "frontend/")):
        return "Not Found", 404
    if path == "widget/embed" or path.startswith("widget/embed/"):
        return "Not Found", 404

    asset_response = _dashboard_file_response(path)
    if asset_response is not None:
        return asset_response

    if path and "." in os.path.basename(path):
        return "Not Found", 404

    return _dashboard_index_response()


if __name__ == '__main__':
    import socket
    from werkzeug.serving import run_simple

    from dotenv import load_dotenv
    load_dotenv()
    
    model = os.getenv("YANDEX_MODEL", "yandexgpt")
    folder = os.getenv("YANDEX_FOLDER_ID", "???")
    
    print("\n" + "="*50)
    print("🚀 AI ТУРМЕНЕДЖЕР - Web UI")
    print("="*50)
    print(f"📍 URL: http://localhost:8080")
    print(f"🤖 Модель: {model}")
    print(f"📁 Folder: {folder[:8]}...")
    print(f"📝 Dialogue log: {_DIALOGUE_LOG_PATH}")
    print(f"📋 Server log: {os.path.join(_LOGS_DIR, 'server_*.log')}")
    print("="*50 + "\n")
    
    # Привязываемся к '::' (IPv6 dual-stack) — принимает и IPv4, и IPv6 соединения.
    # На macOS localhost -> ::1, поэтому без IPv6 браузер получает ERR_CONNECTION_RESET.
    run_simple('::', 8080, app, use_reloader=False, use_debugger=False, threaded=True)
