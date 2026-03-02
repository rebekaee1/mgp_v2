"""
Dashboard API Blueprint — all endpoints for the AIMPACT+ personal cabinet.
Every endpoint is scoped to the authenticated user's company via @require_auth.
"""

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, make_response, request
from werkzeug.utils import secure_filename
from sqlalchemy import func, case, cast, Date, distinct, desc, asc, or_

from auth import (
    check_password, create_access_token, create_refresh_token,
    decode_token, hash_password, require_auth,
)
from database import get_db, is_db_available, check_health as db_check_health
from cache import check_health as cache_check_health, cache_get, cache_set
from models import (
    Company, Assistant, User, Conversation, Message, TourSearch, ApiCall, DailyStat,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
dash_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")

_COUNTRY_NAMES = {
    1: "Турция", 2: "Египет", 3: "ОАЭ", 4: "Таиланд", 5: "Тунис",
    6: "Греция", 7: "Кипр", 8: "Испания", 9: "Италия", 10: "Черногория",
    11: "Болгария", 12: "Хорватия", 13: "Чехия", 14: "Андорра",
    15: "Куба", 16: "Доминикана", 17: "Мексика", 18: "Ямайка",
    19: "Мальдивы", 20: "Сингапур", 21: "Малайзия",
    22: "Шри-Ланка", 23: "Индия (Гоа)", 24: "Вьетнам",
    25: "Южная Корея", 26: "Япония", 27: "ЮАР",
    28: "Индонезия (Бали)", 29: "Камбоджа",
    30: "Танзания", 31: "Иордания", 32: "Марокко", 33: "Оман",
    34: "Бахрейн", 35: "Маврикий", 36: "Мадагаскар",
    40: "Австрия", 41: "Франция", 42: "Сейшелы", 43: "Китай",
    44: "Грузия", 45: "Армения", 46: "Азербайджан", 47: "Узбекистан",
    48: "Казахстан", 49: "Кыргызстан",
    76: "Россия", 90: "Абхазия",
}

_DEPARTURE_NAMES = {
    1: "Москва", 2: "Санкт-Петербург", 3: "Екатеринбург", 4: "Казань",
    5: "Новосибирск", 6: "Ростов-на-Дону", 7: "Самара", 8: "Уфа",
    9: "Краснодар", 10: "Минеральные Воды", 11: "Нижний Новгород",
    12: "Пермь", 13: "Красноярск", 14: "Воронеж", 15: "Волгоград",
    16: "Челябинск", 17: "Омск", 18: "Тюмень", 19: "Иркутск",
    20: "Хабаровск", 21: "Владивосток", 22: "Сочи",
    99: "Без перелёта",
}


_DASH_RE = re.compile(
    r'[\u002D\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00AD\uFE63\uFF0D]'
)

_RU_SUFFIXES = sorted([
    "ями", "ами", "ией", "ием", "ого", "его", "ому", "ему",
    "ых", "их", "ый", "ий", "ая", "яя", "ое", "ее", "ые", "ие",
    "ой", "ей", "ом", "ем", "ым", "им", "ую",
    "ов", "ев", "ам", "ям", "ах", "ях",
    "ию", "ии", "ия",
    "а", "я", "у", "ю", "и", "е", "о", "ы",
], key=len, reverse=True)


def _normalize_text(text: str) -> str:
    """Lowercase + ё→е + all dashes/hyphens→space."""
    text = text.lower().replace("ё", "е")
    text = _DASH_RE.sub(" ", text)
    return text.strip()


_RU_CONSONANTS = set("бвгджзклмнпрстфхцчшщ")


def _ru_stem(word: str) -> str:
    """Remove common Russian suffixes to get a crude stem (min 3 chars)."""
    if len(word) < 4:
        return word
    for sfx in _RU_SUFFIXES:
        if word.endswith(sfx) and len(word) - len(sfx) >= 3:
            return word[:-len(sfx)]
    return word


def _stem_variants(word: str) -> list[str]:
    """Return the stem + variants with fleeting vowels (е/о) inserted."""
    stem = _ru_stem(word)
    variants = [stem]
    if len(stem) >= 3 and stem[-1] in _RU_CONSONANTS:
        for v in ("е", "о"):
            variants.append(stem[:-1] + v + stem[-1])
    return variants


def _match_codes(mapping: dict, word: str) -> list[int]:
    """Stem-aware matching: word against dictionary names.
    Handles fleeting vowels (Египет→Египта) via shared 4-char prefix fallback.
    """
    w = _normalize_text(word)
    stem = _ru_stem(w)
    result = []
    for code, name in mapping.items():
        n = _normalize_text(name)
        n_stem = _ru_stem(n)
        if w in n or n in w:
            result.append(code)
        elif stem in n or n_stem in w:
            result.append(code)
        elif len(stem) >= 4 and len(n_stem) >= 4 and stem[:4] == n_stem[:4]:
            result.append(code)
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _period_start(period: str) -> datetime:
    days_map = {"1d": 1, "3d": 3, "7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = days_map.get(period, 30)
    return datetime.now(timezone.utc) - timedelta(days=days)


def _assistant_ids(db) -> list[uuid.UUID]:
    """Return all assistant IDs belonging to the current user's company."""
    rows = db.query(Assistant.id).filter(Assistant.company_id == g.company_id).all()
    return [r[0] for r in rows]


def _apply_aids_filter(q, aids, entity=None):
    """Always apply assistant_id filter — returns impossible condition if aids is empty."""
    target = entity or Conversation
    if aids:
        return q.filter(target.assistant_id.in_(aids))
    return q.filter(target.assistant_id == None)  # noqa: E711 — no assistants = no data


def _conv_filter(q, period: str, assistant_ids: list):
    """Apply standard time + assistant_id filters to a Conversation query."""
    since = _period_start(period)
    q = q.filter(Conversation.started_at >= since)
    return _apply_aids_filter(q, assistant_ids)


# ── Auth endpoints ────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        user = db.query(User).filter(User.email == email).first()
        if not user or not check_password(password, user.password_hash):
            return jsonify({"error": "Invalid credentials"}), 401

        user.last_login_at = datetime.now(timezone.utc)

        access = create_access_token(user.id, user.company_id, user.role)
        refresh = create_refresh_token(user.id)

        company = db.query(Company).get(user.company_id)

        return jsonify({
            "access_token": access,
            "refresh_token": refresh,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "role": user.role,
                "company": {
                    "id": str(company.id),
                    "name": company.name,
                    "slug": company.slug,
                    "logo_url": company.logo_url,
                } if company else None,
            },
        })


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    data = request.get_json(silent=True) or {}
    token = data.get("refresh_token", "")
    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        return jsonify({"error": "Invalid refresh token"}), 401

    user_id = uuid.UUID(payload["sub"])
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503
        user = db.query(User).get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 401

        access = create_access_token(user.id, user.company_id, user.role)
        return jsonify({"access_token": access})


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503
        user = db.query(User).get(g.current_user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        company = db.query(Company).get(user.company_id)
        return jsonify({
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "company": {
                "id": str(company.id),
                "name": company.name,
                "slug": company.slug,
                "logo_url": company.logo_url,
            } if company else None,
        })


# ── Overview ──────────────────────────────────────────────────────────────────

@dash_bp.route("/overview", methods=["GET"])
@require_auth
def overview():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        prev_since = since - (datetime.now(timezone.utc) - since)

        def _conv_q(start):
            q = db.query(Conversation).filter(Conversation.started_at >= start)
            q = _apply_aids_filter(q, aids)
            return q

        convs_now = _conv_q(since).count()
        convs_prev = _conv_q(prev_since).filter(Conversation.started_at < since).count()

        conv_ids_now = [c.id for c in _conv_q(since).with_entities(Conversation.id).all()]

        booking_now = 0
        booking_prev = 0
        searches_now = 0
        avg_latency = 0
        if conv_ids_now:
            booking_now = _conv_q(since).filter(
                Conversation.has_booking_intent == True  # noqa: E712
            ).count()

            searches_now = db.query(func.count(TourSearch.id)).filter(
                TourSearch.conversation_id.in_(conv_ids_now)
            ).scalar() or 0

            avg_latency = db.query(func.avg(Message.latency_ms)).filter(
                Message.conversation_id.in_(conv_ids_now),
                Message.role == "assistant",
                Message.latency_ms.isnot(None),
            ).scalar() or 0

        booking_prev = _conv_q(prev_since).filter(
            Conversation.started_at < since,
            Conversation.has_booking_intent == True,  # noqa: E712
        ).count()

        def _delta(now_val, prev_val):
            if prev_val == 0:
                return 100.0 if now_val > 0 else 0
            return round((now_val - prev_val) / prev_val * 100, 1)

        # ── Funnel data ──
        funnel = {"total": convs_now, "engaged": 0, "with_search": 0,
                  "with_results": 0, "booking_intent": 0, "potential_leads": 0}
        insights = {"after_hours_pct": 0, "avg_duration_minutes": 0,
                    "empty_search_pct": 0, "avg_user_messages": 0,
                    "booking_intent_pct": 0}

        if conv_ids_now:
            user_msg_counts = dict(
                db.query(Message.conversation_id, func.count(Message.id))
                .filter(Message.conversation_id.in_(conv_ids_now), Message.role == "user")
                .group_by(Message.conversation_id).all()
            )

            convs_data = db.query(
                Conversation.id, Conversation.search_count,
                Conversation.tour_cards_shown, Conversation.started_at,
                Conversation.last_active_at, Conversation.has_booking_intent,
            ).filter(Conversation.id.in_(conv_ids_now)).all()

            total_user_msgs = sum(user_msg_counts.values())
            duration_sum = 0
            duration_count = 0
            after_hours = 0

            for c in convs_data:
                umc = user_msg_counts.get(c.id, 0)
                sc = c.search_count or 0
                tc = c.tour_cards_shown or 0

                is_engaged = umc >= 2
                has_search = is_engaged and sc > 0
                has_cards = has_search and tc > 0
                is_lead = has_cards and umc >= 4
                is_booking = is_lead and c.has_booking_intent

                if is_engaged:
                    funnel["engaged"] += 1
                if has_search:
                    funnel["with_search"] += 1
                if has_cards:
                    funnel["with_results"] += 1
                if is_lead:
                    funnel["potential_leads"] += 1
                if is_booking:
                    funnel["booking_intent"] += 1

                if c.started_at and c.last_active_at:
                    diff = (c.last_active_at - c.started_at).total_seconds()
                    if diff > 0:
                        duration_sum += diff
                        duration_count += 1

                if c.started_at:
                    h_utc = c.started_at.hour if hasattr(c.started_at, 'hour') else 12
                    h_msk = (h_utc + 3) % 24
                    if h_msk < 9 or h_msk >= 18:
                        after_hours += 1

            if convs_now > 0:
                insights["after_hours_pct"] = round(after_hours / convs_now * 100)
                insights["avg_user_messages"] = round(total_user_msgs / convs_now, 1)
                insights["booking_intent_pct"] = round(
                    funnel["booking_intent"] / convs_now * 100, 1
                )
            if duration_count > 0:
                insights["avg_duration_minutes"] = round(duration_sum / duration_count / 60, 1)

        top_dest = db.query(
            TourSearch.country,
            func.count(TourSearch.id).label("cnt"),
        ).filter(
            TourSearch.conversation_id.in_(conv_ids_now),
            TourSearch.country.isnot(None),
        ).group_by(TourSearch.country).order_by(
            func.count(TourSearch.id).desc()
        ).first()
        if top_dest:
            insights["top_destination"] = {
                "name": _COUNTRY_NAMES.get(top_dest.country,
                                           f"#{top_dest.country}"),
                "count": top_dest.cnt,
            }

        budget_row = db.query(
            func.avg(TourSearch.price_to).label("avg_budget"),
        ).filter(
            TourSearch.conversation_id.in_(conv_ids_now),
            TourSearch.price_to.isnot(None),
            TourSearch.price_to > 0,
        ).first()
        if budget_row and budget_row.avg_budget:
            insights["avg_budget"] = round(budget_row.avg_budget)

        return jsonify({
            "conversations": {"value": convs_now, "delta": _delta(convs_now, convs_prev)},
            "booking_intents": {"value": booking_now, "delta": _delta(booking_now, booking_prev)},
            "searches": {"value": searches_now},
            "avg_response_ms": {"value": round(avg_latency)},
            "funnel": funnel,
            "insights": insights,
        })


@dash_bp.route("/overview/chart", methods=["GET"])
@require_auth
def overview_chart():
    period = request.args.get("period", "30d")
    metric = request.args.get("metric", "conversations")

    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        if metric == "conversations":
            q = db.query(
                func.date(Conversation.started_at).label("date"),
                func.count(Conversation.id).label("value"),
            ).filter(Conversation.started_at >= since)
            q = _apply_aids_filter(q, aids)
            rows = q.group_by("date").order_by("date").all()

        elif metric == "messages":
            q = db.query(
                func.date(Message.created_at).label("date"),
                func.count(Message.id).label("value"),
            ).join(Conversation, Message.conversation_id == Conversation.id
            ).filter(Conversation.started_at >= since)
            q = _apply_aids_filter(q, aids)
            rows = q.group_by("date").order_by("date").all()

        elif metric == "booking_intents":
            q = db.query(
                func.date(Conversation.started_at).label("date"),
                func.count(Conversation.id).label("value"),
            ).filter(
                Conversation.started_at >= since,
                Conversation.has_booking_intent == True,  # noqa: E712
            )
            q = _apply_aids_filter(q, aids)
            rows = q.group_by("date").order_by("date").all()

        elif metric == "searches":
            q = db.query(
                func.date(TourSearch.created_at).label("date"),
                func.count(TourSearch.id).label("value"),
            ).join(Conversation, TourSearch.conversation_id == Conversation.id
            ).filter(Conversation.started_at >= since)
            q = _apply_aids_filter(q, aids)
            rows = q.group_by("date").order_by("date").all()
        else:
            rows = []

        data = [{"date": str(r.date), "value": r.value} for r in rows]

        if data:
            from datetime import date as date_type
            dates = {d["date"] for d in data}
            if len(dates) == 1:
                the_date = datetime.strptime(data[0]["date"], "%Y-%m-%d").date()
                padded = []
                for i in range(-4, 5):
                    d = (the_date + timedelta(days=i)).isoformat()
                    padded.append({"date": d, "value": next((x["value"] for x in data if x["date"] == d), 0)})
                data = padded
            elif len(dates) <= 3:
                all_dates = sorted(dates)
                first = datetime.strptime(all_dates[0], "%Y-%m-%d").date()
                last = datetime.strptime(all_dates[-1], "%Y-%m-%d").date()
                first_pad = first - timedelta(days=2)
                last_pad = last + timedelta(days=2)
                padded = []
                cur = first_pad
                while cur <= last_pad:
                    d = cur.isoformat()
                    padded.append({"date": d, "value": next((x["value"] for x in data if x["date"] == d), 0)})
                    cur += timedelta(days=1)
                data = padded

        return jsonify({"data": data})


@dash_bp.route("/overview/recent", methods=["GET"])
@require_auth
def overview_recent():
    limit = min(int(request.args.get("limit", 5)), 20)

    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        q = db.query(Conversation).order_by(desc(Conversation.started_at))
        q = _apply_aids_filter(q, aids)
        convs = q.limit(limit).all()

        result = []
        for c in convs:
            first_msg = db.query(Message).filter(
                Message.conversation_id == c.id,
                Message.role == "user",
            ).order_by(asc(Message.created_at)).first()

            result.append({
                "id": str(c.id),
                "started_at": (c.started_at.isoformat() if c.started_at else None),
                "last_active_at": (c.last_active_at.isoformat() if c.last_active_at else None),
                "message_count": c.message_count,
                "search_count": c.search_count,
                "tour_cards_shown": c.tour_cards_shown,
                "has_booking_intent": c.has_booking_intent,
                "preview": (first_msg.content[:120] + "...") if first_msg and first_msg.content and len(first_msg.content) > 120
                           else (first_msg.content if first_msg else ""),
                "status": c.status,
            })

        return jsonify({"conversations": result})


# ── Conversations ─────────────────────────────────────────────────────────────

@dash_bp.route("/conversations", methods=["GET"])
@require_auth
def conversations_list():
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(int(request.args.get("per_page", 20)), 100)
    except (ValueError, TypeError):
        per_page = 20
    period = request.args.get("period", "all")
    search_text = request.args.get("search", "").strip()
    sort_by = request.args.get("sort_by", "started_at")
    sort_dir = request.args.get("sort_dir", "desc")

    SORT_COLS = {
        "started_at": Conversation.started_at,
        "message_count": Conversation.message_count,
        "search_count": Conversation.search_count,
    }

    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        col = SORT_COLS.get(sort_by, Conversation.started_at)
        order = asc(col) if sort_dir == "asc" else desc(col)
        q = db.query(Conversation).order_by(order)
        q = _apply_aids_filter(q, aids)

        if period != "all":
            q = q.filter(Conversation.started_at >= _period_start(period))

        has_cards = request.args.get("has_cards")
        if has_cards == "true":
            q = q.filter(Conversation.tour_cards_shown > 0)
        elif has_cards == "false":
            q = q.filter(Conversation.tour_cards_shown == 0)

        has_booking = request.args.get("has_booking")
        if has_booking == "true":
            q = q.filter(Conversation.has_booking_intent == True)  # noqa: E712
        elif has_booking == "false":
            q = q.filter(Conversation.has_booking_intent == False)  # noqa: E712

        if search_text:
            search_norm = _normalize_text(search_text)
            words = [w for w in search_norm.split() if len(w) >= 2]
            if not words:
                words = [search_norm]

            msg_q = db.query(Message.conversation_id)
            for word in words:
                variants = _stem_variants(word)
                likes = [
                    func.lower(Message.content).like(f"%{v}%")
                    for v in variants
                ]
                msg_q = msg_q.filter(or_(*likes))
            msg_ids = msg_q

            all_country = set()
            all_departure = set()
            for word in words:
                all_country.update(_match_codes(_COUNTRY_NAMES, word))
                all_departure.update(_match_codes(_DEPARTURE_NAMES, word))

            tour_filters = []
            if all_country:
                tour_filters.append(TourSearch.country.in_(list(all_country)))
            if all_departure:
                tour_filters.append(TourSearch.departure.in_(list(all_departure)))
            if tour_filters:
                tour_ids = db.query(TourSearch.conversation_id).filter(or_(*tour_filters))
                combined = msg_ids.union(tour_ids).subquery()
            else:
                combined = msg_ids.subquery()
            q = q.filter(Conversation.id.in_(combined))

        total = q.count()

        gq = db.query(Conversation.id)
        gq = _apply_aids_filter(gq, aids)
        if period != "all":
            gq = gq.filter(Conversation.started_at >= _period_start(period))

        total_all = gq.count()
        total_with_cards = gq.filter(Conversation.tour_cards_shown > 0).count()
        total_with_booking = gq.filter(
            Conversation.has_booking_intent == True  # noqa: E712
        ).count()

        convs = q.offset((page - 1) * per_page).limit(per_page).all()

        items = []
        for c in convs:
            first_msg = db.query(Message).filter(
                Message.conversation_id == c.id,
                Message.role == "user",
            ).order_by(asc(Message.created_at)).first()

            last_user_msg = db.query(Message).filter(
                Message.conversation_id == c.id,
                Message.role == "user",
            ).order_by(desc(Message.created_at)).first()

            avg_lat = db.query(func.avg(Message.latency_ms)).filter(
                Message.conversation_id == c.id,
                Message.role == "assistant",
                Message.latency_ms.isnot(None),
            ).scalar()

            def _trunc(msg, limit):
                if not msg or not msg.content:
                    return ""
                return (msg.content[:limit] + "...") if len(msg.content) > limit else msg.content

            items.append({
                "id": str(c.id),
                "started_at": (c.started_at.isoformat() if c.started_at else None),
                "last_active_at": (c.last_active_at.isoformat() if c.last_active_at else None),
                "message_count": c.message_count,
                "search_count": c.search_count,
                "tour_cards_shown": c.tour_cards_shown,
                "avg_latency_ms": round(avg_lat) if avg_lat else None,
                "ip_address": c.ip_address,
                "preview": _trunc(first_msg, 120),
                "last_user_message": _trunc(last_user_msg, 80),
                "has_booking_intent": c.has_booking_intent,
                "status": c.status,
            })

        return jsonify({
            "items": items,
            "total": total,
            "total_all": total_all,
            "total_with_cards": total_with_cards,
            "total_with_booking": total_with_booking,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        })


@dash_bp.route("/conversations/<conv_id>", methods=["GET"])
@require_auth
def conversation_detail(conv_id):
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        try:
            cid = uuid.UUID(conv_id)
        except (ValueError, AttributeError):
            return jsonify({"error": "Invalid ID"}), 400

        conv = db.query(Conversation).get(cid)
        if not conv:
            return jsonify({"error": "Not found"}), 404

        aids = _assistant_ids(db)
        if aids and conv.assistant_id not in aids:
            return jsonify({"error": "Not found"}), 404

        messages = db.query(Message).filter(
            Message.conversation_id == conv.id
        ).order_by(asc(Message.created_at)).all()

        avg_lat = db.query(func.avg(Message.latency_ms)).filter(
            Message.conversation_id == conv.id,
            Message.role == "assistant",
            Message.latency_ms.isnot(None),
        ).scalar()

        return jsonify({
            "id": str(conv.id),
            "session_id": conv.session_id,
            "started_at": (conv.started_at.isoformat() if conv.started_at else None),
            "last_active_at": (conv.last_active_at.isoformat() if conv.last_active_at else None),
            "llm_provider": conv.llm_provider,
            "model": conv.model,
            "ip_address": conv.ip_address,
            "user_agent": conv.user_agent,
            "message_count": conv.message_count,
            "search_count": conv.search_count,
            "tour_cards_shown": conv.tour_cards_shown,
            "has_booking_intent": conv.has_booking_intent,
            "avg_latency_ms": round(avg_lat) if avg_lat else None,
            "status": conv.status,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "tour_cards": m.tour_cards,
                    "latency_ms": m.latency_ms,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        })


@dash_bp.route("/conversations/<conv_id>/searches", methods=["GET"])
@require_auth
def conversation_searches(conv_id):
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        try:
            cid = uuid.UUID(conv_id)
        except (ValueError, AttributeError):
            return jsonify({"error": "Invalid ID"}), 400

        aids = _assistant_ids(db)
        conv = db.query(Conversation).filter(Conversation.id == cid).first()
        if not conv or (aids and conv.assistant_id not in aids) or (not aids):
            return jsonify({"error": "Not found"}), 404

        searches = db.query(TourSearch).filter(
            TourSearch.conversation_id == cid
        ).order_by(asc(TourSearch.created_at)).all()

        return jsonify({
            "searches": [
                {
                    "id": s.id,
                    "search_type": s.search_type,
                    "departure": s.departure,
                    "country": s.country,
                    "regions": s.regions,
                    "date_from": s.date_from,
                    "date_to": s.date_to,
                    "nights_from": s.nights_from,
                    "nights_to": s.nights_to,
                    "adults": s.adults,
                    "children": s.children,
                    "stars": s.stars,
                    "meal": s.meal,
                    "price_from": s.price_from,
                    "price_to": s.price_to,
                    "hotels_found": s.hotels_found,
                    "tours_found": s.tours_found,
                    "min_price": s.min_price,
                    "created_at": s.created_at.isoformat(),
                }
                for s in searches
            ]
        })


# ── Analytics ─────────────────────────────────────────────────────────────────

@dash_bp.route("/analytics/destinations", methods=["GET"])
@require_auth
def analytics_destinations():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(
            TourSearch.country,
            func.count(TourSearch.id).label("count"),
        ).join(Conversation, TourSearch.conversation_id == Conversation.id
        ).filter(
            Conversation.started_at >= since,
            TourSearch.country.isnot(None),
        )
        q = _apply_aids_filter(q, aids)
        rows = q.group_by(TourSearch.country).order_by(desc("count")).limit(20).all()

        return jsonify({
            "data": [{"country_code": r.country, "count": r.count} for r in rows]
        })


@dash_bp.route("/analytics/departures", methods=["GET"])
@require_auth
def analytics_departures():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(
            TourSearch.departure,
            func.count(TourSearch.id).label("count"),
        ).join(Conversation, TourSearch.conversation_id == Conversation.id
        ).filter(
            Conversation.started_at >= since,
            TourSearch.departure.isnot(None),
        )
        q = _apply_aids_filter(q, aids)
        rows = q.group_by(TourSearch.departure).order_by(desc("count")).limit(20).all()

        return jsonify({
            "data": [{"departure_code": r.departure, "count": r.count} for r in rows]
        })


@dash_bp.route("/analytics/search-params", methods=["GET"])
@require_auth
def analytics_search_params():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        base = db.query(TourSearch).join(
            Conversation, TourSearch.conversation_id == Conversation.id
        ).filter(Conversation.started_at >= since)
        base = _apply_aids_filter(base, aids)

        stars_q = db.query(
            TourSearch.stars, func.count(TourSearch.id).label("count"),
        ).join(Conversation).filter(
            Conversation.started_at >= since, TourSearch.stars.isnot(None),
        )
        stars_q = _apply_aids_filter(stars_q, aids)
        stars = stars_q.group_by(TourSearch.stars).order_by(TourSearch.stars).all()

        meal_q = db.query(
            TourSearch.meal, func.count(TourSearch.id).label("count"),
        ).join(Conversation).filter(
            Conversation.started_at >= since, TourSearch.meal.isnot(None),
        )
        meal_q = _apply_aids_filter(meal_q, aids)
        meals = meal_q.group_by(TourSearch.meal).order_by(desc("count")).all()

        travelers_q = db.query(
            TourSearch.adults, TourSearch.children,
            func.count(TourSearch.id).label("count"),
        ).join(Conversation).filter(
            Conversation.started_at >= since, TourSearch.adults.isnot(None),
        )
        travelers_q = _apply_aids_filter(travelers_q, aids)
        travelers = travelers_q.group_by(
            TourSearch.adults, TourSearch.children
        ).order_by(desc("count")).all()

        budget_ranges = [
            ("до 50к", 0, 50000),
            ("50-100к", 50000, 100000),
            ("100-150к", 100000, 150000),
            ("150-200к", 150000, 200000),
            ("200-300к", 200000, 300000),
            ("300-500к", 300000, 500000),
            ("500к+", 500000, 999999999),
        ]
        budgets = []
        for label, lo, hi in budget_ranges:
            bq = db.query(func.count(TourSearch.id)).join(Conversation).filter(
                Conversation.started_at >= since,
                TourSearch.price_to.isnot(None),
                TourSearch.price_to >= lo,
                TourSearch.price_to < hi,
            )
            bq = _apply_aids_filter(bq, aids)
            budgets.append({"range": label, "count": bq.scalar() or 0})

        combo_q = db.query(
            TourSearch.stars, TourSearch.meal,
            func.count(TourSearch.id).label("count"),
        ).join(Conversation).filter(
            Conversation.started_at >= since,
            TourSearch.stars.isnot(None),
            TourSearch.meal.isnot(None),
        )
        combo_q = _apply_aids_filter(combo_q, aids)
        combos = combo_q.group_by(TourSearch.stars, TourSearch.meal).all()

        avg_budget_q = db.query(
            func.avg(TourSearch.price_to).label("avg_budget"),
            func.avg(TourSearch.min_price).label("avg_found"),
        ).join(Conversation).filter(
            Conversation.started_at >= since,
            TourSearch.price_to > 0,
            TourSearch.min_price > 0,
        )
        avg_budget_q = _apply_aids_filter(avg_budget_q, aids)
        bp = avg_budget_q.first()

        return jsonify({
            "stars": [{"stars": r.stars, "count": r.count} for r in stars],
            "meals": [{"meal": r.meal, "count": r.count} for r in meals],
            "stars_meal_combos": [
                {"stars": r.stars, "meal": r.meal, "count": r.count}
                for r in combos
            ],
            "budget_vs_price": {
                "avg_budget": round(bp.avg_budget) if bp and bp.avg_budget else None,
                "avg_found": round(bp.avg_found) if bp and bp.avg_found else None,
            },
            "travelers": [
                {"adults": r.adults, "children": r.children or 0, "count": r.count}
                for r in travelers
            ],
            "budgets": budgets,
        })


@dash_bp.route("/analytics/response-times", methods=["GET"])
@require_auth
def analytics_response_times():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(
            func.date(Message.created_at).label("date"),
            Message.latency_ms,
        ).join(Conversation, Message.conversation_id == Conversation.id
        ).filter(
            Conversation.started_at >= since,
            Message.role == "assistant",
            Message.latency_ms.isnot(None),
        )
        q = _apply_aids_filter(q, aids)
        raw = q.order_by(func.date(Message.created_at)).all()

        from collections import defaultdict
        by_date = defaultdict(list)
        for r in raw:
            by_date[str(r.date)].append(r.latency_ms)

        def _percentile(vals, p):
            s = sorted(vals)
            idx = int(len(s) * p / 100)
            return round(s[min(idx, len(s) - 1)])

        data = []
        for date in sorted(by_date):
            vals = by_date[date]
            data.append({
                "date": date,
                "avg_ms": round(sum(vals) / len(vals)),
                "p50_ms": _percentile(vals, 50),
                "p90_ms": _percentile(vals, 90),
            })

        return jsonify({"data": data})


@dash_bp.route("/analytics/search-types", methods=["GET"])
@require_auth
def analytics_search_types():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(
            TourSearch.search_type,
            func.count(TourSearch.id).label("count"),
        ).join(Conversation, TourSearch.conversation_id == Conversation.id
        ).filter(Conversation.started_at >= since)
        q = _apply_aids_filter(q, aids)
        rows = q.group_by(TourSearch.search_type).all()

        nights_q = db.query(
            TourSearch.nights_from, TourSearch.nights_to,
        ).join(Conversation).filter(
            Conversation.started_at >= since,
            TourSearch.nights_from.isnot(None),
        )
        nights_q = _apply_aids_filter(nights_q, aids)
        nights_rows = nights_q.all()
        if nights_rows:
            total_n = sum(
                (r.nights_from + (r.nights_to if r.nights_to is not None else r.nights_from)) / 2
                for r in nights_rows
            )
            avg_nights = round(total_n / len(nights_rows))
        else:
            avg_nights = None

        budget_q = db.query(
            func.avg(TourSearch.price_to).label("avg_budget"),
        ).join(Conversation).filter(
            Conversation.started_at >= since,
            TourSearch.price_to.isnot(None),
            TourSearch.price_to > 0,
        )
        budget_q = _apply_aids_filter(budget_q, aids)
        budget_row = budget_q.first()
        avg_budget = (
            round(budget_row.avg_budget) if budget_row and budget_row.avg_budget
            else None
        )

        return jsonify({
            "types": [{"type": r.search_type, "count": r.count} for r in rows],
            "avg_nights": avg_nights,
            "avg_budget": avg_budget,
        })


@dash_bp.route("/analytics/travel-dates", methods=["GET"])
@require_auth
def analytics_travel_dates():
    """Aggregate requested travel months from tour_searches.date_from."""
    period = request.args.get("period", "30d")
    MONTH_NAMES = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
        5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
    }
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(TourSearch.date_from).join(
            Conversation, TourSearch.conversation_id == Conversation.id
        ).filter(
            Conversation.started_at >= since,
            TourSearch.date_from.isnot(None),
            TourSearch.date_from != "",
        )
        q = _apply_aids_filter(q, aids)

        counts = {}
        for (date_str,) in q.all():
            try:
                parts = date_str.strip().split(".")
                if len(parts) == 3:
                    month = int(parts[1])
                    if 1 <= month <= 12:
                        counts[month] = counts.get(month, 0) + 1
            except (ValueError, IndexError):
                continue

        data = sorted(
            [{"month": MONTH_NAMES[m], "month_num": m, "count": c} for m, c in counts.items()],
            key=lambda x: x["month_num"],
        )

        return jsonify({"data": data})


@dash_bp.route("/analytics/business-metrics", methods=["GET"])
@require_auth
def analytics_business_metrics():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(Conversation).filter(Conversation.started_at >= since)
        q = _apply_aids_filter(q, aids)

        total_convs = q.count()
        if total_convs == 0:
            return jsonify({
                "inquiries_handled": 0, "tours_offered": 0,
                "potential_leads": 0, "after_hours_pct": 0,
                "after_hours_count": 0,
                "booking_intents": 0, "booking_intent_pct": 0,
                "engagement_pct": 0, "engaged_count": 0,
                "total_conversations": 0,
            })

        tours_offered = db.query(func.sum(Conversation.tour_cards_shown)).filter(
            Conversation.started_at >= since,
        )
        tours_offered = _apply_aids_filter(tours_offered, aids)
        tours_offered = tours_offered.scalar() or 0

        conv_ids = [c.id for c in q.with_entities(Conversation.id).all()]

        user_msg_counts = dict(
            db.query(Message.conversation_id, func.count(Message.id))
            .filter(Message.conversation_id.in_(conv_ids), Message.role == "user")
            .group_by(Message.conversation_id).all()
        )

        convs_data = q.with_entities(
            Conversation.id, Conversation.started_at,
            Conversation.tour_cards_shown,
        ).all()

        engaged = 0
        potential_leads = 0
        after_hours = 0

        for c in convs_data:
            umc = user_msg_counts.get(c.id, 0)
            tc = c.tour_cards_shown or 0

            if umc >= 2:
                engaged += 1
            if umc >= 4 and tc > 0:
                potential_leads += 1

            if c.started_at:
                h_utc = c.started_at.hour if hasattr(c.started_at, "hour") else 12
                h_msk = (h_utc + 3) % 24
                if h_msk < 9 or h_msk >= 18:
                    after_hours += 1

        booking_count = q.filter(
            Conversation.has_booking_intent == True  # noqa: E712
        ).count()

        return jsonify({
            "inquiries_handled": total_convs,
            "tours_offered": tours_offered,
            "potential_leads": potential_leads,
            "after_hours_pct": round(after_hours / total_convs * 100) if total_convs else 0,
            "after_hours_count": after_hours,
            "booking_intents": booking_count,
            "booking_intent_pct": round(booking_count / total_convs * 100, 1) if total_convs else 0,
            "engagement_pct": round(engaged / total_convs * 100) if total_convs else 0,
            "engaged_count": engaged,
            "total_conversations": total_convs,
        })


@dash_bp.route("/analytics/performance", methods=["GET"])
@require_auth
def analytics_performance():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(Conversation).filter(Conversation.started_at >= since)
        q = _apply_aids_filter(q, aids)

        total_convs = q.count()
        agg = q.with_entities(
            func.sum(Conversation.message_count).label("total_msgs"),
            func.sum(Conversation.search_count).label("total_searches"),
        ).first()

        avg_msgs = round(agg.total_msgs / total_convs, 1) if total_convs and agg.total_msgs else 0
        avg_searches = round(agg.total_searches / total_convs, 1) if total_convs and agg.total_searches else 0

        conv_ids = [c.id for c in q.with_entities(Conversation.id).all()]

        avg_dur = 0
        empty_search_pct = 0
        retry_pct = 0
        no_result_pct = 0

        if conv_ids:
            convs_data = q.with_entities(
                Conversation.started_at, Conversation.last_active_at,
                Conversation.search_count, Conversation.tour_cards_shown,
            ).all()

            dur_sum, dur_cnt = 0, 0
            retry_cnt = 0
            no_result_cnt = 0
            searched_cnt = 0
            for c in convs_data:
                if c.started_at and c.last_active_at:
                    d = (c.last_active_at - c.started_at).total_seconds()
                    if d > 0:
                        dur_sum += d
                        dur_cnt += 1
                sc = c.search_count or 0
                tc = c.tour_cards_shown or 0
                if sc > 0:
                    searched_cnt += 1
                if sc >= 2:
                    retry_cnt += 1
                if sc > 0 and tc == 0:
                    no_result_cnt += 1

            if dur_cnt:
                avg_dur = round(dur_sum / dur_cnt / 60, 1)
            if searched_cnt:
                no_result_pct = round(no_result_cnt / searched_cnt * 100)
            if total_convs:
                retry_pct = round(retry_cnt / total_convs * 100)

            searches = db.query(TourSearch).filter(
                TourSearch.conversation_id.in_(conv_ids)
            ).all()
            empty = sum(1 for s in searches if (s.tours_found or 0) == 0)
            if searches:
                empty_search_pct = round(empty / len(searches) * 100)

        return jsonify({
            "avg_messages_per_conversation": avg_msgs,
            "avg_searches_per_conversation": avg_searches,
            "total_conversations": total_convs,
            "avg_duration_minutes": avg_dur,
            "empty_search_pct": empty_search_pct,
            "retry_pct": retry_pct,
            "no_result_pct": no_result_pct,
        })


# ── Demand Analytics ──────────────────────────────────────────────────────────

@dash_bp.route("/analytics/demand", methods=["GET"])
@require_auth
def analytics_demand():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        def _base_q():
            q = db.query(TourSearch).join(
                Conversation, TourSearch.conversation_id == Conversation.id
            ).filter(Conversation.started_at >= since)
            q = _apply_aids_filter(q, aids)
            return q

        nights_dist = {}
        for s in _base_q().filter(TourSearch.nights_from.isnot(None)).all():
            nf = s.nights_from if s.nights_from is not None else 7
            nt = s.nights_to if s.nights_to is not None else nf
            avg_n = round((nf + nt) / 2)
            nights_dist[avg_n] = nights_dist.get(avg_n, 0) + 1
        nights_data = sorted(
            [{"nights": k, "count": v} for k, v in nights_dist.items()],
            key=lambda x: x["nights"],
        )

        group_sizes = {}
        for s in _base_q().filter(TourSearch.adults.isnot(None)).all():
            a = s.adults or 2
            c = s.children or 0
            label = f"{a} взр." + (f" + {c} дет." if c else "")
            group_sizes[label] = group_sizes.get(label, 0) + 1
        group_data = sorted(
            [{"group": k, "count": v} for k, v in group_sizes.items()],
            key=lambda x: -x["count"],
        )

        return jsonify({
            "nights_distribution": nights_data,
            "group_sizes": group_data,
        })


@dash_bp.route("/analytics/operators", methods=["GET"])
@require_auth
def analytics_operators():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(Message).join(
            Conversation, Message.conversation_id == Conversation.id
        ).filter(
            Conversation.started_at >= since,
            Message.tour_cards.isnot(None),
        )
        q = _apply_aids_filter(q, aids)

        operators = {}
        total_cards = 0
        for msg in q.all():
            cards = msg.tour_cards if isinstance(msg.tour_cards, list) else []
            for card in cards:
                op = card.get("operator", "Неизвестный")
                if op:
                    operators[op] = operators.get(op, 0) + 1
                    total_cards += 1

        op_data = sorted(
            [{"operator": k, "count": v, "share": round(v / total_cards * 100, 1) if total_cards else 0}
             for k, v in operators.items()],
            key=lambda x: -x["count"],
        )[:15]

        return jsonify({"operators": op_data, "total_cards": total_cards})


@dash_bp.route("/analytics/activity", methods=["GET"])
@require_auth
def analytics_activity():
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(Conversation.started_at).filter(
            Conversation.started_at >= since
        )
        q = _apply_aids_filter(q, aids)

        heatmap = [[0] * 24 for _ in range(7)]
        day_counts = [0] * 7
        hour_counts = [0] * 24

        for row in q.all():
            ts = row.started_at
            if ts:
                h_utc = ts.hour if hasattr(ts, 'hour') else 12
                h_msk = (h_utc + 3) % 24
                dow_shift = 1 if (h_utc + 3) >= 24 else 0
                dow = (ts.weekday() + dow_shift) % 7
                heatmap[dow][h_msk] += 1
                day_counts[dow] += 1
                hour_counts[h_msk] += 1

        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        return jsonify({
            "heatmap": heatmap,
            "day_names": day_names,
            "day_distribution": [{"day": day_names[i], "count": day_counts[i]} for i in range(7)],
            "hour_distribution": [{"hour": i, "count": hour_counts[i]} for i in range(24)],
        })


# ── Widget ────────────────────────────────────────────────────────────────────

_WIDGET_DEFAULTS = {
    "welcome_message": "\U0001f44b Здравствуйте! Я — ИИ-ассистент туристического агентства.\n\nЯ помогу вам:\n• \U0001f50d Подобрать тур по вашим параметрам\n• \U0001f525 Найти горящие предложения\n• \u2753 Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?",
    "primary_color": "#E30613",
    "position": "bottom-right",
    "title": "AI Ассистент",
    "subtitle": "Турагентство",
    "logo_url": None,
}

_LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logos")
_ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp"}
_MAX_LOGO_SIZE = 2 * 1024 * 1024


@dash_bp.route("/widget/config", methods=["GET"])
@require_auth
def widget_config_get():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        assistant = db.query(Assistant).filter(
            Assistant.company_id == g.company_id, Assistant.is_active.is_(True)
        ).first()
        if not assistant:
            return jsonify({"error": "No active assistant"}), 404

        cfg = assistant.widget_config or {}
        return jsonify({
            "assistant_id": str(assistant.id),
            "welcome_message": cfg.get("welcome_message") or _WIDGET_DEFAULTS["welcome_message"],
            "position": cfg.get("position") or _WIDGET_DEFAULTS["position"],
            "primary_color": cfg.get("primary_color") or _WIDGET_DEFAULTS["primary_color"],
            "title": cfg.get("title") or _WIDGET_DEFAULTS["title"],
            "subtitle": cfg.get("subtitle") or _WIDGET_DEFAULTS["subtitle"],
            "logo_url": cfg.get("logo_url") or None,
            "active_preset": cfg.get("active_preset") or None,
        })


@dash_bp.route("/widget/config", methods=["PUT"])
@require_auth
def widget_config_update():
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        assistant = db.query(Assistant).filter(
            Assistant.company_id == g.company_id, Assistant.is_active.is_(True)
        ).first()
        if not assistant:
            return jsonify({"error": "No active assistant"}), 404

        cfg = dict(assistant.widget_config or {})
        for key in ("welcome_message", "position", "primary_color", "title", "subtitle", "logo_url", "active_preset"):
            if key in data:
                cfg[key] = data[key]
        assistant.widget_config = cfg

        return jsonify({"status": "ok"})


@dash_bp.route("/widget/embed-code", methods=["GET"])
@require_auth
def widget_embed_code():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        assistant = db.query(Assistant).filter(
            Assistant.company_id == g.company_id, Assistant.is_active.is_(True)
        ).first()
        if not assistant:
            return jsonify({"error": "No active assistant"}), 404

        host = request.host_url.rstrip("/")
        code = (
            f'<script src="{host}/widget.js" '
            f'data-assistant-id="{assistant.id}"></script>'
        )
        return jsonify({"embed_code": code, "assistant_id": str(assistant.id)})


@dash_bp.route("/widget/logo", methods=["POST"])
@require_auth
def widget_logo_upload():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        assistant = db.query(Assistant).filter(
            Assistant.company_id == g.company_id, Assistant.is_active.is_(True)
        ).first()
        if not assistant:
            return jsonify({"error": "No active assistant"}), 404

        if "logo" not in request.files:
            return jsonify({"error": "Файл не предоставлен"}), 400

        file = request.files["logo"]
        if not file.filename:
            return jsonify({"error": "Пустое имя файла"}), 400

        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in _ALLOWED_LOGO_EXT:
            return jsonify({"error": f"Допустимые форматы: {', '.join(_ALLOWED_LOGO_EXT)}"}), 400

        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > _MAX_LOGO_SIZE:
            return jsonify({"error": "Максимальный размер файла — 2 МБ"}), 400

        header = file.read(16)
        file.seek(0)
        _MAGIC = {
            b"\x89PNG": "png",
            b"\xff\xd8\xff": "jpg",
            b"RIFF": "webp",
        }
        detected = None
        for magic, fmt in _MAGIC.items():
            if header.startswith(magic):
                detected = fmt
                break
        if detected is None or (detected == "webp" and b"WEBP" not in header[:16]):
            return jsonify({"error": "Файл не является допустимым изображением"}), 400

        os.makedirs(_LOGO_DIR, exist_ok=True)

        for old in os.listdir(_LOGO_DIR):
            if old.startswith(str(assistant.id)):
                os.remove(os.path.join(_LOGO_DIR, old))

        from werkzeug.utils import secure_filename as _sf
        safe_ext = _sf(ext) or "png"
        filename = f"{assistant.id}.{safe_ext}"
        filepath = os.path.join(_LOGO_DIR, filename)
        if not os.path.abspath(filepath).startswith(os.path.abspath(_LOGO_DIR)):
            return jsonify({"error": "Invalid path"}), 400
        file.save(filepath)

        logo_url = f"/static/logos/{filename}"
        cfg = dict(assistant.widget_config or {})
        cfg["logo_url"] = logo_url
        assistant.widget_config = cfg

        return jsonify({"status": "ok", "logo_url": logo_url})


@dash_bp.route("/widget/logo", methods=["DELETE"])
@require_auth
def widget_logo_delete():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        assistant = db.query(Assistant).filter(
            Assistant.company_id == g.company_id, Assistant.is_active.is_(True)
        ).first()
        if not assistant:
            return jsonify({"error": "No active assistant"}), 404

        for old in os.listdir(_LOGO_DIR) if os.path.isdir(_LOGO_DIR) else []:
            if old.startswith(str(assistant.id)):
                os.remove(os.path.join(_LOGO_DIR, old))

        cfg = dict(assistant.widget_config or {})
        cfg.pop("logo_url", None)
        cfg.pop("active_preset", None)
        assistant.widget_config = cfg

        return jsonify({"status": "ok"})


# ── System ────────────────────────────────────────────────────────────────────

@dash_bp.route("/system/health", methods=["GET"])
@require_auth
def system_health():
    checks = {
        "postgres": "ok" if db_check_health() else "unavailable",
        "redis": "ok" if cache_check_health() else "unavailable",
    }
    return jsonify(checks)


@dash_bp.route("/assistants", methods=["GET"])
@require_auth
def assistants_list():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        rows = db.query(Assistant).filter(Assistant.company_id == g.company_id).all()
        return jsonify({
            "assistants": [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "llm_provider": a.llm_provider,
                    "llm_model": a.llm_model,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat(),
                }
                for a in rows
            ]
        })


