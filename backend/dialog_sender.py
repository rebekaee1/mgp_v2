from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import func, select

from config import settings
from database import get_db, is_db_available
from models import ApiCall, Assistant, Conversation, Message, RuntimeEventOutbox, TourSearch

logger = logging.getLogger("mgp_bot.dialog_sender")

_CONTRACT_VERSION = "2026-03-09"
_EVENT_TYPE = "conversation_snapshot"
_STATUSES_PENDING = {"pending", "retrying"}
_PAYLOAD_TARGET_BYTES = 64 * 1024
_MAX_API_CALLS = 20
_MAX_API_CALLS_AGGRESSIVE = 8
_MAX_TOUR_CARDS = 10
_MAX_TOUR_CARDS_AGGRESSIVE = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _truncate_text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        text = _json_dumps(value)
    else:
        text = str(value)
    if len(text) <= limit:
        return text
    suffix = f"... [truncated {len(text) - limit} chars]"
    keep = max(0, limit - len(suffix))
    return text[:keep] + suffix


def _payload_size_bytes(payload: dict[str, Any]) -> int:
    return len(_json_dumps(payload).encode("utf-8"))


def _compact_message_content(content: Any, role: Optional[str], level: int) -> Optional[str]:
    if role == "tool":
        if level >= 3:
            return "[tool output omitted]"
        limit = 2000 if level == 0 else 800 if level == 1 else 300
        return _truncate_text(content, limit)

    if level >= 3:
        limit = 600
    elif level == 2:
        limit = 1500
    elif level == 1:
        limit = 2500
    else:
        limit = 4000
    return _truncate_text(content, limit)


def _compact_tool_call(tool_call: Any, level: int) -> Optional[dict[str, Any]]:
    if not isinstance(tool_call, dict):
        return None
    function = dict(tool_call.get("function") or {})
    arguments = function.get("arguments")
    if isinstance(arguments, (dict, list)):
        arguments = _json_dumps(arguments)
    elif arguments is None:
        arguments = "{}"
    else:
        arguments = str(arguments)

    arg_limit = 1200 if level == 0 else 600 if level == 1 else 250 if level == 2 else 120
    return {
        "id": str(tool_call.get("id") or tool_call.get("tool_call_id") or "")[:128] or None,
        "type": str(tool_call.get("type") or "function"),
        "function": {
            "name": str(function.get("name") or tool_call.get("name") or "unknown_function")[:128],
            "arguments": _truncate_text(arguments, arg_limit) or "{}",
        },
    }


def _normalize_tool_calls(tool_calls: Any) -> list[dict]:
    raw = _safe_json(tool_calls)
    if isinstance(raw, list):
        return [item for item in (_compact_tool_call(call, 0) for call in raw) if item]
    if isinstance(raw, dict):
        if isinstance(raw.get("calls"), list):
            return [item for item in (_compact_tool_call(call, 0) for call in raw["calls"]) if item]
        compacted = _compact_tool_call(raw, 0)
        return [compacted] if compacted else []
    return []


