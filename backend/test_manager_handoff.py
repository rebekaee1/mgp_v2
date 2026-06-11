"""Юнит-тесты чистой логики manager_handoff (без БД/Flask).

Запуск: pytest backend/test_manager_handoff.py
Проверяют главный инвариант: по умолчанию фича ИНЕРТНА, и гейт/триггеры
включаются только при флаге + allow-list + channel='max'.
"""
import sys
import types


def _load(enabled=False, allow="", channels="max", resume=10,
          widget_all=False, widget_allow=""):
    cfg = types.ModuleType("config")

    class S:
        operator_handoff_enabled = enabled
        operator_handoff_assistant_ids = allow
        operator_handoff_channels = channels
        operator_handoff_resume_minutes = resume
        operator_handoff_widget_all_tenants = widget_all
        operator_handoff_widget_assistant_ids = widget_allow

    cfg.settings = S()
    sys.modules["config"] = cfg
    import importlib
    import manager_handoff
    importlib.reload(manager_handoff)
    return manager_handoff


AID = "593471b7-42da-4ae0-8499-904dcedd6a4b"


def test_inert_by_default():
    mh = _load(enabled=False, allow=AID)
    assert mh.handoff_enabled(AID, "max") is False


def test_enabled_only_for_allowlisted_max():
    mh = _load(enabled=True, allow=AID)
    assert mh.handoff_enabled(AID, "max") is True
    assert mh.handoff_enabled(AID, "widget") is False           # канал-гейт
    assert mh.handoff_enabled("other-uuid", "max") is False      # allow-list
    assert mh.handoff_enabled(None, "max") is False
    assert mh.handoff_enabled("", "max") is False


def test_trigger_classification():
    mh = _load(enabled=True, allow=AID)
    # booking — само-намерение брони (без упоминания менеджера)
    assert mh.classify_user_trigger("Хочу забронировать") == mh.REASON_BOOKING
    assert mh.classify_user_trigger("оформляем этот вариант") == mh.REASON_BOOKING
    assert mh.classify_user_trigger("беру первый") == mh.REASON_BOOKING
    # manager_request — нужен человек / консультация / бронь ЧЕРЕЗ менеджера
    assert mh.classify_user_trigger("дайте номер менеджера") == mh.REASON_MANAGER_REQUEST
    assert mh.classify_user_trigger("хочу проконсультироваться с менеджером") == mh.REASON_MANAGER_REQUEST
    assert mh.classify_user_trigger("оформить через менеджера") == mh.REASON_MANAGER_REQUEST
    assert mh.classify_user_trigger("соедините с человеком") == mh.REASON_MANAGER_REQUEST
    # contact
    assert mh.classify_user_trigger("+7 916 123-45-67") == mh.REASON_CONTACT
    assert mh.classify_user_trigger("8 916 123 45 67") == mh.REASON_CONTACT
    # широкая эвристика / просто интерес больше НЕ триггерит
    assert mh.classify_user_trigger("смотрю варианты") is None
    assert mh.classify_user_trigger("просто смотрю") is None


def test_priority_order():
    mh = _load(enabled=True, allow=AID)
    # manager_request > contact > booking
    assert mh.classify_user_trigger("дайте менеджера, мой +79161234567") == mh.REASON_MANAGER_REQUEST
    assert mh.classify_user_trigger("хочу забронировать, мой +79161234567") == mh.REASON_CONTACT
    assert (mh.reason_priority(mh.REASON_MANAGER_REQUEST)
            > mh.reason_priority(mh.REASON_CONTACT)
            > mh.reason_priority(mh.REASON_BOOKING) > 0)


def test_no_false_phone_from_long_ids():
    mh = _load(enabled=True, allow=AID)
    assert mh.has_contact("[ИСТОЧНИК: utm_id_99000099000099]") is False
    assert mh.has_contact("заказ 1234567890123456789") is False


def test_alert_reasons():
    mh = _load(enabled=True, allow=AID)
    for r in (mh.REASON_MANAGER_REQUEST, mh.REASON_BOOKING, mh.REASON_CONTACT):
        assert r in mh.ALERT_REASONS
    # широкая эвристика и клик кнопки больше не уведомляют
    assert mh.REASON_BOOKING_INTENT not in mh.ALERT_REASONS
    assert mh.REASON_BOOK_CLICK not in mh.ALERT_REASONS


def test_resume_seconds():
    assert _load(resume=10).resume_after_seconds() == 600
    assert _load(resume=7).resume_after_seconds() == 420
    assert _load(resume=0).resume_after_seconds() == 60   # пол не ниже 60с


def test_texts_no_emoji_for_client():
    mh = _load()
    for txt in (
        mh.ANNOUNCE_TEXT, mh.RESUME_INVITE_TEXT,
        mh.ACK_MANAGER_NOTIFIED, mh.ACK_MANAGER_NOTIFIED_ASK_PHONE,
        mh.OPERATOR_JOINED_TEXT,
    ):
        assert txt and not any(ord(c) > 0x2600 for c in txt), "клиентский текст без эмодзи"


def test_widget_gate_off_when_channel_excluded():
    # widget не в channels → инертно, даже если включён all_tenants
    mh = _load(enabled=True, channels="max", widget_all=True)
    assert mh.handoff_enabled(AID, "widget") is False


def test_widget_all_tenants():
    mh = _load(enabled=True, channels="max,widget", widget_all=True)
    assert mh.handoff_enabled(AID, "widget") is True
    assert mh.handoff_enabled("any-other-uuid", "widget") is True   # все виджеты
    assert mh.handoff_enabled(AID, "max") is False                  # MAX по своему allow-list (пуст)


def test_widget_allowlist_only():
    mh = _load(enabled=True, channels="max,widget", widget_all=False, widget_allow=AID)
    assert mh.handoff_enabled(AID, "widget") is True
    assert mh.handoff_enabled("other-uuid", "widget") is False
    assert mh.handoff_enabled(AID, "max") is False                  # MAX не задет


def test_max_unaffected_by_widget_flags():
    # MAX работает по operator_handoff_assistant_ids, не по виджет-флагам
    mh = _load(enabled=True, allow=AID, channels="max,widget", widget_all=True)
    assert mh.handoff_enabled(AID, "max") is True
    assert mh.handoff_enabled(AID, "widget") is True


def test_request_ack_text_contact_aware():
    mh = _load()
    # контакт уже есть → не просим телефон
    assert mh.request_ack_text(True) == mh.ACK_MANAGER_NOTIFIED
    assert "телефон" not in mh.request_ack_text(True).lower()
    # контакта нет → мягко просим номер
    assert mh.request_ack_text(False) == mh.ACK_MANAGER_NOTIFIED_ASK_PHONE
    assert "телефон" in mh.request_ack_text(False).lower()