@dash_bp.route("/assistants/<assistant_id>", methods=["PUT"])
@require_auth
def assistant_update(assistant_id):
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        a = db.query(Assistant).get(assistant_id)
        if not a or a.company_id != g.company_id:
            return jsonify({"error": "Not found"}), 404

        for field in ("name", "is_active", "system_prompt", "faq_content"):
            if field in data:
                setattr(a, field, data[field])

        return jsonify({"status": "ok"})


# ── Account ───────────────────────────────────────────────────────────────────

@dash_bp.route("/account", methods=["GET"])
@require_auth
def account_get():
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503
        user = db.query(User).get(g.current_user_id)
        company = db.query(Company).get(g.company_id)
        return jsonify({
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "role": user.role,
            },
            "company": {
                "id": str(company.id),
                "name": company.name,
                "slug": company.slug,
                "logo_url": company.logo_url,
            } if company else None,
        })


@dash_bp.route("/account/password", methods=["PUT"])
@require_auth
def account_change_password():
    data = request.get_json(silent=True) or {}
    old_pw = data.get("old_password", "")
    new_pw = data.get("new_password", "")
    if not old_pw or not new_pw or len(new_pw) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503
        user = db.query(User).get(g.current_user_id)
        if not check_password(old_pw, user.password_hash):
            return jsonify({"error": "Old password is incorrect"}), 400
        user.password_hash = hash_password(new_pw)
        return jsonify({"status": "ok"})


