"""
«МоиДокументы-Туризм» CRM API client (moidokumenti.ru).

Документация: API.pdf v1.7. Используется офисами на кабинете
``https://[АККАУНТ].moidokumenti.ru`` (например Travel Time —
``trevel-time.moidokumenti.ru``).

Отличия от U-ON (uon_client.py):
  - База URL включает субдомен аккаунта: {account_url}/api/{method}
  - Метод всегда POST, тело — form-data с двумя полями:
        params = JSON-кодированный массив параметров метода
        key    = ключ доступа к API
  - Сервер возвращает JSON-кодированный ответ.

В этом клиенте реализован только сценарий ассистента — добавление лида:
  /api/add-lead  (name, phone, email, source, fields[])

fields — массив вида [{"name": "...", "values": [...]}, ...]. Сюда
раскладывается контекст запроса клиента (направление, даты, состав, бюджет,
выбранный тур), который ассистент уже собирает в строку-note. note приходит в
формате "Метка: значение; Метка: значение; ..." и парсится в структурированные
поля автоматически — менеджер видит аккуратную карточку, а не один комментарий.

DRY_RUN: логирует payload, но не отправляет запрос (как у U-ON).
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("mgp_bot")

_TIMEOUT = 15.0


class MoiDocumentiClient:
    """Async client for «МоиДокументы-Туризм» CRM API."""

    def __init__(self, runtime_config=None):
        # Адрес кабинета: https://trevel-time.moidokumenti.ru (без /api и без
        # завершающего слэша). Принимаем как полный URL, так и голый субдомен.
        raw_url = (
            getattr(runtime_config, "moidoc_account_url", None)
            or os.getenv("MOIDOC_ACCOUNT_URL", "")
        )
        self._account_url: str = _normalize_account_url(raw_url)

        self._api_key: str = (
            getattr(runtime_config, "moidoc_api_key", None)
            or os.getenv("MOIDOC_API_KEY", "")
        )
        self._source: str = (
            getattr(runtime_config, "moidoc_source", None)
            or os.getenv("MOIDOC_SOURCE", "AI-Ассистент")
        )
        self._dry_run: bool = (
            getattr(runtime_config, "moidoc_dry_run", True)
            if runtime_config and hasattr(runtime_config, "moidoc_dry_run")
            else os.getenv("MOIDOC_DRY_RUN", "true").lower() in ("true", "1", "yes")
        )

        if not self._api_key:
            logger.info("MOIDOC CRM: API key not configured — all calls will be skipped")
        if not self._account_url:
            logger.info("MOIDOC CRM: account URL not configured — all calls will be skipped")

        logger.info(
            "MOIDOC CRM INIT  dry_run=%s  source=%s  account=%s  key_set=%s",
            self._dry_run,
            self._source,
            self._account_url or "(unset)",
            bool(self._api_key),
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def create_lead(
        self,
        name: str,
        phone: str,
        email: str = "",
        note: str = "",
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Создать лид в «МоиДокументы-Туризм» (/api/add-lead).

        note — строка "Метка: значение; ..." (как для U-ON). Если ``fields`` не
        переданы явно, note автоматически раскладывается в структурированные
        поля заказа.
        """
        params: Dict[str, Any] = {
            "name": name,
            "phone": phone,
            "source": self._source,
        }
        if email:
            params["email"] = email

        if fields is None:
            fields = _note_to_fields(note)
        if fields:
            params["fields"] = fields

        return await self._post("add-lead", params)

    # ── Internal ─────────────────────────────────────────────────────────

    async def _post(self, method: str, params: Dict) -> Dict[str, Any]:
        if not self._api_key:
            logger.warning("MOIDOC CRM: skipped /%s — no API key", method)
            return {"ok": False, "error": "MOIDOC API key not configured"}
        if not self._account_url:
            logger.warning("MOIDOC CRM: skipped /%s — no account URL", method)
            return {"ok": False, "error": "MOIDOC account URL not configured"}

        url = f"{self._account_url}/api/{method}"
        body = {
            "params": json.dumps(params, ensure_ascii=False),
            "key": self._api_key,
        }

        if self._dry_run:
            logger.info("[MOIDOC DRY_RUN] Would POST %s: %s", url, params)
            return {"ok": True, "dry_run": True, "method": method, "params": params}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, data=body)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    logger.error("MOIDOC CRM /%s: non-JSON response: %s", method, resp.text[:300])
                    return {"ok": False, "error": "non_json_response"}

                # МоиДокументы возвращает {"result": "success"/"error", ...}.
                result = data.get("result") if isinstance(data, dict) else None
                if result is not None and str(result).lower() != "success":
                    logger.error("MOIDOC CRM /%s => result=%s: %s", method, result, data)
                    return {"ok": False, "error": str(result), "data": data}

                logger.info("MOIDOC CRM /%s => %s", method, data)
                return {"ok": True, "data": data}

            logger.error(
                "MOIDOC CRM /%s HTTP %d: %s",
                method, resp.status_code, resp.text[:300],
            )
            return {"ok": False, "error": f"HTTP {resp.status_code}"}

        except httpx.TimeoutException:
            logger.error("MOIDOC CRM /%s timeout after %.0fs", method, _TIMEOUT)
            return {"ok": False, "error": "timeout"}
        except Exception as exc:
            logger.error("MOIDOC CRM /%s exception: %s", method, exc, exc_info=True)
            return {"ok": False, "error": str(exc)}


def _normalize_account_url(raw: str) -> str:
    """Привести адрес кабинета к виду https://account.moidokumenti.ru (без /api,
    без завершающего слэша). Принимает голый субдомен ('trevel-time'), субдомен
    с доменом или полный URL.
    """
    if not raw:
        return ""
    url = str(raw).strip().rstrip("/")
    if not url:
        return ""
    # Голый субдомен → достроить полный хост.
    if "." not in url and "://" not in url:
        url = f"{url}.moidokumenti.ru"
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    # Срезаем хвост /api, если его случайно указали.
    if url.endswith("/api"):
        url = url[: -len("/api")]
    return url.rstrip("/")


def _note_to_fields(note: str) -> List[Dict[str, Any]]:
    """Разложить note "Метка: значение; Метка: значение" в массив fields.

    Каждый сегмент "Метка: значение" → {"name": "Метка", "values": ["значение"]}.
    Сегмент без двоеточия → {"name": "Комментарий", "values": [segment]}.
    Пустой note → пустой список.
    """
    if not note:
        return []
    fields: List[Dict[str, Any]] = []
    for segment in str(note).split("; "):
        segment = segment.strip()
        if not segment:
            continue
        if ": " in segment:
            label, value = segment.split(": ", 1)
            label = label.strip()
            value = value.strip()
            if label and value:
                fields.append({"name": label, "values": [value]})
                continue
        fields.append({"name": "Комментарий", "values": [segment]})
    return fields
