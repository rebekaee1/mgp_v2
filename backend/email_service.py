"""
Lightweight email sender using Python stdlib (smtplib + email.mime).
No external dependencies required.
"""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import settings

_log = logging.getLogger("email_service")


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an HTML email. Returns True on success, False on failure."""
    if not settings.smtp_user or not settings.smtp_password:
        _log.warning("SMTP not configured — skipping email to %s", to)
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.smtp_use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=15) as srv:
                srv.login(settings.smtp_user, settings.smtp_password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as srv:
                srv.ehlo()
                srv.starttls(context=ssl.create_default_context())
                srv.ehlo()
                srv.login(settings.smtp_user, settings.smtp_password)
                srv.send_message(msg)
        _log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        _log.error("Failed to send email to %s: %s", to, e)
        return False


def build_reset_code_email(code: str) -> str:
    """Build a styled HTML email body for the password reset code."""
    spaced_code = " ".join(code)
    return f"""\
<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#F0F4FF;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
<tr><td align="center">
<table width="420" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,56,255,0.08);">

<tr><td style="background:linear-gradient(135deg,#0038FF,#2557E8);padding:24px 32px;text-align:center;">
  <div style="font-size:20px;font-weight:700;color:#fff;">навылет! AI</div>
  <div style="font-size:12px;color:rgba(255,255,255,0.7);margin-top:4px;">Личный кабинет</div>
</td></tr>

<tr><td style="padding:32px;">
  <div style="font-size:15px;color:#1E293B;font-weight:600;margin-bottom:8px;">Сброс пароля</div>
  <div style="font-size:13px;color:#64748B;line-height:1.5;margin-bottom:24px;">
    Вы запросили сброс пароля для личного кабинета. Используйте код ниже для подтверждения:
  </div>

  <div style="background:#F8FAFC;border:2px dashed #CBD5E1;border-radius:12px;padding:20px;text-align:center;margin-bottom:24px;">
    <div style="font-size:32px;font-weight:700;letter-spacing:8px;color:#0038FF;font-family:monospace;">
      {spaced_code}
    </div>
  </div>

  <div style="font-size:12px;color:#94A3B8;line-height:1.5;">
    Код действителен <strong>10 минут</strong>.<br>
    Если вы не запрашивали сброс пароля, проигнорируйте это письмо.
  </div>
</td></tr>

<tr><td style="background:#F8FAFC;padding:16px 32px;text-align:center;border-top:1px solid #E2E8F0;">
  <div style="font-size:11px;color:#94A3B8;">Powered by AIMPACT+</div>
</td></tr>

</table>
</td></tr>
</table>
</body></html>"""
