#!/usr/bin/env python3
"""Offline unit tests for the re-outreach core. No DB, no network."""
import reoutreach_lib as R

_FAILS = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _FAILS.append(name)


print("== destination resolution ==")
check("Турция", R.resolve_destination("Турция ¦ Москва ¦ август") == "Турция")
check("тайланд->Таиланд", R.resolve_destination("тайланд ¦ Кемерово") == "Таиланд")
check("Вьетнам Муйне", R.resolve_destination("Вьетнам Муйне ¦ Воронеж") == "Вьетнам (Муйне)")
check("departure-only city -> None", R.resolve_destination("Санкт-Петербург") is None)
check("Москва-only -> None", R.resolve_destination("Москва") is None)
check("Египет Эль-Абур", R.resolve_destination("Египет ¦ от 100000 ¦ Эль Абур").startswith("Египет"))

print("== departure ==")
check("из Санкт-Петербурга", R.resolve_departure("Турция ¦ СПб ¦ 6 июля") == "Санкт-Петербурга")
check("из Москвы", R.resolve_departure("Китай ¦ Москва") == "Москвы")

print("== classify ==")
check("handoff -> skip", R.classify({"utext": "Турция", "handoff": True})[0] == "skip")
check("decline -> skip", R.classify({"utext": "Турция", "decline": True})[0] == "skip")
check("no destination -> skip", R.classify({"utext": "Санкт-Петербург", "umsgs": 1})[1] == "no_destination")
check("engaged (click)", R.classify({"utext": "Турция", "clicks": 1, "searches": 1, "cards": 3})[0] == "1_engaged")
check("results", R.classify({"utext": "Турция", "clicks": 0, "searches": 1, "cards": 3})[0] == "4_results")
check("noresults", R.classify({"utext": "Турция", "clicks": 0, "searches": 1, "cards": 0})[0] == "5_noresults")
check("thin", R.classify({"utext": "Турция", "umsgs": 1, "searches": 0, "cards": 0})[0] == "6_thin")
check("incomplete", R.classify({"utext": "Турция ¦ СПб ¦ 6 июля", "umsgs": 3, "searches": 0})[0] == "7_incomplete")

print("== brief + render + validate ==")
rec = {"utext": "Турция ¦ Самара ¦ 15 июля ¦ 2 взрослых ¦ до 150к ¦ 4 звезды ¦ Все включено",
       "searches": 1, "cards": 3, "clicks": 0,
       "search_meta": {"date_from": "2026-07-15", "adults": 2, "children": 0, "stars": 4, "price_to": 150000}}
b = R.extract_brief(rec)
check("brief destination", b["destination"] == "Турция")
check("brief departure", b["departure"] == "Самары")
check("brief dates", b["dates"] == "на 15 июля")
check("brief budget", b["budget"] == 150000)
msg = R.render_message(b, "4_results")
print("     ->", msg)
ok, errs = R.validate(msg, b)
check("validates ok", ok)
check("budget figure allowed", "150 000 ₽" in msg)
check("mentions Турцию (accusative)", "Турцию" in msg)

print("== validate guards ==")
ok2, e2 = R.validate("Здравствуйте! Вариант в Турцию от 225 727 ₽, бронируйте!", {"destination": "Турция", "budget": None})
check("flags stale tour price", "stale_price" in e2)
ok3, e3 = R.validate("Здравствуйте! Туры от МГП в Турцию", {"destination": "Турция"})
check("flags MGP", "mentions_mgp" in e3)
ok4, e4 = R.validate("Здравствуйте! Как дела?", {"destination": "Турция"})
check("flags missing destination", "destination_missing" in e4)

print()
if _FAILS:
    print(f"FAILED ({len(_FAILS)}): {_FAILS}")
    raise SystemExit(1)
print("ALL TESTS PASSED")
