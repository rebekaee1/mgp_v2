#!/usr/bin/env python3
"""Feature 2 — tour-subscription monitor.

Runs INSIDE the backend container (it needs Tourvisor + DB + models). For each
active subscription it searches Tourvisor by the stored criteria, decides whether
a notification is warranted (improvement-only, >=5%, quality floor), and — when
``--send`` — delivers a V1 teaser to the client's MAX chat, persists it into the
dialogue history and records the notification (cadence / stop-after-3).

Timing gates (skipped with --ignore-timing, for fast manual testing):
  • quiet period   — don't interrupt if the client chatted within QUIET_HOURS;
  • send window    — only 10:00–20:00 local (by departure-city TZ);
  • cadence        — at most one notification per CADENCE_HOURS (~1/day).

Testing helpers:
  • --force-trigger — raise the baseline above the current cheapest qualifying
    price so exactly one real teaser fires (lets you see the full cycle live);
  • dry-run by default — only --send actually delivers.

Examples (on server):
  docker exec mgp-backend-1 python /app/subscription_monitor.py            # dry-run
  docker exec mgp-backend-1 python /app/subscription_monitor.py --send --ignore-timing --force-trigger
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta

import subscription_lib as SL
import subscription_store as ST

TEST_ASSISTANT_ID = "593471b7-42da-4ae0-8499-904dcedd6a4b"  # «Навылет! AI» (mgp-tour MAX)
MAX_API = "https://botapi.max.ru"
BACKEND_INTERNAL_URL = "http://127.0.0.1:8080"  # backend on localhost (same container)
BRIDGE_SESSION_TTL = 7 * 24 * 3600  # re-point sessions for 7 days (mirror Feature-1)

QUIET_HOURS = 2        # don't notify if client chatted within the last N hours
CADENCE_HOURS = 20     # >= this many hours between notifications (~1/day)
SEND_FROM, SEND_TO = 10, 20
# departure code -> UTC offset (local send window). Default MSK(+3).
TZ_OFFSET = {1: 3, 2: 5, 3: 5, 4: 5, 5: 3, 6: 5, 7: 4, 8: 3, 9: 7,
             10: 3, 11: 3, 12: 7, 18: 3, 56: 3, 99: 3}


def log(msg):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}", flush=True)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def send_window_ok(departure) -> bool:
    off = TZ_OFFSET.get(departure, 3)
    local_h = (datetime.now(timezone.utc).hour + off) % 24
    return SEND_FROM <= local_h < SEND_TO


def max_send(token: str, chat_id: str, text: str) -> dict:
    url = f"{MAX_API}/messages?chat_id={chat_id}"
    body = json.dumps({"text": text, "format": "markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def sub_to_dict(sub) -> dict:
    """ORM TourSubscription -> plain dict for subscription_lib."""
    return {
        "departure": sub.departure,
        "country": sub.country,
        "regions": sub.regions,
        "dest_text": sub.dest_text,
        "date_from": sub.date_from,
        "date_to": sub.date_to,
        "nights_from": sub.nights_from,
        "nights_to": sub.nights_to,
        "adults": sub.adults,
        "children": sub.children,
        "child_ages": sub.child_ages,
        "min_stars": sub.min_stars,
        "budget": sub.budget,
        "hotel_codes": sub.hotel_codes,
        "hotel_name": sub.hotel_name,
        "baseline_price": sub.baseline_price,
        "last_notified_price": sub.last_notified_price,
        "seen_codes": sub.seen_codes,
    }


def timing_ok(sub, conv_last_active, ignore_timing: bool) -> tuple:
    """Return (ok, reason). reason set when skipping."""
    if ignore_timing:
        return True, None
    now = datetime.now(timezone.utc)
    la = _aware(conv_last_active)
    if la and (now - la) < timedelta(hours=QUIET_HOURS):
        return False, "quiet_period"
    ln = _aware(sub.last_notified_at)
    if ln and (now - ln) < timedelta(hours=CADENCE_HOURS):
        return False, "cadence"
    if not send_window_ok(sub.departure):
        return False, "send_window"
    return True, None


async def _search_one(tv, sub_dict: dict, stage: int) -> list:
    args = SL.build_search_args(sub_dict, floor_stage=stage)
    rid = await tv.search_tours(**args)
    if not rid:
        return []
    try:
        res = await tv.wait_for_search(rid, max_wait=40)
    except Exception as e:  # NoResultsError etc.
        log(f"  search stage={stage} no-results: {type(e).__name__}")
        return []
    return SL.parse_offers(res)


async def search_offers(tv, sub_dict: dict) -> list:
    """Budget-floor cascade (mirror of the main assistant's AUTO-RETRY).

    Stage 0 = premium band (0.90). If it yields NO qualifying offer we step
    the floor down (0.60, then no floor) so the client still gets a useful
    notification when the upper band is empty — premium is just tried first.
    Hotel-centric / cheap-segment subs have no floor, so a single search runs.
    """
    budget = sub_dict.get("budget")
    min_stars = sub_dict.get("min_stars")
    # If no premium floor applies at all (no budget / cheap segment / hotel-
    # centric), there is nothing to widen — one plain search is enough.
    if sub_dict.get("hotel_codes") or SL.budget_floor(budget) is None:
        return await _search_one(tv, sub_dict, 0)

    last_offers: list = []
    for stage in range(SL.FLOOR_MAX_STAGE + 1):
        offers = await _search_one(tv, sub_dict, stage)
        if offers:
            last_offers = offers
        if SL.qualifying(offers, budget, min_stars):
            if stage > 0:
                log(f"  budget-floor widen: stage={stage} (premium band empty → lower floor)")
            return offers
    return last_offers


def fetch_bot_token(db, assistant_id) -> str:
    from models import Assistant
    a = db.get(Assistant, assistant_id)
    rm = getattr(a, "runtime_metadata", None) or {}
    tok = (((rm.get("channels") or {}).get("max") or {}).get("bot_token") or "").strip()
    if not tok:
        raise RuntimeError(f"no MAX bot_token for assistant {assistant_id}")
    return tok


def persist_teaser(db, conversation_id, text: str) -> None:
    from models import Message, Conversation
    db.add(Message(conversation_id=conversation_id, role="assistant", content=text))
    conv = db.get(Conversation, conversation_id)
    if conv is not None:
        conv.last_active_at = datetime.now(timezone.utc)
    db.flush()


def fetch_tenant_slug(db, assistant_id) -> str:
    """company.slug for the assistant — needed for the bridge session key."""
    from models import Assistant, Company
    a = db.get(Assistant, assistant_id)
    if a is None:
        return None
    c = db.get(Company, a.company_id)
    return getattr(c, "slug", None)


def repoint_bridge_session(uid: str, slug: str, session_id: str) -> bool:
    """Re-point the bridge's Redis session (db1) so the client's reply — even
    days later — maps to THIS dialogue with full memory (mirror Feature-1).

    The bridge stores ``max:user:{uid}:tenant:{slug}:session`` in Redis db1.
    We only have the backend REDIS_URL (db0) in-env, so we swap the db index.
    """
    if not (uid and slug and session_id):
        return False
    try:
        import redis as _redis
    except Exception:
        return False
    url = os.environ.get("MAX_REDIS_URL") or os.environ.get("REDIS_URL", "")
    if not url:
        return False
    if not os.environ.get("MAX_REDIS_URL"):
        url = url.rsplit("/", 1)[0] + "/1"  # bridge sessions live in db1
    try:
        cli = _redis.from_url(url, decode_responses=True,
                              socket_connect_timeout=3, socket_timeout=2)
        cli.set(f"max:user:{uid}:tenant:{slug}:session", session_id, ex=BRIDGE_SESSION_TTL)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  repoint failed uid={uid}: {e}")
        return False


def evict_backend_session(session_id: str, assistant_id) -> bool:
    """Ask the backend to drop the warm in-memory handler for this session so
    the client's reply cold-restores from DB (teaser in history + sub hint)."""
    if not session_id:
        return False
    body = json.dumps({"session_id": session_id,
                       "assistant_id": str(assistant_id)}).encode("utf-8")
    req = urllib.request.Request(f"{BACKEND_INTERNAL_URL}/api/runtime/session/evict",
                                 data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode("utf-8"))
            return bool(res.get("evicted"))
    except Exception as e:  # noqa: BLE001
        log(f"  evict failed session={session_id}: {e}")
        return False


async def run(args) -> int:
    import database
    from models import Conversation
    database.init_db(os.environ.get("DATABASE_URL", "postgresql://mgp:mgp@postgres:5432/mgp"))
    from database import get_db
    from openai_handler import OpenAIHandler

    aid = uuid.UUID(args.assistant_id)
    tv = OpenAIHandler().tourvisor
    m = Counter()
    samples = []
    sent = 0
    token = None
    slug = None
    handoffs = []  # (uid, slug, session_id) per delivered teaser — processed after commit

    with get_db() as db:
        ST.expire_due(db)
        subs = ST.get_active_subscriptions(db, aid)
        log(f"active subscriptions: {len(subs)}")
        for sub in subs:
            m["candidates"] += 1
            conv = db.get(Conversation, sub.conversation_id) if sub.conversation_id else None
            conv_last = getattr(conv, "last_active_at", None)
            ok, why = timing_ok(sub, conv_last, args.ignore_timing)
            if not ok:
                m[f"skip_{why}"] += 1
                continue

            sd = sub_to_dict(sub)
            offers = await search_offers(tv, sd)
            if not offers:
                m["no_offers"] += 1
                continue

            # quality+budget cheapest (for baseline bump in test mode)
            q = SL.qualifying(offers, sd.get("budget"), sd.get("min_stars"))
            if not q:
                m["no_quality_in_budget"] += 1
                continue
            if args.force_trigger:
                # raise baseline above current cheapest so it counts as a drop
                sd["baseline_price"] = int(q[0]["price"] * 1.2)
                sd["last_notified_price"] = None

            decision = SL.decide_notification(offers, sd)
            if not decision["notify"]:
                m[f"no_notify_{decision['reason']}"] += 1
                continue

            m["would_notify"] += 1
            teaser = SL.render_teaser(decision, sd)
            offer = decision["offer"]
            if len(samples) < args.samples:
                samples.append({"sub_id": sub.id, "reason": decision["reason"],
                                "price": offer["price"], "hotel": offer["hotelname"],
                                "teaser": teaser})

            if not args.send:
                continue
            if sent >= args.max_send:
                m["capped"] += 1
                continue
            chat_id = sub.external_chat_id or sub.external_user_id
            if not chat_id:
                m["no_chat_id"] += 1
                continue
            try:
                if token is None:
                    token = fetch_bot_token(db, aid)
                max_send(token, str(chat_id), teaser)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200]
                undeliverable = any(k in body.lower() for k in
                                    ("block", "forbidden", "denied", "suspend", "not found", "chat.not"))
                if e.code in (400, 403, 404) and undeliverable:
                    ST.add_optout(db, aid, sub.external_user_id, reason="blocked", source="subscription")
                    ST.stop_subscription(db, sub, reason="undeliverable")
                    m["undeliverable"] += 1
                else:
                    m["send_error"] += 1
                    log(f"SEND ERROR sub={sub.id} http={e.code} {body}")
                continue
            except Exception as e:  # noqa: BLE001
                m["send_error"] += 1
                log(f"SEND ERROR sub={sub.id} {e}")
                continue

            try:
                persist_teaser(db, sub.conversation_id, teaser)
            except Exception as e:  # noqa: BLE001
                log(f"POST-SEND WARN sub={sub.id} (sent ok, persist failed): {e}")
            ST.record_notification(db, sub, price=offer["price"],
                                   hotelcode=offer["hotelcode"], tourid=offer.get("tourid"))
            sent += 1
            m["sent"] += 1
            # Collect the handoff; we re-point + evict AFTER the DB commit so the
            # client's reply cold-restores a fully-persisted dialogue.
            _sid = getattr(conv, "session_id", None)
            if _sid:
                if slug is None:
                    slug = fetch_tenant_slug(db, aid)
                handoffs.append((str(sub.external_user_id or ""), slug, _sid))
            time.sleep(args.throttle_sec)

    # ── Session handoff (mirror Feature-1): now that the teasers are committed,
    #    re-point the bridge session (late replies resume THIS dialogue) and
    #    evict the warm backend handler (so the reply picks up the teaser +
    #    the active-subscription pinned-context hint → assistant shows the card). ──
    for uid, tslug, sid in handoffs:
        if tslug and uid:
            repoint_bridge_session(uid, tslug, sid)
        evict_backend_session(sid, args.assistant_id)
    if handoffs:
        log(f"handoff done for {len(handoffs)} session(s): repoint+evict")

    summary = {"mode": "SEND" if args.send else "DRY-RUN", "metrics": dict(m), "sent": sent}
    log("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    print("\n=== SAMPLE TEASERS ===")
    for s in samples:
        print(f"  [sub {s['sub_id']} {s['reason']}] {s['hotel']} {s['price']} ₽\n   -> {s['teaser']}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assistant-id", default=TEST_ASSISTANT_ID)
    ap.add_argument("--send", action="store_true", help="actually send (else dry-run)")
    ap.add_argument("--ignore-timing", action="store_true",
                    help="bypass quiet/cadence/window (testing)")
    ap.add_argument("--force-trigger", action="store_true",
                    help="raise baseline so the current cheapest fires one teaser (testing)")
    ap.add_argument("--max-send", type=int, default=10)
    ap.add_argument("--throttle-sec", type=float, default=2.0)
    ap.add_argument("--samples", type=int, default=6)
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
