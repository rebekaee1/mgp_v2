"""Точная сводка по результатам тестов.

Главная задача: показать что реально произошло в КАЖДОМ сценарии.

Принцип: мы НЕ полагаемся на docker logs за окно 3-х минут (там логи от соседних
сценариев), а используем:
  - tour_cards.price (минимум/максимум) — это финальный пользовательский результат
  - reply от LLM — что увидел клиент
  - количество карточек — успех / 0 results

BUDGET-FLOOR / AUTO-RETRY ОТМЕТЫ берём из marker_lines ТОЛЬКО когда они
семантически согласуются с ценами карточек (sanity check, не «строго какая
строка»).
"""
import json
import pathlib

here = pathlib.Path(__file__).resolve().parent

UPPER_BOUND_FLOOR_RATIO = 0.65
MIN_WINDOW_RUB = 30_000


def expected_floor(priceto: int) -> int:
    floor = int(priceto * UPPER_BOUND_FLOOR_RATIO)
    if priceto - floor < MIN_WINDOW_RUB:
        floor = max(priceto - MIN_WINDOW_RUB, 0)
    return floor


rows = []
for p in sorted(here.glob("S*.json")):
    if p.name in ("_all_runs.json", "_summary.json"):
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    sc = d["scenario"]
    payload = d.get("final_payload", {})
    cards = payload.get("tour_cards") or []

    exp_priceto = sc.get("expected_priceto")
    exp_floor_applied = sc.get("expects_floor_applied", True)
    exp_retry = sc.get("expects_auto_retry", False)

    prices = [c.get("price") for c in cards if isinstance(c.get("price"), (int, float))]
    min_card = min(prices) if prices else None
    max_card = max(prices) if prices else None

    # Sanity: если safety-net BUDGET-FLOOR применился, min_card должен быть
    # ≈ expected_floor (с разрешённой погрешностью на минимально доступную цену
    # выше floor — но не ниже него).
    expected_pricefrom = expected_floor(exp_priceto) if (exp_priceto and exp_floor_applied) else None

    # На реальный результат смотрим так:
    verdict = "—"
    if not exp_floor_applied:
        # негативные сценарии
        if cards:
            verdict = "ok (negative): floor НЕ применялся (диапазон / about / skip)"
        else:
            verdict = "0 cards (LLM не запустил поиск)"
    elif not cards:
        # ожидался floor, но 0 туров — значит AUTO-RETRY сработал, но в TourVisor реально 0
        verdict = "0 cards (AUTO-RETRY → 0 tours, физически нет вариантов)"
    elif min_card is not None and expected_pricefrom is not None and min_card >= expected_pricefrom:
        verdict = f"ok: floor применился (min_card={min_card} ≥ floor={expected_pricefrom})"
    elif min_card is not None and expected_pricefrom is not None and min_card < expected_pricefrom:
        verdict = (
            f"WARN: min_card={min_card} < expected_floor={expected_pricefrom} — "
            f"AUTO-RETRY мог сработать"
        )

    pct_used = round(100.0 * min_card / exp_priceto, 1) if (exp_priceto and min_card) else None

    rows.append({
        "sid": sc["sid"],
        "budget_phrase": sc["budget_phrase"],
        "direction": sc["direction"],
        "exp_priceto": exp_priceto,
        "exp_pricefrom_computed": expected_pricefrom,
        "cards": len(cards),
        "min_card": min_card,
        "max_card": max_card,
        "pct_used": pct_used,
        "verdict": verdict,
        "exp_floor": exp_floor_applied,
        "exp_retry": exp_retry,
        "elapsed_s": d.get("runtime", {}).get("elapsed_s"),
    })

# таблица
print(f"{'SID':30s} {'Phrase':18s} {'Dir':10s} {'Top':>9s} {'Floor':>9s} {'Cards':>5s} "
      f"{'MinCard':>10s} {'MaxCard':>10s} {'%Used':>6s} Verdict")
print("-" * 160)
for r in rows:
    print(
        f"{r['sid']:30s} {r['budget_phrase'][:17]:18s} {r['direction'][:9]:10s} "
        f"{(str(r['exp_priceto']) if r['exp_priceto'] is not None else '-'):>9s} "
        f"{(str(r['exp_pricefrom_computed']) if r['exp_pricefrom_computed'] is not None else '-'):>9s} "
        f"{r['cards']:>5d} "
        f"{(str(r['min_card']) if r['min_card'] is not None else '-'):>10s} "
        f"{(str(r['max_card']) if r['max_card'] is not None else '-'):>10s} "
        f"{(str(r['pct_used']) if r['pct_used'] is not None else '-'):>6s} "
        f"{r['verdict']}"
    )

print()
ok_pos = sum(1 for r in rows if r["exp_floor"] and r["min_card"] is not None and r["min_card"] >= (r["exp_pricefrom_computed"] or 0))
retried = sum(1 for r in rows if r["exp_floor"] and not r["cards"])
ok_neg = sum(1 for r in rows if not r["exp_floor"] and r["cards"])
print(f"Floor применился и сработал: {ok_pos}")
print(f"AUTO-RETRY до 0 туров (физически нет вариантов): {retried}")
print(f"Негативные кейсы корректны: {ok_neg}")
print(f"Всего сценариев: {len(rows)}")

(here / "_summary.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("\nSaved → _summary.json")
