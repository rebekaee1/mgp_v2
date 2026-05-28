"""Booking-click tracking — подписанный redirect для кнопки «Забронировать».

Зачем: кнопка в MAX/виджете ведёт ПРЯМОЙ ссылкой на сайт партнёра
(anytour.online), клик идёт мимо нас — мы его не видим. Чтобы трекать
«переход на тур» (Цель 5 воронки), оборачиваем ссылку в наш редирект:

    https://<base>/go?u=<dest>&c=<session>&t=<tourid>&s=<hmac>

Эндпойнт /go (в app.py): проверяет HMAC-подпись → ставит has_booking_intent
для диалога → отдаёт 302 на исходный dest. Подпись защищает от подмены
(open-redirect): чужой/битый параметр `u` не пройдёт проверку.

Модуль СОЗНАТЕЛЬНО без Flask/DB зависимостей — чистые функции, тестируется
изолированно. Логика входа в БД и HTTP — в app.py.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import List, Optional
from urllib.parse import quote, urlencode


def sign(session_id: str, tourid: str, dest: str, secret: str) -> str:
    """HMAC-SHA256 подпись (urlsafe base64 без '='). Покрывает sid+tourid+dest."""
    msg = f"{session_id}\n{tourid}\n{dest}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def verify(session_id: str, tourid: str, dest: str, sig: str, secret: str) -> bool:
    """Проверка подписи в constant-time."""
    if not (secret and sig and dest):
        return False
    expected = sign(session_id, tourid, dest, secret)
    return hmac.compare_digest(sig, expected)


def build_redirect_url(base_url: str, dest: str, session_id: str,
                       tourid: str, secret: str) -> str:
    """Собрать подписанный redirect-URL вокруг dest."""
    sig = sign(session_id, tourid, dest, secret)
    qs = urlencode({"u": dest, "c": session_id, "t": tourid, "s": sig}, quote_via=quote)
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{qs}"


def wrap_cards(cards: List[dict], session_id: str, base_url: str,
               secret: str) -> int:
    """Обернуть hotel_link каждой карточки в подписанный redirect.

    Мутирует список на месте. Возвращает число обёрнутых карточек.
    Пропускает: пустые/не-http ссылки и уже обёрнутые (идемпотентно).
    """
    if not (base_url and secret) or not cards:
        return 0
    wrapped = 0
    for card in cards:
        if not isinstance(card, dict):
            continue
        link = (card.get("hotel_link") or "").strip()
        if not link or not (link.startswith("http://") or link.startswith("https://")):
            continue
        if link.startswith(base_url):  # уже обёрнута — не оборачиваем повторно
            continue
        tourid = str(card.get("id") or "")
        card["hotel_link"] = build_redirect_url(base_url, link, session_id, tourid, secret)
        wrapped += 1
    return wrapped
