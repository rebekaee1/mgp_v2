#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тест на РЕАЛЬНОМ рантайм-модуле (как в проде): guard больше не режет
города, которые раньше ложно отклонялись у AnyTour (по данным прод-логов),
и по-прежнему отклоняет несуществующие коды.
"""
import sys
sys.path.insert(0, "backend")
import yandex_handler as yh  # noqa: E402

# Города, которые РАНЬШЕ ложно отклонялись у Павла (из прод-выборки 74 диалогов)
PREV_REJECTED = {
    "Омск": 21, "Оренбург": 28, "Иркутск": 22, "Абакан": 53,
    "Волгоград": 27, "Воронеж": 26, "Сыктывкар": 41, "Ульяновск": 50,
    "Тюмень": 14, "Саратов": 31, "Калининград": 17, "Барнаул": 25,
    "Набережные Челны": 61, "Минеральные Воды": 39, "Магнитогорск": 48,
    "Нижнекамск": 19, "Новый Уренгой": 67, "Новокузнецк": 16,
    "Астрахань": 40, "Архангельск": 29,
}

ok = True
print("=== Guard на реальном модуле: ранее отклонявшиеся города ===")
for name, cid in PREV_REJECTED.items():
    passes = cid in yh._DEPARTURE_CITIES               # guard: НЕ отклоняет
    correct_name = yh._DEPARTURE_CITIES.get(cid)
    line_ok = passes
    ok = ok and line_ok
    print(f"  {'✓' if line_ok else '✗'} {name} (id={cid}) → проходит guard, "
          f"в словаре='{correct_name}'")

print("\n=== Контроль: несуществующие коды по-прежнему отклоняются ===")
for bad in (777, 0, 999, 200):
    rejected = bad not in yh._DEPARTURE_CITIES
    # 0 трактуется как «не указан», guard срабатывает только при dep_code truthy
    ok = ok and rejected
    print(f"  {'✓' if rejected else '✗'} код {bad} → отклоняется (нет в словаре)")

print("\n=== Размер словаря и наличие 99 ===")
print(f"  всего кодов: {len(yh._DEPARTURE_CITIES)} (ожидаем 78)")
print(f"  99 'Без перелёта': {yh._DEPARTURE_CITIES.get(99)!r}")
ok = ok and len(yh._DEPARTURE_CITIES) == 78 and yh._DEPARTURE_CITIES.get(99) == "Без перелёта"

print("\n" + ("ВСЁ ОК ✓" if ok else "ЕСТЬ ОШИБКИ ✗"))
sys.exit(0 if ok else 1)
