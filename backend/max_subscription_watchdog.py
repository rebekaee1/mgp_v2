"""Periodic watchdog that keeps MAX Bot subscriptions alive.

We have observed that MAX silently drops registered webhook subscriptions
(``POST /subscriptions`` returns ``{"success": true}``, then ``GET
/subscriptions`` returns ``[]`` minutes/hours later, with no warning
delivered to us). The end-user symptom is that the bot becomes silent —
the user types a message, MAX accepts it, but never relays the webhook
to our bridge.

This watchdog scans every tenant whose ``runtime_metadata.channels.max``
is enabled, asks MAX for the current subscription list of *that bot*,
and silently re-creates the subscription if our webhook URL is missing.
The ``webhook_secret`` we re-use is the same one already stored in the
DB so the bridge does not have to rotate anything — the bot just starts
delivering again, transparently to the client.

The job is registered by :mod:`scheduler` and runs every
``MAX_WATCHDOG_INTERVAL_MINUTES`` minutes (default 5). It is a single
point of self-healing — no manual operator action needed when MAX drops
a subscription.

Configuration (read from environment via :func:`os.environ`):

* ``MAX_WEBHOOK_PUBLIC_URL`` — the URL MAX must call when a message
  arrives. Same value the bridge uses. If absent, the watchdog logs a
  warning and exits without action (we will not re-subscribe to an
  unknown URL).
* ``MAX_API_BASE_URL`` — defaults to ``https://botapi.max.ru``.
* ``MAX_WATCHDOG_REQUEST_TIMEOUT`` — seconds for each MAX HTTP call
  (default ``10``).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("mgp_bot.max_watchdog")


_DEFAULT_BOT_API_URL = "https://botapi.max.ru"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_url(value: str) -> str:
    """Strip whitespace + trailing slash so URL comparison is robust."""
    return (value or "").strip().rstrip("/")


def _per_tenant_url(base_url: str, slug: str) -> str:
    """Build the per-tenant MAX subscription URL.

    MAX treats each distinct URL as a separate subscription slot and
    silently evicts any prior subscription with the same URL. If two
    bots both subscribe to the same plain ``/max/webhook`` URL, the
    second POST wipes the first — observed live in prod 2026-05-26.

    The cheapest fix is to give every bot a unique URL via a query
    parameter; MAX still echoes the same headers (including the
    ``X-Max-Bot-Api-Secret``) to the bridge, and the bridge ignores
    query strings, so no bridge code change is needed.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}?bot={slug}"


def _collect_enabled_bindings() -> List[Dict[str, str]]:
    """Return active MAX bindings straight from the DB.

    We deliberately re-read on every invocation so a freshly onboarded
    tenant is picked up by the very next watchdog tick — no cache, no
    restart needed.
    """
    try:
        from database import get_db, is_db_available
    except Exception:
        logger.debug("max_watchdog: database module unavailable", exc_info=True)
        return []
    if not is_db_available():
        return []

    try:
        from models import Assistant, Company
    except Exception:
        logger.debug("max_watchdog: models import failed", exc_info=True)
        return []

    bindings: List[Dict[str, str]] = []
    with get_db() as db:
        if db is None:
            return []
        rows = (
            db.query(Assistant, Company)
            .join(Company, Assistant.company_id == Company.id)
            .filter(Assistant.is_active == True)  # noqa: E712
            .filter(Assistant.runtime_metadata.isnot(None))
            .all()
        )
        for assistant, company in rows:
            rm = assistant.runtime_metadata or {}
            if not isinstance(rm, dict):
                continue
            channels = rm.get("channels")
            if not isinstance(channels, dict):
                continue
            max_cfg = channels.get("max")
            if not isinstance(max_cfg, dict) or not max_cfg.get("enabled"):
                continue
            token = (max_cfg.get("bot_token") or "").strip()
            secret = (max_cfg.get("webhook_secret") or "").strip()
            if not token or not secret:
                continue
            bindings.append({
                "assistant_id": str(assistant.id),
                "slug": company.slug,
                "bot_token": token,
                "webhook_secret": secret,
            })
    return bindings


