#!/usr/bin/env python3
"""Deterministic unit tests for the subscription decision/trigger logic."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from subscription_lib import decide_notification, render_teaser, parse_offers  # noqa: E402


def _offers(*pairs):
    """pairs of (hotelcode, price) -> offer list."""
    return [{"hotelcode": str(c), "hotelname": f"HOTEL {c}", "price": p,
             "stars": "5", "region": "Анталья", "picture": None,
             "tourid": f"T{c}", "nights": 7, "meal": "Всё включено",
             "flydate": "10.07.2026"} for c, p in pairs]


CASES = []


def case(name, offers, sub, want_notify, want_reason):
    d = decide_notification(offers, sub)
    ok = (d["notify"] == want_notify and d["reason"] == want_reason)
    CASES.append((ok, name, want_notify, want_reason, d["notify"], d["reason"], d))
    return d


# S1: first notify, NEW hotel not seen, cheaper than baseline -> new_option
case("S1 new in-budget hotel < baseline",
     _offers(("A", 150000), ("B", 180000)),
     {"budget": 200000, "baseline_price": 165000, "last_notified_price": None,
      "seen_codes": ["X", "Y"]}, True, "new_option")

# S2: price drop >=5% vs last_notified -> price_drop
case("S2 >=5% drop vs last notified",
     _offers(("A", 138000)),
     {"budget": 200000, "baseline_price": 165000, "last_notified_price": 150000,
      "seen_codes": ["A"]}, True, "price_drop")

# S3: tiny drop <5% -> no
case("S3 <5% drop -> silent",
     _offers(("A", 146000)),
     {"budget": 200000, "baseline_price": 165000, "last_notified_price": 150000,
      "seen_codes": ["A"]}, False, "no_improvement")

# S4: nothing in budget -> no
case("S4 nothing in budget",
     _offers(("A", 230000), ("B", 250000)),
     {"budget": 200000, "baseline_price": 165000, "last_notified_price": None,
      "seen_codes": []}, False, "no_in_budget")

# S5: in-budget but it's exactly what they already SAW at same price -> no
case("S5 same hotel client already saw, no improvement",
     _offers(("A", 165000)),
     {"budget": 200000, "baseline_price": 165000, "last_notified_price": None,
      "seen_codes": ["A"]}, False, "no_improvement")

# S6: never notified, no baseline known, in-budget -> still silent (no reference to beat)
#     (we only fire new_option when we know what they saw; avoids cold-spam)
case("S6 no baseline, never notified -> silent",
     _offers(("A", 120000)),
     {"budget": 200000, "baseline_price": None, "last_notified_price": None,
      "seen_codes": []}, False, "no_improvement")

# S7: big drop on a hotel they DID see -> price_drop (still valuable)
case("S7 seen hotel drops >=5% -> notify",
     _offers(("A", 140000)),
     {"budget": 200000, "baseline_price": 165000, "last_notified_price": None,
      "seen_codes": ["A"]}, True, "price_drop")

print("=" * 72)
passed = 0
for ok, name, wn, wr, gn, gr, d in CASES:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"        want notify={wn} reason={wr} | got notify={gn} reason={gr}")
    passed += int(ok)
print("=" * 72)
print(f"{passed}/{len(CASES)} passed")

# teaser rendering sanity (price_drop + new_option, generic + hotel-centric)
print("\n--- teaser samples ---")
d = decide_notification(_offers(("A", 138000)),
                        {"budget": 200000, "baseline_price": 165000,
                         "last_notified_price": 150000, "seen_codes": ["A"]})
print("price_drop, generic:\n ", render_teaser(d, {"dest_text": "Турцию"}))
print("price_drop, hotel:\n ", render_teaser(d, {"hotel_name": "Rixos Premium"}))
d2 = decide_notification(_offers(("A", 150000)),
                         {"budget": 200000, "baseline_price": 165000,
                          "last_notified_price": None, "seen_codes": ["X"]})
print("new_option, generic:\n ", render_teaser(d2, {"dest_text": "Турцию"}))

sys.exit(0 if passed == len(CASES) else 1)
