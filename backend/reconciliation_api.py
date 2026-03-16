from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from config import settings
from database import get_db
from dialog_sender import replay_conversation_snapshots, run_dialog_sender_once
from models import ReconciliationRequest

logger = logging.getLogger("mgp_bot.reconciliation")

reconciliation_bp = Blueprint("reconciliation", __name__, url_prefix="/api/runtime")

_ALLOWED_STATUSES = {"queued", "running", "completed", "failed"}


def _auth_failed():
    return jsonify({"error": "Forbidden"}), 403


def _check_bearer() -> bool:
    token = (settings.runtime_provisioning_api_token or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    if not token:
        logger.warning("Reconciliation API token is not configured")
        return False
    return auth == f"Bearer {token}"


def _json_error(status: int, code: str, message: str, retryable: bool = False):
    return jsonify({
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        }
    }), status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_uuid(value: Optional[str], field_name: str) -> Optional[uuid.UUID]:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value).strip())
    except ValueError:
        raise ValueError(f"{field_name} must be a valid UUID")


def _parse_dt(value: Optional[str], field_name: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601 datetime") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _request_public_payload(req: ReconciliationRequest) -> Dict[str, Any]:
    latest_result = dict(req.latest_result or {})
    return {
        "reconciliation_request_id": req.reconciliation_request_id,
        "status": req.status,
        "control_plane_request_id": req.control_plane_request_id,
        "filters": {
            "assistant_id": str(req.assistant_id) if req.assistant_id else None,
            "conversation_id": str(req.conversation_id) if req.conversation_id else None,
            "from": req.occurred_from.isoformat() if req.occurred_from else None,
            "to": req.occurred_to.isoformat() if req.occurred_to else None,
            "limit": req.limit,
        },
        "deliver_now": bool(req.deliver_now),
        "result": {
            "matched_conversations": int(req.matched_conversations or 0),
            "queued_events": int(req.queued_events or 0),
            "delivered_events": int(req.delivered_events or 0),
            **latest_result,
        },
        "error": {
            "code": req.error_code,
            "message": req.error_message,
        } if req.error_code or req.error_message else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "started_at": req.started_at.isoformat() if req.started_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
    }


def _validate_payload(payload: Dict[str, Any]):
    if not isinstance(payload, dict):
        return _json_error(400, "invalid_json", "JSON body must be an object")

    try:
        assistant_id = _parse_uuid(payload.get("assistant_id"), "assistant_id")
        conversation_id = _parse_uuid(payload.get("conversation_id"), "conversation_id")
        occurred_from = _parse_dt(payload.get("from"), "from")
        occurred_to = _parse_dt(payload.get("to"), "to")
    except ValueError as exc:
        return _json_error(422, "invalid_filters", str(exc))

    if not any([assistant_id, conversation_id, occurred_from, occurred_to]):
        return _json_error(
            422,
            "missing_filters",
            "At least one filter is required: assistant_id, conversation_id, from, to",
        )
    if occurred_from and occurred_to and occurred_from > occurred_to:
        return _json_error(422, "invalid_time_range", "`from` must be <= `to`")

    limit_raw = payload.get("limit", 500)
    try:
        limit = max(1, min(int(limit_raw), 5000))
    except (TypeError, ValueError):
        return _json_error(422, "invalid_limit", "`limit` must be an integer")

    deliver_now = bool(payload.get("deliver_now", True))
    request_id = str(payload.get("reconciliation_request_id") or uuid.uuid4())

    return {
        "reconciliation_request_id": request_id,
        "assistant_id": assistant_id,
        "conversation_id": conversation_id,
        "occurred_from": occurred_from,
        "occurred_to": occurred_to,
        "limit": limit,
        "deliver_now": deliver_now,
        "normalized_payload": _normalize_payload({
            "assistant_id": str(assistant_id) if assistant_id else None,
            "conversation_id": str(conversation_id) if conversation_id else None,
            "from": occurred_from.isoformat() if occurred_from else None,
            "to": occurred_to.isoformat() if occurred_to else None,
            "limit": limit,
            "deliver_now": deliver_now,
        }),
    }


def _run_reconciliation_job(request_id: str) -> None:
    with get_db() as db:
        if db is None:
            logger.error("Reconciliation request %s failed: DB unavailable", request_id)
            return
        req = db.get(ReconciliationRequest, request_id)
        if req is None:
            return
        req.status = "running"
        req.started_at = _now()
        req.error_code = None
        req.error_message = None

    try:
        with get_db() as db:
            if db is None:
                raise RuntimeError("database_unavailable")
            req = db.get(ReconciliationRequest, request_id)
            if req is None:
                raise RuntimeError("reconciliation_request_not_found")

            replay_result = replay_conversation_snapshots(
                db,
                assistant_id=req.assistant_id,
                conversation_id=req.conversation_id,
                occurred_from=req.occurred_from,
                occurred_to=req.occurred_to,
                limit=int(req.limit or 500),
            )
            delivered_events = 0
            if req.deliver_now:
                delivered_events = run_dialog_sender_once(limit=max(1, int(req.limit or 500)))

            req.matched_conversations = int(replay_result.get("matched", 0))
            req.queued_events = int(replay_result.get("queued", 0))
            req.delivered_events = int(delivered_events)
            req.latest_result = {
                "matched": int(replay_result.get("matched", 0)),
                "queued": int(replay_result.get("queued", 0)),
                "skipped": int(replay_result.get("skipped", 0)),
                "delivered_now": int(delivered_events),
            }
            req.status = "completed"
            req.completed_at = _now()
            logger.info(
                "Reconciliation completed request=%s matched=%s queued=%s delivered_now=%s",
                request_id,
                req.matched_conversations,
                req.queued_events,
                req.delivered_events,
            )
    except Exception as exc:
        logger.exception("Reconciliation request %s failed", request_id)
        with get_db() as db:
            if db is None:
                return
            req = db.get(ReconciliationRequest, request_id)
            if req is None:
                return
            req.status = "failed"
            req.error_code = "reconciliation_failed"
            req.error_message = str(exc)[:500]
            req.completed_at = _now()


@reconciliation_bp.route("/reconciliation", methods=["POST"])
def create_reconciliation_request():
    if not _check_bearer():
        return _auth_failed()

    payload = request.get_json(silent=True) or {}
    validated = _validate_payload(payload)
    if not isinstance(validated, dict):
        return validated

    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    control_plane_request_id = (request.headers.get("X-Control-Plane-Request-Id") or "").strip()
    if not idempotency_key:
        return _json_error(422, "missing_idempotency_key", "X-Idempotency-Key is required")
    if not control_plane_request_id:
        return _json_error(422, "missing_control_plane_request_id", "X-Control-Plane-Request-Id is required")

    request_id = validated["reconciliation_request_id"]
    with get_db() as db:
        if db is None:
            return _json_error(503, "database_unavailable", "Database is unavailable", retryable=True)

        existing_by_id = db.get(ReconciliationRequest, request_id)
        existing_by_key = db.query(ReconciliationRequest).filter(
            ReconciliationRequest.idempotency_key == idempotency_key
        ).first()
        existing = existing_by_id or existing_by_key
        if existing:
            existing_payload = _normalize_payload(existing.request_payload or {})
            if existing_payload != validated["normalized_payload"]:
                return _json_error(409, "idempotency_conflict", "Idempotency key already used with different payload")
            return jsonify(_request_public_payload(existing)), 200

        req = ReconciliationRequest(
            reconciliation_request_id=request_id,
            idempotency_key=idempotency_key,
            control_plane_request_id=control_plane_request_id,
            status="queued",
            assistant_id=validated["assistant_id"],
            conversation_id=validated["conversation_id"],
            occurred_from=validated["occurred_from"],
            occurred_to=validated["occurred_to"],
            limit=validated["limit"],
            deliver_now=validated["deliver_now"],
            request_payload=json.loads(validated["normalized_payload"]),
            latest_result={},
        )
        db.add(req)
        logger.info(
            "Reconciliation request accepted request=%s idempotency_key=%s control_plane_request_id=%s",
            request_id,
            idempotency_key,
            control_plane_request_id,
        )

    worker = threading.Thread(target=_run_reconciliation_job, args=(request_id,), daemon=True)
    worker.start()
    return jsonify({
        "reconciliation_request_id": request_id,
        "status": "queued",
        "control_plane_request_id": control_plane_request_id,
    }), 202


@reconciliation_bp.route("/reconciliation/<reconciliation_request_id>", methods=["GET"])
def get_reconciliation_request(reconciliation_request_id: str):
    if not _check_bearer():
        return _auth_failed()

    with get_db() as db:
        if db is None:
            return _json_error(503, "database_unavailable", "Database is unavailable", retryable=True)
        req = db.get(ReconciliationRequest, reconciliation_request_id)
        if req is None:
            return _json_error(404, "not_found", "Reconciliation request not found")
        return jsonify(_request_public_payload(req))