def _normalize_tour_card(card: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(card or {})
    hotel_image = normalized.get("hotel_image") or normalized.get("image_url")
    room = normalized.get("room") or normalized.get("room_type")
    flydate = normalized.get("flydate") or normalized.get("date")
    if not flydate:
        flydate = normalized.get("date_from")
    normalized["hotel_image"] = hotel_image
    normalized["room"] = room
    normalized["date"] = flydate
    normalized.setdefault("flydate", flydate)
    normalized.setdefault("operator", normalized.get("operator") or "")
    return normalized


def _normalize_tour_cards(tour_cards: Any) -> list[dict]:
    raw = _safe_json(tour_cards)
    if not isinstance(raw, list):
        return []
    return [_normalize_tour_card(item) for item in raw if isinstance(item, dict)]


def _compact_tour_cards(tour_cards: Any, level: int) -> list[dict]:
    limit = _MAX_TOUR_CARDS if level <= 1 else _MAX_TOUR_CARDS_AGGRESSIVE
    return _normalize_tour_cards(tour_cards)[:limit]


def _runtime_reporting_config(runtime_metadata: dict | None) -> dict[str, Any]:
    runtime_metadata = dict(runtime_metadata or {})
    reporting = runtime_metadata.get("reporting")
    if isinstance(reporting, dict):
        auth = dict(reporting.get("auth") or {})
        return {
            "mode": str(reporting.get("mode") or "none").strip() or "none",
            "contract_version": str(reporting.get("contract_version") or _CONTRACT_VERSION).strip() or _CONTRACT_VERSION,
            "endpoint_url": str(reporting.get("endpoint_url") or "").strip(),
            "auth_header_name": str(auth.get("header_name") or "X-MGP-Service-Token").strip() or "X-MGP-Service-Token",
            "auth_secret": str(auth.get("secret") or "").strip(),
        }

    fallback_url = str(settings.runtime_report_url or "").strip()
    fallback_secret = str(settings.runtime_report_token or "").strip()
    return {
        "mode": "batch_snapshot" if fallback_url and fallback_secret else "none",
        "contract_version": _CONTRACT_VERSION,
        "endpoint_url": fallback_url,
        "auth_header_name": "X-MGP-Service-Token",
        "auth_secret": fallback_secret,
    }


def _to_iso_or_none(value: Optional[datetime]) -> Optional[str]:
    return _iso(value) if value is not None else None


def _api_call_external_id(api_call_id: int) -> str:
    return f"api:{api_call_id}"


def _serialize_message(item: Message) -> dict[str, Any]:
    return {
        "id": item.id,
        "remote_id": item.id,
        "role": item.role,
        "content": _compact_message_content(item.content, item.role, 0),
        "tool_call_id": item.tool_call_id,
        "tool_calls": _normalize_tool_calls(item.tool_calls),
        "tour_cards": _compact_tour_cards(item.tour_cards, 0),
        "latency_ms": item.latency_ms,
        "tokens_prompt": item.tokens_prompt,
        "tokens_completion": item.tokens_completion,
        "created_at": _iso(item.created_at),
    }


def _serialize_tour_search(item: TourSearch) -> dict[str, Any]:
    return {
        "id": item.id,
        "remote_id": item.id,
        "requestid": item.requestid,
        "search_type": item.search_type,
        "departure": item.departure,
        "country": item.country,
        "regions": item.regions,
        "date_from": item.date_from,
        "date_to": item.date_to,
        "nights_from": item.nights_from,
        "nights_to": item.nights_to,
        "adults": item.adults,
        "children": item.children,
        "stars": item.stars,
        "meal": item.meal,
        "price_from": item.price_from,
        "price_to": item.price_to,
        "hotels_found": item.hotels_found,
        "tours_found": item.tours_found,
        "min_price": item.min_price,
        "duration_ms": item.duration_ms,
        "created_at": _iso(item.created_at),
    }


def _serialize_api_call(item: ApiCall) -> dict[str, Any]:
    return {
        "id": _api_call_external_id(item.id),
        "external_id": _api_call_external_id(item.id),
        "service": item.service,
        "endpoint": _truncate_text(item.endpoint, 160),
        "response_code": item.response_code,
        "response_bytes": item.response_bytes,
        "tokens_used": item.tokens_used,
        "latency_ms": item.latency_ms,
        "error": _truncate_text(item.error, 300),
        "created_at": _iso(item.created_at),
    }


def _compact_message_payload(message: dict[str, Any], level: int) -> dict[str, Any]:
    compacted = dict(message or {})
    compacted["content"] = _compact_message_content(compacted.get("content"), compacted.get("role"), level)
    raw_calls = compacted.get("tool_calls")
    if isinstance(raw_calls, list):
        compacted["tool_calls"] = [item for item in (_compact_tool_call(call, level) for call in raw_calls) if item]
    else:
        compacted["tool_calls"] = []
    compacted["tour_cards"] = _compact_tour_cards(compacted.get("tour_cards"), level)
    compacted.pop("conversation_id", None)
    return compacted


def _compact_api_call_payload(api_call: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(api_call or {})
    compacted["endpoint"] = _truncate_text(compacted.get("endpoint"), 160)
    compacted["error"] = _truncate_text(compacted.get("error"), 300)
    compacted.pop("conversation_id", None)
    return compacted


def _compact_snapshot_payload(payload: dict[str, Any], *, level: int = 0) -> dict[str, Any]:
    compacted = dict(payload or {})
    compacted["messages"] = [
        _compact_message_payload(message, level)
        for message in list(compacted.get("messages") or [])
        if isinstance(message, dict)
    ]
    compacted["tour_searches"] = [
        {key: value for key, value in dict(search).items() if key != "conversation_id"}
        for search in list(compacted.get("tour_searches") or [])
        if isinstance(search, dict)
    ]
    api_limit = _MAX_API_CALLS if level <= 1 else _MAX_API_CALLS_AGGRESSIVE
    compacted["api_calls"] = [
        _compact_api_call_payload(api_call)
        for api_call in list(compacted.get("api_calls") or [])[-api_limit:]
        if isinstance(api_call, dict)
    ]
    return compacted


def _fit_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(payload or {})
    initial_size = _payload_size_bytes(current)
    if initial_size <= _PAYLOAD_TARGET_BYTES:
        return current

    for level in (1, 2, 3):
        current = _compact_snapshot_payload(current, level=level)
        if _payload_size_bytes(current) <= _PAYLOAD_TARGET_BYTES:
            logger.info(
                "Dialog snapshot compacted level=%s size=%s->%s bytes",
                level,
                initial_size,
                _payload_size_bytes(current),
            )
            return current

    current = dict(current)
    current["api_calls"] = []
    final_size = _payload_size_bytes(current)
    logger.warning(
        "Dialog snapshot compacted aggressively size=%s->%s bytes",
        initial_size,
        final_size,
    )
    return current


def _build_snapshot_payload(
    assistant: Assistant,
    conversation: Conversation,
    messages: list[Message],
    tour_searches: list[TourSearch],
    api_calls: list[ApiCall],
) -> dict[str, Any]:
    occurred_at = conversation.last_active_at or conversation.started_at or _utcnow()
    payload = {
        "contract_version": _CONTRACT_VERSION,
        "event_type": _EVENT_TYPE,
        "assistant_id": str(assistant.id),
        "conversation_id": str(conversation.id),
        "occurred_at": _iso(occurred_at),
        "conversation": {
            "id": str(conversation.id),
            "assistant_id": str(assistant.id),
            "session_id": conversation.session_id,
            "llm_provider": conversation.llm_provider,
            "model": conversation.model,
            "ip_address": conversation.ip_address,
            "user_agent": conversation.user_agent,
            "message_count": conversation.message_count,
            "search_count": conversation.search_count,
            "tour_cards_shown": conversation.tour_cards_shown,
            "has_booking_intent": bool(conversation.has_booking_intent),
            "status": conversation.status,
            "started_at": _iso(conversation.started_at),
            "last_active_at": _iso(conversation.last_active_at),
        },
        "messages": [_serialize_message(item) for item in messages],
        "tour_searches": [_serialize_tour_search(item) for item in tour_searches],
        "api_calls": [_serialize_api_call(item) for item in api_calls],
    }
    return _fit_snapshot_payload(payload)


def enqueue_conversation_snapshot(db, conversation_id: uuid.UUID, assistant_id: uuid.UUID) -> Optional[str]:
    assistant = db.get(Assistant, assistant_id)
    conversation = db.get(Conversation, conversation_id)
    if assistant is None or conversation is None:
        return None

    reporting = _runtime_reporting_config(assistant.runtime_metadata)
    if reporting.get("mode") != "batch_snapshot":
        logger.debug(
            "Dialog sender skipped conversation=%s assistant=%s reason=reporting_disabled",
            conversation_id, assistant_id,
        )
        return None

    messages = db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    tour_searches = db.execute(
        select(TourSearch).where(TourSearch.conversation_id == conversation_id).order_by(TourSearch.created_at.asc(), TourSearch.id.asc())
    ).scalars().all()
    api_calls = db.execute(
        select(ApiCall).where(ApiCall.conversation_id == conversation_id).order_by(ApiCall.created_at.asc(), ApiCall.id.asc())
    ).scalars().all()

    payload = _build_snapshot_payload(assistant, conversation, messages, tour_searches, api_calls)
    event_id = f"{conversation.id}:{uuid.uuid4().hex}"
    outbox = RuntimeEventOutbox(
        assistant_id=assistant.id,
        conversation_id=conversation.id,
        event_id=event_id,
        event_type=_EVENT_TYPE,
        status="pending",
        payload=payload,
        next_retry_at=_utcnow(),
    )
    db.add(outbox)
    logger.info(
        "Dialog outbox queued assistant=%s conversation=%s event_id=%s messages=%d searches=%d api_calls=%d",
        assistant.id,
        conversation.id,
        event_id,
        len(messages),
        len(tour_searches),
        len(api_calls),
    )
    return event_id


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_due_events(db, limit: int) -> list[RuntimeEventOutbox]:
    now = _utcnow()
    stmt = (
        select(RuntimeEventOutbox)
        .where(
            RuntimeEventOutbox.status.in_(_STATUSES_PENDING),
            (RuntimeEventOutbox.next_retry_at.is_(None)) | (RuntimeEventOutbox.next_retry_at <= now),
        )
        .order_by(RuntimeEventOutbox.created_at.asc(), RuntimeEventOutbox.id.asc())
        .limit(limit)
    )
    return db.execute(stmt).scalars().all()


def collect_delivery_metrics(
    db,
    *,
    reporting_enabled: bool,
    dialog_sender_enabled: bool,
) -> dict[str, Any]:
    counts = dict(
        db.query(RuntimeEventOutbox.status, func.count(RuntimeEventOutbox.id))
        .group_by(RuntimeEventOutbox.status)
        .all()
    )
    oldest_undelivered_at = (
        db.query(func.min(RuntimeEventOutbox.created_at))
        .filter(RuntimeEventOutbox.status.in_(_STATUSES_PENDING))
        .scalar()
    )
    last_successful_delivery_at = (
        db.query(func.max(RuntimeEventOutbox.sent_at))
        .filter(RuntimeEventOutbox.status == "sent")
        .scalar()
    )

    oldest_age_sec: Optional[int] = None
    if oldest_undelivered_at is not None:
        oldest_age_sec = max(0, int((_utcnow() - oldest_undelivered_at).total_seconds()))

    estimated_lag_sec = oldest_age_sec or 0
    failed_count = int(counts.get("failed", 0))
    retrying_count = int(counts.get("retrying", 0))

    pipeline_status = "ok"
    if not reporting_enabled or not dialog_sender_enabled:
        pipeline_status = "disabled"
    elif failed_count >= max(1, int(settings.runtime_dialog_sender_failed_backlog_alert_threshold)):
        pipeline_status = "failed"
    elif oldest_age_sec is not None and oldest_age_sec >= int(settings.runtime_dialog_sender_oldest_pending_alert_seconds):
        pipeline_status = "failed"
    elif retrying_count > 0:
        pipeline_status = "degraded"
    elif oldest_age_sec is not None and oldest_age_sec > int(settings.runtime_dialog_sender_normal_lag_threshold_seconds):
        pipeline_status = "degraded"

    return {
        "dialog_sender_backlog": {
            "pending": int(counts.get("pending", 0)),
            "retrying": retrying_count,
            "failed": failed_count,
        },
        "oldest_undelivered_event_age_sec": oldest_age_sec,
        "last_successful_delivery_at": _to_iso_or_none(last_successful_delivery_at),
        "estimated_delivery_lag_sec": estimated_lag_sec,
        "delivery_pipeline_status": pipeline_status,
        "dialog_sender_alert_thresholds": {
            "normal_lag_sec": int(settings.runtime_dialog_sender_normal_lag_threshold_seconds),
            "oldest_undelivered_alert_sec": int(settings.runtime_dialog_sender_oldest_pending_alert_seconds),
            "failed_backlog_alert_count": int(settings.runtime_dialog_sender_failed_backlog_alert_threshold),
        },
    }


def replay_conversation_snapshots(
    db,
    *,
    assistant_id: Optional[uuid.UUID] = None,
    conversation_id: Optional[uuid.UUID] = None,
    occurred_from: Optional[datetime] = None,
    occurred_to: Optional[datetime] = None,
    limit: int = 500,
) -> dict[str, Any]:
    event_ts = func.coalesce(Conversation.last_active_at, Conversation.started_at)
    stmt = select(Conversation).order_by(event_ts.asc(), Conversation.id.asc())

    if assistant_id is not None:
        stmt = stmt.where(Conversation.assistant_id == assistant_id)
    if conversation_id is not None:
        stmt = stmt.where(Conversation.id == conversation_id)
    if occurred_from is not None:
        stmt = stmt.where(event_ts >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(event_ts <= occurred_to)
    if limit > 0:
        stmt = stmt.limit(limit)

    conversations = db.execute(stmt).scalars().all()
    queued = 0
    skipped = 0
    for conversation in conversations:
        event_id = enqueue_conversation_snapshot(db, conversation.id, conversation.assistant_id)
        if event_id:
            queued += 1
        else:
            skipped += 1

    return {
        "matched": len(conversations),
        "queued": queued,
        "skipped": skipped,
        "assistant_id": str(assistant_id) if assistant_id else None,
        "conversation_id": str(conversation_id) if conversation_id else None,
        "occurred_from": _to_iso_or_none(occurred_from),
        "occurred_to": _to_iso_or_none(occurred_to),
        "limit": limit,
    }


def _compute_retry_delay(attempt: int) -> int:
    base = max(1, int(settings.runtime_dialog_sender_retry_backoff_seconds))
    return min(base * max(1, attempt), int(settings.runtime_dialog_sender_retry_backoff_max_seconds))


def _deliver_outbox_event(db, event: RuntimeEventOutbox) -> None:
    assistant = db.get(Assistant, event.assistant_id)
    if assistant is None:
        event.status = "failed"
        event.last_error = "assistant_not_found"
        return

    reporting = _runtime_reporting_config(assistant.runtime_metadata)
    if reporting.get("mode") != "batch_snapshot":
        event.status = "failed"
        event.last_error = "reporting_disabled"
        return

    endpoint_url = reporting.get("endpoint_url") or ""
    auth_secret = reporting.get("auth_secret") or ""
    auth_header_name = reporting.get("auth_header_name") or "X-MGP-Service-Token"
    if not endpoint_url or not auth_secret:
        event.status = "failed"
        event.last_error = "reporting_config_incomplete"
        return

    event.locked_at = _utcnow()
    event.attempts = (event.attempts or 0) + 1
    event.status = "retrying"

    headers = {
        "Content-Type": "application/json",
        auth_header_name: auth_secret,
        "X-Assistant-Id": str(event.assistant_id),
        "X-Event-Id": event.event_id,
    }

    def _event_body(payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload or {})
        body["event_id"] = event.event_id
        body["event_type"] = event.event_type
        return body

    body = _event_body(event.payload or {})

    try:
        with httpx.Client(timeout=float(settings.runtime_dialog_sender_timeout_seconds)) as client:
            resp = client.post(endpoint_url, json=body, headers=headers)
        event.last_status_code = resp.status_code
        if resp.status_code == 413:
            compacted_payload = _fit_snapshot_payload(_compact_snapshot_payload(event.payload or {}, level=3))
            compacted_body = _event_body(compacted_payload)
            if _payload_hash(compacted_body) != _payload_hash(body):
                event.payload = compacted_payload
                with httpx.Client(timeout=float(settings.runtime_dialog_sender_timeout_seconds)) as client:
                    resp = client.post(endpoint_url, json=compacted_body, headers=headers)
                event.last_status_code = resp.status_code
                body = compacted_body
        if 200 <= resp.status_code < 300 or resp.status_code == 409:
            event.status = "sent"
            event.sent_at = _utcnow()
            event.last_error = None
            event.next_retry_at = None
            logger.info(
                "Dialog outbox delivered assistant=%s conversation=%s event_id=%s code=%s payload_hash=%s",
                event.assistant_id,
                event.conversation_id,
                event.event_id,
                resp.status_code,
                _payload_hash(body),
            )
            return
        event.last_error = f"http_{resp.status_code}"
    except Exception as exc:
        event.last_error = str(exc)[:500]
        event.last_status_code = None

    if event.attempts >= int(settings.runtime_dialog_sender_max_attempts):
        event.status = "failed"
        event.next_retry_at = None
    else:
        event.status = "retrying"
        event.next_retry_at = _utcnow() + timedelta(seconds=_compute_retry_delay(event.attempts))

    logger.warning(
        "Dialog outbox delivery failed assistant=%s conversation=%s event_id=%s attempt=%s status=%s error=%s",
        event.assistant_id,
        event.conversation_id,
        event.event_id,
        event.attempts,
        event.status,
        event.last_error,
    )


def run_dialog_sender_once(limit: Optional[int] = None) -> int:
    if not is_db_available():
        return 0

    processed = 0
    with get_db() as db:
        if db is None:
            return 0
        events = _load_due_events(db, limit or int(settings.runtime_dialog_sender_batch_size))
        for event in events:
            _deliver_outbox_event(db, event)
            processed += 1
    return processed


def backfill_reporting_config(
    assistant: Assistant,
    endpoint_url: str,
    auth_header_name: str,
    auth_secret: str,
    contract_version: str = _CONTRACT_VERSION,
) -> None:
    metadata = dict(assistant.runtime_metadata or {})
    metadata["reporting"] = {
        "mode": "batch_snapshot",
        "contract_version": contract_version,
        "endpoint_url": endpoint_url,
        "accepted_event_types": [_EVENT_TYPE],
        "auth": {
            "type": "shared_secret",
            "header_name": auth_header_name,
            "secret": auth_secret,
        },
    }
    assistant.runtime_metadata = metadata
