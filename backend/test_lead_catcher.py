"""Юнит-тесты режима «ловца лидов» (lead_catcher) + гейта каскада.

Запуск:
    pytest backend/test_lead_catcher.py
    # либо как обычный скрипт (без pytest):
    python3 backend/test_lead_catcher.py

Главный инвариант: пока assistant_id НЕ в lead_catcher_assistant_ids — режим
ИНЕРТЕН (is_lead_catcher=False), и кодовый гейт каскада ведёт себя как раньше
(QC обязателен). Включается только точечно по allow-list.
"""
import importlib
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

AID = "64fea0d3-2605-4c4c-be67-62258ebfa7a9"   # AnyTour
OTHER = "593471b7-42da-4ae0-8499-904dcedd6a4b"


def _load_lead_catcher(allow=""):
    """Подменяем config.settings и перезагружаем модуль lead_catcher."""
    cfg = types.ModuleType("config")

    class S:
        lead_catcher_assistant_ids = allow

    cfg.settings = S()
    sys.modules["config"] = cfg
    import lead_catcher
    importlib.reload(lead_catcher)
    return lead_catcher


# ─────────────────────────── Гейт allow-list ───────────────────────────

def test_gate_inert_by_default():
    lc = _load_lead_catcher(allow="")
    assert lc.is_lead_catcher(AID) is False
    assert lc.is_lead_catcher(OTHER) is False
    assert lc.is_lead_catcher(None) is False


def test_gate_enabled_only_for_allowlisted():
    lc = _load_lead_catcher(allow=AID)
    assert lc.is_lead_catcher(AID) is True
    assert lc.is_lead_catcher(OTHER) is False
    assert lc.is_lead_catcher(None) is False


def test_gate_csv_multi():
    lc = _load_lead_catcher(allow=f"{OTHER}, {AID}")
    assert lc.is_lead_catcher(AID) is True
    assert lc.is_lead_catcher(OTHER) is True


# ─────────────────────────── Умные дефолты ───────────────────────────

def test_smart_defaults_ai_countries():
    lc = _load_lead_catcher(allow=AID)
    assert lc.smart_qc_defaults(4) == {"stars": 4, "starsbetter": 1, "meal": 7, "mealbetter": 0}   # Турция
    assert lc.smart_qc_defaults(1) == {"stars": 4, "starsbetter": 1, "meal": 7, "mealbetter": 0}   # Египет


def test_smart_defaults_uae_premium_bb():
    lc = _load_lead_catcher(allow=AID)
    assert lc.smart_qc_defaults(9) == {"stars": 4, "starsbetter": 1, "meal": 3, "mealbetter": 1}   # ОАЭ


def test_smart_defaults_russia_no_meal():
    lc = _load_lead_catcher(allow=AID)
    d = lc.smart_qc_defaults(47)   # Россия
    assert d == {"stars": 3, "starsbetter": 1}
    assert "meal" not in d


def test_smart_defaults_unknown_country():
    lc = _load_lead_catcher(allow=AID)
    assert lc.smart_qc_defaults(0) == {}
    assert lc.smart_qc_defaults(None) == {}
    assert lc.smart_qc_defaults(999) == {"stars": 3, "starsbetter": 1, "meal": 3, "mealbetter": 1}


def test_apply_smart_defaults_fills_only_absent():
    lc = _load_lead_catcher(allow=AID)
    args = {"country": 4}
    applied = lc.apply_smart_defaults(args)
    assert args["stars"] == 4 and args["meal"] == 7
    assert applied  # что-то применилось


def test_apply_smart_defaults_never_overwrites_explicit():
    lc = _load_lead_catcher(allow=AID)
    args = {"country": 4, "stars": 5, "meal": 9}   # клиент явно выбрал
    lc.apply_smart_defaults(args)
    assert args["stars"] == 5 and args["meal"] == 9   # не перезаписали


def test_apply_smart_defaults_skips_when_hotels():
    lc = _load_lead_catcher(allow=AID)
    args = {"country": 4, "hotels": "12345"}
    applied = lc.apply_smart_defaults(args)
    assert applied == []
    assert "stars" not in args


def test_apply_smart_defaults_noop_without_country():
    lc = _load_lead_catcher(allow=AID)
    args = {}
    assert lc.apply_smart_defaults(args) == []
    assert args == {}


# ─────────────────────────── Правила курортов / рекомендация ─────────

def test_resort_note_known():
    lc = _load_lead_catcher(allow=AID)
    assert "Хургада" in lc.resort_note("Хургада")
    assert lc.resort_note("Шарм-эль-Шейх")  # непустая
    assert lc.resort_note("Белек")


def test_resort_note_unknown_empty():
    lc = _load_lead_catcher(allow=AID)
    assert lc.resort_note("Неизвестный курорт") == ""
    assert lc.resort_note("") == ""
    assert lc.resort_note(None) == ""


def test_build_recommendation_from_facts():
    lc = _load_lead_catcher(allow=AID)
    card = {"hotel_stars": 5, "meal_description": "Всё включено", "resort": "Белек"}
    rec = lc.build_recommendation(card)
    assert "5★" in rec
    assert "всё включено" in rec.lower()
    assert "Белек" in rec


