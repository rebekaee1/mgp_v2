#!/usr/bin/env python3
"""Local SQLite test for subscription_store (no Postgres, no network).

Run from backend/:  cd backend && python3 ../.test_results/subscription/test_store_local.py
"""
import os, sys, uuid
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import database  # noqa: E402
from models import Company, Assistant, Conversation, TourSubscription  # noqa: E402  (register tables first!)
import subscription_store as ST  # noqa: E402
database.init_db("sqlite:///:memory:")  # create_all builds all tables incl. new ones
from database import get_db  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((bool(cond), name))


AID = uuid.uuid4()
CID = uuid.uuid4()
UID = "max_user_777"


def seed():
    with get_db() as s:
        comp = Company(name="Test", slug="test-spare")
        s.add(comp); s.flush()
        a = Assistant(id=AID, company_id=comp.id, name="Навылет AI")
        s.add(a); s.flush()
        c = Conversation(id=CID, session_id="sess-1", assistant_id=AID,
                         llm_provider="openai", model="gpt-5-mini", channel="max",
                         external_user_id=UID)
        s.add(c); s.flush()


def base_fields(**over):
    f = dict(assistant_id=AID, conversation_id=CID, channel="max",
             external_user_id=UID, external_chat_id="chat_1",
             country=4, dest_text="Турцию", date_from="10.07.2026", date_to="20.07.2026",
             nights_from=7, nights_to=10, adults=2, min_stars=5, budget=200000,
             baseline_price=165000, seen_codes=["111", "222"])
    f.update(over)
    return f


def main():
    seed()

    # 1) create + get_active
    with get_db() as s:
        sub = ST.upsert_subscription(s, **base_fields())
        sid = sub.id
        active = ST.get_active_subscriptions(s, AID)
        check("create -> 1 active", len(active) == 1)
        check("expires_at set (~travel+2d)", sub.expires_at is not None)

    # 2) one-active-per-client: second upsert supersedes the first
    with get_db() as s:
        ST.upsert_subscription(s, **base_fields(country=1, dest_text="Египет", budget=150000))
        active = ST.get_active_subscriptions(s, AID)
        check("second upsert -> still 1 active", len(active) == 1)
        check("active is the newest (Египет)", active[0].dest_text == "Египет")

    # 3) opt-out global + is_opted_out
    with get_db() as s:
        ST.add_optout(s, AID, UID, reason="optout_phrase", source="subscription")
        check("is_opted_out True", ST.is_opted_out(s, AID, UID) is True)
        check("is_opted_out other uid False", ST.is_opted_out(s, AID, "other") is False)

    # 4) notification streak -> auto stop after 3
    with get_db() as s:
        sub = ST.upsert_subscription(s, **base_fields())
        ST.record_notification(s, sub, price=150000, hotelcode="A1", tourid="T1")
        check("after 1 notif: sent=1 streak=1 active",
              sub.notifications_sent == 1 and sub.silent_streak == 1 and sub.status == "active")
        ST.record_notification(s, sub, price=145000, hotelcode="A2")
        ST.record_notification(s, sub, price=140000, hotelcode="A3")
        check("after 3 notif: stopped(max_silence)",
              sub.status == "stopped" and sub.stop_reason == "max_silence")

    # 5) reply resets streak (before hitting 3)
    with get_db() as s:
        sub = ST.upsert_subscription(s, **base_fields())
        ST.record_notification(s, sub, price=150000, hotelcode="B1")
        ST.record_notification(s, sub, price=145000, hotelcode="B2")
        ST.record_reply(s, AID, UID)
        s.refresh(sub)
        check("reply resets streak to 0", sub.silent_streak == 0 and sub.status == "active")
        ST.record_notification(s, sub, price=140000, hotelcode="B3")
        check("after reply, 1 more notif still active (streak=1)",
              sub.silent_streak == 1 and sub.status == "active")

    # 6) expiry by travel date in the past
    with get_db() as s:
        past = (datetime.now(timezone.utc) - timedelta(days=1))
        sub = ST.upsert_subscription(s, **base_fields(date_from="01.01.2020", expires_at=past))
        n = ST.expire_due(s)
        s.refresh(sub)
        check("expire_due marks past-dated expired", sub.status == "expired" and n >= 1)

    print("=" * 64)
    ok = sum(1 for r, _ in RESULTS if r)
    for r, name in RESULTS:
        print(f"[{'PASS' if r else 'FAIL'}] {name}")
    print("=" * 64)
    print(f"{ok}/{len(RESULTS)} passed")
    sys.exit(0 if ok == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
