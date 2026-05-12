"""Tenant-level administration for the MAX Messenger channel.

The CLI shells in cli.py wrap these helpers so we can also reuse them from
``deploy/provision_clients.sh`` and (later) from an internal HTTP endpoint
without re-implementing the validation / DB write logic in three places.

The channel config lives under ``assistants.runtime_metadata.channels.max``
as a plain JSON object so the existing reporting/secret machinery applies
unchanged. Layout::

    {
      "channels": {
        "max": {
          "enabled": true,
          "bot_token": "...",                # mandatory
          "webhook_secret": "...",           # mandatory, 5..256 [A-Za-z0-9_-]
          "bot_username": "mgp_tour_bot",    # optional, cosmetic
          "bot_user_id": 123,                 # optional, returned by /me
          "subscribed_at": "2026-05-12T...",   # optional, set after manual POST /subscriptions
          "validated_at": "2026-05-12T..."     # last successful GET /me
        }
      }
    }

We deliberately do NOT post to MAX's ``/subscriptions`` from this module.
That call is currently made by an operator using ``curl`` because every
tenant's webhook URL must be entered in MAX's own dev console — see
MAX_LK_INTEGRATION_HANDOFF.md (delivered with phase C).
"""
from __future__ import annotations

import json
import logging
import re
import secrets as _secrets_mod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("mgp_bot.max_admin")

# MAX ``secret`` for ``POST /subscriptions`` must match this regex
# (https://dev.max.ru/docs-api/methods/POST/subscriptions).
WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{5,256}$")
_DEFAULT_BOT_API_URL = "https://botapi.max.ru"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def generate_webhook_secret(length: int = 32) -> str:
    """Return a URL-safe webhook secret that fits the MAX regex."""
    raw = _secrets_mod.token_urlsafe(length)
    # ``token_urlsafe`` only emits [A-Za-z0-9_-], so the regex is satisfied
    # by construction. The slice keeps the secret a sensible length.
    return raw[: max(8, min(64, length * 2))]


def validate_webhook_secret(value: str) -> Optional[str]:
    """Return ``None`` if the secret matches MAX's regex, else an error msg."""
    if not value:
        return "webhook_secret is empty"
    if not WEBHOOK_SECRET_RE.fullmatch(value):
        return (
            "webhook_secret must match ^[A-Za-z0-9_-]{5,256}$ "
            f"(got length={len(value)})"
        )
    return None


def fetch_bot_info(bot_token: str, base_url: str = _DEFAULT_BOT_API_URL, timeout: float = 10.0) -> Tuple[bool, Dict[str, Any]]:
    """Call ``GET /me`` on the MAX bot API to confirm the token is alive.

    Returns ``(ok, payload)``. On error, ``payload`` contains a short reason.
    """
    url = f"{base_url.rstrip('/')}/me?access_token={bot_token}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return False, {"error": f"transport: {exc}"}
    if response.status_code >= 400:
        body = (response.text or "")[:300]
        return False, {
            "error": f"http {response.status_code}",
            "body": body,
        }
    try:
        data = response.json()
    except ValueError:
        return False, {"error": "invalid_json_response"}
    if not isinstance(data, dict):
        return False, {"error": "unexpected_response_shape"}
    return True, data


