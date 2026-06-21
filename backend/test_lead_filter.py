"""Юнит-тесты lead-filter (Павел/Anytour): какие заявки НЕ доводим до менеджеров.

Запуск:
    pytest backend/test_lead_filter.py
    # либо как обычный скрипт (без pytest):
    python3 backend/test_lead_filter.py

Тестируем ЧИСТУЮ логику lead_catcher.lead_suppression_decision() — без БД/сети.
Главный инвариант: пустой/отсутствующий конфиг → None (фича инертна для тенанта).
РФ=47, Абхазия=46.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lead_catcher import lead_suppression_decision as decide  # noqa: E402

PAVEL_LF = {"block_countries": [47, 46], "min_tour_price": 150000}


# ─────────────────────────── Инертность (другие тенанты) ───────────────────────────

def test_no_config_is_inert():
    assert decide(None, 47, 100000) is None
    assert decide({}, 47, 100000) is None
    assert decide("nope", 47, 100000) is None  # type: ignore[arg-type]


# ─────────────────────────── Блокировка по стране ───────────────────────────

def test_block_rf_by_code():
    assert decide(PAVEL_LF, 47, 500000) == "blocked_country"


def test_block_abkhazia_by_code():
    assert decide(PAVEL_LF, 46, 500000) == "blocked_country"


def test_block_by_country_name_backup():
    # код страны неизвестен (None), но карточка брони знает название
    assert decide(PAVEL_LF, None, 500000, dest_country_name="Россия") == "blocked_country"
    assert decide(PAVEL_LF, None, 500000, dest_country_name="абхазия") == "blocked_country"


def test_country_block_priority_over_price():
    # РФ + дорогой тур → всё равно blocked_country (страна важнее цены)
    assert decide(PAVEL_LF, 47, 999999) == "blocked_country"


def test_foreign_country_not_blocked():
    # Турция (4), цена выше порога → пропускаем (None)
    assert decide(PAVEL_LF, 4, 300000) is None
    assert decide(PAVEL_LF, 4, 300000, dest_country_name="Турция") is None


# ─────────────────────────── Порог цены ───────────────────────────

def test_below_min_price():
    assert decide(PAVEL_LF, 4, 120000) == "below_min_price"


def test_exactly_at_floor_not_blocked():
    # ровно 150000 — НЕ дешевле порога → пропускаем
    assert decide(PAVEL_LF, 4, 150000) is None


def test_above_floor_not_blocked():
    assert decide(PAVEL_LF, 4, 200000) is None


def test_unknown_price_not_suppressed_by_floor():
    # цена неизвестна → по порогу НЕ подавляем (не теряем потенциальный лид)
    assert decide(PAVEL_LF, 4, None) is None


# ─────────────────────────── Частичные/битые конфиги ───────────────────────────

def test_only_country_filter():
    lf = {"block_countries": [47, 46]}
    assert decide(lf, 47, 100000) == "blocked_country"
    assert decide(lf, 4, 100000) is None  # порога нет → дешёвый иностранный проходит


def test_only_price_filter():
    lf = {"min_tour_price": 150000}
    assert decide(lf, 47, 100000) == "below_min_price"  # страны нет в фильтре, но дёшево
    assert decide(lf, 47, 500000) is None  # РФ, но дорогой и страна не блокируется


def test_malformed_block_countries_ignored():
    lf = {"block_countries": ["абв", None], "min_tour_price": 150000}
    # битый список стран не роняет логику; порог продолжает работать
    assert decide(lf, 47, 120000) == "below_min_price"
    assert decide(lf, 47, 500000) is None


def test_malformed_min_price_ignored():
    lf = {"block_countries": [47], "min_tour_price": "сто"}
    assert decide(lf, 47, 120000) == "blocked_country"  # страна всё ещё ловится
    assert decide(lf, 4, 120000) is None  # битый порог игнорируется


# ─────────────────────── Интеграция: методы хендлера ───────────────────────
# Проверяем реальные обёртки на YandexGPTHandler (детекция страны из обычного
# поиска + фолбэк на «горящие», name-backup из карточки брони, цена). Если
# yandex_handler не импортируется в окружении — тесты тихо пропускаются.

import types  # noqa: E402

try:
    import yandex_handler as _yh  # noqa: E402
    _HANDLER_OK = True
except Exception:  # noqa: BLE001  # pragma: no cover
    _HANDLER_OK = False


def _mk(widget_config=None, last_search=None, hot_ctx=None, cache=None, actualized=None):
    h = _yh.YandexGPTHandler.__new__(_yh.YandexGPTHandler)
    h.runtime_config = types.SimpleNamespace(widget_config=widget_config)
    h._last_search_params = last_search or {}
    h._hot_subscribe_ctx = hot_ctx or {}
    h._booking_cards_cache = cache or {}
    h._tour_actualized_id = actualized
    return h


def test_handler_inert_without_config():
    if not _HANDLER_OK:
        return
    h = _mk(widget_config=None, last_search={"_country": 47})
    assert h._lead_suppression_reason() is None  # нет lead_filter → инертно


def test_handler_blocks_rf_from_regular_search():
    if not _HANDLER_OK:
        return
    h = _mk(widget_config={"lead_filter": {"block_countries": [47, 46]}},
            last_search={"_country": 47})
    assert h._lead_suppression_reason() == "blocked_country"


def test_handler_blocks_rf_from_hot_fallback():
    if not _HANDLER_OK:
        return
    # обычного поиска не было, страна только в «горящих» контексте
    h = _mk(widget_config={"lead_filter": {"block_countries": [47, 46]}},
            last_search={}, hot_ctx={"_country": 46})
    assert h._dialogue_country_code() == 46
    assert h._lead_suppression_reason() == "blocked_country"


def test_handler_regular_overrides_hot():
    if not _HANDLER_OK:
        return
    # последний обычный поиск — Турция (4); «горящие» РФ устарели → НЕ режем
    h = _mk(widget_config={"lead_filter": {"block_countries": [47, 46]}},
            last_search={"_country": 4}, hot_ctx={"_country": 47})
    assert h._dialogue_country_code() == 4
    assert h._lead_suppression_reason() is None


def test_handler_foreign_not_blocked():
    if not _HANDLER_OK:
        return
    h = _mk(widget_config={"lead_filter": {"block_countries": [47, 46]}},
            last_search={"_country": 4})
    assert h._lead_suppression_reason() is None


def test_handler_booking_card_name_backup():
    if not _HANDLER_OK:
        return
    # поиска нет, но карточка брони знает страну → ловим по имени
    h = _mk(widget_config={"lead_filter": {"block_countries": [47, 46]}})
    assert h._lead_suppression_reason(booking_card={"country": "Россия", "price": 300000}) == "blocked_country"


def test_handler_price_floor_when_enabled():
    if not _HANDLER_OK:
        return
    # порог включён в конфиге (в проде у Павла его НЕ ставим) — проверяем код-путь
    h = _mk(widget_config={"lead_filter": {"block_countries": [47, 46], "min_tour_price": 150000}},
            last_search={"_country": 4})
    assert h._lead_suppression_reason(booking_card={"country": "Турция", "price": 120000}) == "below_min_price"
    assert h._lead_suppression_reason(booking_card={"country": "Турция", "price": 200000}) is None


def test_handler_best_known_price_picks_min_from_cache():
    if not _HANDLER_OK:
        return
    h = _mk(cache={"1": {"price": 250000}, "2": {"price": 180000}, "3": {"price": 0}})
    assert h._best_known_tour_price() == 180000


# ─────────────────────────── Запуск без pytest ───────────────────────────

if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{passed}/{len(funcs)} passed")
    sys.exit(0 if passed == len(funcs) else 1)
