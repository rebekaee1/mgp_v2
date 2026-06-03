"""Storage layer for tour subscriptions (Feature 2).

Pure SQLAlchemy ORM (works on both Postgres in prod and SQLite in tests). Used by
the assistant's ``subscribe_tours`` tool handler (create) and by the background
monitor job (read active / record notification / record reply / expire / stop).

Lifecycle (locked with product owner):
  active until the EARLIEST of — travel dates passed (else +30d) / opt-out /
  3 notifications without a single reply. Opt-out is GLOBAL (Ф.1 + Ф.2).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from models import TourSubscription, ContactOptout

MAX_SILENT_STREAK = 3          # stop after N notifications with no reply
DEFAULT_TTL_DAYS = 30          # fallback lifetime when no concrete travel date


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat naive datetimes (as SQLite returns) as UTC so comparisons are safe
    on both Postgres (tz-aware) and SQLite (naive)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_ddmmyyyy(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def compute_expires_at(date_from: Optional[str], created: Optional[datetime] = None) -> datetime:
    """Lifetime end: a few days past the travel date if known, else +TTL days."""
    created = created or _utcnow()
    travel = _parse_ddmmyyyy(date_from)
    if travel:
        # keep watching until just after the departure window
        return travel + timedelta(days=2)
    return created + timedelta(days=DEFAULT_TTL_DAYS)


# ── opt-out (global do-not-contact) ────────────────────────────────────────────
def is_opted_out(session: Session, assistant_id, external_user_id, channel: str = "max") -> bool:
    if not external_user_id:
        return False
    q = select(ContactOptout.id).where(
        and_(
            ContactOptout.external_user_id == str(external_user_id),
            ContactOptout.channel == channel,
        )
    )
    # opt-out is honoured per-assistant; a NULL assistant_id row = global block
    rows = session.execute(q).first()
    return rows is not None


def add_optout(session: Session, assistant_id, external_user_id, channel: str = "max",
               reason: str = "optout_phrase", source: str = "subscription") -> None:
    if not external_user_id:
        return
    exists = session.execute(
        select(ContactOptout.id).where(and_(
            ContactOptout.assistant_id == assistant_id,
            ContactOptout.external_user_id == str(external_user_id),
            ContactOptout.channel == channel,
        ))
    ).first()
    if exists:
        return
    session.add(ContactOptout(
        assistant_id=assistant_id, external_user_id=str(external_user_id),
        channel=channel, reason=reason, source=source,
    ))
    session.flush()


# ── subscriptions ──────────────────────────────────────────────────────────────
def get_active_for_user(session: Session, assistant_id, external_user_id,
                        channel: str = "max") -> Optional[TourSubscription]:
    return session.execute(
        select(TourSubscription).where(and_(
            TourSubscription.assistant_id == assistant_id,
            TourSubscription.external_user_id == str(external_user_id),
            TourSubscription.channel == channel,
            TourSubscription.status == "active",
        ))
    ).scalars().first()


def upsert_subscription(session: Session, **fields) -> TourSubscription:
    """Create a subscription, enforcing ONE active subscription per client.

    Any existing active subscription for the same (assistant, user, channel) is
    superseded (status -> 'stopped', reason 'superseded').
    """
    assistant_id = fields.get("assistant_id")
    uid = fields.get("external_user_id")
    channel = fields.get("channel", "max")

    if uid:
        for old in session.execute(
            select(TourSubscription).where(and_(
                TourSubscription.assistant_id == assistant_id,
                TourSubscription.external_user_id == str(uid),
                TourSubscription.channel == channel,
                TourSubscription.status == "active",
            ))
        ).scalars().all():
            old.status = "stopped"
            old.stop_reason = "superseded"

    fields.setdefault("status", "active")
    if not fields.get("expires_at"):
        fields["expires_at"] = compute_expires_at(fields.get("date_from"))
    if fields.get("travel_date") is None:
        fields["travel_date"] = fields.get("date_from")
    sub = TourSubscription(**fields)
    session.add(sub)
    session.flush()
    return sub


def get_active_subscriptions(session: Session, assistant_id=None,
                             now: Optional[datetime] = None) -> List[TourSubscription]:
    """Active, non-expired subscriptions (optionally for one assistant)."""
    now = now or _utcnow()
    conds = [TourSubscription.status == "active"]
    if assistant_id is not None:
        conds.append(TourSubscription.assistant_id == assistant_id)
    subs = session.execute(
        select(TourSubscription).where(and_(*conds))
    ).scalars().all()
    return [s for s in subs if not (_aware(s.expires_at) and _aware(s.expires_at) <= now)]


def record_notification(session: Session, sub: TourSubscription, *, price: int,
                        hotelcode: str, tourid: Optional[str] = None) -> None:
    """Mark that we sent a teaser; bump streak and auto-stop after the limit."""
    sub.last_notified_price = int(price) if price is not None else sub.last_notified_price
    sub.last_notified_hotelcode = str(hotelcode) if hotelcode is not None else sub.last_notified_hotelcode
    if tourid:
        sub.last_tourid = str(tourid)
    sub.last_notified_at = _utcnow()
    sub.notifications_sent = (sub.notifications_sent or 0) + 1
    sub.silent_streak = (sub.silent_streak or 0) + 1
    if sub.silent_streak >= MAX_SILENT_STREAK:
        sub.status = "stopped"
        sub.stop_reason = "max_silence"
    session.flush()


def record_reply(session: Session, assistant_id, external_user_id,
                 channel: str = "max") -> int:
    """Client replied — reset silence streak on their active subscription."""
    n = 0
    for sub in session.execute(
        select(TourSubscription).where(and_(
            TourSubscription.assistant_id == assistant_id,
            TourSubscription.external_user_id == str(external_user_id),
            TourSubscription.channel == channel,
            TourSubscription.status == "active",
        ))
    ).scalars().all():
        sub.silent_streak = 0
        sub.last_reply_at = _utcnow()
        n += 1
    session.flush()
    return n


def stop_subscription(session: Session, sub: TourSubscription, reason: str = "manual") -> None:
    sub.status = "stopped"
    sub.stop_reason = reason
    session.flush()


def expire_due(session: Session, now: Optional[datetime] = None) -> int:
    """Mark expired any active subscription past its lifetime. Returns count."""
    now = now or _utcnow()
    n = 0
    for sub in session.execute(
        select(TourSubscription).where(TourSubscription.status == "active")
    ).scalars().all():
        if _aware(sub.expires_at) and _aware(sub.expires_at) <= now:
            sub.status = "expired"
            sub.stop_reason = "dates_passed" if sub.travel_date else "ttl"
            n += 1
    session.flush()
    return n
