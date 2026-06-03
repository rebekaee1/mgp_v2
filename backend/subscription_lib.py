#!/usr/bin/env python3
"""Feature 2 — core matching / trigger logic for tour subscriptions.

Pure, dependency-free (stdlib only) so it is trivially unit-testable and can be
imported both by local harnesses and by the production monitor job. NO I/O here:
the caller supplies Tourvisor search results; this module only parses + decides.

Decision rule (locked with product owner):
  • match is SOFT  — budget + direction + dates + pax are the gate; stars/meal are
    preferences, not hard filters.
  • trigger is IMPROVEMENT-ONLY with a >=5% threshold:
       - notify on a price DROP of >=5% versus the best price we've ever referenced
         (min of [price the client saw in dialogue, last price we notified]);
       - on the FIRST notification, also notify if a genuinely NEW in-budget hotel
         (not shown in the dialogue) appears at a price <= what the client saw.
  • dedup — we never re-notify the same/worse offer; each new ping must beat the
    last notified price by the threshold.
"""
from __future__ import annotations

DROP_PCT = 0.05  # >=5% improvement required to (re)notify
DEFAULT_MIN_STARS = 4  # quality floor when the client's level is unknown
# names that signal a transit / airport / hostel placeholder (not a resort)
_TRANSIT_MARKERS = ("airport", "аэропорт", "transit", "транзит", "hostel",
                    "хостел", "apartment", "апартамент", "guest house", "гостевой")


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ── build Tourvisor search kwargs from a subscription (SOFT match) ─────────────
def build_search_args(sub: dict) -> dict:
    """Map a subscription's stored criteria to tourvisor_client.search_tours kwargs.

    SOFT match: we search by direction + dates + pax + budget only. Stars/meal are
    NOT passed as hard filters (they're preferences) so that a strong in-budget
    option is never hidden. A hotel-centric subscription narrows by `hotel_codes`.

    Accepts both the stored ``country`` field and the test-only ``country_code``.
    """
    args = {
        "departure": sub.get("departure") or 1,
        "country": sub.get("country") or sub.get("country_code"),
        "date_from": sub.get("date_from"),
        "date_to": sub.get("date_to"),
        "nights_from": sub.get("nights_from") or 7,
        "nights_to": sub.get("nights_to") or 10,
        "adults": sub.get("adults") or 2,
        "children": sub.get("children") or 0,
        "price_to": sub.get("budget"),
    }
    if sub.get("child_ages"):
        args["child_ages"] = list(sub["child_ages"])
    if sub.get("regions"):
        args["regions"] = sub["regions"]
    if sub.get("hotel_codes"):
        args["hotels"] = ",".join(str(c) for c in sub["hotel_codes"])
    # quality floor applied at SEARCH time so page 1 already holds the cheapest
    # hotels of the client's level (results are price-ascending; 5* resorts in
    # budget otherwise sit on later pages and get missed). Meal stays unconstrained.
    if sub.get("min_stars"):
        args["stars"] = int(sub["min_stars"])
        args["starsbetter"] = 1  # "N stars and better"
    return {k: v for k, v in args.items() if v is not None}


# ── parsing Tourvisor search results into flat offers ──────────────────────────
def parse_offers(result: dict) -> list:
    """Flatten a Tourvisor `wait_for_search` result into a list of offers."""
    hotels = (result or {}).get("result", {}).get("hotel")
    if hotels is None:
        hotels = []
    if isinstance(hotels, dict):
        hotels = [hotels]
    offers = []
    for h in hotels:
        price = _to_int(h.get("price"))
        if price is None:
            continue
        tours = h.get("tours") or {}
        tlist = tours.get("tour") if isinstance(tours, dict) else tours
        if isinstance(tlist, dict):
            tlist = [tlist]
        cheapest = None
        for t in (tlist or []):
            tp = _to_int(t.get("price"))
            if tp is None:
                continue
            if cheapest is None or tp < _to_int(cheapest.get("price")):
                cheapest = t
        bt = cheapest or {}
        offers.append({
            "hotelcode": str(h.get("hotelcode")),
            "hotelname": (h.get("hotelname") or "").strip(),
            "price": price,
            "stars": h.get("hotelstars"),
            "stars_int": _to_int(h.get("hotelstars")),
            "rating": h.get("hotelrating"),
            "region": h.get("regionname"),
            "picture": h.get("picturelink"),
            "tourid": bt.get("tourid"),
            "nights": _to_int(bt.get("nights")),
            "meal": (bt.get("mealrussian") or "").strip() or None,
            "flydate": bt.get("flydate"),
        })
    return offers


def _is_transit(name: str) -> bool:
    n = (name or "").lower()
    return any(m in n for m in _TRANSIT_MARKERS)


