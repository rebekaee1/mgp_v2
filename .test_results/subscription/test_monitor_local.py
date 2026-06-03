#!/usr/bin/env python3
"""Local end-to-end DRY-RUN of subscription_monitor against a seeded SQLite DB and
LIVE Tourvisor. NO MAX send. Verifies: read active sub -> search -> decide -> teaser.

Run from backend/:  cd backend && python3 ../.test_results/subscription/test_monitor_local.py
"""
import os, sys, uuid, asyncio
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

DB_FILE = "/tmp/sub_mon_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE}"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))
_CREDS = os.environ.get("MGP_E2E_CREDS", "/tmp/mgp_e2e_creds.env")
if os.path.exists(_CREDS):
    load_dotenv(_CREDS, override=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE}"  # ensure creds file didn't override
import logging  # noqa: E402
logging.disable(logging.WARNING)

import database  # noqa: E402
from models import Company, Assistant, Conversation  # noqa: E402  (register tables)
import subscription_store as ST  # noqa: E402
database.init_db(os.environ["DATABASE_URL"])
from database import get_db  # noqa: E402

TEST_AID = uuid.UUID("593471b7-42da-4ae0-8499-904dcedd6a4b")


def seed():
    with get_db() as s:
        comp = Company(name="MGP Tour", slug="mgp-tour")
        s.add(comp); s.flush()
        s.add(Assistant(id=TEST_AID, company_id=comp.id, name="Навылет AI"))
        s.flush()
        conv = Conversation(session_id="sess-mon-1", assistant_id=TEST_AID,
                            llm_provider="openai", model="gpt-5-mini", channel="max",
                            external_user_id="testuid", external_chat_id="testchat")
        s.add(conv); s.flush()
        ST.upsert_subscription(
            s, assistant_id=TEST_AID, conversation_id=conv.id, channel="max",
            external_user_id="testuid", external_chat_id="testchat",
            departure=1, country=4, dest_text="Турцию",
            date_from="10.07.2026", date_to="20.07.2026",
            nights_from=7, nights_to=10, adults=2, min_stars=5, budget=200000,
            baseline_price=165000, seen_codes=[],
        )
        print("seeded 1 subscription (Турция 5* <=200k, baseline 165k)")


def main():
    seed()
    import subscription_monitor as MON
    args = Namespace(assistant_id=str(TEST_AID), send=False, ignore_timing=True,
                     force_trigger=False, max_send=10, throttle_sec=0, samples=6)
    asyncio.run(MON.run(args))


if __name__ == "__main__":
    main()
