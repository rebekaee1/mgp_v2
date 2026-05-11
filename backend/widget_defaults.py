"""Single source of truth for default widget settings.

Imported by both the dashboard API (which surfaces defaults in the editor
preview) and the runtime metadata endpoint (which serves them to channel
adapters like ``mgp-max-bridge``). Keeping the values in one place ensures
the website widget and the MAX bot show the *same* greeting / branding
when a tenant has not customised them yet.
"""

from __future__ import annotations


WIDGET_DEFAULTS: dict[str, object] = {
    # Same first-line greeting the dashboard preview shows. Long enough to
    # explain what the bot can do, short enough to fit comfortably in a
    # mobile messenger viewport. Markdown is supported by both renderers
    # (website widget + MAX bridge) so ``**bold**`` here works in both
    # channels.
    "welcome_message": (
        "\U0001f44b Здравствуйте! Я — ИИ-ассистент туристического агентства.\n\n"
        "Я помогу вам:\n"
        "• \U0001f50d Подобрать тур по вашим параметрам\n"
        "• \U0001f525 Найти горящие предложения\n"
        "• \u2753 Ответить на вопросы о визах, оплате, документах\n\n"
        "Куда бы вы хотели поехать?"
    ),
    "primary_color": "#E30613",
    "position": "bottom-right",
    "title": "AI Ассистент",
    "subtitle": "Турагентство",
    "logo_url": None,
}