def _stamp_subscribed_at(assistant_id: str) -> None:
    """Refresh ``runtime_metadata.channels.max.subscribed_at`` after a re-subscribe.

    Best-effort: a failure here does not prevent the actual re-subscribe
    from being effective, so we only log and move on.
    """
    try:
        from database import get_db
        from models import Assistant
        import uuid
    except Exception:
        logger.debug("max_watchdog: cannot import DB helpers to stamp subscribed_at", exc_info=True)
        return

    try:
        aid = uuid.UUID(str(assistant_id))
    except (ValueError, TypeError):
        return

    try:
        with get_db() as db:
            if db is None:
                return
            assistant = db.query(Assistant).filter(Assistant.id == aid).first()
            if assistant is None:
                return
            rm = dict(assistant.runtime_metadata or {})
            channels = dict(rm.get("channels") or {})
            max_cfg = dict(channels.get("max") or {})
            if not max_cfg:
                return
            max_cfg["subscribed_at"] = _utcnow_iso()
            channels["max"] = max_cfg
            rm["channels"] = channels
            assistant.runtime_metadata = rm
    except Exception:
        logger.exception("max_watchdog: failed to stamp subscribed_at for %s", assistant_id)


def _is_our_webhook_present(subscriptions: Any, target_url: str) -> bool:
    """``True`` if any subscription points to ``target_url`` (slash-tolerant)."""
    if not isinstance(subscriptions, list):
        return False
    target = _normalise_url(target_url)
    if not target:
        return False
    for sub in subscriptions:
        if not isinstance(sub, dict):
            continue
        if _normalise_url(sub.get("url") or "") == target:
            return True
    return False


def _stale_subscription_urls(subscriptions: Any, target_url: str) -> list:
    """Return URLs that should be removed: any subscription with a URL
    that is not our canonical ``target_url`` (after normalisation).

    Used to clean up duplicates left over from earlier subscription
    attempts (e.g. legacy ``/max/webhook`` without the ``?bot=`` query
    parameter, which would otherwise cause MAX to deliver every event
    twice once a duplicate is present).
    """
    if not isinstance(subscriptions, list):
        return []
    target = _normalise_url(target_url)
    stale = []
    for sub in subscriptions:
        if not isinstance(sub, dict):
            continue
        url = sub.get("url") or ""
        if _normalise_url(url) != target:
            stale.append(url)
    return stale


