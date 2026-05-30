#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Детерминированный локальный тест правки городов вылета.

Проверяет (без поднятия стека / без LLM), что после правки:
  T1  _DEPARTURE_CITIES в коде == полный живой список Tourvisor (78 кодов).
  T2  guard (dep_code in _DEPARTURE_CITIES) НЕ режет ни один из реальных городов.
  T3  _DEPARTURE_VALIDATION: «вылет из <город>» → ВЕРНЫЙ ID (first-match),
      без cross-match на чужой город.
  T4  _DEPARTURE_VERIFY покрывает все ID и матчит свой город.
  T5  Города-направления («в Сочи», «в Анапу», «в Казань» …) НЕ трактуются
      как город вылета (нет ложного departure).
  T6  Синонимы (СПб/Питер/Екб/ННов/Минводы) → правильный ID.
  T7  «Без перелёта»/«поезд»/«автобус» → 99.
  T8  Таблица 6.2 в system_prompt.md == живой список (по ID).
  T9  В промпте больше НЕТ противоречивых запретов.

Запуск:  python3 .test_results/departures_fix/test_departures.py
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
HANDLER = os.path.join(ROOT, "backend", "yandex_handler.py")
PROMPT = os.path.join(ROOT, "system_prompt.md")
LIVE = os.path.join(HERE, "tv_departures_live.json")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))


