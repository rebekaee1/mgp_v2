"""
Web UI для чата с AI-менеджером турагентства
Flask + Server-Sent Events для streaming
"""

import asyncio
import os
import time
import uuid
import logging
from flask import Flask, render_template, request, Response, jsonify, stream_with_context, g, send_from_directory
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
CORS(app, resources={
    r"/api/*": {"origins": "*"},
})

from dashboard_api import auth_bp, dash_bp
app.register_blueprint(auth_bp)
app.register_blueprint(dash_bp)

from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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
        except Exception as e:
            logging.getLogger("mgp_bot").warning("Infrastructure init: %s", e)
        _infra_done = True

# === ЛОГИРОВАНИЕ ===
from datetime import datetime as _dt

# Директория для логов
_LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(_LOGS_DIR, exist_ok=True)

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
with open(_DIALOGUE_LOG_PATH, "w", encoding="utf-8") as _f:
    _f.write(f"# 📝 Диалоговый лог AI-Турменеджера МГП\n")
    _f.write(f"**Дата:** {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    _f.write(f"---\n")


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
_handlers: dict[str, dict] = {}  # session_id → {"handler": Handler, "last_active": float}
SESSION_TTL_SECONDS = 30 * 60  # 30 минут неактивности → удаление


def get_handler(session_id: str):
    """Получить или создать handler для сессии (thread-safe)"""
    with _handlers_lock:
        if session_id in _handlers:
            _handlers[session_id]["last_active"] = time.time()
            return _handlers[session_id]["handler"]
        handler = _HandlerClass()
        # Подключаем диалоговый лог
        handler._dialogue_log_callback = lambda direction, content: _write_dialogue_log(session_id, direction, content)
        _handlers[session_id] = {"handler": handler, "last_active": time.time()}
        logger.info("🆕 New session %s  (provider: %s, total sessions: %d)", session_id[:8], _llm_provider, len(_handlers))
        _write_dialogue_log(session_id, "SYSTEM", f"New session created (provider: {_llm_provider}, model: {handler.model})")
        return handler


def _cleanup_stale_sessions():
    """Удалить сессии, неактивные дольше SESSION_TTL_SECONDS"""
    now = time.time()
    with _handlers_lock:
        stale = [sid for sid, info in _handlers.items()
                 if now - info["last_active"] > SESSION_TTL_SECONDS]
        for sid in stale:
            handler = _handlers[sid]["handler"]
            try:
                handler.close_sync()
            except Exception:
                logger.debug("close_sync failed for session %s", sid[:8], exc_info=True)
            del _handlers[sid]
        if stale:
            logger.info("🧹 Cleaned up %d stale sessions (remaining: %d)", len(stale), len(_handlers))


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
                     ip_address: str = None, user_agent: str = None,
                     history_snapshot: list = None,
                     assistant_id: str = None):
    """
    Записать в PostgreSQL ПОЛНЫЙ ПУТЬ без исключений:
    - КАЖДАЯ запись из history_snapshot (user, assistant, tool, синтетические retry)
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

            conv = db.query(Conversation).filter(
                Conversation.session_id == session_id
            ).first()

            if conv is None:
                ip_addr = ip_address
                ua = user_agent
                if ip_addr is None:
                    try:
                        ip_addr = request.remote_addr
                        ua = request.headers.get('User-Agent', '')[:500]
                    except RuntimeError:
                        pass
                _aid = None
                if assistant_id:
                    try:
                        _aid = uuid.UUID(assistant_id) if isinstance(assistant_id, str) else assistant_id
                    except (ValueError, AttributeError):
                        pass
                conv = Conversation(
                    session_id=session_id,
                    llm_provider=_llm_provider,
                    model=model_name,
                    ip_address=ip_addr,
                    user_agent=ua,
                    assistant_id=_aid,
                )
                db.add(conv)
                db.flush()

            msg_count = 0
            final_reply_in_snapshot = False

            if history_snapshot:
                last_idx = len(history_snapshot) - 1

                for i, entry in enumerate(history_snapshot):
                    role = entry.get("role", "")
                    content = entry.get("content") or ""
                    tc_data = entry.get("tool_calls")
                    tc_id = entry.get("tool_call_id")
                    is_last = (i == last_idx)

                    is_final_reply = (
                        is_last and role == "assistant"
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

                    if is_final_reply:
                        if tour_cards:
                            msg.tour_cards = tour_cards
                        msg.latency_ms = latency_ms
                        final_reply_in_snapshot = True

                    db.add(msg)
                    msg_count += 1

                    if tc_data:
                        _log_tour_searches(db, conv.id, tc_data, tour_cards=tour_cards)

            if not final_reply_in_snapshot:
                if not history_snapshot:
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
                db.add(fallback_msg)
                msg_count += 1

            conv.message_count = (conv.message_count or 0) + msg_count
            if tour_cards:
                conv.tour_cards_shown = (conv.tour_cards_shown or 0) + len(tour_cards)
                conv.search_count = (conv.search_count or 0) + 1

            if not conv.has_booking_intent:
                user_texts = [
                    m.content for m in db.query(Message.content).filter(
                        Message.conversation_id == conv.id,
                        Message.role == "user",
                    ).all()
                ]
                if check_conversation_booking_intent(user_texts):
                    conv.has_booking_intent = True

    except Exception as e:
        logger.debug("DB logging failed (non-critical): %s", e)


def _log_tour_searches(db, conv_id, tool_calls_data, tour_cards=None):
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
                country=_int(args.get("country") or args.get("countries")),
                regions=str(args.get("regions", "")) or None,
                date_from=args.get("datefrom"),
                date_to=args.get("dateto"),
                nights_from=_int(args.get("nightsfrom")),
                nights_to=_int(args.get("nightsto") or args.get("maxdays")),
                adults=_int(args.get("adults")),
                children=_int(args.get("children")),
                stars=_int(args.get("stars")),
                meal=_int(args.get("meal")),
                price_from=_int(args.get("pricefrom")),
                price_to=_int(args.get("priceto")),
                tours_found=tours_found,
                hotels_found=hotels_found,
                min_price=min_price,
            )
            db.add(search)
    except Exception:
        pass


# Путь к новому фронтенду (frontend/) — абсолютный путь для корректной работы send_from_directory
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"))


@app.route('/')
def index():
    """Главная страница — новый чат-виджет"""
    return send_from_directory(_FRONTEND_DIR, 'index.html')


@app.route('/widget')
def widget():
    """Новый чат-виджет с визуальными карточками туров"""
    return send_from_directory(_FRONTEND_DIR, 'index.html')


@app.route('/frontend/<path:filename>')
def frontend_static(filename):
    """Статические файлы нового фронтенда (CSS, JS)"""
    return send_from_directory(_FRONTEND_DIR, filename)


@app.route('/widget.js')
def widget_js():
    return send_from_directory(_FRONTEND_DIR, 'script.js', mimetype='application/javascript')


@app.route('/widget.css')
def widget_css():
    return send_from_directory(_FRONTEND_DIR, 'styles.css', mimetype='text/css')


WIDGET_DEFAULTS = {
    "welcome_message": "\U0001f44b Здравствуйте! Я — ИИ-ассистент туристического агентства.\n\nЯ помогу вам:\n• \U0001f50d Подобрать тур по вашим параметрам\n• \U0001f525 Найти горящие предложения\n• \u2753 Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?",
    "primary_color": "#E30613",
    "position": "bottom-right",
    "title": "AI Ассистент",
    "subtitle": "Турагентство",
    "logo_url": None,
}


@app.route('/api/widget/config')
def public_widget_config():
    """Public widget config (no auth). Widget calls this on init."""
    _init_infrastructure()
    from database import get_db
    from models import Assistant

    assistant_id = request.args.get('assistant_id')

    with get_db() as db:
        if db is None:
            return jsonify(WIDGET_DEFAULTS)

        if assistant_id:
            assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
        else:
            assistant = db.query(Assistant).filter(Assistant.is_active.is_(True)).first()

        if not assistant:
            return jsonify(WIDGET_DEFAULTS)

        cfg = assistant.widget_config or {}
        return jsonify({
            "welcome_message": cfg.get("welcome_message") or WIDGET_DEFAULTS["welcome_message"],
            "primary_color": cfg.get("primary_color") or WIDGET_DEFAULTS["primary_color"],
            "position": cfg.get("position") or WIDGET_DEFAULTS["position"],
            "title": cfg.get("title") or WIDGET_DEFAULTS["title"],
            "subtitle": cfg.get("subtitle") or WIDGET_DEFAULTS["subtitle"],
            "logo_url": cfg.get("logo_url") or None,
        })


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

    if request.path.startswith(('/api/chat', '/api/v1/chat')):
        from cache import rate_limit_check
        from config import settings
        ip_key = f"rl:ip:{request.remote_addr}:{int(time.time()) // 60}"
        if not rate_limit_check(ip_key, settings.rate_limit_per_ip, 60):
            return jsonify({"error": "Rate limit exceeded"}), 429

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
    data = request.json
    message = data.get('message', '')
    session_id = data.get('session_id', 'default')
    
    if not message:
        return jsonify({'error': 'Empty message'}), 400
    
    handler = get_handler(session_id)
    
    try:
        _hist_before = len(handler.full_history)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        response = loop.run_until_complete(handler.chat(message))
        loop.close()
        _new_entries = handler.full_history[_hist_before:]
        
        _latency_ms = int((time.perf_counter() - g._req_start) * 1000) if hasattr(g, '_req_start') else None
        _log_chat_to_db(session_id, message, response, [],
                        _latency_ms, model_name=getattr(handler, 'model', 'unknown'),
                        history_snapshot=_new_entries)
        
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
    data = request.json
    message = data.get('message', '')
    conversation_id = data.get('conversation_id', str(uuid.uuid4()))
    assistant_id = data.get('assistant_id')

    if not message:
        return jsonify({
            'error': 'Empty message',
            'reply': '',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 400

    # conversation_id → session_id
    session_id = conversation_id

    log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "INFO")
    log(f"📨 [v1] Новое сообщение от {session_id[:8]}...", "MSG")
    log(f"   └─ \"{message[:100]}{'...' if len(message) > 100 else ''}\"", "MSG")

    _write_dialogue_log(session_id, "USER", message)

    handler = get_handler(session_id)

    try:
        _hist_before = len(handler.full_history)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        reply = loop.run_until_complete(handler.chat(message))
        loop.close()
        _new_entries = handler.full_history[_hist_before:]

        tour_cards = list(handler._pending_tour_cards)
        handler._pending_tour_cards = []

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
                        history_snapshot=_new_entries,
                        assistant_id=assistant_id)

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
            'reply': 'Извините, произошла техническая ошибка. Попробуйте ещё раз.',
            'tour_cards': [],
            'conversation_id': conversation_id
        }), 500


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """Chat со streaming через SSE"""
    data = request.json
    message = data.get('message', '')
    session_id = data.get('conversation_id') or data.get('session_id', 'default')
    _stream_assistant_id = data.get('assistant_id')
    
    log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "INFO")
    log(f"📨 Новое сообщение от {session_id[:8]}...", "MSG")
    log(f"   └─ \"{message[:100]}{'...' if len(message) > 100 else ''}\"", "MSG")
    
    # Логируем входящее сообщение пользователя
    _write_dialogue_log(session_id, "USER", message)
    
    if not message:
        log("❌ Пустое сообщение!", "ERROR")
        return jsonify({'error': 'Empty message'}), 400
    
    handler = get_handler(session_id)
    _stream_ip = request.remote_addr
    _stream_ua = request.headers.get('User-Agent', '')[:500]
    _stream_start = time.perf_counter()
    log(f"📊 Модель: {handler.model}", "INFO")
    log(f"📊 История: {len(handler.input_list)} сообщений", "INFO")
    
    def generate():
        token_queue = queue.Queue()
        result = {'response': '', 'error': None}
        token_count = [0]  # Счётчик токенов
        accumulated_text = ['']  # Накопленный текст для dedup
        first_line = [None]  # Первая строка ответа
        dedup_active = [False]  # Флаг: обнаружен дубликат, прекращаем отправку
        
        def on_token(token):
            accumulated_text[0] += token
            
            # Определяем первую строку (после первого \n)
            if first_line[0] is None:
                nl_idx = accumulated_text[0].find('\n')
                if nl_idx > 10:
                    first_line[0] = accumulated_text[0][:nl_idx].strip()
            
            # Проверяем дубликат: если первая строка повторилась
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
                result['response'] = response
                result['tour_cards'] = _tour_cards
                log(f"✅ Ответ получен: {len(response)} символов, {token_count[0]} токенов", "OK")
                log(f"   └─ \"{response[:150]}{'...' if len(response) > 150 else ''}\"", "OK")
                _write_dialogue_log(session_id, "ASSISTANT", response)
                _stream_latency = int((time.perf_counter() - _stream_start) * 1000)
                _log_chat_to_db(session_id, message, response, _tour_cards,
                                latency_ms=_stream_latency,
                                model_name=getattr(handler, 'model', 'unknown'),
                                ip_address=_stream_ip, user_agent=_stream_ua,
                                history_snapshot=_new_entries,
                                assistant_id=_stream_assistant_id)
                token_queue.put(('done', response))
            except Exception as e:
                result['error'] = str(e)
                logger.exception("stream chat error session_id=%s", session_id)
                log(f"❌ ОШИБКА: {e}", "ERROR")
                _write_dialogue_log(session_id, "ERROR", str(e))
                token_queue.put(('error', str(e)))
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=run_chat)
        thread.start()
        
        # Стримим токены
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


@app.route('/api/health')
def health():
    """Health check для Docker healthcheck и мониторинга."""
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
    all_ok = checks.get("postgres") == "ok" and checks.get("redis") == "ok"
    return jsonify(checks), 200 if all_ok else 503


@app.route('/api/status')
def status():
    """Статус сервера"""
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
    Используется для мониторинга качества работы AI-ассистента.
    """
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