@dash_bp.route("/account/profile", methods=["PUT"])
@require_auth
def account_update_profile():
    data = request.get_json(silent=True) or {}
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503
        user = db.query(User).get(g.current_user_id)
        if "name" in data:
            user.name = data["name"]
        company = db.query(Company).get(g.company_id)
        if company and "company_name" in data:
            company.name = data["company_name"]
        return jsonify({"status": "ok"})


# ── Reset Data ────────────────────────────────────────────────────────────────

@dash_bp.route("/account/reset-data", methods=["POST"])
@require_auth
def account_reset_data():
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not password:
        return jsonify({"error": "Необходимо указать пароль"}), 400

    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        user = db.query(User).get(g.current_user_id)
        if not check_password(password, user.password_hash):
            return jsonify({"error": "Неверный пароль"}), 403

        aids = [
            a.id for a in db.query(Assistant.id).filter(
                Assistant.company_id == g.company_id
            ).all()
        ]

        if aids:
            conv_ids = [
                c.id for c in db.query(Conversation.id).filter(
                    Conversation.assistant_id.in_(aids)
                ).all()
            ]
            if conv_ids:
                db.query(Message).filter(
                    Message.conversation_id.in_(conv_ids)
                ).delete(synchronize_session=False)
                db.query(TourSearch).filter(
                    TourSearch.conversation_id.in_(conv_ids)
                ).delete(synchronize_session=False)
                db.query(ApiCall).filter(
                    ApiCall.conversation_id.in_(conv_ids)
                ).delete(synchronize_session=False)
            db.query(Conversation).filter(
                Conversation.assistant_id.in_(aids)
            ).delete(synchronize_session=False)

        return jsonify({"status": "ok", "message": "Все данные сброшены"})


