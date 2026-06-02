"""Re-outreach (Feature 1) core logic — pure, offline-testable, no DB/network.

Pipeline per conversation record:
  classify()  -> bucket ('1_engaged'/'4_results'/'5_noresults'/'6_thin'/'7_incomplete')
                 or a ('skip', reason) — exclusions + the "real destination" rule.
  extract_brief() -> structured facts (destination, departure, dates, pax, budget, wishes).
  render_message() -> ONE AnyTour-voice message, deterministic template, guard-railed.
  validate() -> sanity checks (has destination, length, no stale tour price, no 'МГП').

Rules locked with the user:
  * write only if a REAL destination (country/resort) is present — a bare departure
    city or an office question => skip;
  * never restate a previously-shown TOUR price (offer to refresh); the client's OWN
    stated budget MAY be referenced (it's their figure, accurate);
  * one message, AnyTour voice, <=~360 chars, <=1 emoji, polite "вы", never 'МГП';
  * handoff-to-manager and explicit declines => skip.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

ASSISTANT_ANYTOUR = "64fea0d3-2605-4c4c-be67-62258ebfa7a9"
MANAGER_PHONE = "8 (800) 700-29-15"
MAX_LEN = 360

# ── Destination dictionary: canonical display -> alias regex. Order matters
#    (first match wins). Foreign countries + clear resort destinations only;
#    plain departure cities are intentionally NOT here (ambiguous => skip).
_DEST_RULES: list[tuple[str, str, str]] = [
    # (canonical, country_regex, resort_regex)
    ("Турция", r"турци|анталь?[ия]|кемер(?!ов)|алань?я|\bсиде\b|белек|бодрум|мармарис|фетхие|кушадас", r"кемер(?!ов)|анталь?я|алань?я|сиде|белек|бодрум|мармарис|фетхие"),
    ("Египет", r"египет|хургад|шарм|эль.?шейх|эль.?абур|марса.?алам|дахаб|таба", r"хургад|шарм|эль.?абур|марса.?алам|дахаб|таба"),
    ("Таиланд", r"таила?нд|тайла?нд|пхукет|паттай[яи]|краби|самуи", r"пхукет|паттай[яи]|краби|самуи"),
    ("Вьетнам", r"вьетнам|нячанг|муйне|фукуок|фантьет|дананг", r"нячанг|муйне|фукуок|фантьет|дананг"),
    ("ОАЭ", r"\bоаэ\b|эмират|дубай|абу.?даби|шарджа|фуджейр|рас.?эль.?хайм", r"дубай|абу.?даби|шарджа|фуджейр"),
    ("Абхазия", r"абхаз|гагр|пицунд|сухум|гудаут", r"гагр|пицунд|сухум|гудаут"),
    ("Китай (Хайнань)", r"хайнань|сань`?я|\bсанья\b|\bкитай", r"сань`?я|санья"),
    ("Мальдивы", r"мальдив", r""),
    ("Шри-Ланка", r"шри.?ланк|\bланка\b", r""),
    ("Куба", r"\bкуба\b|варадеро", r"варадеро"),
    ("Доминикана", r"доминикан|пунта.?кана", r"пунта.?кана"),
    ("Бали", r"\bбали\b|индонез", r""),
    ("Тунис", r"тунис|хаммамет|\bсус\b|джерба", r"хаммамет|джерба"),
    ("Грузия", r"грузи|батуми|тбилиси|кобулети", r"батуми|кобулети"),
    ("Армения", r"армени|ереван", r""),
    ("Сочи", r"\bсочи\b|адлер|красная поляна", r"адлер|красная поляна"),
    ("Анапа", r"анапа|витязево", r"витязево"),
    ("Крым", r"\bкрым|ялта|севастопол|евпатори|феодоси|\bсудак|алушта|саки", r"ялта|севастопол|евпатори|феодоси|судак|алушта"),
    ("Геленджик", r"геленджик|кабардинк", r"кабардинк"),
    ("Соль-Илецк", r"соль.?илецк", r""),
    ("Кавказские Минводы", r"кисловодск|ессентук|пятигорск|минеральн", r"кисловодск|ессентук|пятигорск"),
    ("Калининград", r"калининград|зеленоградск|светлогорск", r"зеленоградск|светлогорск"),
]
_DEST_COMPILED = [(c, re.compile(cr, re.I), re.compile(rr, re.I) if rr else None) for c, cr, rr in _DEST_RULES]

# Fixed declension table (acc = винительный «в …», prep = предложный «по …»)
# keyed by the canonical BASE (resort-in-parens kept as-is, base declined).
_FORMS: dict[str, tuple[str, str]] = {
    "Турция": ("Турцию", "Турции"), "Египет": ("Египет", "Египте"),
    "Таиланд": ("Таиланд", "Таиланде"), "Вьетнам": ("Вьетнам", "Вьетнаме"),
    "ОАЭ": ("ОАЭ", "ОАЭ"), "Абхазия": ("Абхазию", "Абхазии"),
    "Китай": ("Китай", "Китае"), "Мальдивы": ("Мальдивы", "Мальдивах"),
    "Шри-Ланка": ("Шри-Ланку", "Шри-Ланке"), "Куба": ("Кубу", "Кубе"),
    "Доминикана": ("Доминикану", "Доминикане"), "Бали": ("Бали", "Бали"),
    "Тунис": ("Тунис", "Тунисе"), "Грузия": ("Грузию", "Грузии"),
    "Армения": ("Армению", "Армении"), "Сочи": ("Сочи", "Сочи"),
    "Анапа": ("Анапу", "Анапе"), "Крым": ("Крым", "Крыму"),
    "Геленджик": ("Геленджик", "Геленджике"), "Соль-Илецк": ("Соль-Илецк", "Соль-Илецке"),
    "Кавказские Минводы": ("Кавказские Минводы", "Кавказских Минводах"),
    "Калининград": ("Калининград", "Калининграде"),
}


def decline(dest: Optional[str], case: str = "acc") -> Optional[str]:
    """Decline a resolved destination. case: 'acc' (в …) or 'prep' (по …).
    Resort in parens is kept as-is; only the country base is declined."""
    if not dest:
        return dest
    base, sep, rest = dest.partition(" (")
    forms = _FORMS.get(base)
    if forms:
        base = forms[0] if case == "acc" else forms[1]
    return base + (sep + rest if rest else "")

# Departure cities (used only to render "из {city}" — NOT a destination signal).
_DEPARTURES = [
    ("Москвы", r"москв"), ("Санкт-Петербурга", r"санкт.?петербург|\bспб\b|\bпитер"),
    ("Казани", r"казан"), ("Екатеринбурга", r"екатеринбург|екб"), ("Новосибирска", r"новосибирск"),
    ("Самары", r"самар"), ("Уфы", r"\bуфа|\bуфы"), ("Краснодара", r"краснодар"),
    ("Ростова-на-Дону", r"ростов"), ("Воронежа", r"воронеж"), ("Перми", r"\bперм"),
    ("Омска", r"\bомск"), ("Челябинска", r"челябинск"), ("Тюмени", r"тюмен"),
    ("Кемерово", r"кемеров"), ("Красноярска", r"красноярск"), ("Сочи", r"\bсочи\b"),
    ("Минеральных Вод", r"минеральн"), ("Нижнего Новгорода", r"нижн\w* новгород|\bннов"),
]
_DEP_COMPILED = [(d, re.compile(r, re.I)) for d, r in _DEPARTURES]

# Tourvisor departure code -> city (genitive, for "из {city}"). Authoritative
# source for the departure, mirrors backend _DEPARTURE_CITY_NAMES (99 = no flight).
_DEP_CODE_GEN = {
    1: "Москвы", 2: "Перми", 3: "Екатеринбурга", 4: "Уфы", 5: "Санкт-Петербурга",
    6: "Челябинска", 7: "Самары", 8: "Нижнего Новгорода", 9: "Новосибирска",
    10: "Казани", 11: "Краснодара", 12: "Красноярска", 18: "Ростова-на-Дону", 56: "Сочи",
}

# Tourvisor country code -> name (mirror of backend/dashboard_api.py). Used to
# anchor the destination on the ACTUAL searched country for buckets with a search
# (multi-country dialogues are ambiguous by text alone).
_COUNTRY_NAMES = {
    1: "Египет", 2: "Таиланд", 3: "Индия", 4: "Турция", 5: "Тунис",
    6: "Греция", 7: "Индонезия", 8: "Мальдивы", 9: "ОАЭ", 10: "Куба",
    11: "Доминикана", 12: "Шри-Ланка", 13: "Китай", 14: "Испания",
    15: "Кипр", 16: "Вьетнам", 17: "Андорра", 18: "Мексика",
    19: "Чехия", 20: "Болгария", 21: "Черногория", 22: "Хорватия",
    23: "Марокко", 24: "Италия", 25: "Сингапур", 26: "Филиппины",
    27: "Маврикий", 28: "Сейшелы", 29: "Иордания", 30: "Израиль",
    46: "Абхазия", 47: "Россия", 53: "Армения", 54: "Грузия",
    55: "Азербайджан", 56: "Узбекистан", 57: "Беларусь", 78: "Казахстан",
}

_MONTHS = {1:"январь",2:"февраль",3:"март",4:"апрель",5:"май",6:"июнь",
           7:"июль",8:"август",9:"сентябрь",10:"октябрь",11:"ноябрь",12:"декабрь"}
_MONTHS_GEN = {1:"января",2:"февраля",3:"марта",4:"апреля",5:"мая",6:"июня",
               7:"июля",8:"августа",9:"сентября",10:"октября",11:"ноября",12:"декабря"}


def resolve_destination(text: Optional[str]) -> Optional[str]:
    """Return a human destination ('Турция', 'Вьетнам (Муйне)') or None.

    When the dialogue mentions several countries (client switched their mind),
    we pick the one mentioned LAST — that reflects the client's final intent,
    not the order of our rule table.
    """
    if not text:
        return None
    best = None  # (last_pos, canonical, resort_re)
    for canonical, country_re, resort_re in _DEST_COMPILED:
        positions = [mm.start() for mm in country_re.finditer(text)]
        if positions:
            last = max(positions)
            if best is None or last > best[0]:
                best = (last, canonical, resort_re)
    if best is None:
        return None
    _, canonical, resort_re = best
    if resort_re:
        m = resort_re.search(text)
        if m:
            resort = m.group(0)
            resort = resort[:1].upper() + resort[1:]
            base = canonical.split(" (")[0]
            return f"{base} ({resort})"
    return canonical


def resolve_departure(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for disp, rgx in _DEP_COMPILED:
        if rgx.search(text):
            return disp
    return None


def _fmt_dates(date_from: Optional[str]) -> Optional[str]:
    """'2026-07-06' -> 'на 6 июля'; '2026-07-..' month only -> 'на июль'."""
    if not date_from:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_from)
    if not m:
        return None
    mon = int(m.group(2)); day = int(m.group(3))
    if day and 1 <= mon <= 12:
        return f"на {day} {_MONTHS_GEN[mon]}"
    if 1 <= mon <= 12:
        return f"на {_MONTHS[mon]}"
    return None


def classify(rec: dict) -> Tuple[str, Optional[str]]:
    """Return (bucket, None) or ('skip', reason)."""
    if rec.get("handoff"):
        return "skip", "manager_handoff"
    if rec.get("decline"):
        return "skip", "explicit_decline"
    dest = resolve_destination(rec.get("utext"))
    if not dest:
        return "skip", "no_destination"
    searches = int(rec.get("searches") or 0)
    cards = int(rec.get("cards") or 0)
    clicks = int(rec.get("clicks") or 0)
    umsgs = int(rec.get("umsgs") or 0)
    if rec.get("submitted") or clicks > 0:
        return "1_engaged", None
    if searches >= 1 and cards >= 1:
        return "4_results", None
    if searches >= 1 and cards == 0:
        return "5_noresults", None
    if umsgs <= 1:
        return "6_thin", None
    return "7_incomplete", None


def _resolve_destination_anchored(text, meta) -> Optional[str]:
    """Prefer the ACTUALLY-SEARCHED country (authoritative for multi-country
    dialogues); keep text resolution for resort detail / Russia / no-search."""
    dest_text = resolve_destination(text)
    code = (meta or {}).get("country")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    if code:
        cname = _COUNTRY_NAMES.get(code)
        if cname and cname != "Россия":
            if dest_text and dest_text.split(" (")[0] == cname:
                return dest_text          # same country -> keep resort detail
            return cname                   # searched country wins over ambiguous text
    return dest_text


def extract_brief(rec: dict) -> dict:
    text = rec.get("utext") or ""
    meta = rec.get("search_meta") or {}
    pax = None
    a = meta.get("adults"); kids = meta.get("children")
    if a:
        parts = [f"{a} взрослых" if a != 1 else "1 взрослый"]
        if kids:
            parts.append(f"{kids} ребёнок" if kids == 1 else f"{kids} детей")
        pax = ", ".join(parts)
    budget = meta.get("price_to") or None
    wishes = []
    if re.search(r"все.?включено|всё.?включено|ultra|ультра", text, re.I):
        wishes.append("«всё включено»")
    stars = meta.get("stars")
    if stars and stars >= 4:
        wishes.append(f"{stars}★")
    # Prefer the AUTHORITATIVE departure from the actual search (structured),
    # fall back to text parsing only when no search ran (buckets 6/7).
    dep = _DEP_CODE_GEN.get(meta.get("departure")) or resolve_departure(text)
    return {
        "destination": _resolve_destination_anchored(text, meta),
        "departure": dep,
        "dates": _fmt_dates(meta.get("date_from")),
        "pax": pax,
        "budget": int(budget) if budget else None,
        "wishes": wishes,
    }


def _recap(brief: dict, case: str = "acc", with_pax: bool = False) -> str:
    """declined destination [из dep] [на dates] [, pax]."""
    s = decline(brief["destination"], case)
    if brief.get("departure"):
        s += f" из {brief['departure']}"
    if brief.get("dates"):
        s += f" {brief['dates']}"
    if with_pax and brief.get("pax"):
        s += f", {brief['pax']}"
    return s


def _budget_clause(brief: dict) -> str:
    b = brief.get("budget")
    if b and b >= 30000:
        formatted = f"{b:,}".replace(",", " ")
        return f" под ваш бюджет до {formatted} ₽"
    return ""


def _missing_params(brief: dict) -> str:
    miss = []
    if not brief.get("dates"):
        miss.append("даты")
    if not brief.get("budget"):
        miss.append("примерный бюджет")
    if not brief.get("pax"):
        miss.append("состав")
    if not miss:
        return "удобный для связи способ"
    return " и ".join(miss) if len(miss) <= 2 else ", ".join(miss[:-1]) + " и " + miss[-1]


def render_message(brief: dict, bucket: str, manager_phone: Optional[str] = MANAGER_PHONE) -> str:
    dest_acc = decline(brief["destination"], "acc")
    if bucket == "1_engaged":
        recap = _recap(brief, "acc", with_pax=True)
        phone_clause = f" На связи: {manager_phone}." if manager_phone else ""
        msg = (f"Здравствуйте! Как ваши успехи с поездкой в {recap}? Удалось определиться? "
               f"Если нужно — обновлю подборку под актуальные цены или подберу альтернативу."
               f"{phone_clause}")
    elif bucket == "4_results":
        recap = _recap(brief, "acc", with_pax=True)
        msg = (f"Здравствуйте! Вы смотрели туры в {recap}. Цены могли обновиться — "
               f"прислать свежую подборку{_budget_clause(brief)}?")
    elif bucket == "5_noresults":
        recap5 = _recap(brief, "prep", with_pax=False)
        msg = (f"Здравствуйте! По {recap5} точных вариантов тогда не нашлось. "
               f"Сейчас можно расширить даты/бюджет или поймать новые предложения — подобрать?")
    elif bucket == "6_thin":
        msg = (f"Здравствуйте! Вы интересовались турами в {dest_acc}. Подобрать актуальные варианты? "
               f"Подскажите город вылета, даты и бюджет — и пришлю подборку.")
    elif bucket == "7_incomplete":
        recap = _recap(brief, "acc", with_pax=False)
        msg = (f"Здравствуйте! Вы подбирали тур в {recap}. Готов прислать варианты — "
               f"подскажите {_missing_params(brief)}, и подберу лучшее.")
    else:
        msg = ""
    return re.sub(r"\s+", " ", msg).strip()


_PRICE_RE = re.compile(r"\d[\d\s.,]{2,}\s*(?:₽|руб|тыс\b|т\.?р\.?|000)", re.I)


def validate(msg: str, brief: dict, forbid_stale_price: bool = True) -> Tuple[bool, list]:
    errs = []
    if not msg:
        return False, ["empty"]
    if len(msg) > MAX_LEN:
        errs.append(f"too_long({len(msg)})")
    dest = brief.get("destination")
    if dest:
        # message must mention the destination — accept the country base in any
        # form (nom/acc/prep) OR the resort token (in parens), by stem.
        forms = {dest.split(" (")[0],
                 decline(dest, "acc").split(" (")[0],
                 decline(dest, "prep").split(" (")[0]}
        ok_dest = any(f and f in msg for f in forms)
        if not ok_dest and "(" in dest:
            resort = dest.split("(", 1)[1].rstrip(")").strip()
            if resort and resort[:5] in msg:  # 'Евпатори' matches 'Евпатория/Евпаторию'
                ok_dest = True
        if not ok_dest:
            errs.append("destination_missing")
    if re.search(r"\bмгп\b|магазин горящих", msg, re.I):
        errs.append("mentions_mgp")
    # No stale TOUR price. The client's OWN budget is allowed and rendered as
    # "до X ₽"; strip it, then any remaining price-like token is a violation.
    if forbid_stale_price:
        budget_str = f"{brief['budget']:,}".replace(",", " ") if brief.get("budget") else None
        scan = msg.replace(budget_str, "") if budget_str else msg
        if _PRICE_RE.search(scan):
            errs.append("stale_price")
    emojis = re.findall(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", msg)
    if len(emojis) > 1:
        errs.append("too_many_emoji")
    return (len(errs) == 0), errs