# ── Извлекаем константы из кода через AST (без импорта модуля) ──
def extract_const(name: str):
    with open(HANDLER, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return ast.literal_eval(node.value)
    raise RuntimeError(f"{name} not found")


_DEPARTURE_CITIES = extract_const("_DEPARTURE_CITIES")
_DEPARTURE_VALIDATION = extract_const("_DEPARTURE_VALIDATION")
_DEPARTURE_VERIFY = extract_const("_DEPARTURE_VERIFY")

with open(LIVE, "r", encoding="utf-8") as f:
    live = json.load(f)

live_by_id = {int(d["id"]): d for d in live}
live_ids = set(live_by_id)            # incl. 99
live_city_ids = {i for i in live_ids if i != 99}


def first_match_id(text: str):
    """Повторяет логику handler: lower + первый матч в _DEPARTURE_VALIDATION."""
    t = text.lower()
    for pattern, dep_id in _DEPARTURE_VALIDATION:
        if re.search(pattern, t):
            return dep_id
    return None


print("\n=== T1: _DEPARTURE_CITIES (код) == живой список Tourvisor ===")
code_ids = set(_DEPARTURE_CITIES)
missing = sorted(live_ids - code_ids)
extra = sorted(code_ids - live_ids)
check("Нет недостающих городов в коде", not missing,
      f"missing={[ (i, live_by_id[i]['name']) for i in missing]}" if missing else f"{len(code_ids)} кодов")
check("Нет лишних городов в коде", not extra, f"extra={extra}" if extra else "ok")

print("\n=== T2: guard НЕ режет ни один реальный город ===")
rejected = [i for i in live_city_ids if i not in _DEPARTURE_CITIES]
check("Все 77 городов проходят guard (dep in _DEPARTURE_CITIES)", not rejected,
      f"rejected={rejected}" if rejected else "все проходят")
# Контроль: явно несуществующий код всё ещё отклоняется
check("Несуществующий код (777) корректно отклоняется", 777 not in _DEPARTURE_CITIES)

print("\n=== T3: _DEPARTURE_VALIDATION — «вылет из <город>» → верный ID ===")
val_fail = []
for cid in sorted(live_city_ids):
    namefrom = live_by_id[cid]["namefrom"]
    phrase = f"добрый день, планирую тур, вылет из {namefrom.lower()}"
    got = first_match_id(phrase)
    if got != cid:
        val_fail.append((cid, namefrom, got, _DEPARTURE_CITIES.get(got)))
check("Каждый город из своего «из <namefrom>» резолвится верно (no cross-match)",
      not val_fail,
      "ВСЕ 77 ок" if not val_fail else f"ошибки: {val_fail[:8]}")

print("\n=== T4: _DEPARTURE_VERIFY покрывает все ID и матчит свой город ===")
ver_missing = sorted(set(_DEPARTURE_CITIES) - set(_DEPARTURE_VERIFY))
check("VERIFY покрывает все ID из _DEPARTURE_CITIES", not ver_missing,
      f"missing={ver_missing}" if ver_missing else "ok")
ver_fail = []
for cid in sorted(live_city_ids):
    pat = _DEPARTURE_VERIFY.get(cid)
    namefrom = live_by_id[cid]["namefrom"].lower()
    if not pat or not re.search(pat, namefrom):
        ver_fail.append((cid, live_by_id[cid]["name"], pat))
check("VERIFY-паттерн матчит namefrom своего города", not ver_fail,
      "ВСЕ ок" if not ver_fail else f"ошибки: {ver_fail[:8]}")

print("\n=== T5: города-направления НЕ трактуются как город вылета ===")
dest_phrases = [
    "хочу поехать в сочи",
    "тур в анапу на двоих",
    "отдых в геленджике",
    "хочу в казань",
    "поехать в санкт-петербург",
    "тур в москву",
    "отдых в калининграде",
    "хочу в крым",
]
dest_fail = [(p, first_match_id(p)) for p in dest_phrases if first_match_id(p) is not None]
check("«в <город>» (направление) не даёт departure", not dest_fail,
      "ок" if not dest_fail else f"ложно: {dest_fail}")

print("\n=== T6: синонимы → правильный ID ===")
syn = [
    ("вылет из спб", 5), ("из питера", 5), ("из санкт-петербурга", 5),
    ("из екб", 3), ("из еката", 3),
    ("из ннов", 8), ("из нижнего новгорода", 8),
    ("из минвод", 39), ("вылет из мин. вод", 39),
    ("из мск... вылет из москвы", 1),
    ("из набережных челнов", 61), ("из наб.челнов", 61),
    ("из южно-сахалинска", 24), ("из петропавловска-камчатского", 43),
]
syn_fail = [(p, exp, first_match_id(p)) for p, exp in syn if first_match_id(p) != exp]
check("Синонимы резолвятся верно", not syn_fail,
      "ок" if not syn_fail else f"ошибки: {syn_fail}")

print("\n=== T7: «без перелёта» / поезд / автобус → 99 ===")
nf = ["без перелёта", "только отель без перелета", "хочу на поезде", "автобусный тур", "поездом"]
nf_fail = [(p, first_match_id(p)) for p in nf if first_match_id(p) != 99]
check("No-flight фразы → 99", not nf_fail, "ок" if not nf_fail else f"ошибки: {nf_fail}")

print("\n=== T8: таблица 6.2 в промпте == живой список (по ID) ===")
with open(PROMPT, "r", encoding="utf-8") as f:
    prompt_text = f.read()
m = re.search(r"### 6\.2[^\n]*\n(.*?)(?:\n### )", prompt_text, re.S)
table_block = m.group(1) if m else ""
# Извлекаем все пары «название | число»
pairs = re.findall(r"\|\s*([A-Za-zА-Яа-яЁё.\- ]+?)\s*\|\s*(\d+)\s*", table_block)
prompt_ids = {int(num) for _, num in pairs}
p_missing = sorted(live_ids - prompt_ids)
p_extra = sorted(prompt_ids - live_ids)
check("Таблица 6.2 содержит все ID живого списка", not p_missing,
      f"missing={p_missing}" if p_missing else f"{len(prompt_ids)} ID")
check("В таблице 6.2 нет лишних/неверных ID", not p_extra,
      f"extra={p_extra}" if p_extra else "ok")
# Архангельск (29) присутствует с правильным ID
arh = [(n, int(num)) for n, num in pairs if "рхангельск" in n]
check("Архангельск=29 присутствует в таблице 6.2", arh == [("Архангельск", 29)], str(arh))

print("\n=== T9: в промпте убраны противоречивые запреты ===")
banned = [
    "Города вне этого списка НЕДОСТУПНЫ",
    "Используй ТОЛЬКО города из таблицы 6.2",
    "они НЕ поддерживаются агентством",
]
present = [b for b in banned if b in prompt_text]
check("Старые запреты удалены", not present, "ок" if not present else f"осталось: {present}")
# И появился гибридный ориентир
check("Появилась инструкция доверять get_dictionaries(type=departure)",
      "get_dictionaries(type=departure)" in table_block or
      "источник истины" in prompt_text)

# ── Итог ──
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 60)
print(f"ИТОГО: {passed}/{total} проверок пройдено")
if passed != total:
    print("ПРОВАЛЕНЫ:")
    for n, ok, d in results:
        if not ok:
            print(f"  ✗ {n} — {d}")
print("=" * 60)
sys.exit(0 if passed == total else 1)
