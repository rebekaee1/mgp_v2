#!/usr/bin/env python3
"""Unit test for YandexGPTHandler._handle_subscribe_tours (Feature 2 opt-in).

Uses a lightweight stub `self` (SimpleNamespace) so we exercise the pure handler
logic without constructing the full handler / network. Verifies that criteria are
assembled from the last-search cache into _pending_subscription, and that the
no-search guard fires.

Run from backend/:  cd backend && python3 ../.test_results/subscription/test_optin_handler.py
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import yandex_handler as Y  # noqa: E402

fails = []


def expect(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


# ── happy path: full criteria assembled ──
fake = types.SimpleNamespace(
    _last_search_params={
        "departure": 1, "_country": 4, "_regions": None,
        "datefrom": "10.07.2026", "dateto": "20.07.2026",
        "nightsfrom": 7, "nightsto": 10, "adults": 2, "child": 0,
        "stars": 5, "starsbetter": 1, "priceto": 200000,
    },
    _last_search_result={"min_price": 165000, "hotels_found": 120},
    _tourid_map={
        1: {"tourid": "T1", "hotelcode": "111", "hotelname": "A"},
        2: {"tourid": "T2", "hotelcode": "222", "hotelname": "B"},
    },
    _user_stated_budget=200000,
    _pending_subscription=None,
)
res = Y.YandexGPTHandler._handle_subscribe_tours(fake, {"dest_text": "Турцию"})
ps = fake._pending_subscription
expect("returns ok", res.get("status") == "ok")
expect("country=4", ps and ps["country"] == 4)
expect("budget=200000", ps and ps["budget"] == 200000)
expect("min_stars=5", ps and ps["min_stars"] == 5)
expect("dates carried", ps and ps["date_from"] == "10.07.2026" and ps["date_to"] == "20.07.2026")
expect("adults=2", ps and ps["adults"] == 2)
expect("seen_codes from tourid_map", ps and ps["seen_codes"] == ["111", "222"])
expect("baseline_price=165000", ps and ps["baseline_price"] == 165000)
expect("dest_text carried", ps and ps["dest_text"] == "Турцию")

# ── budget override via arg + hotel-centric ──
fake.b_pending = None
fake._pending_subscription = None
res2 = Y.YandexGPTHandler._handle_subscribe_tours(
    fake, {"dest_text": "Турцию", "budget": 250000, "hotel": "Rixos Premium"})
ps2 = fake._pending_subscription
expect("budget override=250000", ps2 and ps2["budget"] == 250000)
expect("hotel_name carried", ps2 and ps2["hotel_name"] == "Rixos Premium")

# ── guard: no prior search -> error, no pending set ──
fake3 = types.SimpleNamespace(
    _last_search_params={}, _last_search_result=None, _tourid_map={},
    _user_stated_budget=None, _pending_subscription=None,
)
res3 = Y.YandexGPTHandler._handle_subscribe_tours(fake3, {"dest_text": "Турцию"})
expect("no-search -> error", res3.get("status") == "error")
expect("no-search -> pending stays None", fake3._pending_subscription is None)

print("=" * 56)
print(f"{'ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(0 if not fails else 1)
