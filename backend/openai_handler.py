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

    def __init__(self):
        # Initialize all shared state from parent (tourvisor, history, metrics, etc.)
        super().__init__()

        # Validate OpenAI API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY не указан в .env! "
                "Добавьте OPENAI_API_KEY=sk-... в backend/.env"
            )

        # Override with OpenAI client
        # OPENAI_BASE_URL — для прокси (если OpenAI API недоступен напрямую, напр. из России)
        base_url = os.getenv("OPENAI_BASE_URL")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
            logger.info("🌐 OpenAI proxy: %s", base_url)

        self.openai_client = OpenAI(timeout=120.0, **client_kwargs)
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

        # Pinned context survives history trimming (tour cards summary)
        self._pinned_context: Optional[str] = None
        # Pinned search intent survives trimming (e.g. "без перелёта")
        self._pinned_search_intent: Optional[str] = None
        # Collected cascade slots — injected as system message to prevent "forgetting"
        self._collected_slots: Dict[str, str] = {}

        # Build OpenAI-formatted tools from function_schemas.json
        self.openai_tools = self._build_openai_tools()

        logger.info(
            "🤖 OpenAIHandler INIT  model=%s  tools=%d",
            self.model, len(self.openai_tools)
        )

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
            messages.append({
                "role": "system",
                "content": (
                    "[СОБРАННЫЕ ПАРАМЕТРЫ КЛИЕНТА — НЕ переспрашивай]\n"
                    + "\n".join(slot_lines)
                    + "\nЕсли клиент НЕ меняет параметр — используй сохранённое значение."
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
             r'индия|китай|япони|южная корея|мексик|бразили)\w*', None),
        ],
        "Город вылета": [
            (r'\b(?:москв|питер|спб|санкт.?петербург|екатеринбург|екб|казан[ьи]|'
             r'новосибирск|нск|краснодар|красноярск|ростов|уф[аеы]|пермь?|'
             r'челябинск|самар[аеу]|нижн\w+ новгород|сочи)\w*', None),
            (r'без\s*перел[её]т', "без перелёта"),
        ],
        "Даты": [
            (r'(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)', None),
            (r'(\d{1,2})\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|'
             r'сентября|октября|ноября|декабря)', None),
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
    }

    def _update_collected_slots(self, user_message: str):
        """Extract and pin cascade parameters from user messages."""
        text = user_message.lower().strip()
        for slot_name, patterns in self._SLOT_PATTERNS.items():
            for pattern, fixed_value in patterns:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    value = fixed_value or m.group(0)
                    self._collected_slots[slot_name] = value
                    break

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

        if self._collected_slots:
            logger.debug("📌 SLOTS: %s", self._collected_slots)

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

        while iteration < max_iterations:
            iteration += 1
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
                if usage:
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
                        "Сервис временно перегружен. "
                        "Подождите несколько секунд и повторите."
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
                        "Извините, диалог стал слишком длинным. "
                        "Пожалуйста, начните новый чат."
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
                    "Произошла временная ошибка. "
                    "Попробуйте ещё раз или начните новый чат."
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
                self.full_history.append(assistant_msg)

                # Log
                func_names = [tc.function.name for tc in message.tool_calls]
                logger.info(
                    "🔧 TOOL CALLS: %s", ", ".join(func_names)
                )

                # Оптимизация: параллельное выполнение tool calls
                _LARGE_FUNCS = {
                    'get_search_results', 'get_hotel_info', 'get_hot_tours'
                }

                def _truncate_tool_output(func_name, output):
                    limit = 2000 if func_name in _LARGE_FUNCS else 1000
                    if len(output) > limit:
                        return output[:limit] + "…"
                    return output

                if len(message.tool_calls) == 1:
                    tc = message.tool_calls[0]
                    arguments = tc.function.arguments or "{}"
                    result = await self._execute_function(
                        tc.function.name, arguments, tc.id
                    )
                    self.full_history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _truncate_tool_output(
                            tc.function.name, result["output"]
                        )
                    })
                else:
                    async def _exec_tool_call(tool_call):
                        args = tool_call.function.arguments or "{}"
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
                        self.full_history.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": _truncate_tool_output(
                                tc_name, result["output"]
                            )
                        })

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
                        "Извините, произошла ошибка. "
                        "Попробуйте переформулировать запрос."
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
                        "Извините, не удалось обработать запрос. "
                        "Попробуйте переформулировать."
                    )
                self.full_history.append({
                    "role": "user",
                    "content": (
                        "Продолжи обработку моего запроса "
                        "на основе полученных данных."
                    )
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

            # Sentence-level dedup (catches intra-paragraph question repeats)
            final_text = _dedup_sentences(final_text)

            # Strip orphaned dialogue-continuation fragments after last '?'
            final_text = _strip_trailing_fragment(final_text)

            # Strip leaked function names (e.g. "get_tour_details")
            final_text = _RE_FUNC_NAMES.sub('', final_text)
            final_text = re.sub(r'\s{2,}', ' ', final_text).strip()

            # Save to history
            self.full_history.append({
                "role": "assistant", "content": final_text
            })

            total_ms = int((time.perf_counter() - chat_start) * 1000)
            logger.info(
                "🤖 ASSISTANT << %d chars  %d iterations  %dms total  \"%s\"",
                len(final_text), iteration, total_ms,
                final_text[:200] + ("…" if len(final_text) > 200 else "")
            )
            return final_text

        logger.error("🤖 MAX ITERATIONS REACHED (%d)", max_iterations)
        return (
            "Извините, запрос оказался слишком сложным. "
            "Попробуйте ещё раз или уточните параметры."
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
        self._last_departure_city = "Москва"
        self._last_requestid = None
        self._tourid_map = {}
        self._tour_details_cache = {}
        self._last_search_params = {}
        self._user_stated_budget = None
        self._empty_iterations = 0
        self.previous_response_id = None
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
