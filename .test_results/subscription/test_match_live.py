#!/usr/bin/env python3
"""Phase 1a LIVE test: run synthetic subscriptions through the FULL matcher path
against the real Tourvisor API. NO sends, NO DB — just prints what the monitor
WOULD do (qualifying offers + notify decision + teaser).

Run from backend/:  cd backend && python3 ../.test_results/subscription/test_match_live.py
"""
import os, sys, asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, HERE)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))
_CREDS = os.environ.get("MGP_E2E_CREDS", "/tmp/mgp_e2e_creds.env")
if os.path.exists(_CREDS):
    load_dotenv(_CREDS, override=True)
import logging  # noqa: E402
logging.disable(logging.WARNING)
from openai_handler import OpenAIHandler  # noqa: E402
import subscription_lib as S  # noqa: E402


# synthetic subscriptions (criteria a real client could have left)
SUBS = [
    {"name": "T1 Турция 200к, видел 5* за 165к (порог качества 5*)",
     "country_code": 4, "departure": 1, "date_from": "10.07.2026", "date_to": "20.07.2026",
     "nights_from": 7, "nights_to": 10, "adults": 2, "budget": 200000, "min_stars": 5,
     "baseline_price": 165000, "last_notified_price": None, "seen_codes": [],
     "dest_text": "Турцию"},
    {"name": "T2 Турция бюджет 70к (ниже рынка) — ожидаем 'нет в бюджете'",
     "country_code": 4, "departure": 1, "date_from": "10.07.2026", "date_to": "20.07.2026",
     "nights_from": 7, "nights_to": 10, "adults": 2, "budget": 70000,
     "baseline_price": 90000, "last_notified_price": None, "seen_codes": [],
     "dest_text": "Турцию"},
    {"name": "T3 Турция 200к, baseline=85к last_notified=85к (дедуп/улучшение)",
     "country_code": 4, "departure": 1, "date_from": "10.07.2026", "date_to": "20.07.2026",
     "nights_from": 7, "nights_to": 10, "adults": 2, "budget": 200000,
     "baseline_price": 85000, "last_notified_price": 85000, "seen_codes": [],
     "dest_text": "Турцию"},
    {"name": "T4 Египет 150к, видел 4* за 130к (порог 4*)",
     "country_code": 1, "departure": 1, "date_from": "10.07.2026", "date_to": "20.07.2026",
     "nights_from": 7, "nights_to": 10, "adults": 2, "budget": 150000, "min_stars": 4,
     "baseline_price": 130000, "last_notified_price": None, "seen_codes": [],
     "dest_text": "Египет"},
]


async def run_one(tv, sub):
    args = S.build_search_args(sub)
    print(f"\n=== {sub['name']}")
    print(f"    search args: {args}")
    try:
        rid = await tv.search_tours(**args)
        res = await tv.wait_for_search(rid, max_wait=40)
    except Exception as e:  # NoResultsError etc.
        print(f"    search -> {type(e).__name__}: {e}")
        # emulate empty result for the decision
        d = S.decide_notification([], sub)
        print(f"    decision: notify={d['notify']} reason={d['reason']}")
        return
    offers = S.parse_offers(res)
    q = S.qualifying(offers, sub["budget"], sub.get("min_stars"))
    cheapest_any = min((o["price"] for o in offers if o["price"]), default=None)
    print(f"    offers parsed: {len(offers)} | cheapest_any={cheapest_any} | "
          f"quality in-budget(<= {sub['budget']}, >={sub.get('min_stars') or 4}*): {len(q)}")
    if q:
        for o in q[:3]:
            print(f"      • {o['hotelname']} ({o['hotelcode']}) {o['stars']}* {o['price']} ₽ "
                  f"[{o['nights']}н, {o['meal'] or '—'}, {o['flydate']}] tourid={o['tourid']}")
    d = S.decide_notification(offers, sub)
    print(f"    DECISION: notify={d['notify']} reason={d['reason']} "
          f"prev={d.get('prev_price')} drop={d.get('drop_abs')} ({d.get('drop_pct')}%)")
    if d["notify"]:
        print(f"    TEASER: {S.render_teaser(d, sub)}")


async def main():
    h = OpenAIHandler()
    tv = h.tourvisor
    for sub in SUBS:
        await run_one(tv, sub)
    print("\n[done]")


if __name__ == "__main__":
    asyncio.run(main())
