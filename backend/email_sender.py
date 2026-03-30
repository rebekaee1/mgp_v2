"""Booking request email sender via SMTP.

Sends HTML-formatted booking request emails to tenant notification addresses.
SMTP credentials are configured via environment variables.
"""

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("mgp_bot.email")

_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.timeweb.ru")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")
_SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "AI-Ассистент")
_SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "true").lower() in ("true", "1", "yes")


def _build_booking_html(
    client_name: str,
    client_phone: str,
    client_email: str,
    hotel_name: str,
    country: str,
    resort: str,
    departure_city: str,
    fly_date: str,
    nights: int,
    price: int,
    operator: str,
    meal: str,
    room_type: str,
    stars: int,
    tour_link: str,
    request_number: int,
    agency_name: str = "Магазин Горящих Путёвок",
    comment: str = "",
) -> str:
    stars_str = f"{'★' * stars}{'☆' * (5 - stars)}" if stars else ""
    price_formatted = f"{price:,}".replace(",", " ") if price else "—"

    return f"""\
<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f8;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:20px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#0066F0 0%,#004BBF 100%);padding:28px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <span style="font-size:22px;font-weight:700;color:#ffffff;letter-spacing:-0.3px;">{agency_name}</span>
            <br>
            <span style="font-size:13px;color:rgba(255,255,255,0.75);margin-top:4px;display:inline-block;">AI-Ассистент — заявка на тур</span>
          </td>
          <td style="text-align:right;vertical-align:top;">
            <span style="display:inline-block;background:rgba(255,255,255,0.2);color:#fff;font-size:13px;font-weight:600;padding:6px 14px;border-radius:20px;">Заявка #{request_number}</span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Client info -->
  <tr>
    <td style="padding:24px 32px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f7ff;border-radius:10px;padding:20px;">
        <tr><td style="padding:20px;">
          <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin-bottom:12px;font-weight:600;">Данные клиента</div>
          <div style="font-size:18px;font-weight:700;color:#111827;">{client_name}</div>
          <div style="font-size:15px;color:#374151;margin-top:6px;">📞 <a href="tel:{client_phone}" style="color:#0066F0;text-decoration:none;">{client_phone}</a></div>
          {"<div style='font-size:15px;color:#374151;margin-top:4px;'>✉️ <a href='mailto:" + client_email + "' style='color:#0066F0;text-decoration:none;'>" + client_email + "</a></div>" if client_email else ""}
        </td></tr>
      </table>
    </td>
  </tr>

  <!-- Tour details -->
  <tr>
    <td style="padding:0 32px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
        <tr>
          <td colspan="2" style="background:#f9fafb;padding:16px 20px;border-bottom:1px solid #e5e7eb;">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;font-weight:600;">Параметры тура</div>
          </td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;width:140px;border-bottom:1px solid #f3f4f6;">Отель</td>
          <td style="padding:12px 20px;font-size:14px;font-weight:600;color:#111827;border-bottom:1px solid #f3f4f6;">{hotel_name} {stars_str}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Страна</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{country}{", " + resort if resort else ""}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Город вылета</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{departure_city}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Вылет</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{fly_date}, {nights} ночей</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Питание</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{meal}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Номер</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{room_type}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Оператор</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{operator}</td>
        </tr>
        <tr style="background:#f0fdf4;">
          <td style="padding:14px 20px;color:#6b7280;font-size:14px;font-weight:600;">Стоимость</td>
          <td style="padding:14px 20px;font-size:18px;font-weight:700;color:#059669;">{price_formatted} руб.</td>
        </tr>
      </table>
    </td>
  </tr>

  {"<!-- Comment --><tr><td style='padding:0 32px 20px;'><div style='background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 18px;font-size:14px;color:#92400e;'><b>Комментарий:</b> " + comment + "</div></td></tr>" if comment else ""}

  <!-- CTA -->
  {"<tr><td style='padding:0 32px 24px;text-align:center;'><a href='" + tour_link + "' style='display:inline-block;background:#0066F0;color:#ffffff;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;text-decoration:none;'>Открыть тур</a></td></tr>" if tour_link else ""}

  <!-- Footer -->
  <tr>
    <td style="padding:20px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;">
      <div style="font-size:12px;color:#9ca3af;text-align:center;">
        Заявка сформирована AI-ассистентом · <a href="https://navilet.ru" style="color:#6b7280;">navilet.ru</a>
      </div>
    </td>
  </tr>

</table>
</body>
</html>"""


def send_booking_email(
    to_email: str,
    client_name: str,
    client_phone: str,
    hotel_name: str,
    country: str,
    price: int,
    request_number: int,
    client_email: str = "",
    resort: str = "",
    departure_city: str = "Москва",
    fly_date: str = "",
    nights: int = 0,
    operator: str = "",
    meal: str = "",
    room_type: str = "",
    stars: int = 0,
    tour_link: str = "",
    agency_name: str = "Магазин Горящих Путёвок",
    comment: str = "",
    from_email: Optional[str] = None,
) -> dict:
    """Send a booking request email. Returns {"ok": True, "request_number": N} or {"ok": False, "error": "..."}."""

    smtp_user = from_email or _SMTP_USER
    if not smtp_user or not _SMTP_PASS:
        return {"ok": False, "error": "SMTP credentials not configured"}

    subject = f"Заявка #{request_number} от AI-ассистента — {country}, {price:,} руб.".replace(",", " ") if price else f"Заявка #{request_number} от AI-ассистента — {country}"

    html_body = _build_booking_html(
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
        hotel_name=hotel_name,
        country=country,
        resort=resort,
        departure_city=departure_city,
        fly_date=fly_date,
        nights=nights,
        price=price,
        operator=operator,
        meal=meal,
        room_type=room_type,
        stars=stars,
        tour_link=tour_link,
        request_number=request_number,
        agency_name=agency_name,
        comment=comment,
    )

    plain_text = (
        f"Заявка #{request_number}\n\n"
        f"{client_name}\n{client_phone}\n{client_email}\n\n"
        f"Отель: {hotel_name}\nСтрана: {country}\n"
        f"Город вылета: {departure_city}\nВылет: {fly_date}, {nights} ночей\n"
        f"Питание: {meal}\nОператор: {operator}\n"
        f"Стоимость: {price} руб.\n"
        f"Ссылка: {tour_link}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_SMTP_FROM_NAME} <{smtp_user}>"
    msg["To"] = to_email
    msg["Reply-To"] = to_email
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if _SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context, timeout=15) as server:
                server.login(smtp_user, _SMTP_PASS)
                server.sendmail(smtp_user, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(smtp_user, _SMTP_PASS)
                server.sendmail(smtp_user, [to_email], msg.as_string())

        logger.info("📧 Booking email sent to=%s subject='%s'", to_email, subject)
        return {"ok": True, "request_number": request_number}

    except Exception as e:
        logger.error("📧 Email send failed to=%s: %s", to_email, e, exc_info=True)
        return {"ok": False, "error": str(e)}
