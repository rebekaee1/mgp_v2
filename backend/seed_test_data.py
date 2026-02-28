#!/usr/bin/env python3
"""
Seed script: inserts 7 realistic test conversations into the database.
Uses real TourVisor API field format, real hotel names, real country/departure IDs,
and realistic price ranges for 2026 season.

Usage:
    cd backend && python3 seed_test_data.py
"""

import uuid
import json
import random
from datetime import datetime, timedelta, timezone

from config import settings
from database import init_db, get_db
from models import Assistant, Conversation, Message, TourSearch


def _ts(days_ago, hour=10, minute=0):
    return datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=days_ago)


def _tool_call(name, args_dict):
    return [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args_dict, ensure_ascii=False)}}]


def _card(hotel_name, stars, country, resort, meal_desc, price, nights, operator, fly_date, image_url=None):
    """Build a tour card matching the real _map_hotel_to_card format."""
    return {
        "hotel_name": hotel_name,
        "hotel_stars": stars,
        "hotel_rating": round(random.uniform(3.8, 4.9), 1),
        "country": country,
        "resort": resort,
        "region": resort,
        "date_from": fly_date,
        "date_to": None,
        "nights": nights,
        "price": price,
        "price_per_person": None,
        "food_type": "",
        "meal_description": meal_desc,
        "room_type": "Standard",
        "image_url": image_url,
        "hotel_link": "#",
        "id": str(uuid.uuid4().hex[:16]),
        "departure_city": "Москва",
        "is_hotel_only": False,
        "flight_included": True,
        "operator": operator,
    }


def _hot_card(hotel_name, stars, country, resort, meal_code, meal_ru, price_pp, nights, operator, fly_date, image_url=None):
    """Build a hot tour card matching _map_hot_tour_to_card format (price per person)."""
    return {
        "hotel_name": hotel_name,
        "hotel_stars": stars,
        "hotel_rating": round(random.uniform(3.5, 4.8), 1),
        "country": country,
        "resort": resort,
        "region": resort,
        "date_from": fly_date,
        "date_to": None,
        "nights": nights,
        "price": price_pp,
        "price_per_person": price_pp,
        "food_type": meal_code,
        "meal_description": meal_ru,
        "room_type": "Standard",
        "image_url": image_url,
        "hotel_link": "#",
        "id": str(uuid.uuid4().hex[:16]),
        "departure_city": "Москва",
        "is_hotel_only": False,
        "flight_included": True,
        "operator": operator,
    }


