"""
OpenAI GPT Handler — миграция с Yandex GPT на OpenAI (GPT-5 Mini)

Ключевые отличия от YandexGPTHandler:
- Нативный Function Calling (tool_calls) — НЕ нужен plaintext regex parsing
- Формат сообщений: role="tool" для результатов функций (а не role="user")
- OpenAI SDK вместо прямого HTTP к Yandex Completion API

Наследует ВСЮ бизнес-логику из YandexGPTHandler:
- _dispatch_function (~1200 строк маршрутизации TourVisor API)
- _execute_function (выполнение + логирование)
- _check_cascade_slots (проверка полноты каскада)
- Все safety-net правки (F1-F8, P1-P15, R6-R9, C2, H1-H2)
- _resolve_tourid_from_text, _dialogue_log, метрики
"""

import os
import re
import json
import asyncio
import time
import logging
from typing import Optional, Dict, List
from openai import OpenAI
from dotenv import load_dotenv

try:
    from yandex_handler import (
        YandexGPTHandler,
        _is_promised_search,
        _dedup_response,
        _strip_reasoning_leak,
        _strip_technical_ids,
        _dedup_sentences,
        _strip_trailing_fragment,
        StreamCallback,
    )
except ImportError:
    from backend.yandex_handler import (
        YandexGPTHandler,
        _is_promised_search,
        _dedup_response,
        _strip_reasoning_leak,
        _strip_technical_ids,
        _dedup_sentences,
        _strip_trailing_fragment,
        StreamCallback,
    )

load_dotenv()

logger = logging.getLogger("mgp_bot")

_RE_FUNC_NAMES = re.compile(
    r'\(?(get_tour_details|search_tours|get_search_results|'
    r'get_search_status|get_hotel_info|actualize_tour|'
    r'get_hot_tours|continue_search|get_dictionaries|'
    r'get_current_date)\)?',
    re.IGNORECASE
)


