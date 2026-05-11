"""Unit-sanity для safety-net BUDGET-FLOOR.

Проверяем:
  1) regex триггера — позитивные/негативные случаи.
  2) Boundary cases для вычисления нижней границы (priceto × 0.65 c MIN_WIDTH 30 000 ₽).
  3) Не конфликтует с «около N» (тот должен срабатывать первым).

Запускается без docker и без LLM — чистый sanity на правила.
Можно так:

    python3 .test_results/budget_upper_floor/test_regex_and_boundaries.py
"""
from __future__ import annotations

import re
import sys
from typing import Optional

# Скопировано из backend/yandex_handler.py (Safety-net BUDGET-FLOOR).
# Если правишь регулярку в проде — поправь и здесь.
ABOUT_RE = re.compile(r"(?:около|примерно|порядка|в\s+район[еу]|плюс.?минус)")
UPPER_ONLY_RE = re.compile(
    r"(?:до\s+\d|не\s+(?:более|выше|дороже|больше)\s*\d|"
    r"максимум\s*\d|в\s+пределах\s*\d|бюджет\s+до\s+\d)",
    re.IGNORECASE,
)

UPPER_BOUND_FLOOR_RATIO = 0.65
MIN_WINDOW_RUB = 30_000


def compute_floor(priceto: int) -> int:
    """Зеркальная функция блока Safety-net BUDGET-FLOOR."""
    floor = int(priceto * UPPER_BOUND_FLOOR_RATIO)
    if priceto - floor < MIN_WINDOW_RUB:
        floor = max(priceto - MIN_WINDOW_RUB, 0)
    return floor


def classify(text: str) -> str:
    """Какой safety-net сработает на этом тексте?

    Возвращает: 'about' | 'upper_only' | 'none'.
    Логика повторяет порядок if/elif в yandex_handler.py.
    """
    txt = text.lower()
    if ABOUT_RE.search(txt):
        return "about"
    if UPPER_ONLY_RE.search(txt):
        return "upper_only"
    return "none"


POSITIVE_UPPER_ONLY: list[str] = [
    "до 100к",
    "до 100000",
    "до 150 тыс",
    "до 300к на двоих",
    "не более 200",
    "не более 250к",
    "не выше 180000",
    "не дороже 300",
    "не больше 500к",
    "максимум 200к",
    "максимум 350000",
    "в пределах 250",
    "в пределах 300к",
    "бюджет до 400к",
    "бюджет до 1 миллиона рублей до 1000000",
    "ну, до 250 максимум",
    "до 300",
]

POSITIVE_ABOUT: list[str] = [
    "около 200к",
    "примерно 150",
    "порядка 250000",
    "в районе 300к",
    "плюс минус 200к",
    "плюс-минус 200к",
]

NEGATIVE: list[str] = [
    "любой бюджет",
    "не важен",
    "150-200к",
    "100к-200к",
    "от 200к",
    "150 200",
    "пропустим",
    "как получится",
    "150 тыс",
    "200 тысяч на руки",
]


def test_regex() -> tuple[int, int, list[str]]:
    passed = 0
    failed = 0
    errors: list[str] = []

    for txt in POSITIVE_UPPER_ONLY:
        got = classify(txt)
        if got == "upper_only":
            passed += 1
        else:
            failed += 1
            errors.append(f"[expect upper_only got {got}] {txt!r}")

    for txt in POSITIVE_ABOUT:
        got = classify(txt)
        if got == "about":
            passed += 1
        else:
            failed += 1
            errors.append(f"[expect about got {got}] {txt!r}")

    for txt in NEGATIVE:
        got = classify(txt)
        if got == "none":
            passed += 1
        else:
            failed += 1
            errors.append(f"[expect none got {got}] {txt!r}")

    return passed, failed, errors


BOUNDARY_CASES: list[tuple[int, int]] = [
    # (priceto, expected_floor)
    (30_000, 0),         # priceto = MIN_WIDTH → floor = 0 (нельзя ниже)
    (50_000, 20_000),    # min-width защитил: 50k − 30k = 20k (а не int(50k * 0.65) = 32500)
    (80_000, 50_000),    # 0.65 × 80k = 52000, но 80k − 50k = 30k OK → 52000? нет: 80k-50k=30k ≥ MIN_WINDOW
                          # Лучше пересчитаем: floor=int(80k*0.65)=52000, 80k-52k=28k < 30k → floor = 80k-30k = 50000.
    (100_000, 65_000),   # 0.65 × 100k = 65000, окно 35k ≥ 30k → 65000
    (150_000, 97_500),   # 0.65 × 150k = 97500, окно 52500 → 97500
    (200_000, 130_000),  # 0.65 × 200k = 130000, окно 70k → 130000
    (300_000, 195_000),  # 0.65 × 300k = 195000, окно 105k → 195000
    (500_000, 325_000),  # 0.65 × 500k = 325000, окно 175k → 325000
    (1_000_000, 650_000),
]


def test_boundaries() -> tuple[int, int, list[str]]:
    passed = 0
    failed = 0
    errors: list[str] = []
    for priceto, expected in BOUNDARY_CASES:
        got = compute_floor(priceto)
        if got == expected:
            passed += 1
        else:
            failed += 1
            errors.append(f"compute_floor({priceto}) = {got}, expected {expected}")
    return passed, failed, errors


def test_precedence_about_over_upper_only() -> tuple[int, int, list[str]]:
    """Если в тексте есть и «около», и «до» — должен сработать ABOUT (он первый в if/elif)."""
    txt = "около 200к, но не более 250"
    got = classify(txt)
    if got == "about":
        return 1, 0, []
    return 0, 1, [f"precedence failed: expected 'about' on {txt!r}, got {got}"]


def main() -> int:
    total_pass = 0
    total_fail = 0
    all_errors: list[str] = []

    for name, fn in [
        ("regex", test_regex),
        ("boundary", test_boundaries),
        ("precedence", test_precedence_about_over_upper_only),
    ]:
        p, f, errs = fn()
        total_pass += p
        total_fail += f
        all_errors.extend(errs)
        print(f"  {name:12s}  pass={p}  fail={f}")

    print()
    if total_fail == 0:
        print(f"OK — {total_pass} checks passed")
        return 0
    print(f"FAIL — {total_pass} passed, {total_fail} failed")
    for err in all_errors:
        print(f"  - {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