def seed():
    if not init_db(settings.database_url):
        print("ERROR: Cannot connect to database")
        return

    with get_db() as db:
        if db is None:
            print("ERROR: DB session unavailable")
            return

        assistant = db.query(Assistant).first()
        if not assistant:
            print("ERROR: No assistant found. Run cli.py create-user first.")
            return

        aid = assistant.id
        print(f"Using assistant: {assistant.name} (id={aid})")

        # Clear existing conversations for a clean slate
        from models import Conversation as Conv
        old_count = db.query(Conv).count()
        if old_count > 0:
            print(f"Clearing {old_count} existing conversations...")
            db.query(Message).delete()
            db.query(TourSearch).delete()
            db.query(Conv).delete()
            db.flush()

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 1: Турция, семья, Белек, all-inclusive, 7 ночей
        # Типичный запрос: departure=1 (Москва), country=1 (Турция)
        # stars=5, meal=5 (AI), adults=2, children=1, price_to=200000
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c1_id = uuid.uuid4()
        c1_start = _ts(days_ago=1, hour=10, minute=22)
        db.add(Conversation(
            id=c1_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="185.67.34.112",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            message_count=6, search_count=1, tour_cards_shown=3,
            status="completed", started_at=c1_start,
            last_active_at=c1_start + timedelta(minutes=8),
        ))

        c1_cards = [
            _card("Rixos Premium Belek", 5, "Турция", "Белек",
                  "Ультра всё включено", 187500, 7, "Anex Tour", "15.04.2026"),
            _card("Calista Luxury Resort", 5, "Турция", "Белек",
                  "Всё включено", 168200, 7, "Pegas Touristik", "15.04.2026"),
            _card("Regnum Carya Golf & Spa Resort", 5, "Турция", "Белек",
                  "Ультра всё включено", 195800, 7, "Coral Travel", "16.04.2026"),
        ]

        c1_search_args = {"departure": 1, "country": 1, "datefrom": "15.04.2026", "dateto": "20.04.2026",
                          "nightsfrom": 7, "nightsto": 7, "adults": 2, "child": 1, "stars": 5, "meal": 5, "priceto": 200000}

        _add_msgs(db, c1_id, c1_start, [
            ("user", "Здравствуйте! Планируем семейный отдых в Турции — 2 взрослых и ребёнок 6 лет. Хотим Белек, 5 звёзд, ультра всё включено. На 7 ночей, вылет из Москвы в середине апреля. Бюджет до 200 тысяч.", 0),
            ("assistant", "Здравствуйте! Отличный выбор — Белек идеален для семейного отдыха. Сейчас подберу для вас лучшие варианты.", 6,
             {"tool_calls": _tool_call("search_tours", c1_search_args), "latency_ms": 1850}),
            ("tool", '{"status": "ok", "hotels_found": 14, "tours_found": 89}', 14, {"tool_call_id": "call_tv_s1"}),
            ("assistant", "Нашёл 89 туров в 14 отелях Белека! Вот три лучших варианта для вашей семьи:", 22,
             {"tour_cards": c1_cards, "latency_ms": 1200}),
            ("user", "Rixos за 187 тысяч — отлично! Там есть детский клуб?", 180),
            ("assistant", "Да, в Rixos Premium Belek один из лучших детских клубов — Rixy Kids Club для детей от 4 до 12 лет с русскоязычными аниматорами. Также есть собственный аквапарк, мини-зоопарк и детская площадка. Для бронирования обратитесь к вашему менеджеру — передам ему параметры подбора.", 195, {"latency_ms": 2100}),
        ])

        db.add(TourSearch(
            conversation_id=c1_id, search_type="regular", departure=1, country=1,
            nights_from=7, nights_to=7, adults=2, children=1, stars=5, meal=5,
            price_to=200000, hotels_found=14, tours_found=89, min_price=112500,
            date_from="2026-04-15", date_to="2026-04-20", created_at=c1_start + timedelta(seconds=6),
        ))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 2: Египет, горящие туры, Хургада, 2 взрослых
        # hot tours: city=1 (Москва), countries=2 (Египет), stars=5, meal=5
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c2_id = uuid.uuid4()
        c2_start = _ts(days_ago=3, hour=14, minute=10)
        db.add(Conversation(
            id=c2_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="95.142.78.201",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
            message_count=4, search_count=1, tour_cards_shown=2,
            status="completed", started_at=c2_start,
            last_active_at=c2_start + timedelta(minutes=5),
        ))

        c2_cards = [
            _hot_card("Jaz Aquamarine Resort", 5, "Египет", "Хургада",
                      "AI", "Всё включено", 52400, 7, "Coral Travel", "02.03.2026"),
            _hot_card("Steigenberger Aldau Beach Hotel", 5, "Египет", "Хургада",
                      "AI", "Всё включено", 58900, 7, "Anex Tour", "03.03.2026"),
        ]

        c2_search_args = {"city": 1, "countries": "2", "stars": 5, "meal": 5, "items": 10}

        _add_msgs(db, c2_id, c2_start, [
            ("user", "Привет! Есть горящие туры в Египет? Хургада, 5 звёзд, всё включено, на двоих. Что-нибудь недорогое.", 0),
            ("assistant", "Привет! Сейчас посмотрю горящие предложения в Хургаду. Горящие туры — это отличная возможность сэкономить!",
             5, {"tool_calls": _tool_call("get_hot_tours", c2_search_args), "latency_ms": 1600}),
            ("tool", '{"status": "ok", "tours_found": 8}', 12, {"tool_call_id": "call_hot1"}),
            ("assistant", "Нашёл горящие предложения! Обратите внимание — цены указаны за одного человека, итого на двоих будет в два раза больше:", 18,
             {"tour_cards": c2_cards, "latency_ms": 1100}),
        ])

        db.add(TourSearch(
            conversation_id=c2_id, search_type="hot", departure=1, country=2,
            adults=2, stars=5, meal=5,
            hotels_found=6, tours_found=8, min_price=48700,
            created_at=c2_start + timedelta(seconds=5),
        ))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 3: ОАЭ, Дубай, пара, 10 ночей, полупансион
        # departure=1, country=3 (ОАЭ), stars=5, meal=3 (HB), nights=10
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c3_id = uuid.uuid4()
        c3_start = _ts(days_ago=2, hour=19, minute=5)
        db.add(Conversation(
            id=c3_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="77.88.55.43",
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) Mobile/15E148 Safari/604.1",
            message_count=8, search_count=1, tour_cards_shown=4,
            status="completed", started_at=c3_start,
            last_active_at=c3_start + timedelta(minutes=14),
        ))

        c3_cards = [
            _card("Atlantis The Palm", 5, "ОАЭ", "Дубай",
                  "Завтрак и ужин", 289000, 10, "FUN&SUN", "10.03.2026"),
            _card("Jumeirah Beach Hotel", 5, "ОАЭ", "Дубай",
                  "Завтрак и ужин", 265000, 10, "Coral Travel", "10.03.2026"),
            _card("One&Only Royal Mirage", 5, "ОАЭ", "Дубай",
                  "Завтрак и ужин", 312000, 10, "Anex Tour", "11.03.2026"),
            _card("Madinat Jumeirah", 5, "ОАЭ", "Дубай",
                  "Только завтрак", 278500, 10, "TUI", "10.03.2026"),
        ]

        c3_search_args = {"departure": 1, "country": 3, "datefrom": "10.03.2026", "dateto": "15.03.2026",
                          "nightsfrom": 10, "nightsto": 10, "adults": 2, "child": 0, "stars": 5, "meal": 3, "priceto": 350000}

        _add_msgs(db, c3_id, c3_start, [
            ("user", "Добрый вечер! Планируем с женой поездку в Дубай на 10 ночей. 5 звёзд, полупансион. Бюджет до 350 тысяч. Вылет из Москвы, начало марта.", 0),
            ("assistant", "Добрый вечер! Дубай — прекрасный выбор. Подберу лучшие варианты 5-звёздочных отелей с полупансионом.", 7,
             {"tool_calls": _tool_call("search_tours", c3_search_args), "latency_ms": 2200}),
            ("tool", '{"status": "ok", "hotels_found": 11, "tours_found": 52}', 16, {"tool_call_id": "call_uae1"}),
            ("assistant", "Нашёл 52 тура в 11 отелях Дубая. Вот лучшие варианты:", 24,
             {"tour_cards": c3_cards, "latency_ms": 1400}),
            ("user", "Atlantis The Palm — это с аквапарком? Расскажите подробнее.", 180),
            ("assistant", "Да, Atlantis The Palm включает бесплатный доступ в аквапарк Aquaventure — один из крупнейших в мире. Также в отеле есть аквариум Lost Chambers, дельфинарий и 23 ресторана, включая Nobu и Ossiano (подводный ресторан). 289 000 ₽ за 10 ночей на двоих с полупансионом — хорошая цена для этого уровня.", 200, {"latency_ms": 2800}),
            ("user", "А Jumeirah Beach Hotel за 265 тысяч — тоже хороший?", 420),
            ("assistant", "Jumeirah Beach Hotel — отличный вариант! Он находится напротив Burj Al Arab, имеет собственный пляж и бесплатный доступ в аквапарк Wild Wadi. За 265 000 ₽ с полупансионом — это лучшее соотношение цена/качество из подобранных вариантов. Для бронирования обратитесь к менеджеру.", 445, {"latency_ms": 2100}),
        ])

        db.add(TourSearch(
            conversation_id=c3_id, search_type="regular", departure=1, country=3,
            nights_from=10, nights_to=10, adults=2, stars=5, meal=3,
            price_to=350000, hotels_found=11, tours_found=52, min_price=198000,
            date_from="2026-03-10", date_to="2026-03-15", created_at=c3_start + timedelta(seconds=7),
        ))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 4: Быстрый вопрос без поиска — информационный
        # Пользователь спрашивает про направления и документы
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c4_id = uuid.uuid4()
        c4_start = _ts(days_ago=5, hour=11, minute=30)
        db.add(Conversation(
            id=c4_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="213.87.120.5",
            user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/131.0.6778.135 Mobile Safari/537.36",
            message_count=4, search_count=0, tour_cards_shown=0,
            status="completed", started_at=c4_start,
            last_active_at=c4_start + timedelta(minutes=3),
        ))

        _add_msgs(db, c4_id, c4_start, [
            ("user", "Какие страны доступны для поиска туров?", 0),
            ("assistant", "Через наш сервис вы можете найти туры в более чем 30 стран. Самые популярные направления:\n\n- Турция — семейный отдых, всё включено\n- Египет — круглогодичное тёплое море\n- ОАЭ — премиальный отдых в Дубае и Абу-Даби\n- Таиланд — экзотика, острова Пхукет и Самуи\n- Греция — культура, острова Крит и Родос\n- Кипр — пляжи и история\n- Мальдивы — уединённый отдых\n- Вьетнам — бюджетная экзотика\n\nКакое направление вас интересует?", 8, {"latency_ms": 2400}),
            ("user", "А нужна ли виза в Турцию?", 120),
            ("assistant", "Для граждан России виза в Турцию не требуется при поездках до 60 дней. Вам понадобится только загранпаспорт, действительный минимум 4 месяца после даты возвращения. Медицинская страховка рекомендуется, обычно она уже включена в стоимость тура. Хотите подобрать тур в Турцию?", 130, {"latency_ms": 1900}),
        ])

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 5: Таиланд vs Вьетнам — сравнение двух стран
        # Два последовательных поиска: country=4 (Таиланд), затем country=24 (Вьетнам)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c5_id = uuid.uuid4()
        c5_start = _ts(days_ago=4, hour=16, minute=45)
        db.add(Conversation(
            id=c5_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="178.176.42.99",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Firefox/134.0",
            message_count=10, search_count=2, tour_cards_shown=3,
            status="completed", started_at=c5_start,
            last_active_at=c5_start + timedelta(minutes=16),
        ))

        c5_thai_cards = [
            _card("Centara Grand Beach Resort Phuket", 5, "Таиланд", "Пхукет",
                  "Только завтрак", 125800, 10, "Pegas Touristik", "20.03.2026"),
            _card("Kata Thani Phuket Beach Resort", 5, "Таиланд", "Пхукет",
                  "Только завтрак", 112500, 10, "Coral Travel", "21.03.2026"),
        ]

        c5_vn_cards = [
            _card("Vinpearl Resort & Spa Nha Trang", 5, "Вьетнам", "Нячанг",
                  "Только завтрак", 94200, 10, "Anex Tour", "20.03.2026"),
        ]

        c5_thai_args = {"departure": 1, "country": 4, "datefrom": "20.03.2026", "dateto": "25.03.2026",
                        "nightsfrom": 10, "nightsto": 10, "adults": 2, "child": 0, "stars": 5, "priceto": 150000}
        c5_vn_args = {"departure": 1, "country": 24, "datefrom": "20.03.2026", "dateto": "25.03.2026",
                      "nightsfrom": 10, "nightsto": 10, "adults": 2, "child": 0, "priceto": 150000}

        _add_msgs(db, c5_id, c5_start, [
            ("user", "Привет! Думаем куда поехать — Таиланд или Вьетнам. На двоих, 10 ночей, вылет из Москвы, середина марта. Бюджет до 150 тысяч.", 0),
            ("assistant", "Привет! Оба направления отличные! Сначала посмотрю Таиланд, потом Вьетнам для сравнения.", 5,
             {"tool_calls": _tool_call("search_tours", c5_thai_args), "latency_ms": 1300}),
            ("tool", '{"status": "ok", "hotels_found": 9, "tours_found": 34}', 14, {"tool_call_id": "call_th1"}),
            ("assistant", "По Таиланду нашёл 34 тура на Пхукете. Лучшие варианты:", 22,
             {"tour_cards": c5_thai_cards, "latency_ms": 1050}),
            ("user", "А что по Вьетнаму?", 150),
            ("assistant", "Сейчас посмотрю Вьетнам с теми же параметрами.", 156,
             {"tool_calls": _tool_call("search_tours", c5_vn_args), "latency_ms": 1150}),
            ("tool", '{"status": "ok", "hotels_found": 5, "tours_found": 19}', 165, {"tool_call_id": "call_vn1"}),
            ("assistant", "По Вьетнаму нашёл 19 туров в Нячанге:", 172,
             {"tour_cards": c5_vn_cards, "latency_ms": 980}),
            ("user", "Вьетнам дешевле, но в Таиланде больше выбор. Наверное, возьмём Kata Thani за 112 тысяч.", 600),
            ("assistant", "Отличный выбор! Kata Thani расположен на пляже Kata Noi — одном из лучших на Пхукете. 112 500 ₽ за 10 ночей в 5-звёздочном отеле — прекрасная цена. Для бронирования обратитесь к менеджеру.", 620, {"latency_ms": 1700}),
        ])

        db.add(TourSearch(
            conversation_id=c5_id, search_type="regular", departure=1, country=4,
            nights_from=10, nights_to=10, adults=2, stars=5,
            price_to=150000, hotels_found=9, tours_found=34, min_price=89000,
            date_from="2026-03-20", date_to="2026-03-25", created_at=c5_start + timedelta(seconds=5),
        ))
        db.add(TourSearch(
            conversation_id=c5_id, search_type="regular", departure=1, country=24,
            nights_from=10, nights_to=10, adults=2,
            price_to=150000, hotels_found=5, tours_found=19, min_price=72000,
            date_from="2026-03-20", date_to="2026-03-25", created_at=c5_start + timedelta(seconds=156),
        ))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 6: Кипр, бюджетный отдых, 4 звезды, полный пансион
        # departure=1, country=7 (Кипр), stars=4, meal=4 (FB)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c6_id = uuid.uuid4()
        c6_start = _ts(days_ago=6, hour=9, minute=15)
        db.add(Conversation(
            id=c6_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="46.242.11.88",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            message_count=6, search_count=1, tour_cards_shown=3,
            status="completed", started_at=c6_start,
            last_active_at=c6_start + timedelta(minutes=7),
        ))

        c6_cards = [
            _card("Constantinos The Great Beach Hotel", 4, "Кипр", "Протарас",
                  "Полный пансион", 89500, 7, "Pegas Touristik", "01.05.2026"),
            _card("Tsokkos Protaras Beach Hotel", 4, "Кипр", "Протарас",
                  "Полный пансион", 82300, 7, "TUI", "01.05.2026"),
            _card("Capo Bay Hotel", 4, "Кипр", "Протарас",
                  "Полный пансион", 91200, 7, "Coral Travel", "02.05.2026"),
        ]

        c6_search_args = {"departure": 1, "country": 7, "datefrom": "01.05.2026", "dateto": "05.05.2026",
                          "nightsfrom": 7, "nightsto": 7, "adults": 2, "child": 0, "stars": 4, "meal": 4, "priceto": 100000}

        _add_msgs(db, c6_id, c6_start, [
            ("user", "Хочу на Кипр в начале мая. 4 звезды, полный пансион, 7 ночей, на двоих. Бюджет до 100 тысяч.", 0),
            ("assistant", "Кипр в мае — отличная идея, море уже тёплое! Ищу варианты 4-звёздочных отелей с полным пансионом.", 6,
             {"tool_calls": _tool_call("search_tours", c6_search_args), "latency_ms": 1750}),
            ("tool", '{"status": "ok", "hotels_found": 8, "tours_found": 42}', 14, {"tool_call_id": "call_cy1"}),
            ("assistant", "Нашёл 42 тура в 8 отелях Кипра. Протарас — один из лучших курортов для спокойного отдыха:", 21,
             {"tour_cards": c6_cards, "latency_ms": 1100}),
            ("user", "Tsokkos за 82 тысячи — хороший вариант. Спасибо!", 300),
            ("assistant", "Пожалуйста! Tsokkos Protaras Beach Hotel — надёжный выбор с хорошими отзывами. Находится прямо на пляже Fig Tree Bay, который входит в топ-10 пляжей Европы. Приятного отдыха!", 315, {"latency_ms": 1500}),
        ])

        db.add(TourSearch(
            conversation_id=c6_id, search_type="regular", departure=1, country=7,
            nights_from=7, nights_to=7, adults=2, stars=4, meal=4,
            price_to=100000, hotels_found=8, tours_found=42, min_price=68900,
            date_from="2026-05-01", date_to="2026-05-05", created_at=c6_start + timedelta(seconds=6),
        ))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Scenario 7: Санкт-Петербург → Греция, с детьми, нет результатов → расширение
        # departure=2 (СПб), country=6 (Греция), 2 взрослых + 2 детей
        # Первый поиск не даёт результатов, ассистент предлагает убрать фильтр
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        c7_id = uuid.uuid4()
        c7_start = _ts(days_ago=7, hour=13, minute=0)
        db.add(Conversation(
            id=c7_id, session_id=f"ses_{uuid.uuid4().hex[:12]}",
            assistant_id=aid, llm_provider="openai", model="openai/gpt-5-mini",
            ip_address="31.173.85.200",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/131.0.0.0 Safari/537.36",
            message_count=8, search_count=2, tour_cards_shown=2,
            status="completed", started_at=c7_start,
            last_active_at=c7_start + timedelta(minutes=12),
        ))

        c7_cards = [
            _card("Aldemar Knossos Royal", 5, "Греция", "Крит",
                  "Всё включено", 198500, 10, "Anex Tour", "15.06.2026"),
            _card("Grecotel Creta Palace", 5, "Греция", "Крит",
                  "Полный пансион", 185200, 10, "Coral Travel", "15.06.2026"),
        ]

        c7_first_args = {"departure": 2, "country": 6, "datefrom": "15.06.2026", "dateto": "20.06.2026",
                         "nightsfrom": 10, "nightsto": 10, "adults": 2, "child": 2, "stars": 5, "meal": 6, "priceto": 180000}
        c7_second_args = {"departure": 2, "country": 6, "datefrom": "15.06.2026", "dateto": "20.06.2026",
                          "nightsfrom": 10, "nightsto": 10, "adults": 2, "child": 2, "stars": 5, "priceto": 200000}

        _add_msgs(db, c7_id, c7_start, [
            ("user", "Из Петербурга в Грецию, 2 взрослых и 2 детей (4 и 8 лет), 10 ночей, 5 звёзд, ультра всё включено. Бюджет до 180 тысяч. Середина июня.", 0),
            ("assistant", "Ищу туры из Санкт-Петербурга в Грецию с ультра всё включено. Обратите внимание, что из Петербурга выбор может быть ограничен.", 7,
             {"tool_calls": _tool_call("search_tours", c7_first_args), "latency_ms": 2100}),
            ("tool", '{"status": "ok", "hotels_found": 0, "tours_found": 0}', 18, {"tool_call_id": "call_gr1"}),
            ("assistant", "К сожалению, туров с ультра всё включено из Санкт-Петербурга в Грецию не нашлось — это редкая комбинация для греческих отелей. Предлагаю расширить поиск: убрать ограничение по типу питания и немного увеличить бюджет до 200 000 ₽. Ищу?", 28, {"latency_ms": 1800}),
            ("user", "Да, давайте попробуем без ограничения по питанию.", 180),
            ("assistant", "Ищу варианты 5 звёзд без ограничения по питанию, бюджет до 200 000 ₽.", 186,
             {"tool_calls": _tool_call("search_tours", c7_second_args), "latency_ms": 1500}),
            ("tool", '{"status": "ok", "hotels_found": 4, "tours_found": 18}', 196, {"tool_call_id": "call_gr2"}),
            ("assistant", "Нашёл 18 туров в 4 отелях на Крите! Вот лучшие варианты для семьи с детьми:", 205,
             {"tour_cards": c7_cards, "latency_ms": 1200}),
        ])

        db.add(TourSearch(
            conversation_id=c7_id, search_type="regular", departure=2, country=6,
            nights_from=10, nights_to=10, adults=2, children=2, stars=5, meal=6,
            price_to=180000, hotels_found=0, tours_found=0,
            date_from="2026-06-15", date_to="2026-06-20", created_at=c7_start + timedelta(seconds=7),
        ))
        db.add(TourSearch(
            conversation_id=c7_id, search_type="regular", departure=2, country=6,
            nights_from=10, nights_to=10, adults=2, children=2, stars=5,
            price_to=200000, hotels_found=4, tours_found=18, min_price=165000,
            date_from="2026-06-15", date_to="2026-06-20", created_at=c7_start + timedelta(seconds=186),
        ))

        print("\nSeeded 7 conversations successfully!")
        print("  1. Turkey family — Belek, 5*, UAI, 7n (3 cards)")
        print("  2. Egypt hot deals — Hurghada, 5*, AI (2 cards, hot)")
        print("  3. UAE Dubai — 5*, HB, 10n (4 cards)")
        print("  4. Info only — no search, country list + visa")
        print("  5. Thailand vs Vietnam — comparison, 2 searches (3 cards)")
        print("  6. Cyprus budget — 4*, FB, 7n (3 cards)")
        print("  7. SPb→Greece — failed search → retry without meal filter (2 cards)")


def _add_msgs(db, conv_id, base_time, messages):
    """Helper to add messages to a conversation.
    messages: list of (role, content, seconds_offset, extras_dict)
    """
    for item in messages:
        role = item[0]
        content = item[1]
        offset_sec = item[2]
        extras = item[3] if len(item) > 3 else {}

        msg = Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            latency_ms=extras.get("latency_ms"),
            tool_calls=extras.get("tool_calls"),
            tool_call_id=extras.get("tool_call_id"),
            tour_cards=extras.get("tour_cards"),
            created_at=base_time + timedelta(seconds=offset_sec),
        )
        db.add(msg)


if __name__ == "__main__":
    seed()