def qualifying(offers: list, budget, min_stars=None) -> list:
    """In-budget offers, cheapest first, with a QUALITY floor.

    Quality (locked): notify only on hotels at the client's level — stars >= the
    level they were looking at (fallback DEFAULT_MIN_STARS), and never transit /
    airport / hostel placeholders. A hotel with UNKNOWN stars is kept only if its
    name does not look like a transit placeholder (we rely on the name filter
    rather than dropping every unrated hotel).
    """
    b = _to_int(budget)
    floor = _to_int(min_stars) or DEFAULT_MIN_STARS
    out = []
    for o in offers:
        if not o["price"]:
            continue
        if b and o["price"] > b:
            continue
        if _is_transit(o.get("hotelname")):
            continue
        s = o.get("stars_int")
        if s is not None and s < floor:
            continue
        out.append(o)
    return sorted(out, key=lambda o: o["price"])


# ── the core decision ──────────────────────────────────────────────────────────
def decide_notification(offers: list, sub: dict) -> dict:
    """Decide whether to notify the subscriber.

    sub keys used:
      budget                int   — client's budget ceiling
      baseline_price        int?  — cheapest price the client SAW in the dialogue
      last_notified_price   int?  — price of our most recent notification (None if none)
      seen_codes            iter? — hotelcodes shown in the dialogue (anti-rerun)

    returns: {notify, reason, offer, prev_price, drop_abs, drop_pct}
    """
    budget = sub.get("budget")
    q = qualifying(offers, budget, sub.get("min_stars"))
    if not q:
        return {"notify": False, "reason": "no_in_budget", "offer": None,
                "prev_price": None, "drop_abs": 0, "drop_pct": 0.0}

    best = q[0]
    baseline = _to_int(sub.get("baseline_price"))
    last = _to_int(sub.get("last_notified_price"))
    seen = {str(c) for c in (sub.get("seen_codes") or [])}
    is_seen = best["hotelcode"] in seen
    refs = [p for p in (baseline, last) if p]
    effective = min(refs) if refs else None

    # 1) improvement trigger — >=5% better than the best we've ever referenced.
    #    Reason depends on whether the client already saw this exact hotel:
    #      seen hotel got cheaper  -> "price_drop"  ("подешевел")
    #      a different hotel beats it -> "new_option" ("появился выгодный вариант")
    if effective and best["price"] <= effective * (1 - DROP_PCT):
        drop = effective - best["price"]
        return {"notify": True,
                "reason": "price_drop" if is_seen else "new_option",
                "offer": best, "prev_price": effective, "drop_abs": drop,
                "drop_pct": round(drop / effective * 100, 1)}

    # 2) new-option trigger — first notification only: a hotel the client did NOT
    #    see in the dialogue, at a price <= what they saw (even if <5% better)
    if last is None and baseline and not is_seen and best["price"] <= baseline:
        drop = max(0, baseline - best["price"])
        return {"notify": True, "reason": "new_option", "offer": best,
                "prev_price": baseline, "drop_abs": drop,
                "drop_pct": round(drop / baseline * 100, 1) if baseline else 0.0}

    return {"notify": False, "reason": "no_improvement", "offer": best,
            "prev_price": effective, "drop_abs": 0, "drop_pct": 0.0}


# ── notification text (V1 tone: benefit + care) ─────────────────────────────────
def _fmt_money(v) -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def render_teaser(decision: dict, sub: dict) -> str:
    """V1-tone teaser. The card itself is shown by the normal assistant flow on 'да'."""
    offer = decision.get("offer") or {}
    dest = sub.get("dest_text") or offer.get("region") or "вашему запросу"
    hotel = sub.get("hotel_name")  # set only for hotel-centric subscriptions
    price = _fmt_money(offer.get("price"))
    if decision.get("reason") == "price_drop":
        prev = _fmt_money(decision.get("prev_price"))
        if hotel:
            return (f"Здравствуйте! 🙂 Хорошая новость: отель {hotel}, который вы "
                    f"присматривали, подешевел — теперь от ~{price} ₽ (раньше ~{prev}). "
                    f"Показать актуальный вариант?")
        return (f"Здравствуйте! 🙂 Хорошая новость по вашему запросу: тур в {dest} "
                f"подешевел — теперь от ~{price} ₽ (раньше ~{prev}). Показать предложение?")
    # new_option
    if hotel:
        return (f"Здравствуйте! 🙂 По отелю {hotel} появился выгодный вариант — "
                f"от ~{price} ₽. Прислать?")
    return (f"Здравствуйте! 🙂 По вашему запросу ({dest}) появилось выгодное "
            f"предложение — от ~{price} ₽. Показать?")