def _coerce_runtime_metadata(raw: Any) -> Dict[str, Any]:
    """Return ``runtime_metadata`` as a mutable dict, parsing JSON if needed."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        # SQLAlchemy returns a fresh dict on read; safe to mutate.
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _resolve_assistant(db, *, slug: str):
    from models import Assistant, Company  # local import to avoid cycle
    row = (
        db.query(Assistant, Company)
        .join(Company, Assistant.company_id == Company.id)
        .filter(Company.slug == slug)
        .filter(Assistant.is_active == True)  # noqa: E712
        .first()
    )
    return row  # tuple (Assistant, Company) or None


def enable_max_channel(
    db,
    *,
    slug: str,
    bot_token: str,
    webhook_secret: Optional[str] = None,
    bot_username: Optional[str] = None,
    skip_validate: bool = False,
    bot_api_base_url: str = _DEFAULT_BOT_API_URL,
) -> Dict[str, Any]:
    """Idempotently enable the MAX channel for one tenant.

    Returns a JSON-able status dict. Caller is responsible for committing
    the session.
    """
    if not bot_token or not bot_token.strip():
        return {"ok": False, "error": "bot_token is required"}

    bot_token = bot_token.strip()

    if webhook_secret:
        webhook_secret = webhook_secret.strip()
        err = validate_webhook_secret(webhook_secret)
        if err:
            return {"ok": False, "error": err}

    row = _resolve_assistant(db, slug=slug)
    if row is None:
        return {"ok": False, "error": f"assistant with slug={slug!r} not found"}
    assistant, company = row

    rm = _coerce_runtime_metadata(assistant.runtime_metadata)
    channels = rm.get("channels")
    if not isinstance(channels, dict):
        channels = {}
    existing_max = channels.get("max") if isinstance(channels, dict) else None
    if not isinstance(existing_max, dict):
        existing_max = {}

    if not webhook_secret:
        # Keep the existing secret on a repeat run so we don't break MAX's
        # subscription. Generate a fresh one only on the very first call.
        webhook_secret = (existing_max.get("webhook_secret") or "").strip()
        if not webhook_secret:
            webhook_secret = generate_webhook_secret()

    info_payload: Dict[str, Any] = {}
    if not skip_validate:
        ok, info_payload = fetch_bot_info(bot_token, base_url=bot_api_base_url)
        if not ok:
            return {
                "ok": False,
                "error": "bot_token failed MAX /me validation",
                "details": info_payload,
            }
        resolved_username = (
            (info_payload.get("username") if isinstance(info_payload, dict) else None)
            or bot_username
        )
        resolved_user_id = info_payload.get("user_id") if isinstance(info_payload, dict) else None
    else:
        resolved_username = bot_username or existing_max.get("bot_username")
        resolved_user_id = existing_max.get("bot_user_id")

    new_max_cfg = {
        "enabled": True,
        "bot_token": bot_token,
        "webhook_secret": webhook_secret,
        "bot_username": resolved_username or None,
        "bot_user_id": resolved_user_id,
        "subscribed_at": existing_max.get("subscribed_at"),
        "validated_at": existing_max.get("validated_at") if skip_validate else _utcnow_iso(),
    }
    # Drop ``None`` fields to keep the JSON clean.
    new_max_cfg = {k: v for k, v in new_max_cfg.items() if v is not None}

    channels = dict(channels)
    channels["max"] = new_max_cfg
    rm["channels"] = channels
    assistant.runtime_metadata = rm
    # SQLAlchemy ORM tracks dict mutation for some dialects but not for the
    # JSON column in this codebase — assign a fresh dict to force a write.

    logger.info(
        "max_channel enabled slug=%s assistant_id=%s username=%s validated=%s",
        slug, assistant.id, resolved_username, not skip_validate,
    )

    return {
        "ok": True,
        "slug": slug,
        "assistant_id": str(assistant.id),
        "enabled": True,
        "bot_username": resolved_username,
        "bot_user_id": resolved_user_id,
        "webhook_secret": webhook_secret,
        "validated": not skip_validate,
    }


def disable_max_channel(db, *, slug: str) -> Dict[str, Any]:
    row = _resolve_assistant(db, slug=slug)
    if row is None:
        return {"ok": False, "error": f"assistant with slug={slug!r} not found"}
    assistant, _ = row
    rm = _coerce_runtime_metadata(assistant.runtime_metadata)
    channels = rm.get("channels") if isinstance(rm.get("channels"), dict) else {}
    max_cfg = channels.get("max") if isinstance(channels.get("max"), dict) else {}
    if not max_cfg:
        return {"ok": True, "slug": slug, "noop": True, "reason": "channel was not configured"}
    max_cfg = dict(max_cfg)
    max_cfg["enabled"] = False
    channels = dict(channels)
    channels["max"] = max_cfg
    rm["channels"] = channels
    assistant.runtime_metadata = rm
    logger.info("max_channel disabled slug=%s assistant_id=%s", slug, assistant.id)
    return {"ok": True, "slug": slug, "enabled": False}


def get_max_channel_status(db, *, slug: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return a JSON-able list of MAX channel status rows, one per tenant.

    With ``slug`` filters to a single tenant; without it returns all
    tenants that have *any* ``runtime_metadata.channels.max`` config
    (enabled or not).
    """
    from models import Assistant, Company  # local import to avoid cycle

    query = (
        db.query(Assistant, Company)
        .join(Company, Assistant.company_id == Company.id)
        .filter(Assistant.is_active == True)  # noqa: E712
    )
    if slug:
        query = query.filter(Company.slug == slug)
    out: List[Dict[str, Any]] = []
    for assistant, company in query.all():
        rm = _coerce_runtime_metadata(assistant.runtime_metadata)
        channels = rm.get("channels") if isinstance(rm.get("channels"), dict) else {}
        max_cfg = channels.get("max") if isinstance(channels.get("max"), dict) else None
        if slug is None and not max_cfg:
            continue
        out.append({
            "slug": company.slug,
            "assistant_id": str(assistant.id),
            "configured": bool(max_cfg),
            "enabled": bool((max_cfg or {}).get("enabled")) if max_cfg else False,
            "bot_username": (max_cfg or {}).get("bot_username"),
            "bot_user_id": (max_cfg or {}).get("bot_user_id"),
            "webhook_secret_present": bool((max_cfg or {}).get("webhook_secret")),
            "subscribed_at": (max_cfg or {}).get("subscribed_at"),
            "validated_at": (max_cfg or {}).get("validated_at"),
        })
    return out