class OpenAIHandler(YandexGPTHandler):
    """
    OpenAI GPT Handler с нативным Function Calling.

    Наследует:
    - _dispatch_function (вся бизнес-логика TourVisor API)
    - _execute_function (выполнение + логирование)
    - Все safety-net правки (F1-F8, P1-P15, R6-R9, C2, H1-H2)
    - _resolve_tourid_from_text, _dialogue_log, метрики, tour_cards

    Переопределяет:
    - __init__ (OpenAI SDK вместо Yandex HTTP)
    - chat() (нативные tool_calls вместо plaintext parsing)
    - chat_stream() (делегирует в chat())
    - close_sync(), reset()
    """

    def __init__(self, runtime_config=None):
        # Initialize all shared state from parent (tourvisor, history, metrics, etc.)
        super().__init__(runtime_config=runtime_config)

        # Validate OpenAI API key
        api_key = getattr(runtime_config, "llm_api_key", None) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY не указан в .env! "
                "Добавьте OPENAI_API_KEY=sk-... в backend/.env"
            )

        # Override with OpenAI client
        # OPENAI_BASE_URL — для прокси (если OpenAI API недоступен напрямую, напр. из России)
        base_url = getattr(runtime_config, "openai_base_url", None) or os.getenv("OPENAI_BASE_URL")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
            logger.info("🌐 OpenAI proxy: %s", base_url)

        self.openai_client = OpenAI(timeout=120.0, **client_kwargs)
        self.model = getattr(runtime_config, "llm_model", None) or os.getenv("OPENAI_MODEL", "gpt-5-mini")

        # Pinned context survives history trimming (tour cards summary)
        self._pinned_context: Optional[str] = None
        # Pinned search intent survives trimming (e.g. "без перелёта")
        self._pinned_search_intent: Optional[str] = None
        # Collected cascade slots — injected as system message to prevent "forgetting"
        self._collected_slots: Dict[str, str] = {}
        self._nights_from_date_range = False

        # 0 = не показывали, 1 = мягкое (60 msgs), 2 = финальное (72 msgs)
        self._context_warning_stage = 0

        # Build OpenAI-formatted tools from function_schemas.json
        self.openai_tools = self._build_openai_tools()

        logger.info(
            "🤖 OpenAIHandler INIT  model=%s  tools=%d  assistant=%s  source=%s",
            self.model,
            len(self.openai_tools),
            getattr(runtime_config, "assistant_id", None),
            getattr(runtime_config, "source", "env-default"),
        )

    # ─── Argument sanitizer ──────────────────────────────────────────────

    @staticmethod
    def _sanitize_arguments(arguments: str) -> str:
        """Strip \\r, trailing garbage, and self-correction narratives from model JSON."""
        if not arguments:
            return "{}"
        cleaned = arguments.replace('\r', '').replace('\t', ' ')
        brace_end = cleaned.rfind('}')
        if brace_end >= 0 and brace_end < len(cleaned) - 1:
            cleaned = cleaned[:brace_end + 1]
        brace_start = cleaned.find('{')
        if brace_start > 0:
            cleaned = cleaned[brace_start:]
        return cleaned

    # ─── Tools ────────────────────────────────────────────────────────────

    def _build_openai_tools(self) -> List[Dict]:
        """
        Convert function_schemas.json to OpenAI tools format.

        Yandex format:  {"type": "function", "name": "...", "parameters": {...}}
        OpenAI format:  {"type": "function", "function": {"name": "...", "parameters": {...}}}
        """
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "function_schemas.json"
        )
        with open(schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        openai_tools = []
        for tool in data.get("tools", []):
            if tool.get("type") == "function":
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    }
                })

        logger.info("🔧 Loaded %d OpenAI tools from function_schemas.json", len(openai_tools))
        return openai_tools

    # ─── Messages Builder ─────────────────────────────────────────────────

    def _build_openai_messages(self) -> List[Dict]:
        """
        Build messages array for OpenAI Chat Completions API.

        Format:
        - {"role": "system", "content": "..."}          — system prompt
        - {"role": "user", "content": "..."}             — user messages
        - {"role": "assistant", "content": "..."}        — text responses
        - {"role": "assistant", "tool_calls": [...]}     — function calls
        - {"role": "tool", "tool_call_id": "...", ...}   — function results
        """
        messages = []

        # System prompt
        if self.instructions:
            messages.append({"role": "system", "content": self.instructions})

        # Pinned context (tour cards summary — survives trimming)
        if self._pinned_context:
            messages.append({
                "role": "system",
                "content": self._pinned_context
            })

        # Pinned search intent (e.g. "без перелёта" — survives trimming)
        if self._pinned_search_intent:
            messages.append({
                "role": "system",
                "content": self._pinned_search_intent
            })

        # Collected cascade slots reminder (prevents model from re-asking known params)
        if self._collected_slots:
            slot_lines = [f"- {k}: {v}" for k, v in self._collected_slots.items()]
            _slots_suffix = "\nЕсли клиент НЕ меняет параметр — используй сохранённое значение."
            if self._nights_from_date_range and "Длительность" in self._collected_slots:
                _slots_suffix += (
                    "\n⛔ Ночи ВЫЧИСЛЕНЫ из диапазона дат клиента. "
                    "НЕ спрашивай «на сколько ночей?». Длительность уже известна."
                )
            messages.append({
                "role": "system",
                "content": (
                    "[СОБРАННЫЕ ПАРАМЕТРЫ КЛИЕНТА — НЕ переспрашивай]\n"
                    + "\n".join(slot_lines)
                    + _slots_suffix
                )
            })

        # Full history
        for item in self.full_history:
            role = item.get("role")

            if role == "user":
                messages.append({
                    "role": "user",
                    "content": item.get("content", "")
                })
            elif role == "assistant":
                msg = {"role": "assistant", "content": item.get("content")}
                if "tool_calls" in item:
                    msg["tool_calls"] = item["tool_calls"]
                messages.append(msg)
            elif role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("tool_call_id", ""),
                    "content": item.get("content", "")
                })

        return messages

    # ─── Slot Tracker ──────────────────────────────────────────────────────

    _SLOT_PATTERNS = {
        "Направление": [
            (r'\b(?:турци[яюи]|египе?т|оаэ|эмират|таиланд|мальдив|греци|кипр|'
             r'вьетнам|шри.?ланк|куб[аеу]|доминикан|индонези|бали|тунис|'
             r'черногори|болгари|хорвати|абхази|росси|сочи|крым|анап|'
             r'геленджик|калининград|кмв|марокк|израил|иордани|'
             r'индия|китай|япони|южная корея|мексик|бразили|'
             r'казан[ьи]|карели|байкал|алтай|дагестан|домбай|шерегеш|'
             r'архыз|приэльбрусь|урал|подмосковь|золот\w+ кольц|'
             r'мурманск|псков|воронеж|татарстан)\w*', None),
        ],
        "Город вылета": [
            (r'\b(?:екатеринбург|екб|'
             r'новосибирск|нск|краснодар|красноярск|ростов|уф[аеы]|пермь?|'
             r'челябинск|самар[аеу]|нижн\w+ новгород)\w*', None),
            (r'(?:из|с)\s+(?:москв|казан|питер|спб|санкт.?петербург|сочи)\w*', None),
            (r'без\s*перел[её]т', "без перелёта"),
        ],
        "Даты": [
            (r'(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)', None),
            (r'(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|'
             r'сентября|октября|ноября|декабря)', None),
            (r'(\d{1,2})\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|'
             r'сентября|октября|ноября|декабря)', None),
            (r'после\s+(\d{1,2})\s*[./]?\s*(\d{1,2})', None),
            (r'после\s+(\d{1,2})\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|'
             r'сентябр|октябр|ноябр|декабр)', None),
            (r'ближайш\w*\s*(?:вылет|дат|рейс)?', "ближайший вылет"),
            (r'(?:всё?\s*равно|не\s*важно|неважно)\s*когда', "ближайший вылет"),
            (r'какой\s+есть\s+(?:вылет|рейс)', "ближайший вылет"),
        ],
        "Длительность": [
            (r'(\d+)\s*(?:ноч|ночей)', None),
            (r'(\d+)\s*(?:дн|дней|день)', None),
            (r'(?:на\s+)?(?:неделю|недельку)', "7 ночей"),
            (r'(?:две\s+недели|2\s+недели)', "14 ночей"),
        ],
        "Состав": [
            (r'(?:(\d+)\s*(?:взрослы|взр))', None),
            (r'(?:вдво[её]м|с (?:мужем|женой|парнем|девушкой))', "2 взрослых"),
        ],
        "Дети": [
            (r'(\d+)\s*(?:ребён|ребен|дет)', None),
            (r'(?:без\s*детей)', "без детей"),
        ],
        "Возраст ребёнка": [
            (r'^(\d{1,2})$', None),
        ],
        "Питание": [
            (r'(?:вс[её]\s*включен|all\s*inclusive|олл\s*инклюзив)', "всё включено"),
            (r'(?:завтрак)', "завтраки"),
            (r'(?:полупансион)', "полупансион"),
            (r'(?:полный\s*пансион)', "полный пансион"),
        ],
        "Звёздность": [
            (r'(\d)\s*(?:звёзд|звезд|★|\*)', None),
            (r'\b(люб\w+)\b.*(?:звёзд|звезд|★|\*|категори|вариант)', "любая"),
        ],
        "Отель": [
            # Латинские бренды (международные сети и турецкие/мировые цепочки)
            (r'\b(?:rixos|hilton|delphin|swissotel|kempinski|calista|titanic|gloria|'
             r'regnum|maxx\s*royal|limak|barut|voyage|selectum|papillon|granada|'
             r'nirvana|ic\s+hotels?|ela\s+quality|xanadu|trendy|liberty|sueno|'
             r'crystal|adalya|orange\s*county|club\s*sera|starlight|lara\s*barut|'
             r'sheraton|marriott|radisson|accor|hyatt|intercontinental|iberostar|'
             r'vinpearl|centara|pullman|novotel|melia|riu|sandals|cornelia|'
             r'susesi|cullinan|dobedan|tui\s*blue|amara|royal\s*wings|bellis|'
             r'max\s*royal|asteria|kirman|side\s*star|pine\s*bay|paloma|kaya|'
             r'vogue|amelia|utopia|siam\s*elegant|four\s*seasons|ritz|w\s+hotel|'
             r'jw\s+marriott|st\.\s*regis|waldorf|conrad|sofitel|fairmont)\b', None),
            # Кириллические бренды (как пользователь может написать)
            (r'\b(?:риксос|хилтон|дельфин|шератон|марриотт|радиссон|калиста|'
             r'титаник|глория|регнум|лимак|барут|макс\s*роял|кемпински|'
             r'свиссотель|ибэростар|хаятт|интерконтиненталь|пульман|новотель|'
             r'фор\s*сизонс|мелиа|амара|палома|астериа|вояж|корнелиа|утопия)\b', None),
            # Российские отели (Сочи, Крым, Абхазия, КМВ) — кириллица И латиница
            (r'\b(?:аквамарин|аквалоо|бридж\s*резорт|космос|жемчужина|литфонд|'
             r'маринс\s*парк|богатырь|имеретинск|бархатн\w*|сириус|санрайз|'
             r'sunrise|bridge\s*resort|marins\s*park|bogatyr|mriya|мрия|'
             r'swissotel\s*сочи|гранд\s*отель|парк\s*инн|рэдиссон|азимут|'
             r'cosmos|amaks|амакс|alean|алеан|rosa\s*khutor|роза\s*хутор|'
             r'горки\s*город|radisson\s*rosa|green\s*park|грин\s*парк|'
             r'гранд\s*каньон)\b', None),
            # Контекстный паттерн: "отель X" / "hotel X" / "в отеле X"
            (r'(?:(?:в\s+)?отел[ьеи]|hotel)\s+([а-яёa-z]{3,})', None),
        ],
    }

    _DESTINATION_REGION_CODES = {
        'сочи': '426', 'крым': '423', 'анап': '597', 'геленджик': '598',
        'калининград': '425', 'казан': '517', 'дагестан': '662',
        'алтай': '496', 'шерегеш': '498', 'карели': '526', 'байкал': '565',
        'домбай': '523', 'архыз': '525', 'кмв': '424', 'кисловодск': '424',
        'подмосковь': '469', 'урал': '563', 'мурманск': '668',
        'питер': '470', 'санкт': '470', 'красн': '495',
        'псков': '617', 'воронеж': '661', 'татарстан': '618',
        'приэльбрусь': '524', 'золот': '527',
    }

    def _update_collected_slots(self, user_message: str):
        """Extract and pin cascade parameters from user messages."""
        text = user_message.lower().strip()
        for slot_name, patterns in self._SLOT_PATTERNS.items():
            for pattern, fixed_value in patterns:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    value = fixed_value or m.group(0)
                    if slot_name == "Направление":
                        for prefix, region_id in self._DESTINATION_REGION_CODES.items():
                            if prefix in value:
                                value = f"{value} (regions={region_id})"
                                break
                    self._collected_slots[slot_name] = value
                    break

        # Date-range → nights: "с 16 по 28 апреля", "с 1-15 июня", "1-15 июня" = N ночей
        _range_m = re.search(
            r'(?:с\s+)?(\d{1,2})\s*(?:по|до|-|–)\s*(\d{1,2})\s*'
            r'(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|'
            r'сентябр|октябр|ноябр|декабр)',
            text, re.IGNORECASE
        )
        _has_explicit_duration = bool(re.search(
            r'(\d+)\s*(?:ноч|ночей|дн|дней|день)|(?:на\s+)?(?:неделю|недельку)|(?:две\s+недели|2\s+недели)',
            text, re.IGNORECASE
        ))
        if _range_m:
            _day_from = int(_range_m.group(1))
            _day_to = int(_range_m.group(2))
            _nights = _day_to - _day_from
            if 1 <= _nights <= 30:
                self._collected_slots["Даты"] = _range_m.group(0)
                if not _has_explicit_duration:
                    self._collected_slots["Длительность"] = f"{_nights} ночей"
                    self._nights_from_date_range = True
                    logger.debug("📌 NIGHTS-FROM-RANGE: %d ночей из '%s'", _nights, _range_m.group(0))
                else:
                    logger.debug("📌 DATE-RANGE + EXPLICIT-DURATION: range '%s', не перезаписываем длительность", _range_m.group(0))

        # Context-aware: bare "любой/любая/без разницы" → check what model asked
        if re.match(r'^(?:любой|любая|любые|без разницы|все равно|всё равно|неважно|не важно)$', text):
            last_assistant = ""
            for msg in reversed(self.full_history):
                if msg.get("role") == "assistant" and msg.get("content"):
                    last_assistant = msg["content"].lower()
                    break
            if any(w in last_assistant for w in ("звёзд", "звезд", "категори", "★")):
                self._collected_slots["Звёздность"] = "любая"
            elif any(w in last_assistant for w in ("питани", "meal")):
                self._collected_slots["Питание"] = "любое"

        # Авто-заполнение звёздности при обнаружении отеля/бренда
        if "Отель" in self._collected_slots and "Звёздность" not in self._collected_slots:
            self._collected_slots["Звёздность"] = "авто (из каталога отеля, НЕ спрашивать)"
            logger.debug("📌 HOTEL-AUTO-STARS: %s -> stars auto", self._collected_slots["Отель"])

        if self._collected_slots:
            logger.debug("📌 SLOTS: %s", self._collected_slots)

    # ─── Context Summary (for limit warning) ───────────────────────────────

    def _build_context_summary(self) -> str:
        """Собрать сводку параметров клиента для предупреждения о лимите."""
        lines = []
        if self._collected_slots:
            for k, v in self._collected_slots.items():
                lines.append(f"  {k}: {v}")
        if self._pinned_context:
            for line in self._pinned_context.split("\n"):
                if line.strip() and not line.startswith("["):
                    lines.append(f"  {line.strip()}")
        return "\n".join(lines)

    # ─── History Trimming (tool_call-aware) ───────────────────────────────

    @staticmethod
    def _group_into_blocks(messages):
        """Group messages into atomic blocks: tool_call assistant + its tool results stay together."""
        blocks = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                block = [msg]
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    block.append(messages[j])
                    j += 1
                blocks.append(block)
                i = j
            else:
                blocks.append([msg])
                i += 1
        return blocks

    def _trim_history(self):
        """
        Trim history while preserving tool_call/tool_result pairs as atomic blocks.
        Removes oldest non-system blocks until under the limit.
        """
        if len(self.full_history) <= self._max_history_len:
            return

        old_len = len(self.full_history)
        blocks = self._group_into_blocks(self.full_history)

        total = sum(len(b) for b in blocks)
        while total > self._max_history_len and len(blocks) > 3:
            removed = blocks.pop(1)
            total -= len(removed)

        self.full_history = [msg for block in blocks for msg in block]
        logger.info(
            "✂️ TRIM full_history: %d → %d messages",
            old_len, len(self.full_history)
        )

    # ─── OpenAI API Call ──────────────────────────────────────────────────

    def _call_openai_sync(self, messages: List[Dict]):
        """
        Synchronous OpenAI API call.
        Run in thread via asyncio.to_thread() to avoid blocking the event loop.
        """
        return self.openai_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self.openai_tools,
            temperature=0.2,
            max_tokens=4096,
            extra_body={"reasoning_effort": "low"},
        )

    # ─── Main Chat Loop ──────────────────────────────────────────────────

    async def chat(self, user_message: str) -> str:
        """
        Send message and get response using OpenAI GPT with native tool calling.

        Key differences from YandexGPTHandler.chat():
        - No plaintext function call parsing (tool_calls are native JSON)
        - No content filter bypass (OpenAI doesn't have Yandex's content filter)
        - No role alternation hacks (_append_history not needed)
        - Tool results stored as role="tool" (not role="user")
        """
        # Reset tour cards for this message
        self._pending_tour_cards = []
        self._metrics["total_messages"] += 1

        # Add user message to history
        self.full_history.append({"role": "user", "content": user_message})
        self._trim_history()

        # Track collected cascade slots from user message
        self._update_collected_slots(user_message)

        # Detect and pin "без перелёта" intent so it survives trimming
        if re.search(r'без\s*перел[её]т', user_message, re.IGNORECASE):
            self._pinned_search_intent = "[ПАРАМЕТР КЛИЕНТА: тур БЕЗ ПЕРЕЛЁТА (departure=99). НЕ спрашивай город вылета.]"
            logger.info("📌 Pinned search intent: без перелёта")

        logger.info(
            "👤 USER >> \"%s\"  full_history=%d  model=%s",
            user_message[:150], len(self.full_history), self.model
        )

        max_iterations = 20
        iteration = 0
        chat_start = time.perf_counter()
        empty_retries = 0
        timeout_retries = 0
        geo_retries = 0
        self._last_message_usage = None

        while iteration < max_iterations:
            iteration += 1

            elapsed = time.perf_counter() - chat_start
            if elapsed > 90:
                logger.error(
                    "⏱ WALL-CLOCK TIMEOUT after %.1fs at iteration %d",
                    elapsed, iteration
                )
                return (
                    "Что-то пошло не так — попробуйте повторить "
                    "запрос ещё раз."
                )

            messages = self._build_openai_messages()

            logger.info(
                "🔄 ITERATION %d/%d  messages=%d  model=%s",
                iteration, max_iterations, len(messages), self.model
            )

            t0 = time.perf_counter()
            try:
                response = await asyncio.to_thread(
                    self._call_openai_sync, messages
                )
                api_ms = int((time.perf_counter() - t0) * 1000)

                choice = response.choices[0]
                message = choice.message
                finish_reason = choice.finish_reason

                # Token usage logging
                usage = response.usage
                _total_tokens = None
                _usage_payload = None
                if usage:
                    _total_tokens = usage.total_tokens
                    _usage_payload = {
                        "tokens_prompt": usage.prompt_tokens,
                        "tokens_completion": usage.completion_tokens,
                    }
                    logger.info(
                        "🤖 OPENAI API <<  %dms  finish=%s  "
                        "tokens: prompt=%d completion=%d total=%d",
                        api_ms, finish_reason,
                        usage.prompt_tokens, usage.completion_tokens,
                        usage.total_tokens
                    )
                else:
                    logger.info(
                        "🤖 OPENAI API <<  %dms  finish=%s",
                        api_ms, finish_reason
                    )
                self._last_message_usage = _usage_payload

                self._pending_api_calls.append({
                    "service": "openai",
                    "endpoint": f"chat.completions/{self.model}",
                    "response_code": 200,
                    "tokens_used": _total_tokens,
                    "latency_ms": api_ms,
                })

            except Exception as e:
                api_ms = int((time.perf_counter() - t0) * 1000)
                error_str = str(e)
                logger.error(
                    "🤖 OPENAI API !! ERROR  %dms  %s",
                    api_ms, error_str[:300]
                )

                # Rate limit
                if "429" in error_str or "rate_limit" in error_str.lower():
                    return (
                        "Секундочку, сейчас много обращений — "
                        "повторите через пару секунд!"
                    )

                # Token limit exceeded
                if ("context_length_exceeded" in error_str
                        or "maximum context length" in error_str
                        or "max_tokens" in error_str.lower()):
                    logger.warning(
                        "⚠️ TOKEN LIMIT EXCEEDED — trimming history "
                        "from %d messages",
                        len(self.full_history)
                    )
                    if len(self.full_history) > 8:
                        blocks = self._group_into_blocks(self.full_history)
                        head_blocks = blocks[:1]
                        tail_blocks = blocks[-3:] if len(blocks) > 3 else blocks[1:]
                        self.full_history = [
                            m for b in (head_blocks + tail_blocks) for m in b
                        ]
                        logger.info(
                            "✅ History trimmed to %d messages",
                            len(self.full_history)
                        )
                    empty_retries += 1
                    if empty_retries < 3:
                        continue
                    return (
                        "Наш диалог получился очень длинным — "
                        "начните новый чат, и я с радостью продолжу!"
                    )

                # Invalid request (orphaned tool message, malformed history)
                if "400" in error_str or "invalid" in error_str.lower():
                    logger.warning(
                        "⚠️ 400 ERROR — attempting history cleanup"
                    )
                    self._cleanup_history()
                    empty_retries += 1
                    if empty_retries < 3:
                        continue

                # Timeout (server-side, e.g. OpenRouter)
                if "timed out" in error_str.lower() or "timeout" in error_str.lower():
                    timeout_retries += 1
                    if timeout_retries < 2:
                        logger.warning(
                            "⏱️ TIMEOUT RETRY %d/2 — повтор через 2с",
                            timeout_retries
                        )
                        await asyncio.sleep(2)
                        continue

                # Geo-blocking (OpenRouter → OpenAI from Russia)
                if ("403" in error_str
                        or "unsupported_country" in error_str
                        or "Forbidden" in error_str):
                    geo_retries += 1
                    if geo_retries < 2:
                        logger.warning(
                            "⚠️ 403 GEO-BLOCK RETRY %d/2 — повтор через 3с",
                            geo_retries
                        )
                        await asyncio.sleep(3)
                        continue

                # Connection reset (OpenRouter drops long requests)
                if any(kw in error_str for kw in (
                    "ConnectionReset", "RemoteDisconnected",
                    "Connection reset", "connection reset",
                    "ConnectionError", "RemoteProtocolError",
                )):
                    timeout_retries += 1
                    if timeout_retries < 2:
                        logger.warning(
                            "🔌 CONNECTION RESET RETRY %d/2 — повтор через 3с",
                            timeout_retries
                        )
                        await asyncio.sleep(3)
                        continue

                return (
                    "Что-то пошло не так — попробуйте повторить "
                    "запрос ещё раз."
                )

            # ── Handle tool calls (native) ──
            if message.tool_calls:
                # Store assistant message with tool_calls in history
                assistant_msg = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in message.tool_calls
                    ]
                }
                if _usage_payload:
                    assistant_msg.update(_usage_payload)
                self.full_history.append(assistant_msg)

                # Log
                func_names = [tc.function.name for tc in message.tool_calls]
                logger.info(
                    "🔧 TOOL CALLS: %s", ", ".join(func_names)
                )

                # Guard: truncated tool-call arguments (model hit max_tokens)
                _completion_tokens = usage.completion_tokens if usage else 0
                if finish_reason == "length" or _completion_tokens >= 4086:
                    logger.warning(
                        "⚠️ TOOL CALLS TRUNCATED (finish=%s, completion=%s) — "
                        "skipping execution, injecting hint",
                        finish_reason, _completion_tokens or "?"
                    )
                    for tc in message.tool_calls:
                        self.full_history.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({
                                "error": (
                                    "Аргументы обрезаны — НЕ вызывай get_dictionaries! "
                                    "Коды регионов: Сочи=426, Крым=423, Казань=517, "
                                    "Дагестан=662, Алтай=496, Шерегеш=498, Карелия=526, "
                                    "Байкал=565, КМВ=424, СПб=470, Москва=469, "
                                    "Красная Поляна=495, Анапа=597. "
                                    "Вызови search_tours НАПРЯМУЮ с regions=ID."
                                )
                            }, ensure_ascii=False)
                        })
                    empty_retries += 1
                    if empty_retries >= 3:
                        return (
                            "Что-то пошло не так — попробуйте повторить "
                            "или упростить запрос."
                        )
                    continue

                # Оптимизация: параллельное выполнение tool calls
                _LARGE_FUNCS = {
                    'get_search_results', 'get_hotel_info', 'get_hot_tours'
                }
                _DETAIL_FUNCS = {
                    'get_tour_details'
                }

                def _truncate_tool_output(func_name, output):
                    if func_name in _DETAIL_FUNCS:
                        limit = 4000
                    elif func_name in _LARGE_FUNCS:
                        limit = 2000
                    else:
                        limit = 1000
                    if len(output) > limit:
                        return output[:limit] + "…"
                    return output

                _had_json_error = False

                if len(message.tool_calls) == 1:
                    tc = message.tool_calls[0]
                    arguments = self._sanitize_arguments(tc.function.arguments or "{}")
                    result = await self._execute_function(
                        tc.function.name, arguments, tc.id
                    )
                    output_str = result.get("output", "")
                    if "невалидный JSON" in output_str:
                        _had_json_error = True
                        self._json_error_streak = getattr(self, '_json_error_streak', 0) + 1
                        if self._json_error_streak >= 3:
                            self.full_history.pop()
                            return (
                                "Что-то пошло не так — попробуйте повторить "
                                "запрос ещё раз."
                            )
                        if self._json_error_streak >= 2:
                            result["output"] = json.dumps({
                                "error": (
                                    f"СТОП. Уже {self._json_error_streak} ошибок JSON подряд для {tc.function.name}. "
                                    f"Передай ТОЛЬКО простые параметры из схемы. "
                                    f'Пример: {{"type": "region", "regcountry": 47}}. '
                                    f"Никаких массивов, списков или дополнительных полей."
                                )
                            }, ensure_ascii=False)
                    self.full_history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _truncate_tool_output(
                            tc.function.name, result["output"]
                        )
                    })
                else:
                    async def _exec_tool_call(tool_call):
                        args = self._sanitize_arguments(tool_call.function.arguments or "{}")
                        return (
                            tool_call.id,
                            tool_call.function.name,
                            await self._execute_function(
                                tool_call.function.name, args, tool_call.id
                            )
                        )

                    results = await asyncio.gather(*[
                        _exec_tool_call(tc) for tc in message.tool_calls
                    ])

                    for tc_id, tc_name, result in results:
                        output_str = result.get("output", "")
                        if "невалидный JSON" in output_str:
                            _had_json_error = True
                            self._json_error_streak = getattr(self, '_json_error_streak', 0) + 1
                            if self._json_error_streak >= 2:
                                result["output"] = json.dumps({
                                    "error": (
                                        f"СТОП. Уже {self._json_error_streak} ошибок JSON подряд для {tc_name}. "
                                        f"Передай ТОЛЬКО простые параметры из схемы. "
                                        f'Пример: {{"type": "region", "regcountry": 47}}. '
                                        f"Никаких массивов, списков или дополнительных полей."
                                    )
                                }, ensure_ascii=False)
                        self.full_history.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": _truncate_tool_output(
                                tc_name, result["output"]
                            )
                        })

                    if _had_json_error and getattr(self, '_json_error_streak', 0) >= 3:
                        return (
                            "Что-то пошло не так — попробуйте повторить "
                            "запрос ещё раз."
                        )

                if not _had_json_error:
                    self._json_error_streak = 0

                logger.info(
                    "🔄 TOOL CALLS DONE  count=%d  continuing…",
                    len(message.tool_calls)
                )

                # Update pinned context when tour cards are available
                if self._tourid_map:
                    lines = ["[КОНТЕКСТ: текущие показанные туры]"]
                    for pos, entry in sorted(self._tourid_map.items()):
                        lines.append(
                            f"{pos}. {entry.get('hotelname', '?')} "
                            f"(tourid={entry['tourid']}, "
                            f"hotelcode={entry.get('hotelcode', '?')})"
                        )
                    self._pinned_context = "\n".join(lines)

                continue

            # ── Handle text response ──
            final_text = message.content or ""

            # Content filter (OpenAI)
            if finish_reason == "content_filter":
                empty_retries += 1
                logger.warning(
                    "⚠️ CONTENT_FILTER detected (#%d): \"%s\"",
                    empty_retries, final_text[:100]
                )
                if empty_retries >= 3:
                    return (
                        "Что-то пошло не так — попробуйте "
                        "переформулировать запрос."
                    )
                self.full_history.append({
                    "role": "user",
                    "content": (
                        "Пожалуйста, продолжи помогать "
                        "с подбором тура."
                    )
                })
                continue

            # Truncated response (max_tokens) — trim to last complete sentence
            if finish_reason == "length" and final_text:
                logger.warning(
                    "⚠️ Response truncated (max_tokens). "
                    "Length: %d chars", len(final_text)
                )
                for sep in ['. ', '! ', '? ', '.\n']:
                    idx = final_text.rfind(sep)
                    if idx > len(final_text) * 0.5:
                        final_text = final_text[:idx + 1]
                        break

            # Empty response
            if not final_text:
                empty_retries += 1
                logger.warning(
                    "⚠️ EMPTY RESPONSE #%d", empty_retries
                )
                if empty_retries >= 3:
                    if self._pending_tour_cards:
                        return (
                            "Вот что нашёл по вашему запросу! "
                            "Посмотрите варианты и скажите, "
                            "какой заинтересовал — расскажу подробнее."
                        )
                    return (
                        "Что-то пошло не так — попробуйте повторить "
                        "запрос ещё раз."
                    )
                self.full_history.append({
                    "role": "user",
                    "content": (
                        "Продолжи обработку моего запроса "
                        "на основе полученных данных."
                    )
                })
                continue

            # Safety-net: deadlock cycle "уже показаны" / "горящие туры уже показаны"
            _already_shown_match = re.search(
                r'(?:горящие\s+)?туры?\s+уже\s+(?:показан|отображ|выведен)',
                final_text, re.IGNORECASE
            )
            if _already_shown_match:
                _recent_assistant = [
                    m.get("content", "") for m in self.full_history[-10:]
                    if m.get("role") == "assistant" and m.get("content")
                ]
                _already_shown_count = sum(
                    1 for txt in _recent_assistant
                    if re.search(r'туры?\s+уже\s+(?:показан|отображ)', txt, re.IGNORECASE)
                )
                if _already_shown_count >= 1:
                    empty_retries += 1
                    logger.warning(
                        "⚠️ ALREADY-SHOWN-DEADLOCK detected (#%d): count=%d",
                        empty_retries, _already_shown_count
                    )
                    if empty_retries < 2:
                        self.full_history.append({"role": "assistant", "content": final_text})
                        self.full_history.append({"role": "user", "content":
                            "СИСТЕМНАЯ ОШИБКА: Ты уже говорил 'туры показаны', но клиент "
                            "их не видит — это проблема интерфейса. ЗАПРЕЩЕНО повторять "
                            "'уже показаны'! Вместо этого: 1) Предложи обновить страницу; "
                            "2) ВЫЗОВИ get_hot_tours заново чтобы отправить данные повторно; "
                            "3) Предложи сделать обычный поиск search_tours. "
                            "ДЕЙСТВУЙ, не объясняй!"
                        })
                        continue

            # Safety-net: bot asks about dates but user said "ближайший" or "после X"
            _asks_date = re.search(
                r'(?:как\w+\s*месяц|какие\s*дат|когда\s*план|на\s*как\w+\s*месяц|'
                r'промежут\w*\s*дат|уточн\w+\s*дат|конкретн\w+\s*дат)',
                final_text, re.IGNORECASE
            )
            if _asks_date:
                _user_said_nearest = any(
                    re.search(r'ближайш|всё?\s*равно.*когда|неважно\s*когда|не\s*важно\s*когда',
                              m.get("content", ""), re.IGNORECASE)
                    for m in self.full_history[-8:] if m.get("role") == "user"
                )
                # Check for "после X" pattern (date, not duration like "после 3 дней")
                _after_date_re = (
                    r'после\s+(\d{1,2})\s*[./ ]\s*(\d{1,2})(?!\s*(?:ноч|дн|дней|день|недел))'
                    r'|после\s+(\d{1,2})\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|'
                    r'сентябр|октябр|ноябр|декабр)'
                )
                _user_said_after = any(
                    re.search(_after_date_re, m.get("content", ""), re.IGNORECASE)
                    for m in self.full_history[-8:] if m.get("role") == "user"
                )
                if _user_said_after:
                    empty_retries += 1
                    logger.warning(
                        "⚠️ DATE-ASK-AFTER-OVERRIDE: bot asks date but user said 'после X' (#%d)",
                        empty_retries
                    )
                    if empty_retries < 2:
                        # Extract the "после X" value from user messages
                        _month_map = {
                            'январ': '01', 'феврал': '02', 'март': '03', 'апрел': '04',
                            'мая': '05', 'май': '05', 'июн': '06', 'июл': '07',
                            'август': '08', 'сентябр': '09', 'октябр': '10',
                            'ноябр': '11', 'декабр': '12',
                        }
                        _after_day = "?"
                        _after_month = "?"
                        for m in self.full_history[-8:]:
                            if m.get("role") != "user":
                                continue
                            _txt = m.get("content", "")
                            # Try "после DD.MM" or "после DD MM"
                            _dm = re.search(r'после\s+(\d{1,2})\s*[./ ]\s*(\d{1,2})', _txt, re.IGNORECASE)
                            if _dm:
                                _after_day = _dm.group(1)
                                _after_month = _dm.group(2).zfill(2)
                                break
                            # Try "после DD месяц_название"
                            _dn = re.search(
                                r'после\s+(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|'
                                r'ма[яй]\w*|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|'
                                r'ноябр\w*|декабр\w*)', _txt, re.IGNORECASE
                            )
                            if _dn:
                                _after_day = _dn.group(1)
                                _mname = _dn.group(2).lower()
                                for prefix, num in _month_map.items():
                                    if _mname.startswith(prefix):
                                        _after_month = num
                                        break
                                break
                        self.full_history.append({"role": "assistant", "content": final_text})
                        self.full_history.append({"role": "user", "content":
                            f"СИСТЕМНАЯ ОШИБКА: Клиент сказал 'после {_after_day}.{_after_month}'. "
                            f"Это означает datefrom={_after_day}.{_after_month}! "
                            f"НЕ спрашивай конкретную дату! Слот Даты ЗАПОЛНЕН. "
                            f"dateto = datefrom + 14 дней. "
                            f"Если ночи неизвестны — спроси ТОЛЬКО про ночи, НЕ про даты."
                        })
                        continue
                if _user_said_nearest:
                    empty_retries += 1
                    logger.warning(
                        "⚠️ DATE-ASK-OVERRIDE: bot asks date but user said 'ближайший' (#%d)",
                        empty_retries
                    )
                    if empty_retries < 2:
                        self.full_history.append({"role": "assistant", "content": final_text})
                        self.full_history.append({"role": "user", "content":
                            "СИСТЕМНАЯ ОШИБКА: Клиент сказал 'ближайший вылет'. "
                            "НЕ спрашивай дату! НЕМЕДЛЕННО вызови search_tours "
                            "с datefrom=завтра, dateto=+14 дней. "
                            "Слот Даты ЗАПОЛНЕН."
                        })
                        continue

            # Safety-net: bot asks about nights but user gave "с X по Y"
            _asks_nights = re.search(
                r'(?:сколько\s*ноч|на\s*сколько\s*ноч|длительн|количеств\w*\s*ноч)',
                final_text, re.IGNORECASE
            )
            if _asks_nights:
                _all_user = " ".join(
                    m.get("content", "") for m in self.full_history[-8:]
                    if m.get("role") == "user"
                ).lower()
                _range_match = re.search(
                    r'с\s+(\d{1,2})\s*(?:по|до)\s*(\d{1,2})\s*'
                    r'(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|'
                    r'сентябр|октябр|ноябр|декабр)',
                    _all_user, re.IGNORECASE
                )
                if _range_match:
                    _n = int(_range_match.group(2)) - int(_range_match.group(1))
                    if 1 <= _n <= 30:
                        empty_retries += 1
                        logger.warning(
                            "⚠️ NIGHTS-ASK-OVERRIDE: bot asks nights but range=%d (#%d)",
                            _n, empty_retries
                        )
                        if empty_retries < 2:
                            self.full_history.append({"role": "assistant", "content": final_text})
                            self.full_history.append({"role": "user", "content":
                                f"СИСТЕМНАЯ ОШИБКА: Клиент указал 'с {_range_match.group(1)} "
                                f"по {_range_match.group(2)}' = {_n} ночей. НЕ спрашивай ночи! "
                                f"nightsfrom={_n}, nightsto={_n}. "
                                f"НЕМЕДЛЕННО вызови search_tours."
                            })
                            continue

            # Safety-net: bot asks about QC (stars/meal) before Состав slot
            # Only match actual QUESTIONS (какой/какую/сколько), not statements like "подберу 4★ всё включено"
            _asks_qc = re.search(
                r'(?:как\w+\s*(?:категори|звёзд|питани)|какую?\s*(?:категори|звёзд|питани)|'
                r'сколько\s*звёзд|какую?\s*звёздност\w*|тип\s*питани\w*\s*(?:предпочит|хотите|интерес|рассматр))',
                final_text, re.IGNORECASE
            )
            _has_composition = (
                "Состав" in self._collected_slots or
                "Дети" in self._collected_slots or
                any(re.search(r'(?:взросл|детей|ребён|вдвоём|семь|компани)', m.get("content", ""), re.IGNORECASE)
                    for m in self.full_history[-10:] if m.get("role") == "user")
            )
            if _asks_qc and not _has_composition:
                empty_retries += 1
                logger.warning(
                    "⚠️ QC-BEFORE-COMPOSITION: bot asks QC but Состав unknown (#%d)",
                    empty_retries
                )
                if empty_retries < 2:
                    self.full_history.append({"role": "assistant", "content": final_text})
                    self.full_history.append({"role": "user", "content":
                        "СИСТЕМНАЯ ОШИБКА: Ты спросил о звёздности/питании (слот 5), "
                        "но ещё не знаешь СОСТАВ группы (слот 4)! "
                        "СТРОГИЙ ПОРЯДОК: Направление → Город → Даты → **Состав** → QC. "
                        "СНАЧАЛА спроси: 'Сколько взрослых и будут ли дети?' "
                        "Только ПОСЛЕ этого переходи к QC."
                    })
                    continue

            # Safety-net: bot asks about stars but user named a specific hotel/brand
            _asks_stars = re.search(
                r'(?:как\w+\s*(?:категори|звёзд)|какую?\s*(?:категори|звёзд)|'
                r'сколько\s*звёзд|звёздност\w*\s*(?:отел|предпочит)|'
                r'категори\w+\s*отел)',
                final_text, re.IGNORECASE
            )
            if _asks_stars and "Отель" in self._collected_slots:
                empty_retries += 1
                logger.warning(
                    "⚠️ STARS-ASK-OVERRIDE: bot asks stars but hotel='%s' (#%d)",
                    self._collected_slots["Отель"], empty_retries
                )
                if empty_retries < 2:
                    self.full_history.append({"role": "assistant", "content": final_text})
                    self.full_history.append({"role": "user", "content":
                        f"СИСТЕМНАЯ ОШИБКА: Клиент назвал конкретный отель "
                        f"'{self._collected_slots['Отель']}'. НЕ спрашивай звёздность! "
                        f"Звёздность определяется автоматически из каталога. "
                        f"Найди отель через get_dictionaries(type=hotel) и продолжи."
                    })
                    continue

            # Promised search detection (safety-net)
            if _is_promised_search(final_text):
                empty_retries += 1
                self._metrics["promised_search_detections"] = \
                    self._metrics.get("promised_search_detections", 0) + 1
                logger.warning(
                    "⚠️ PROMISED-SEARCH detected (#%d): \"%s\"",
                    empty_retries, final_text[:150]
                )
                if empty_retries < 2:
                    self.full_history.append({
                        "role": "assistant", "content": final_text
                    })
                    self.full_history.append({
                        "role": "user",
                        "content": (
                            "СИСТЕМНАЯ ОШИБКА: Ты ОПИСАЛ намерение "
                            "поиска текстом, но НЕ вызвал функцию. "
                            "НЕМЕДЛЕННО вызови get_current_date(), "
                            "затем search_tours() с собранными "
                            "параметрами. НИКОГДА не пиши "
                            "'сейчас поищу' — ВЫЗЫВАЙ функцию!"
                        )
                    })
                    continue

            # Search pipeline break detection (safety-net)
            if getattr(self, '_search_awaiting_results', False):
                logger.warning(
                    "⚠️ SEARCH-PIPELINE-BREAK: model stopped without get_search_results"
                )
                empty_retries += 1
                if empty_retries < 3:
                    self.full_history.append({
                        "role": "assistant", "content": final_text
                    })
                    self.full_history.append({
                        "role": "user",
                        "content": (
                            f"СИСТЕМНАЯ ОШИБКА: search_tours вернул requestid, "
                            f"но ты НЕ вызвал get_search_status и get_search_results. "
                            f"НЕМЕДЛЕННО вызови get_search_status(requestid="
                            f"{self._last_requestid}). НЕ отвечай клиенту пока "
                            f"не получишь результаты через get_search_results!"
                        )
                    })
                    continue
                else:
                    self._search_awaiting_results = False

            # Result leak detection (safety-net)
            if final_text.lstrip().startswith("Результаты запросов"):
                logger.warning("⚠️ RESULT-LEAK detected")
                self._metrics.setdefault("result_leak_filtered", 0)
                self._metrics["result_leak_filtered"] += 1
                if self._pending_tour_cards:
                    final_text = (
                        "Вот что нашёл по вашему запросу! "
                        "Посмотрите варианты и скажите, "
                        "какой заинтересовал — расскажу подробнее."
                    )
                else:
                    empty_retries += 1
                    if empty_retries < 3:
                        self.full_history.append({
                            "role": "assistant", "content": final_text
                        })
                        self.full_history.append({
                            "role": "user",
                            "content": (
                                "Ответь клиенту нормальным текстом — "
                                "НЕ показывай сырые данные функций. "
                                "Если нужно вызвать ещё функцию — вызови."
                            )
                        })
                        continue
                    final_text = "Я обработал ваш запрос. Чем могу помочь?"

            # Dedup (safety-net, unlikely with OpenAI but harmless)
            final_text = _dedup_response(final_text)

            # Strip leaked LLM reasoning / JSON fragments from end of response
            final_text = _strip_reasoning_leak(final_text)

            # Strip leaked internal IDs (tourid, hotelcode, requestid)
            final_text = _strip_technical_ids(final_text)

            # Sentence-level dedup (catches intra-paragraph question repeats)
            final_text = _dedup_sentences(final_text)

            # Strip orphaned dialogue-continuation fragments after last '?'
            final_text = _strip_trailing_fragment(final_text)

            # Strip leaked function names (e.g. "get_tour_details")
            final_text = _RE_FUNC_NAMES.sub('', final_text)
            final_text = re.sub(r'\s{2,}', ' ', final_text).strip()

            # Hide technical error messages from user
            final_text = re.sub(
                r'(?:возникла\s+)?техническ\w+\s+ошибк\w+',
                'не удалось выполнить поиск',
                final_text, flags=re.IGNORECASE
            )

            # Save to history
            assistant_entry = {"role": "assistant", "content": final_text}
            if _usage_payload:
                assistant_entry.update(_usage_payload)
            self.full_history.append(assistant_entry)

            # ── Context limit warning ──
            _hist_len = len(self.full_history)
            _is_error_response = final_text.startswith(("Что-то пошло не так", "Секундочку", "Наш диалог получился", "Извините", "Произошла", "К сожалению"))

            if not _is_error_response and self._context_warning_stage < 2:
                _WARNING_SOFT = 60
                _WARNING_HARD = 72

                if _hist_len >= _WARNING_HARD and self._context_warning_stage < 2:
                    summary = self._build_context_summary()
                    warning = (
                        "\n\n---\n"
                        "Диалог подходит к завершению. Рекомендую связаться с менеджером: "
                        "+7 (499) 685-25-57 или начать новый чат."
                    )
                    if summary:
                        warning += (
                            "\nВот данные из нашего разговора, чтобы не пришлось повторять:\n"
                            + summary
                        )
                    final_text += warning
                    self._context_warning_stage = 2
                    logger.info(
                        "⚠️ CONTEXT-WARNING stage=2 (hard)  history=%d",
                        _hist_len
                    )

                elif _hist_len >= _WARNING_SOFT and self._context_warning_stage < 1:
                    final_text += (
                        "\n\n---\n"
                        "Наш диалог уже достаточно длинный. Для максимального "
                        "качества подбора рекомендую связаться с менеджером "
                        "по телефону +7 (499) 685-25-57 — он поможет оформить "
                        "бронирование и ответит на все вопросы. "
                        "Также вы можете начать новый чат."
                    )
                    self._context_warning_stage = 1
                    logger.info(
                        "⚠️ CONTEXT-WARNING stage=1 (soft)  history=%d",
                        _hist_len
                    )

            total_ms = int((time.perf_counter() - chat_start) * 1000)
            logger.info(
                "🤖 ASSISTANT << %d chars  %d iterations  %dms total  \"%s\"",
                len(final_text), iteration, total_ms,
                final_text[:200] + ("…" if len(final_text) > 200 else "")
            )
            return final_text

        logger.error("🤖 MAX ITERATIONS REACHED (%d)", max_iterations)
        return (
            "Что-то пошло не так — попробуйте уточнить "
            "параметры и повторить."
        )

    # ─── History Cleanup ──────────────────────────────────────────────────

    def _cleanup_history(self):
        """
        Remove invalid message sequences from full_history.
        Uses block grouping to keep tool_call/tool_result pairs atomic.
        """
        blocks = self._group_into_blocks(self.full_history)
        cleaned_blocks = []
        for block in blocks:
            msg = block[0]
            if msg.get("role") == "tool":
                logger.debug(
                    "🧹 CLEANUP: skipping orphaned tool message "
                    "tool_call_id=%s",
                    msg.get("tool_call_id", "?")
                )
                continue
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                tc_ids = {tc["id"] for tc in msg["tool_calls"]}
                found_ids = {
                    m.get("tool_call_id")
                    for m in block[1:]
                    if m.get("role") == "tool"
                }
                if tc_ids != found_ids:
                    logger.debug(
                        "🧹 CLEANUP: removing incomplete tool_call block "
                        "expected=%s found=%s",
                        tc_ids, found_ids
                    )
                    continue
            cleaned_blocks.append(block)

        cleaned = [msg for block in cleaned_blocks for msg in block]
        if len(cleaned) != len(self.full_history):
            logger.info(
                "🧹 CLEANUP: %d → %d messages (removed %d invalid)",
                len(self.full_history), len(cleaned),
                len(self.full_history) - len(cleaned)
            )
        self.full_history = cleaned

    # ─── Streaming (fallback to non-streaming) ────────────────────────────

    async def chat_stream(
        self,
        user_message: str,
        on_token: Optional[StreamCallback] = None
    ) -> str:
        """
        Streaming not yet implemented for OpenAI.
        Falls back to regular chat().
        """
        logger.warning(
            "⚠️ chat_stream() fallback to chat() — "
            "streaming не реализован для OpenAI"
        )
        result = await self.chat(user_message)
        if on_token:
            on_token(result)
        return result

    # ─── Lifecycle ────────────────────────────────────────────────────────

    def close_sync(self):
        """Close OpenAI client resources."""
        try:
            self.openai_client.close()
        except Exception:
            pass

    def reset(self):
        """Reset dialogue history and all caches."""
        old_len = len(self.full_history)
        self.full_history = []
        self.input_list = []
        self._pending_tour_cards = []
        self._pinned_context = None
        self._pinned_search_intent = None
        self._collected_slots = {}
        self._nights_from_date_range = False
        self._last_departure_city = "Москва"
        self._last_requestid = None
        self._tourid_map = {}
        self._tour_details_cache = {}
        self._shown_flight_signatures = {}
        self._last_search_params = {}
        self._user_stated_budget = None
        self._empty_iterations = 0
        self.previous_response_id = None
        self._pending_api_calls = []
        self._last_message_usage = None
        self._json_error_streak = 0
        self._context_warning_stage = 0
        self._metrics = {
            "promised_search_detections": 0,
            "cascade_incomplete_detections": 0,
            "dateto_corrections": 0,
            "total_searches": 0,
            "total_messages": 0,
        }
        logger.info(
            "🔄 HANDLER RESET  cleared %d messages from full_history",
            old_len
        )
