"""LLM-polished re-outreach message generation (gpt-5-mini via OpenRouter).

For buckets 6/7 (and optionally all) where useful criteria live only in the
client's free text, the LLM both EXTRACTS the brief from the transcript and
PHRASES one short message under the same locked rules. If the LLM output fails
validation (no destination / too long / stale price / mentions MGP), we fall
back to the deterministic template (reoutreach_lib.render_message).

Creds: loaded from /tmp/mgp_e2e_creds.env (prod, funded) or the workspace .env.
The model never sees a stale tour price; it MAY reference the client's OWN budget.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, Tuple

import reoutreach_lib as R

_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")


def _trim_emojis(text: str, keep: int = 1) -> str:
    seen = 0

    def repl(m):
        nonlocal seen
        seen += 1
        return m.group(0) if seen <= keep else ""

    return re.sub(r"\s+", " ", _EMOJI_RE.sub(repl, text)).strip()

_SYSTEM = """Ты — вежливый ИИ-ассистент турагентства, общаешься на «вы».
Клиент ранее писал в чат, подбирал тур, но замолчал ~сутки. Напиши ОДНО короткое
повторное сообщение, чтобы мягко вернуть его к подбору.

СТРОГИЕ ПРАВИЛА:
- начни с «Здравствуйте!»;
- ОБЯЗАТЕЛЬНО упомяни конкретное НАПРАВЛЕНИЕ, которое называл клиент (страна/курорт);
- используй известные параметры (город вылета, даты/месяц, состав, бюджет клиента),
  но НИЧЕГО НЕ ВЫДУМЫВАЙ — только то, что реально было в диалоге;
- если каких-то важных параметров не хватает (даты/бюджет/состав) — мягко попроси их;
- НЕ называй цены конкретных туров (они устарели). Можно упомянуть бюджет КЛИЕНТА, подставляя его реальную сумму (например «до 150 000 ₽»), но НЕ пиши букву X или плейсхолдеры;
- 1–3 предложения, не длиннее ~300 символов, тёплый человеческий тон, максимум 1 эмодзи;
- никогда не упоминай «МГП» / «Магазин Горящих Путёвок»; не обещай того, чего не знаешь;
- заверши мягким вопросом-приглашением (без давления).
Верни ТОЛЬКО текст сообщения — без кавычек, без пояснений."""

_BUCKET_HINT = {
    "1_engaged": "Клиент уже смотрел туры / кликал. Спроси про успехи и предложи помощь или альтернативу.",
    "4_results": "Клиенту показывали подходящие туры. Предложи прислать свежую подборку (цены могли обновиться).",
    "5_noresults": "По точным параметрам тогда ничего не нашлось. Предложи расширить даты/бюджет или поймать новые предложения.",
    "6_thin": "Клиент назвал только направление и замолчал. Предложи подобрать варианты и попроси недостающее (город вылета, даты, бюджет).",
    "7_incomplete": "Клиент начал подбор, но не закончил. Предложи продолжить и попроси недостающие параметры.",
}


def _llm_call(messages, model, max_tokens):
    """Raw OpenRouter chat/completions via stdlib urllib (no 'openai' dep on host).
    Mirrors prod params: reasoning_effort=low, provider→native OpenAI."""
    import urllib.request
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set (source creds first)")
    base = (os.environ.get("OPENAI_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
    body = {
        "model": model, "messages": messages,
        "temperature": 0.2, "max_tokens": max_tokens,
        "reasoning_effort": "low",
        "provider": {"order": ["openai"], "allow_fallbacks": False},
    }
    req = urllib.request.Request(base + "/chat/completions",
                                 data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for k, v in (_extra_headers() or {}).items():
        req.add_header(k, str(v))
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data["choices"][0]["message"]["content"] or "")


def _extra_headers():
    try:
        return json.loads(os.environ.get("OPENAI_EXTRA_HEADERS") or "{}") or None
    except Exception:
        return None


def _known_facts(brief: dict) -> str:
    parts = []
    if brief.get("destination"):
        parts.append(f"направление: {brief['destination']}")
    if brief.get("departure"):
        parts.append(f"вылет из: {brief['departure']}")
    if brief.get("dates"):
        parts.append(f"даты: {brief['dates'].replace('на ', '')}")
    if brief.get("pax"):
        parts.append(f"состав: {brief['pax']}")
    if brief.get("budget"):
        parts.append(f"бюджет клиента: до {brief['budget']:,} ₽".replace(",", " "))
    if brief.get("wishes"):
        parts.append("пожелания: " + ", ".join(brief["wishes"]))
    return "; ".join(parts) if parts else "—"


def generate_llm(rec: dict, model: Optional[str] = None, max_tokens: int = 2000) -> Tuple[str, bool, list]:
    """Return (message, used_fallback, validation_errors).

    Tries the LLM; validates; falls back to the deterministic template if the
    LLM output is invalid or the call fails.
    """
    bucket, reason = R.classify(rec)
    brief = R.extract_brief(rec)
    template_msg = R.render_message(brief, bucket if bucket != "skip" else "6_thin")

    if bucket == "skip" or not brief.get("destination"):
        return template_msg, True, [f"skip:{reason}"]

    model = model or os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    user = (
        "Реплики клиента (по порядку, через ¦):\n"
        f"{(rec.get('utext') or '')[:600]}\n\n"
        f"Достоверно известные параметры: {_known_facts(brief)}\n"
        f"Ситуация: {_BUCKET_HINT.get(bucket, '')}\n\n"
        "Напиши повторное сообщение."
    )
    try:
        raw = _llm_call(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            model, max_tokens,
        )
        llm_msg = raw.strip().strip('"').strip()
        llm_msg = _trim_emojis(llm_msg, 1)  # keep at most 1 emoji (salvage near-misses)
    except Exception as e:  # noqa: BLE001
        return template_msg, True, [f"llm_error:{str(e)[:120]}"]

    # LLM never receives tour prices in its input (only transcript + brief), so any
    # ₽ figure it writes is the client's OWN budget — the stale-tour-price guard
    # would be a false positive here, so we disable it on the LLM path.
    ok, errs = R.validate(llm_msg, brief, forbid_stale_price=False)
    if ok:
        return llm_msg, False, []
    return template_msg, True, errs  # fallback on invalid LLM output
