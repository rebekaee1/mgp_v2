"""Booking request email sender via SMTP + IMAP save-to-sent.

Sends HTML-formatted booking request emails to tenant notification addresses.
After sending, saves a copy to the Sent folder via IMAP so the message
appears in Timeweb webmail's «Отправленные».

SMTP/IMAP credentials are configured via environment variables.
"""

import imaplib
import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.base import MIMEBase
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

_IMAP_HOST = os.getenv("IMAP_HOST", "imap.timeweb.ru")
_IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "logo.png")
_LOGO_CID = "logo_navilet"


def _save_to_sent(msg_bytes: bytes) -> None:
    """Append sent message to IMAP Sent folder (best-effort, non-blocking)."""
    if not _SMTP_USER or not _SMTP_PASS:
        return
    try:
        imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, timeout=10)
        imap.login(_SMTP_USER, _SMTP_PASS)
        for folder in ("Sent", "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-", "INBOX.Sent"):
            status, _ = imap.select(folder)
            if status == "OK":
                imap.append(folder, "\\Seen", None, msg_bytes)
                logger.info("📧 Saved copy to IMAP folder '%s'", folder)
                break
        imap.logout()
    except Exception as e:
        logger.warning("📧 Could not save to IMAP Sent: %s", e)


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

  <!-- Header with logo -->
  <tr>
    <td style="background:linear-gradient(135deg,#0066F0 0%,#004BBF 100%);padding:24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;">
            <div style="display:inline-block;background:#ffffff;border-radius:8px;padding:6px 12px;">
              <img src="cid:{_LOGO_CID}" alt="{agency_name}" height="30" style="display:block;height:30px;max-width:180px;" />
            </div>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            <span style="display:inline-block;background:rgba(255,255,255,0.2);color:#fff;font-size:13px;font-weight:600;padding:6px 14px;border-radius:20px;">Заявка #{request_number}</span>
          </td>
        </tr>
        <tr>
          <td colspan="2" style="padding-top:10px;">
            <span style="font-size:13px;color:rgba(255,255,255,0.8);">AI-Ассистент — заявка на бронирование тура</span>
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
          <div style="font-size:15px;color:#374151;margin-top:6px;">&#128222; <a href="tel:{client_phone}" style="color:#0066F0;text-decoration:none;">{client_phone}</a></div>
          {"<div style='font-size:15px;color:#374151;margin-top:4px;'>&#9993; <a href='mailto:" + client_email + "' style='color:#0066F0;text-decoration:none;'>" + client_email + "</a></div>" if client_email else ""}
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
        Заявка сформирована AI-ассистентом &middot; <a href="https://navilet.ru" style="color:#6b7280;">navilet.ru</a>
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
    """Send a booking request email and save to Sent folder.

    Returns {"ok": True, "request_number": N} or {"ok": False, "error": "..."}.
    """
    smtp_user = from_email or _SMTP_USER
    if not smtp_user or not _SMTP_PASS:
        return {"ok": False, "error": "SMTP credentials not configured"}

    subject = (
        f"Заявка #{request_number} от AI-ассистента — {country}, {price:,} руб.".replace(",", " ")
        if price
        else f"Заявка #{request_number} от AI-ассистента — {country}"
    )

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

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = f"{_SMTP_FROM_NAME} <{smtp_user}>"
    msg["To"] = to_email
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(plain_text, "plain", "utf-8"))
    alt_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt_part)

    if os.path.isfile(_LOGO_PATH):
        with open(_LOGO_PATH, "rb") as f:
            logo_data = f.read()
        logo_attach = MIMEBase("image", "png")
        logo_attach.set_payload(logo_data)
        from email.encoders import encode_base64
        encode_base64(logo_attach)
        logo_attach.add_header("Content-ID", f"<{_LOGO_CID}>")
        logo_attach.add_header("Content-Disposition", "inline", filename="logo.png")
        msg.attach(logo_attach)

    msg_bytes = msg.as_bytes()

    try:
        if _SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context, timeout=15) as server:
                server.login(smtp_user, _SMTP_PASS)
                server.sendmail(smtp_user, [to_email], msg_bytes)
        else:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(smtp_user, _SMTP_PASS)
                server.sendmail(smtp_user, [to_email], msg_bytes)

        logger.info("📧 Booking email #%d sent to=%s", request_number, to_email)

        try:
            _save_to_sent(msg_bytes)
        except Exception:
            pass

        return {"ok": True, "request_number": request_number}

    except Exception as e:
        logger.error("📧 Email send failed to=%s: %s", to_email, e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _build_lead_html(
    client_name: str,
    client_phone: str,
    client_email: str,
    request_number: int,
    crm_type: str,
    crm_id: Optional[int],
    comment: str,
    search_country: str,
    search_dates: str,
    search_pax: str,
    search_budget: str,
    departure_city: str,
    hotel_name: str,
    country: str,
    resort: str,
    fly_date: str,
    nights: int,
    price: int,
    operator: str,
    meal: str,
    room_type: str,
    stars: int,
    tour_link: str,
    agency_name: str,
) -> str:
    """Build HTML body for a lead-duplicate email.

    Layout mirrors `_build_booking_html` (blue header, navilet logo, client
    info card, footer). Two variants for the middle section:
      - if `hotel_name` is set: "Параметры тура" table (same as Tambov booking).
      - otherwise: "Параметры запроса" table with search context.
    """
    has_tour = bool(hotel_name)
    badge_label = "Заявка" if crm_type == "request" else "Лид"
    subtitle = (
        "AI-Ассистент — заявка на бронирование тура"
        if has_tour
        else "AI-Ассистент — новый лид от клиента"
    )
    crm_id_block = (
        f"<div style='font-size:12px;color:#6b7280;margin-top:8px;'>U-ON #{crm_id}</div>"
        if crm_id
        else ""
    )

    if has_tour:
        stars_str = f"{'★' * stars}{'☆' * (5 - stars)}" if stars else ""
        price_formatted = f"{price:,}".replace(",", " ") if price else "—"
        middle_block = f"""
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
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{departure_city or "—"}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Вылет</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{fly_date or "—"}{f", {nights} ночей" if nights else ""}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Питание</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{meal or "—"}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Номер</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{room_type or "—"}</td>
        </tr>
        <tr>
          <td style="padding:12px 20px;color:#6b7280;font-size:14px;border-bottom:1px solid #f3f4f6;">Оператор</td>
          <td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{operator or "—"}</td>
        </tr>
        <tr style="background:#f0fdf4;">
          <td style="padding:14px 20px;color:#6b7280;font-size:14px;font-weight:600;">Стоимость</td>
          <td style="padding:14px 20px;font-size:18px;font-weight:700;color:#059669;">{price_formatted} руб.</td>
        </tr>
      </table>
    </td>
  </tr>"""
    else:
        rows = []
        if search_country:
            rows.append(("Направление", search_country))
        if departure_city:
            rows.append(("Город вылета", departure_city))
        if search_dates:
            rows.append(("Даты", search_dates))
        if search_pax:
            rows.append(("Состав", search_pax))
        if search_budget:
            rows.append(("Бюджет", search_budget))

        if rows:
            row_html = ""
            for label, value in rows:
                row_html += (
                    f'<tr><td style="padding:12px 20px;color:#6b7280;font-size:14px;width:140px;border-bottom:1px solid #f3f4f6;">{label}</td>'
                    f'<td style="padding:12px 20px;font-size:14px;color:#111827;border-bottom:1px solid #f3f4f6;">{value}</td></tr>'
                )
            middle_block = f"""
  <tr>
    <td style="padding:0 32px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
        <tr>
          <td colspan="2" style="background:#f9fafb;padding:16px 20px;border-bottom:1px solid #e5e7eb;">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;font-weight:600;">Параметры запроса</div>
          </td>
        </tr>
        {row_html}
      </table>
    </td>
  </tr>"""
        else:
            middle_block = """
  <tr>
    <td style="padding:0 32px 24px;">
      <div style="background:#f9fafb;border:1px dashed #e5e7eb;border-radius:10px;padding:18px;font-size:14px;color:#6b7280;text-align:center;">
        Клиент оставил контакт без указания деталей запроса. Свяжитесь с ним для уточнения параметров.
      </div>
    </td>
  </tr>"""

    comment_block = (
        f"<tr><td style='padding:0 32px 20px;'><div style='background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 18px;font-size:14px;color:#92400e;'><b>Комментарий ассистента:</b> {comment}</div></td></tr>"
        if comment
        else ""
    )
    cta_block = (
        f"<tr><td style='padding:0 32px 24px;text-align:center;'><a href='{tour_link}' style='display:inline-block;background:#0066F0;color:#ffffff;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;text-decoration:none;'>Открыть тур</a></td></tr>"
        if tour_link
        else ""
    )
    email_block = (
        f"<div style='font-size:15px;color:#374151;margin-top:4px;'>&#9993; <a href='mailto:{client_email}' style='color:#0066F0;text-decoration:none;'>{client_email}</a></div>"
        if client_email
        else ""
    )

    return f"""\
<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f8;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:20px auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

  <!-- Header with logo -->
  <tr>
    <td style="background:linear-gradient(135deg,#0066F0 0%,#004BBF 100%);padding:24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;">
            <div style="display:inline-block;background:#ffffff;border-radius:8px;padding:6px 12px;">
              <img src="cid:{_LOGO_CID}" alt="{agency_name}" height="30" style="display:block;height:30px;max-width:180px;" />
            </div>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            <span style="display:inline-block;background:rgba(255,255,255,0.2);color:#fff;font-size:13px;font-weight:600;padding:6px 14px;border-radius:20px;">{badge_label} #{request_number}</span>
          </td>
        </tr>
        <tr>
          <td colspan="2" style="padding-top:10px;">
            <span style="font-size:13px;color:rgba(255,255,255,0.8);">{subtitle}</span>
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
          <div style="font-size:15px;color:#374151;margin-top:6px;">&#128222; <a href="tel:{client_phone}" style="color:#0066F0;text-decoration:none;">{client_phone}</a></div>
          {email_block}
          {crm_id_block}
        </td></tr>
      </table>
    </td>
  </tr>
{middle_block}
  {comment_block}

  {cta_block}

  <!-- Footer -->
  <tr>
    <td style="padding:20px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;">
      <div style="font-size:12px;color:#9ca3af;text-align:center;">
        Заявка сформирована AI-ассистентом &middot; <a href="https://navilet.ru" style="color:#6b7280;">navilet.ru</a>
      </div>
    </td>
  </tr>

</table>
</body>
</html>"""


def send_lead_email(
    to_email: str,
    client_name: str,
    client_phone: str,
    request_number: int,
    crm_type: str,
    crm_id: Optional[int] = None,
    client_email: str = "",
    comment: str = "",
    search_country: str = "",
    search_dates: str = "",
    search_pax: str = "",
    search_budget: str = "",
    departure_city: str = "",
    hotel_name: str = "",
    country: str = "",
    resort: str = "",
    fly_date: str = "",
    nights: int = 0,
    price: int = 0,
    operator: str = "",
    meal: str = "",
    room_type: str = "",
    stars: int = 0,
    tour_link: str = "",
    agency_name: str = "Магазин Горящих Путёвок",
    from_email: Optional[str] = None,
) -> dict:
    """Send a lead-duplicate email and save to Sent folder.

    Used to mirror successful U-ON CRM submissions to a notification mailbox
    (e.g. online@mgp.ru). Best-effort — caller MUST treat failures as
    non-fatal because the lead is already persisted in CRM.

    Returns {"ok": True, "request_number": N} or {"ok": False, "error": "..."}.
    """
    smtp_user = from_email or _SMTP_USER
    if not smtp_user or not _SMTP_PASS:
        return {"ok": False, "error": "SMTP credentials not configured"}

    has_tour = bool(hotel_name)
    badge_label = "Заявка" if crm_type == "request" else "Лид"

    if has_tour and price:
        subject = (
            f"{badge_label} #{request_number} от AI-ассистента — {country}, {price:,} руб."
            .replace(",", " ")
        )
    elif has_tour:
        subject = f"{badge_label} #{request_number} от AI-ассистента — {country}"
    else:
        country_part = search_country or "без направления"
        subject = f"{badge_label} #{request_number} от AI-ассистента — {country_part}"

    html_body = _build_lead_html(
        client_name=client_name,
        client_phone=client_phone,
        client_email=client_email,
        request_number=request_number,
        crm_type=crm_type,
        crm_id=crm_id,
        comment=comment,
        search_country=search_country,
        search_dates=search_dates,
        search_pax=search_pax,
        search_budget=search_budget,
        departure_city=departure_city,
        hotel_name=hotel_name,
        country=country,
        resort=resort,
        fly_date=fly_date,
        nights=nights,
        price=price,
        operator=operator,
        meal=meal,
        room_type=room_type,
        stars=stars,
        tour_link=tour_link,
        agency_name=agency_name,
    )

    plain_lines = [
        f"{badge_label} #{request_number}",
        "",
        client_name,
        client_phone,
    ]
    if client_email:
        plain_lines.append(client_email)
    plain_lines.append("")
    if has_tour:
        plain_lines.append(f"Отель: {hotel_name}")
        plain_lines.append(f"Страна: {country}")
        if departure_city:
            plain_lines.append(f"Город вылета: {departure_city}")
        if fly_date:
            plain_lines.append(f"Вылет: {fly_date}, {nights} ночей")
        if meal:
            plain_lines.append(f"Питание: {meal}")
        if operator:
            plain_lines.append(f"Оператор: {operator}")
        if price:
            plain_lines.append(f"Стоимость: {price} руб.")
        if tour_link:
            plain_lines.append(f"Ссылка: {tour_link}")
    else:
        if search_country:
            plain_lines.append(f"Направление: {search_country}")
        if departure_city:
            plain_lines.append(f"Город вылета: {departure_city}")
        if search_dates:
            plain_lines.append(f"Даты: {search_dates}")
        if search_pax:
            plain_lines.append(f"Состав: {search_pax}")
        if search_budget:
            plain_lines.append(f"Бюджет: {search_budget}")
    if comment:
        plain_lines.append("")
        plain_lines.append(f"Комментарий: {comment}")
    if crm_id:
        plain_lines.append("")
        plain_lines.append(f"U-ON ID: {crm_id}")
    plain_text = "\n".join(plain_lines) + "\n"

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = f"{_SMTP_FROM_NAME} <{smtp_user}>"
    msg["To"] = to_email
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(plain_text, "plain", "utf-8"))
    alt_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt_part)

    if os.path.isfile(_LOGO_PATH):
        with open(_LOGO_PATH, "rb") as f:
            logo_data = f.read()
        logo_attach = MIMEBase("image", "png")
        logo_attach.set_payload(logo_data)
        from email.encoders import encode_base64
        encode_base64(logo_attach)
        logo_attach.add_header("Content-ID", f"<{_LOGO_CID}>")
        logo_attach.add_header("Content-Disposition", "inline", filename="logo.png")
        msg.attach(logo_attach)

    msg_bytes = msg.as_bytes()

    try:
        if _SMTP_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, context=context, timeout=15) as server:
                server.login(smtp_user, _SMTP_PASS)
                server.sendmail(smtp_user, [to_email], msg_bytes)
        else:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(smtp_user, _SMTP_PASS)
                server.sendmail(smtp_user, [to_email], msg_bytes)

        logger.info(
            "📧 Lead-duplicate email #%d sent to=%s (crm_type=%s, crm_id=%s)",
            request_number, to_email, crm_type, crm_id,
        )

        try:
            _save_to_sent(msg_bytes)
        except Exception:
            pass

        return {"ok": True, "request_number": request_number}

    except Exception as e:
        logger.error("📧 Lead-duplicate email send failed to=%s: %s", to_email, e, exc_info=True)
        return {"ok": False, "error": str(e)}
