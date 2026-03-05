"""
PDF analytics report renderer for навылет! AI.
Uses fpdf2 (pure Python) to generate professional A4 PDF reports.
"""

from fpdf import FPDF
import os

_MEAL_NAMES = {
    2: "RO (без питания)", 3: "BB (завтрак)", 4: "HB (полупансион)",
    5: "FB (полный пансион)", 6: "HB+ (расш.)", 7: "AI (все включено)",
    8: "FB+ (расш.)", 9: "UAI (ультра AI)",
}
_STARS_LABELS = {2: "2 звезды", 3: "3 звезды", 4: "4 звезды", 5: "5 звезд"}
_DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Brand palette matching the dashboard
PRIMARY = (0, 56, 255)
PRIMARY_LIGHT = (230, 237, 255)
PRIMARY_DARK = (0, 40, 180)
SUCCESS = (16, 185, 129)
SUCCESS_LIGHT = (236, 253, 245)
WARNING = (245, 158, 11)
WARNING_LIGHT = (255, 251, 235)
DANGER = (239, 68, 68)
PURPLE = (124, 58, 237)
PURPLE_LIGHT = (245, 243, 255)
CYAN = (6, 182, 212)
ORANGE = (249, 115, 22)
INDIGO = (79, 70, 229)
PINK = (219, 39, 119)

TEXT_PRIMARY = (15, 23, 42)
TEXT_SECONDARY = (71, 85, 105)
TEXT_TERTIARY = (148, 163, 184)
BG_SUBTLE = (248, 250, 252)
BG_MUTED = (241, 245, 249)
BORDER = (226, 232, 240)
WHITE = (255, 255, 255)

_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")


def _fmt(n):
    if n is None:
        return "--"
    return f"{n:,.0f}".replace(",", " ")


def _needs_page_break(pdf, height_needed):
    return pdf.get_y() + height_needed > pdf.h - pdf.b_margin - 5


class ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self._load_fonts()
        self.set_auto_page_break(auto=True, margin=22)
        self.alias_nb_pages()
        self._page_w = 0

    def _load_fonts(self):
        candidates = [
            ("/System/Library/Fonts/Supplemental/Arial.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            ("/Library/Fonts/Arial Unicode.ttf", None),
            ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
        self._has_unicode_font = False
        for regular, bold in candidates:
            if os.path.isfile(regular):
                self.add_font("RF", "", regular)
                if bold and os.path.isfile(bold):
                    self.add_font("RF", "B", bold)
                else:
                    self.add_font("RF", "B", regular)
                self._has_unicode_font = True
                return

    @property
    def _f(self):
        return "RF" if self._has_unicode_font else "Helvetica"

    @property
    def _content_w(self):
        return self.w - self.l_margin - self.r_margin

    def header(self):
        if self.page_no() == 1:
            return
        self.set_fill_color(*PRIMARY)
        self.rect(0, 0, self.w, 3, "F")
        if os.path.isfile(_LOGO_PATH):
            self.image(_LOGO_PATH, x=self.l_margin, y=5, h=7)
        else:
            self.set_font(self._f, "B", 8)
            self.set_text_color(*PRIMARY)
            self.set_xy(self.l_margin, 5)
            self.cell(40, 7, "навылет! AI")
        self.set_font(self._f, "", 7)
        self.set_text_color(*TEXT_TERTIARY)
        self.set_xy(self.w - self.r_margin - 60, 6)
        self.cell(60, 5, "Аналитический отчёт", align="R")
        self.set_y(16)

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(*BORDER)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_font(self._f, "", 6)
        self.set_text_color(*TEXT_TERTIARY)
        self.set_y(-10)
        self.cell(self._content_w / 2, 4, "навылет! AI  --  Аналитический отчёт")
        self.cell(self._content_w / 2, 4, f"Стр. {self.page_no()}/{{nb}}", align="R")

    # ── Drawing helpers ──

    def _section(self, title, icon_color=PRIMARY):
        if _needs_page_break(self, 30):
            self.add_page()
        self.ln(5)
        y = self.get_y()
        self.set_fill_color(*icon_color)
        self.rect(self.l_margin, y + 1.5, 3, 6, "F")
        self.set_font(self._f, "B", 11)
        self.set_text_color(*TEXT_PRIMARY)
        self.set_xy(self.l_margin + 6, y)
        self.cell(0, 9, title)
        self.ln(11)

    def _subsection(self, title, items_count=0):
        needed = 8 + items_count * 5.5
        if _needs_page_break(self, needed):
            self.add_page()
        self.set_font(self._f, "B", 8)
        self.set_text_color(*TEXT_SECONDARY)
        self.cell(0, 5, title)
        self.ln(5)

    def _bar_row(self, label, value, max_val, color=PRIMARY, label_w=42, bar_w=None):
        if bar_w is None:
            bar_w = self._content_w - label_w - 22
        pct = value / max_val if max_val else 0
        y = self.get_y()

        self.set_font(self._f, "", 7.5)
        self.set_text_color(*TEXT_SECONDARY)
        self.set_xy(self.l_margin, y)
        self.cell(label_w, 4.5, label, align="R")

        bar_x = self.l_margin + label_w + 3
        self.set_fill_color(*BG_MUTED)
        self.rect(bar_x, y + 0.5, bar_w, 3.5, "F")

        if pct > 0:
            self.set_fill_color(*color)
            self.rect(bar_x, y + 0.5, max(pct * bar_w, 1.5), 3.5, "F")

        self.set_font(self._f, "B", 7)
        self.set_text_color(*TEXT_PRIMARY)
        self.set_xy(bar_x + bar_w + 2, y)
        self.cell(16, 4.5, _fmt(value), align="R")
        self.ln(5.5)

    def _kpi_card(self, x, y, w, h, value, label, accent=PRIMARY, subtitle=""):
        self.set_fill_color(*BG_SUBTLE)
        self.rect(x, y, w, h, "F")

        self.set_fill_color(*accent)
        self.rect(x, y, w, 2, "F")

        self.set_font(self._f, "B", 16)
        self.set_text_color(*accent)
        self.set_xy(x + 4, y + 5)
        self.cell(w - 8, 8, str(value))

        self.set_font(self._f, "", 7)
        self.set_text_color(*TEXT_SECONDARY)
        self.set_xy(x + 4, y + 14)
        self.cell(w - 8, 4, label)

        if subtitle:
            self.set_font(self._f, "", 6)
            self.set_text_color(*TEXT_TERTIARY)
            self.set_xy(x + 4, y + 18)
            self.cell(w - 8, 3, subtitle)

    def _funnel_row(self, label, count, total, color, prev_count=None):
        pct = count / total * 100 if total else 0
        y = self.get_y()
        full_w = self._content_w

        self.set_font(self._f, "", 7.5)
        self.set_text_color(*TEXT_SECONDARY)
        self.set_xy(self.l_margin, y)
        self.cell(44, 5, label)

        bar_x = self.l_margin + 46
        bar_w = full_w - 80
        self.set_fill_color(*BG_MUTED)
        self.rect(bar_x, y + 0.8, bar_w, 3.5, "F")

        if pct > 0:
            self.set_fill_color(*color)
            self.rect(bar_x, y + 0.8, max(pct / 100 * bar_w, 1.5), 3.5, "F")

        self.set_font(self._f, "B", 7.5)
        self.set_text_color(*TEXT_PRIMARY)
        self.set_xy(self.l_margin + full_w - 32, y)
        self.cell(32, 5, f"{_fmt(count)}  ({pct:.0f}%)", align="R")

        if prev_count is not None and prev_count > 0 and count < prev_count:
            conv = count / prev_count * 100
            self.set_font(self._f, "", 6)
            self.set_text_color(*TEXT_TERTIARY)
            self.set_xy(bar_x + pct / 100 * bar_w + 2, y - 0.5)
            if bar_x + pct / 100 * bar_w + 20 < self.l_margin + full_w - 35:
                self.cell(20, 5, f"{conv:.0f}%")

        self.ln(6)


def render_report_pdf(data: dict, logo_path=None) -> bytes:
    pdf = ReportPDF()
    pdf.add_page()

    period_label = data.get("period_label", "30 дней")
    generated = data.get("generated_at", "")
    bm = data.get("business_metrics", {})
    funnel = data.get("funnel", {})

    # ═══════════════════════════════════════════════════════════════════════════
    # PAGE 1: COVER + KPIs + FUNNEL
    # ═══════════════════════════════════════════════════════════════════════════

    # -- Branded header bar --
    pdf.set_fill_color(*PRIMARY)
    pdf.rect(0, 0, pdf.w, 40, "F")

    pdf.set_fill_color(*PRIMARY_DARK)
    pdf.rect(0, 38, pdf.w, 2, "F")

    if os.path.isfile(_LOGO_PATH):
        pdf.image(_LOGO_PATH, x=pdf.l_margin, y=8, h=12)
    else:
        pdf.set_font(pdf._f, "B", 16)
        pdf.set_text_color(*WHITE)
        pdf.set_xy(pdf.l_margin, 8)
        pdf.cell(60, 12, "навылет! AI")

    pdf.set_font(pdf._f, "B", 18)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(pdf.l_margin, 22)
    pdf.cell(0, 8, "Аналитический отчёт")

    pdf.set_font(pdf._f, "", 9)
    pdf.set_text_color(200, 215, 255)
    pdf.set_xy(pdf.w - pdf.r_margin - 80, 10)
    pdf.cell(80, 5, f"Период: {period_label}", align="R")
    pdf.set_xy(pdf.w - pdf.r_margin - 80, 16)
    pdf.cell(80, 5, f"Дата: {generated}", align="R")

    pdf.set_y(46)

    # -- KPI cards (2 rows x 3) --
    cw = (pdf._content_w - 8) / 3
    ch = 24
    x0 = pdf.l_margin
    y0 = pdf.get_y()

    cards = [
        (_fmt(bm.get("inquiries_handled", 0)), "Обработано обращений", PRIMARY, ""),
        (_fmt(bm.get("tours_offered", 0)), "Туров подобрано", CYAN, ""),
        (_fmt(bm.get("potential_leads", 0)), "Потенциальные лиды", SUCCESS, ""),
        (f'{bm.get("after_hours_pct", 0)}%', "Работа 24/7", PURPLE, "в нерабочее время"),
        (_fmt(bm.get("booking_intents", 0)), "Запросы на бронь", ORANGE, ""),
        (f'{bm.get("engagement_pct", 0)}%', "Вовлечённость", INDIGO, ""),
    ]
    for i, (val, label, color, sub) in enumerate(cards):
        col = i % 3
        row = i // 3
        pdf._kpi_card(x0 + col * (cw + 4), y0 + row * (ch + 3), cw, ch, val, label, color, sub)

    pdf.set_y(y0 + 2 * (ch + 3) + 4)

    # -- Funnel --
    pdf._section("Воронка конверсии", PRIMARY)
    total = funnel.get("total", 1) or 1
    steps = [
        ("Все диалоги", funnel.get("total", 0), PRIMARY),
        ("Вовлечённые (>= 2 сообщ.)", funnel.get("engaged", 0), (59, 130, 246)),
        ("Показаны карточки туров", funnel.get("with_results", 0), (96, 165, 250)),
        ("Потенциальные лиды", funnel.get("potential_leads", 0), SUCCESS),
        ("Запросы на бронь", funnel.get("booking_intent", 0), ORANGE),
    ]
    prev = None
    for label, count, color in steps:
        pdf._funnel_row(label, count, total, color, prev)
        prev = count

    # -- AI Report --
    report_text = data.get("ai_report_text", "")
    if report_text:
        pdf._section("AI-аналитика", SUCCESS)
        content_lines = [l.strip() for l in report_text.split("\n") if l.strip()]

        ai_x = pdf.l_margin
        ai_w = pdf._content_w

        y_start = pdf.get_y()
        pdf.set_font(pdf._f, "", 7.5)
        test_y = y_start + 6
        for line in content_lines:
            line_h = pdf.get_string_width(line) / (ai_w - 16) * 4 + 4.5
            test_y += line_h
        box_h = test_y - y_start + 4

        if _needs_page_break(pdf, box_h):
            pdf.add_page()
            y_start = pdf.get_y()

        pdf.set_fill_color(*SUCCESS_LIGHT)
        pdf.rect(ai_x, y_start, ai_w, box_h, "F")
        pdf.set_fill_color(*SUCCESS)
        pdf.rect(ai_x, y_start, 2.5, box_h, "F")

        pdf.set_font(pdf._f, "", 7.5)
        pdf.set_text_color(*TEXT_PRIMARY)
        pdf.set_xy(ai_x + 8, y_start + 4)
        for line in content_lines:
            pdf.multi_cell(ai_w - 16, 4, line)
            pdf.set_x(ai_x + 8)
            pdf.ln(0.5)

        pdf.set_y(y_start + box_h + 4)

    # ═══════════════════════════════════════════════════════════════════════════
    # GEOGRAPHY
    # ═══════════════════════════════════════════════════════════════════════════
    destinations = data.get("destinations", [])
    departures = data.get("departures", [])
    destinations = [d for d in destinations if d.get("count", 0) > 0]
    departures = [d for d in departures if d.get("count", 0) > 0]

    if destinations or departures:
        pdf._section("География", PRIMARY)

        if destinations:
            items = destinations[:8]
            pdf._subsection("Популярные направления", len(items))
            d_max = max(d["count"] for d in items)
            for d in items:
                pdf._bar_row(d["name"], d["count"], d_max, PRIMARY)

        if departures:
            items = departures[:8]
            pdf.ln(1)
            pdf._subsection("Города вылета", len(items))
            dep_max = max(d["count"] for d in items)
            for d in items:
                pdf._bar_row(d["name"], d["count"], dep_max, (59, 130, 246))

    # ═══════════════════════════════════════════════════════════════════════════
    # SEARCH PREFERENCES
    # ═══════════════════════════════════════════════════════════════════════════
    stars_data = data.get("stars", [])
    meals_data = data.get("meals", [])
    budgets_data = [b for b in data.get("budgets", []) if b.get("count", 0) > 0]
    budget_vs_price = data.get("budget_vs_price", {})

    has_prefs = stars_data or meals_data or budgets_data
    if has_prefs:
        pdf._section("Предпочтения поиска", WARNING)

        if stars_data:
            pdf._subsection("Звёздность отелей", len(stars_data))
            s_max = max(s["count"] for s in stars_data)
            for s in stars_data:
                label = _STARS_LABELS.get(s["stars"], f'{s["stars"]} зв.')
                pdf._bar_row(label, s["count"], s_max, WARNING)

        if meals_data:
            items = meals_data[:6]
            pdf.ln(1)
            pdf._subsection("Тип питания", len(items))
            m_max = max(m["count"] for m in items)
            for m in items:
                label = _MEAL_NAMES.get(m["meal"], str(m["meal"]))
                pdf._bar_row(label, m["count"], m_max, SUCCESS)

        if budgets_data:
            pdf.ln(1)
            pdf._subsection("Бюджет", len(budgets_data))
            b_max = max(b["count"] for b in budgets_data)
            for b in budgets_data:
                pdf._bar_row(b["range"], b["count"], b_max, PURPLE)

        avg_b = budget_vs_price.get("avg_budget")
        avg_f = budget_vs_price.get("avg_found")
        if avg_b or avg_f:
            pdf.ln(2)
            y_bp = pdf.get_y()
            bpw = (pdf._content_w - 6) / 2
            for i, (val, label, color) in enumerate([
                (_fmt(avg_b) + " руб.", "Средний бюджет клиента", PURPLE),
                (_fmt(avg_f) + " руб.", "Средняя найденная цена", SUCCESS),
            ]):
                pdf._kpi_card(
                    pdf.l_margin + i * (bpw + 6), y_bp, bpw, 22, val, label, color
                )
            pdf.set_y(y_bp + 26)

    # ═══════════════════════════════════════════════════════════════════════════
    # DEMAND
    # ═══════════════════════════════════════════════════════════════════════════
    nights_data = [n for n in data.get("nights_distribution", []) if n.get("count", 0) > 0]
    groups_data = [g for g in data.get("group_sizes", []) if g.get("count", 0) > 0]
    travel_dates = [t for t in data.get("travel_dates", []) if t.get("count", 0) > 0]

    if nights_data or groups_data or travel_dates:
        pdf._section("Анализ спроса", CYAN)

        if nights_data:
            pdf._subsection("Длительность поездки", len(nights_data))
            n_max = max(n["count"] for n in nights_data)
            for n in nights_data:
                pdf._bar_row(f'{n["nights"]} ноч.', n["count"], n_max, CYAN)

        if groups_data:
            items = groups_data[:6]
            pdf.ln(1)
            pdf._subsection("Состав группы", len(items))
            g_max = max(g["count"] for g in items)
            for g_item in items:
                pdf._bar_row(g_item["group"], g_item["count"], g_max, PINK)

        if travel_dates:
            pdf.ln(1)
            pdf._subsection("Желаемые даты вылета", len(travel_dates))
            td_max = max(t["count"] for t in travel_dates)
            for t in travel_dates:
                pdf._bar_row(t["month"], t["count"], td_max, ORANGE)

    # ═══════════════════════════════════════════════════════════════════════════
    # ACTIVITY
    # ═══════════════════════════════════════════════════════════════════════════
    heatmap = data.get("heatmap", [])
    day_dist = [d for d in data.get("day_distribution", []) if d.get("count", 0) > 0]
    hour_dist = data.get("hour_distribution", [])
    has_heatmap = heatmap and any(any(row) for row in heatmap)

    if has_heatmap or day_dist:
        pdf._section("Активность", INDIGO)

        if has_heatmap:
            heatmap_h = 7 * 5.5 + 10
            if _needs_page_break(pdf, heatmap_h):
                pdf.add_page()

            pdf._subsection("Тепловая карта (по МСК)")
            max_val = max(max(row) for row in heatmap)
            cell_w = (pdf._content_w - 14) / 24
            cell_h = 5
            start_x = pdf.l_margin + 14

            pdf.set_font(pdf._f, "", 5)
            pdf.set_text_color(*TEXT_TERTIARY)
            for h in range(24):
                pdf.set_xy(start_x + h * cell_w, pdf.get_y())
                pdf.cell(cell_w, 3, str(h), align="C")
            pdf.ln(3.5)

            for dow in range(7):
                y_row = pdf.get_y()
                pdf.set_font(pdf._f, "", 6.5)
                pdf.set_text_color(*TEXT_SECONDARY)
                pdf.set_xy(pdf.l_margin, y_row)
                pdf.cell(12, cell_h, _DAY_NAMES[dow], align="R")

                for h in range(24):
                    val = heatmap[dow][h] if dow < len(heatmap) and h < len(heatmap[dow]) else 0
                    if max_val > 0 and val > 0:
                        intensity = val / max_val
                        r = int(230 - intensity * 180)
                        g = int(237 - intensity * 137)
                        b = int(255 - intensity * 55)
                        pdf.set_fill_color(r, g, b)
                    else:
                        pdf.set_fill_color(*BG_MUTED)
                    pdf.rect(
                        start_x + h * cell_w + 0.3, y_row + 0.3,
                        cell_w - 0.6, cell_h - 0.6, "F"
                    )
                pdf.ln(cell_h)
            pdf.ln(3)

        if day_dist:
            pdf._subsection("По дням недели", len(day_dist))
            d_max = max(d["count"] for d in day_dist)
            for d in day_dist:
                pdf._bar_row(d["day"], d["count"], d_max, INDIGO)

        if hour_dist:
            peak = sorted(hour_dist, key=lambda x: -x["count"])[:5]
            peak = [p for p in peak if p["count"] > 0]
            if peak:
                pdf.ln(1)
                pdf._subsection("Пиковые часы", len(peak))
                p_max = max(p["count"] for p in peak)
                for p in peak:
                    pdf._bar_row(f'{p["hour"]}:00', p["count"], p_max, INDIGO)

    # ═══════════════════════════════════════════════════════════════════════════
    # PERFORMANCE
    # ═══════════════════════════════════════════════════════════════════════════
    perf = data.get("performance", {})
    if perf:
        pdf._section("Производительность", DANGER)

        y_p = pdf.get_y()
        pw = (pdf._content_w - 8) / 3
        perf_cards = [
            (f'{perf.get("avg_response_sec", 0)} сек', "Время ответа", PRIMARY),
            (str(perf.get("avg_messages_per_conversation", 0)), "Сообщений / диалог", CYAN),
            (f'{perf.get("avg_duration_minutes", 0)} мин', "Длительность диалога", PURPLE),
        ]
        for i, (val, label, color) in enumerate(perf_cards):
            pdf._kpi_card(pdf.l_margin + i * (pw + 4), y_p, pw, 22, val, label, color)
        pdf.set_y(y_p + 26)

        perf_pcts = [
            ("Пустых поисков", perf.get("empty_search_pct", 0)),
            ("Повторных поисков", perf.get("retry_pct", 0)),
            ("Без результатов", perf.get("no_result_pct", 0)),
        ]
        y_pct = pdf.get_y()
        for i, (label, val) in enumerate(perf_pcts):
            x_pos = pdf.l_margin + i * (pw + 4)
            bg = (254, 242, 242) if val > 25 else BG_SUBTLE
            pdf.set_fill_color(*bg)
            pdf.rect(x_pos, y_pct, pw, 16, "F")

            color = DANGER if val > 25 else WARNING if val > 15 else TEXT_PRIMARY
            pdf.set_font(pdf._f, "B", 13)
            pdf.set_text_color(*color)
            pdf.set_xy(x_pos + 4, y_pct + 2)
            pdf.cell(pw - 8, 6, f"{val}%")

            pdf.set_font(pdf._f, "", 6.5)
            pdf.set_text_color(*TEXT_SECONDARY)
            pdf.set_xy(x_pos + 4, y_pct + 9)
            pdf.cell(pw - 8, 4, label)

        pdf.set_y(y_pct + 20)

    # ═══════════════════════════════════════════════════════════════════════════
    # FINAL FOOTER
    # ═══════════════════════════════════════════════════════════════════════════
    pdf.ln(6)
    y_end = pdf.get_y()
    if y_end + 14 > pdf.h - pdf.b_margin:
        pdf.add_page()
    pdf.set_fill_color(*BG_SUBTLE)
    pdf.rect(pdf.l_margin, pdf.get_y(), pdf._content_w, 10, "F")
    pdf.set_font(pdf._f, "", 6.5)
    pdf.set_text_color(*TEXT_TERTIARY)
    pdf.set_xy(pdf.l_margin + 4, pdf.get_y() + 3)
    pdf.cell(0, 4, f"Отчёт сгенерирован автоматически  |  навылет! AI  |  {generated}")

    return pdf.output()