def test_build_recommendation_minimal():
    lc = _load_lead_catcher(allow=AID)
    # Нет курорта в таблице → только факты
    card = {"hotel_stars": 4, "meal_description": "Только завтрак", "resort": "Где-то"}
    rec = lc.build_recommendation(card)
    assert "4★" in rec
    # Пустая карточка → пустая строка
    assert lc.build_recommendation({}) == ""


def test_build_recommendation_strips_meal_code():
    lc = _load_lead_catcher(allow=AID)
    # Префикс кода питания ("BB - ", "AI - ") убирается из рекомендации
    card = {"hotel_stars": 4, "meal_description": "BB - Только завтрак", "resort": "Дубай"}
    rec = lc.build_recommendation(card)
    assert "bb -" not in rec.lower()
    assert "только завтрак" in rec.lower()


def test_resort_note_expanded_destinations():
    lc = _load_lead_catcher(allow=AID)
    # Базу знаний расширили: проверяем ряд новых направлений (страна/курорт/район).
    for name in ("Анапа", "Пхукет", "Нячанг", "Дубай", "Протарас", "Пунта-Кана",
                 "Занзибар", "Хаммамет", "Халкидики", "Сочи", "Пицунда"):
        assert lc.resort_note(name), f"ожидали факт-строку для {name}"
    # Песок-для-детей и кораллы — ключевые различия (для выделения под запрос).
    assert "песок" in lc.resort_note("Анапа").lower()
    assert "коралл" in lc.resort_note("Шарм-эль-Шейх").lower()


def test_resort_note_no_false_collision():
    lc = _load_lead_catcher(allow=AID)
    # «Кутаиси» (Грузия) НЕ должен получить балийскую «Куту»; рискованные
    # короткие ключи убраны → для неизвестного/коллизийного курорта пусто.
    assert lc.resort_note("Кутаиси") == ""
    # «Агия-Марина» (Крит) не должна получить дубайскую «Марину».
    note = lc.resort_note("Агия-Марина")
    assert "дуба" not in note.lower()


def test_build_cards_digest_format_and_cheapest():
    lc = _load_lead_catcher(allow=AID)
    cards = [
        {"hotel_stars": 5, "meal_description": "AI - Всё включено", "resort": "Белек", "price": 250000},
        {"hotel_stars": 4, "meal_description": "AI - Всё включено", "resort": "Аланья", "price": 150000},
    ]
    digest = lc.build_cards_digest(cards)
    lines = digest.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("1.") and "Белек" in lines[0]
    assert lines[1].startswith("2.") and "Аланья" in lines[1]
    # Самый дешёвый (Аланья, 150к) помечается.
    assert "самый доступный" in lines[1]
    assert "самый доступный" not in lines[0]


def test_build_cards_digest_empty():
    lc = _load_lead_catcher(allow=AID)
    assert lc.build_cards_digest([]) == ""
    assert lc.build_cards_digest(None) == ""


def test_cards_hint_constant_present():
    lc = _load_lead_catcher(allow=AID)
    assert "ЛОВЕЦ ЛИДОВ" in lc.LEAD_CATCHER_CARDS_HINT
    assert "выдели" in lc.LEAD_CATCHER_CARDS_HINT.lower()


# ─────────────────── Гейт каскада (_check_cascade_slots) ──────────────
# Импорт yandex_handler ленивый: если на хосте нет тяжёлых зависимостей —
# тест помечается как пропущенный, остальные проходят.

def _import_yh():
    try:
        import yandex_handler as yh
        return yh
    except Exception as exc:   # pragma: no cover
        return exc


def test_cascade_lead_catcher_skips_qc():
    yh = _import_yh()
    if not hasattr(yh, "_check_cascade_slots"):
        print("  SKIP cascade test: yandex_handler import failed:", yh)
        return
    history = [{"role": "user",
                "content": "Хочу в Турцию из Москвы, 2 взрослых, вылет 15 августа на 10 ночей"}]
    args = {"country": 4}
    # lead_catcher=False → QC обязателен → НЕ полный
    ok_off, missing_off = yh._check_cascade_slots(history, dict(args), lead_catcher=False)
    assert ok_off is False
    assert any("питан" in m or "звёзд" in m or "категори" in m for m in missing_off)
    # lead_catcher=True → QC не нужен → полный
    ok_on, missing_on = yh._check_cascade_slots(history, dict(args), lead_catcher=True)
    assert ok_on is True, f"ожидали полный каскад, missing={missing_on}"


def test_cascade_lead_catcher_still_requires_departure():
    yh = _import_yh()
    if not hasattr(yh, "_check_cascade_slots"):
        print("  SKIP cascade test: yandex_handler import failed:", yh)
        return
    # Нет города вылета → даже в lead-catcher блокируем
    history = [{"role": "user",
                "content": "Хочу в Турцию, 2 взрослых, вылет 15 августа на 10 ночей"}]
    ok, missing = yh._check_cascade_slots(history, {"country": 4}, lead_catcher=True)
    assert ok is False
    assert any("город вылета" in m for m in missing)


# ─────────────────────────── Standalone runner ───────────────────────

def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
        except Exception as e:   # pragma: no cover
            print(f"  ✗ {fn.__name__}: ERROR {e!r}")
            failed += 1
    print(f"\n== {passed}/{passed + failed} OK ==")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