def run_subscription_watchdog_once() -> Dict[str, Any]:
    """Single watchdog pass: scan all active MAX bots and re-subscribe if needed.

    Returns a dict summary (counts + per-bot status) suitable for logging
    and for ad-hoc invocation from a shell. Safe to call concurrently
    with itself thanks to ``max_instances=1`` on the scheduler side, but
    even without that lock it would only briefly duplicate a re-subscribe
    POST, which is idempotent on MAX's side.
    """
    base_webhook = (os.environ.get("MAX_WEBHOOK_PUBLIC_URL") or "").strip()
    if not base_webhook:
        logger.warning(
            "max_watchdog: MAX_WEBHOOK_PUBLIC_URL is not set; cannot self-heal subscriptions"
        )
        return {"skipped": True, "reason": "no_webhook_url"}

    base_url = (os.environ.get("MAX_API_BASE_URL") or _DEFAULT_BOT_API_URL).rstrip("/")
    try:
        timeout = float(os.environ.get("MAX_WATCHDOG_REQUEST_TIMEOUT", "10"))
    except (TypeError, ValueError):
        timeout = 10.0

    bindings = _collect_enabled_bindings()
    summary: Dict[str, Any] = {
        "checked": 0,
        "healthy": 0,
        "resubscribed": 0,
        "errors": 0,
        "details": [],
    }
    if not bindings:
        logger.debug("max_watchdog: no enabled MAX bindings to check")
        return summary

    with httpx.Client(timeout=timeout) as client:
        for binding in bindings:
            summary["checked"] += 1
            slug = binding["slug"]
            target_url = _per_tenant_url(base_webhook, slug)
            headers_get = {"Authorization": binding["bot_token"]}
            try:
                resp = client.get(f"{base_url}/subscriptions", headers=headers_get)
            except (httpx.HTTPError, OSError) as exc:
                logger.warning(
                    "max_watchdog: GET /subscriptions transport error slug=%s: %s",
                    slug, exc,
                )
                summary["errors"] += 1
                summary["details"].append({"slug": slug, "status": "get_transport_error"})
                continue

            if resp.status_code >= 400:
                logger.warning(
                    "max_watchdog: GET /subscriptions HTTP %s slug=%s body=%s",
                    resp.status_code, slug, (resp.text or "")[:200],
                )
                summary["errors"] += 1
                summary["details"].append({
                    "slug": slug,
                    "status": "get_http_error",
                    "http": resp.status_code,
                })
                continue

            try:
                payload = resp.json()
            except ValueError:
                logger.warning("max_watchdog: invalid JSON from GET /subscriptions slug=%s", slug)
                summary["errors"] += 1
                summary["details"].append({"slug": slug, "status": "get_invalid_json"})
                continue

            subscriptions = payload.get("subscriptions") if isinstance(payload, dict) else None

            # Remove any stale duplicates (e.g. legacy bare ``/max/webhook``
            # left over from before we introduced per-tenant URLs). MAX
            # would otherwise deliver each event twice once a duplicate
            # is present.
            stale_urls = _stale_subscription_urls(subscriptions, target_url)
            for stale_url in stale_urls:
                try:
                    dresp = client.delete(
                        f"{base_url}/subscriptions",
                        params={"url": stale_url},
                        headers={"Authorization": binding["bot_token"]},
                    )
                    if dresp.status_code < 400:
                        logger.info(
                            "max_watchdog: removed stale subscription slug=%s url=%s",
                            slug, stale_url,
                        )
                    else:
                        logger.warning(
                            "max_watchdog: DELETE stale subscription HTTP %s slug=%s url=%s",
                            dresp.status_code, slug, stale_url,
                        )
                except (httpx.HTTPError, OSError) as exc:
                    logger.warning(
                        "max_watchdog: DELETE stale subscription transport error slug=%s: %s",
                        slug, exc,
                    )

            if _is_our_webhook_present(subscriptions, target_url):
                summary["healthy"] += 1
                if stale_urls:
                    summary["details"].append({
                        "slug": slug,
                        "status": "cleaned_stale",
                        "removed": len(stale_urls),
                    })
                continue

            logger.warning(
                "max_watchdog: subscription missing for slug=%s — re-subscribing (current subs=%d)",
                slug, len(subscriptions or []) if isinstance(subscriptions, list) else -1,
            )

            try:
                rsub = client.post(
                    f"{base_url}/subscriptions",
                    headers={
                        "Authorization": binding["bot_token"],
                        "Content-Type": "application/json",
                    },
                    json={"url": target_url, "secret": binding["webhook_secret"]},
                )
            except (httpx.HTTPError, OSError) as exc:
                logger.error(
                    "max_watchdog: POST /subscriptions transport error slug=%s: %s",
                    slug, exc,
                )
                summary["errors"] += 1
                summary["details"].append({"slug": slug, "status": "post_transport_error"})
                continue

            if rsub.status_code >= 400:
                logger.error(
                    "max_watchdog: POST /subscriptions HTTP %s slug=%s body=%s",
                    rsub.status_code, slug, (rsub.text or "")[:200],
                )
                summary["errors"] += 1
                summary["details"].append({
                    "slug": slug,
                    "status": "post_http_error",
                    "http": rsub.status_code,
                })
                continue

            summary["resubscribed"] += 1
            summary["details"].append({"slug": slug, "status": "resubscribed"})
            _stamp_subscribed_at(binding["assistant_id"])
            logger.info("max_watchdog: re-subscribed slug=%s url=%s", slug, target_url)

    if summary["resubscribed"] or summary["errors"]:
        logger.info(
            "max_watchdog summary: checked=%d healthy=%d resubscribed=%d errors=%d",
            summary["checked"], summary["healthy"], summary["resubscribed"], summary["errors"],
        )
    else:
        logger.debug(
            "max_watchdog summary: checked=%d all healthy",
            summary["checked"],
        )
    return summary