# ── CSV Export ────────────────────────────────────────────────────────────────

@dash_bp.route("/export/conversations", methods=["GET"])
@require_auth
def export_conversations():
    import csv
    import io
    period = request.args.get("period", "30d")
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        aids = _assistant_ids(db)
        since = _period_start(period)

        q = db.query(Conversation).filter(Conversation.started_at >= since)
        q = _apply_aids_filter(q, aids)
        convs = q.order_by(Conversation.started_at.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID", "Дата", "Кол-во сообщений", "Кол-во поисков",
            "Показано карточек", "Город отправления", "Страна",
        ])
        for c in convs:
            first_search = db.query(TourSearch).filter(
                TourSearch.conversation_id == c.id
            ).first()
            writer.writerow([
                str(c.id),
                c.started_at.strftime("%Y-%m-%d %H:%M") if c.started_at else "",
                c.message_count or 0,
                c.search_count or 0,
                c.tour_cards_shown or 0,
                first_search.departure if first_search else "",
                first_search.country if first_search else "",
            ])

        resp = make_response(output.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=conversations.csv"
        return resp


# ── Daily stats aggregation ──────────────────────────────────────────────────

@dash_bp.route("/aggregate", methods=["POST"])
@require_auth
def aggregate_daily():
    """Aggregate stats for the previous day (call via cron or manually)."""
    with get_db() as db:
        if db is None:
            return jsonify({"error": "Database unavailable"}), 503

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        date_str = yesterday.isoformat()

        existing = db.query(DailyStat).filter(DailyStat.date == date_str).first()
        if existing:
            return jsonify({"status": "already_exists", "date": date_str})

        day_start = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        convs = db.query(func.count(Conversation.id)).filter(
            Conversation.started_at >= day_start, Conversation.started_at < day_end,
        ).scalar() or 0

        msgs = db.query(func.count(Message.id)).join(Conversation).filter(
            Conversation.started_at >= day_start, Conversation.started_at < day_end,
        ).scalar() or 0

        searches = db.query(func.count(TourSearch.id)).join(Conversation).filter(
            Conversation.started_at >= day_start, Conversation.started_at < day_end,
        ).scalar() or 0

        avg_ms = db.query(func.avg(Message.latency_ms)).join(Conversation).filter(
            Conversation.started_at >= day_start, Conversation.started_at < day_end,
            Message.role == "assistant", Message.latency_ms.isnot(None),
        ).scalar() or 0

        unique_ips = db.query(func.count(distinct(Conversation.ip_address))).filter(
            Conversation.started_at >= day_start, Conversation.started_at < day_end,
        ).scalar() or 0

        tours_shown = db.query(func.sum(Conversation.tour_cards_shown)).filter(
            Conversation.started_at >= day_start, Conversation.started_at < day_end,
        ).scalar() or 0

        stat = DailyStat(
            date=date_str,
            conversations_total=convs,
            messages_total=msgs,
            searches_total=searches,
            tours_shown=tours_shown,
            avg_response_ms=round(avg_ms),
            unique_ips=unique_ips,
        )
        db.add(stat)
        return jsonify({"status": "ok", "date": date_str})
