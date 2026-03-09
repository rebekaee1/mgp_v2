import json
import logging
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from flask import Blueprint, jsonify, request

from config import settings
from database import get_db, is_db_available
from models import Assistant, Company, ProvisioningRequest, User
from auth import hash_password

logger = logging.getLogger("mgp_bot.provisioning")

provisioning_bp = Blueprint("provisioning", __name__, url_prefix="/api/provisioning")

_ALLOWED_STATUSES = {"accepted", "provisioning", "runtime_ready", "failed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth_failed():
    return jsonify({"error": "Forbidden"}), 403


def _check_bearer() -> bool:
    token = (settings.runtime_provisioning_api_token or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    if not token:
        logger.warning("Provisioning API token is not configured")
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


def _normalize_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _callback_url(payload: Dict[str, Any]) -> Optional[str]:
    callback = payload.get("callback") or {}
    return callback.get("url") or payload.get("callback_url")


def _callback_token(payload: Dict[str, Any]) -> Optional[str]:
    callback = payload.get("callback") or {}
    auth = callback.get("auth") or {}
    return auth.get("token") or payload.get("callback_token")


def _sanitize_runtime_metadata(runtime_metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = deepcopy(runtime_metadata or {})
    service_auth = meta.get("service_auth")
    if isinstance(service_auth, dict):
        service_auth.pop("secret", None)
    return meta


def _assistant_result_payload(assistant: Assistant) -> Dict[str, Any]:
    runtime_metadata = dict(assistant.runtime_metadata or {})
    service_auth = dict(runtime_metadata.get("service_auth") or {})
    return {
        "company_id": str(assistant.company_id),
        "assistant_id": str(assistant.id),
        "runtime_metadata": _sanitize_runtime_metadata(runtime_metadata),
        "runtime": {
            "runtime_instance_id": settings.runtime_instance_id or os.getenv("HOSTNAME") or "mgp-runtime",
            "public_base_url": assistant.bot_server_url or settings.runtime_public_base_url or "",
            "health_url": f"{(assistant.bot_server_url or settings.runtime_public_base_url or '').rstrip('/')}/api/health" if (assistant.bot_server_url or settings.runtime_public_base_url) else None,
            "status_url": f"{(assistant.bot_server_url or settings.runtime_public_base_url or '').rstrip('/')}/api/runtime/status" if (assistant.bot_server_url or settings.runtime_public_base_url) else None,
            "metadata_url": f"{(assistant.bot_server_url or settings.runtime_public_base_url or '').rstrip('/')}/api/runtime/metadata?assistant_id={assistant.id}" if (assistant.bot_server_url or settings.runtime_public_base_url) else None,
            "service_auth": {
                "mode": service_auth.get("mode"),
                "header_name": service_auth.get("header_name"),
                "scope": service_auth.get("scope"),
            } if service_auth else None,
        },
    }


def _request_public_payload(req: ProvisioningRequest) -> Dict[str, Any]:
    payload = {
        "provisioning_request_id": req.provisioning_request_id,
        "status": req.status,
        "control_plane_request_id": req.control_plane_request_id,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "runtime": None,
        "tenant": None,
        "error": None,
    }
    result = dict(req.latest_result or {})
    runtime = result.get("runtime")
    if runtime:
        payload["runtime"] = runtime
    tenant = result.get("tenant")
    if tenant:
        payload["tenant"] = tenant
    if req.error_code or req.error_message:
        payload["error"] = {
            "code": req.error_code,
            "message": req.error_message,
            "retryable": bool(req.error_retryable),
        }
    return payload


def _update_request_status(req: ProvisioningRequest, status: str,
                           latest_result: Optional[Dict[str, Any]] = None,
                           error: Optional[Dict[str, Any]] = None) -> None:
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"Unsupported provisioning status: {status}")
    req.status = status
    if latest_result is not None:
        req.latest_result = latest_result
    if error:
        req.error_code = error.get("code")
        req.error_message = error.get("message")
        req.error_retryable = bool(error.get("retryable"))
    else:
        req.error_code = None
        req.error_message = None
        req.error_retryable = None


def _send_callback(req_id: str, status: str) -> None:
    try:
        with get_db() as db:
            if db is None:
                return
            req = db.get(ProvisioningRequest, req_id)
            if req is None or not req.callback_url:
                return
            body = _request_public_payload(req)
            body["status"] = status
            headers = {"Content-Type": "application/json"}
            if req.callback_token:
                headers["Authorization"] = f"Bearer {req.callback_token}"
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(req.callback_url, json=body, headers=headers)
                logger.info(
                    "Provisioning callback sent request=%s status=%s code=%s",
                    req_id, status, resp.status_code,
                )
    except Exception:
        logger.warning("Provisioning callback failed for %s status=%s", req_id, status, exc_info=True)


def _start_callback(req_id: str, status: str) -> None:
    thread = threading.Thread(target=_send_callback, args=(req_id, status), daemon=True)
    thread.start()


def _validate_request_payload(payload: Dict[str, Any]) -> Optional[tuple]:
    if not isinstance(payload, dict):
        return _json_error(400, "invalid_json", "JSON body must be an object")

    provisioning_request_id = str(payload.get("provisioning_request_id") or "").strip()
    if not provisioning_request_id:
        return _json_error(422, "missing_provisioning_request_id", "provisioning_request_id is required")

    tenant = payload.get("tenant") or {}
    admin_user = payload.get("admin_user") or {}
    assistant = payload.get("assistant") or {}
    runtime = payload.get("runtime") or {}
    service_auth = runtime.get("service_auth") or {}

    required_checks = [
        (tenant.get("company_name"), "missing_company_name", "tenant.company_name is required"),
        (tenant.get("company_slug"), "missing_company_slug", "tenant.company_slug is required"),
        (admin_user.get("email"), "missing_admin_email", "admin_user.email is required"),
        (assistant.get("assistant_id"), "missing_assistant_id", "assistant.assistant_id is required"),
        (assistant.get("name"), "missing_assistant_name", "assistant.name is required"),
        (service_auth.get("secret"), "missing_runtime_secret", "runtime.service_auth.secret is required"),
    ]
    for value, code, message in required_checks:
        if not str(value or "").strip():
            return _json_error(422, code, message)

    header_name = (service_auth.get("header_name") or "X-MGP-Service-Token").strip()
    if header_name != "X-MGP-Service-Token":
        return _json_error(422, "invalid_service_auth_header", "runtime.service_auth.header_name must be X-MGP-Service-Token")

    mode = (service_auth.get("mode") or "shared_secret").strip()
    if mode != "shared_secret":
        return _json_error(422, "invalid_service_auth_mode", "runtime.service_auth.mode must be shared_secret")

    scope = (service_auth.get("scope") or "runtime").strip()
    if scope != "runtime":
        return _json_error(422, "invalid_service_auth_scope", "runtime.service_auth.scope must be runtime")

    try:
        uuid.UUID(str(assistant.get("assistant_id")).strip())
    except (ValueError, TypeError, AttributeError):
        return _json_error(422, "invalid_assistant_id", "assistant.assistant_id must be a valid UUID")

    return None


def _apply_provisioning(req_id: str) -> None:
    try:
        if not is_db_available():
            logger.error("Provisioning request %s failed: DB unavailable", req_id)
            return

        with get_db() as db:
            if db is None:
                return
            req = db.get(ProvisioningRequest, req_id)
            if req is None:
                return

            payload = dict(req.request_payload or {})
            tenant = payload.get("tenant") or {}
            admin_user = payload.get("admin_user") or {}
            assistant_payload = payload.get("assistant") or {}
            runtime = payload.get("runtime") or {}
            service_auth = runtime.get("service_auth") or {}
            llm_provider = (assistant_payload.get("llm_provider") or settings.llm_provider or "openai").strip().lower()
            default_llm_model = settings.openai_model if llm_provider == "openai" else settings.yandex_model
            default_llm_api_key = settings.openai_api_key if llm_provider == "openai" else settings.yandex_api_key
            runtime_public_base_url = (
                assistant_payload.get("bot_server_url")
                or runtime.get("public_base_url")
                or settings.runtime_public_base_url
                or None
            )

            _update_request_status(req, "provisioning")
            db.flush()

        _start_callback(req_id, "provisioning")

        with get_db() as db:
            req = db.get(ProvisioningRequest, req_id)
            if req is None:
                return

            company_slug = str(tenant["company_slug"]).strip()
            company_name = str(tenant["company_name"]).strip()
            admin_email = str(admin_user["email"]).strip()
            assistant_name = str(assistant_payload["name"]).strip()
            assistant_id = uuid.UUID(str(assistant_payload["assistant_id"]).strip())

            existing_company = db.query(Company).filter(Company.slug == company_slug).first()
            existing_user = db.query(User).filter(User.email == admin_email).first()
            existing_assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()

            if existing_company or existing_user or existing_assistant:
                error = {
                    "code": "resource_conflict",
                    "message": "Company, admin user, or assistant already exists",
                    "retryable": False,
                }
                _update_request_status(req, "failed", error=error)
                db.flush()
                _start_callback(req_id, "failed")
                return

            company = Company(
                name=company_name,
                slug=company_slug,
                logo_url=tenant.get("company_logo_url"),
            )
            db.add(company)
            db.flush()

            user = User(
                company_id=company.id,
                email=admin_email,
                password_hash=hash_password(str(admin_user.get("password") or uuid.uuid4().hex)),
                name=(admin_user.get("name") or admin_email.split("@")[0]).strip(),
                role=(admin_user.get("role") or "admin").strip(),
            )
            db.add(user)

            runtime_metadata = {
                "service_auth": {
                    "mode": service_auth.get("mode") or "shared_secret",
                    "header_name": service_auth.get("header_name") or "X-MGP-Service-Token",
                    "scope": service_auth.get("scope") or "runtime",
                    "secret": service_auth["secret"],
                },
                "provisioning": {
                    "provisioning_request_id": req.provisioning_request_id,
                    "control_plane_request_id": req.control_plane_request_id,
                    "provisioned_at": _now_iso(),
                },
            }

            assistant = Assistant(
                id=assistant_id,
                company_id=company.id,
                name=assistant_name,
                tourvisor_login=assistant_payload.get("tourvisor_login") or settings.tourvisor_auth_login,
                tourvisor_pass=assistant_payload.get("tourvisor_pass") or settings.tourvisor_auth_pass,
                llm_provider=llm_provider,
                llm_api_key=assistant_payload.get("llm_api_key") or default_llm_api_key,
                llm_model=assistant_payload.get("llm_model") or default_llm_model,
                system_prompt=assistant_payload.get("system_prompt") or None,
                faq_content=assistant_payload.get("faq_content") or None,
                widget_config=assistant_payload.get("widget_config") or None,
                runtime_metadata=runtime_metadata,
                bot_server_url=runtime_public_base_url,
                allowed_domains=(assistant_payload.get("allowed_domains") or "").strip() or None,
                is_active=True,
            )
            db.add(assistant)
            db.flush()

            latest_result = {
                "runtime": _assistant_result_payload(assistant)["runtime"],
                "tenant": {
                    "company_id": str(company.id),
                    "assistant_id": str(assistant.id),
                },
            }
            req.company_id = company.id
            req.assistant_id = assistant.id
            _update_request_status(req, "runtime_ready", latest_result=latest_result)

        _start_callback(req_id, "runtime_ready")
    except Exception as exc:
        logger.exception("Provisioning request %s failed", req_id)
        try:
            with get_db() as db:
                if db is None:
                    return
                req = db.get(ProvisioningRequest, req_id)
                if req is None:
                    return
                _update_request_status(req, "failed", error={
                    "code": "internal_error",
                    "message": str(exc),
                    "retryable": False,
                })
        finally:
            _start_callback(req_id, "failed")


@provisioning_bp.route("/tenants", methods=["POST"])
def create_tenant():
    if not _check_bearer():
        return _auth_failed()

    payload = request.get_json(silent=True)
    validation_error = _validate_request_payload(payload)
    if validation_error:
        return validation_error

    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    control_plane_request_id = (request.headers.get("X-Control-Plane-Request-Id") or "").strip()
    if not idempotency_key:
        return _json_error(422, "missing_idempotency_key", "X-Idempotency-Key is required")
    if not control_plane_request_id:
        return _json_error(422, "missing_control_plane_request_id", "X-Control-Plane-Request-Id is required")

    normalized_payload = _normalize_payload(payload)
    provisioning_request_id = str(payload["provisioning_request_id"]).strip()

    with get_db() as db:
        if db is None:
            return _json_error(503, "database_unavailable", "Database is unavailable", retryable=True)

        existing_by_id = db.get(ProvisioningRequest, provisioning_request_id)
        existing_by_key = db.query(ProvisioningRequest).filter(
            ProvisioningRequest.idempotency_key == idempotency_key
        ).first()

        existing = existing_by_id or existing_by_key
        if existing:
            existing_payload = _normalize_payload(existing.request_payload or {})
            if existing_payload != normalized_payload:
                return _json_error(409, "idempotency_conflict", "Idempotency key already used with different payload")
            return jsonify(_request_public_payload(existing)), 200

        req = ProvisioningRequest(
            provisioning_request_id=provisioning_request_id,
            idempotency_key=idempotency_key,
            control_plane_request_id=control_plane_request_id,
            callback_url=_callback_url(payload),
            callback_token=_callback_token(payload),
            status="accepted",
            request_payload=payload,
            latest_result={
                "runtime": None,
                "tenant": None,
            },
        )
        db.add(req)

    _start_callback(provisioning_request_id, "accepted")
    worker = threading.Thread(target=_apply_provisioning, args=(provisioning_request_id,), daemon=True)
    worker.start()

    return jsonify({
        "provisioning_request_id": provisioning_request_id,
        "status": "accepted",
        "control_plane_request_id": control_plane_request_id,
    }), 202


@provisioning_bp.route("/tenants/<provisioning_request_id>", methods=["GET"])
def get_tenant_status(provisioning_request_id: str):
    if not _check_bearer():
        return _auth_failed()

    with get_db() as db:
        if db is None:
            return _json_error(503, "database_unavailable", "Database is unavailable", retryable=True)
        req = db.get(ProvisioningRequest, provisioning_request_id)
        if req is None:
            return _json_error(404, "not_found", "Provisioning request not found")
        return jsonify(_request_public_payload(req))
