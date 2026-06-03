#!/usr/bin/env python3
"""Phase 1a probe: run ONE synthetic subscription search against LIVE Tourvisor
and dump the hotel result structure (so the matcher parses real fields, not guesses).
Run from backend/: cd backend && python3 ../.test_results/subscription/probe_search.py
"""
import os, sys, json, asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, ".env"))
_CREDS = os.environ.get("MGP_E2E_CREDS", "/tmp/mgp_e2e_creds.env")
if os.path.exists(_CREDS):
    load_dotenv(_CREDS, override=True)
import logging  # noqa: E402
logging.disable(logging.WARNING)
from openai_handler import OpenAIHandler  # noqa: E402


async def main():
    h = OpenAIHandler()
    tv = h.tourvisor
    # Турция, Москва(1)/country=4, июль 2026, 7-10 ночей, 2 взрослых, до 200к
    rid = await tv.search_tours(departure=1, country=4, date_from="10.07.2026",
                                date_to="20.07.2026", nights_from=7, nights_to=10,
                                adults=2, price_to=200000)
    print("requestid:", rid)
    res = await tv.wait_for_search(rid, max_wait=40)
    status = res.get("status", {})
    hotels = res.get("result", {}).get("hotel", [])
    if not isinstance(hotels, list):
        hotels = [hotels]
    print("status:", json.dumps({k: status.get(k) for k in ("minprice","hotelsfound","toursfound","state")}, ensure_ascii=False))
    print("hotels_count:", len(hotels))
    for hh in hotels[:3]:
        print("--- hotel keys:", list(hh.keys()))
        print(json.dumps({k: hh.get(k) for k in ("hotelcode","hotelname","price","stars","rating","fulldesclink","picturelink")}, ensure_ascii=False))
        tours = hh.get("tours", {})
        tlist = tours.get("tour") if isinstance(tours, dict) else tours
        if isinstance(tlist, list) and tlist:
            print("    tour[0] keys:", list(tlist[0].keys()))
            print("    tour[0]:", json.dumps({k: tlist[0].get(k) for k in ("tourid","price","nights","meal","operatorname","flydate")}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
