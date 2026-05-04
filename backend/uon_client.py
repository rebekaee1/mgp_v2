"""
U-ON CRM API Client.

POST методы:
  create_lead  — обращение (клиент оставил контакт, тур не выбран)
  create_request — заявка (клиент выбрал конкретный тур)

GET методы (read-only, для feature "Статус заявки"):
  get_user_by_phone — поиск клиента по телефону
  get_requests_by_client — заявки конкретного клиента
  get_leads_by_client — обращения (lead) конкретного клиента

Особенности U-ON API:
  - source — СТРОКА ("AI-Ассистент"), НЕ числовой ID
  - request/create автоматически создаёт клиента из u_name/u_phone
  - r_u_id (ID менеджера) НЕ передаётся — CRM назначит сама
  - IP whitelisting: запросы принимаются ТОЛЬКО с разрешённых IP
  - DRY_RUN: логирует payload, но не отправляет запрос (только для POST)
  - GET запросы НЕ подчиняются DRY_RUN — это read-only безопасные операции;
    при отсутствии API key они возвращают {"ok": False, "error": "no_api_key"}.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("mgp_bot")

_BASE_URL = "https://api.u-on.ru"
_TIMEOUT = 15.0


class UONClient:
    """Async client for U-ON CRM API."""

    def __init__(self, runtime_config=None):
        self._api_key: str = (
            getattr(runtime_config, "uon_api_key", None)
            or os.getenv("UON_API_KEY", "")
        )
        self._source: str = (
            getattr(runtime_config, "uon_source", None)
            or os.getenv("UON_SOURCE", "AI-Ассистент")
        )
        self._dry_run: bool = (
            getattr(runtime_config, "uon_dry_run", True)
            if runtime_config and hasattr(runtime_config, "uon_dry_run")
            else os.getenv("UON_DRY_RUN", "true").lower() in ("true", "1", "yes")
        )

        if not self._api_key:
            logger.info("UON CRM: API key not configured — all calls will be skipped")

        logger.info(
            "UON CRM INIT  dry_run=%s  source=%s  key_set=%s",
            self._dry_run,
            self._source,
            bool(self._api_key),
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def create_lead(
        self,
        name: str,
        phone: str,
        email: str = "",
        note: str = "",
    ) -> Dict[str, Any]:
        """Создать обращение (lead) в U-ON CRM."""
        payload = {
            "u_name": name,
            "u_phone": phone,
            "source": self._source,
        }
        if email:
            payload["u_email"] = email
        if note:
            payload["note"] = note

        return await self._post("lead/create.json", payload)

    async def create_request(
        self,
        name: str,
        phone: str,
        email: str = "",
        note: str = "",
        price: Optional[float] = None,
        date_begin: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Создать заявку (request) в U-ON CRM."""
        payload = {
            "u_name": name,
            "u_phone": phone,
            "source": self._source,
        }
        if email:
            payload["u_email"] = email
        if note:
            payload["note"] = note
        if price is not None:
            payload["r_price"] = price
        if date_begin:
            payload["r_dat_begin"] = date_begin
        if date_end:
            payload["r_dat_end"] = date_end

        return await self._post("request/create.json", payload)

    # ── GET (read-only) ──────────────────────────────────────────────────

    async def get_user_by_phone(self, phone: str) -> Dict[str, Any]:
        """Найти клиента по телефону.

        Возвращает dict в формате:
          {"ok": True, "users": [...]}  # список найденных клиентов (может быть пустым)
          {"ok": False, "error": "..."}  # при ошибке

        Телефон нормализуется: убираются пробелы/скобки/дефисы, +7/8 → 7.
        """
        normalized = _normalize_phone(phone)
        if not normalized:
            return {"ok": False, "error": "invalid_phone"}

        result = await self._get(f"user/phone/{normalized}.json")
        if not result.get("ok"):
            return result

        data = result.get("data") or {}
        users = data.get("users") or []
        if isinstance(users, dict):
            users = [users]
        return {"ok": True, "users": users}

    async def get_requests_by_client(self, client_id: int) -> Dict[str, Any]:
        """Получить список заявок (request) конкретного клиента.

        Возвращает:
          {"ok": True, "requests": [...]}
          {"ok": False, "error": "..."}
        """
        if not client_id:
            return {"ok": False, "error": "invalid_client_id"}

        result = await self._get(f"request-by-client/{client_id}.json")
        if not result.get("ok"):
            return result

        data = result.get("data") or {}
        requests = data.get("requests") or []
        if isinstance(requests, dict):
            requests = [requests]
        return {"ok": True, "requests": requests}

    async def get_leads_by_client(self, client_id: int) -> Dict[str, Any]:
        """Получить список обращений (lead) конкретного клиента.

        Возвращает:
          {"ok": True, "leads": [...]}
          {"ok": False, "error": "..."}
        """
        if not client_id:
            return {"ok": False, "error": "invalid_client_id"}

        result = await self._get(f"lead-by-client/{client_id}.json")
        if not result.get("ok"):
            return result

        data = result.get("data") or {}
        leads = data.get("leads") or []
        if isinstance(leads, dict):
            leads = [leads]
        return {"ok": True, "leads": leads}

    # ── Internal ─────────────────────────────────────────────────────────

    async def _post(self, endpoint: str, payload: Dict) -> Dict[str, Any]:
        if not self._api_key:
            logger.warning("UON CRM: skipped %s — no API key", endpoint)
            return {"ok": False, "error": "UON API key not configured"}

        url = f"{_BASE_URL}/{self._api_key}/{endpoint}"

        if self._dry_run:
            logger.info("[UON DRY_RUN] Would POST /%s: %s", endpoint, payload)
            return {"ok": True, "dry_run": True, "endpoint": endpoint, "payload": payload}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, data=payload)

            if resp.status_code == 200:
                data = resp.json()
                logger.info("UON CRM /%s => %s", endpoint, data)
                return {"ok": True, "data": data}

            logger.error(
                "UON CRM /%s HTTP %d: %s",
                endpoint, resp.status_code, resp.text[:300],
            )
            return {"ok": False, "error": f"HTTP {resp.status_code}"}

        except httpx.TimeoutException:
            logger.error("UON CRM /%s timeout after %.0fs", endpoint, _TIMEOUT)
            return {"ok": False, "error": "timeout"}
        except Exception as exc:
            logger.error("UON CRM /%s exception: %s", endpoint, exc, exc_info=True)
            return {"ok": False, "error": str(exc)}

    async def _get(self, endpoint: str) -> Dict[str, Any]:
        """Generic GET helper. Read-only, не подчиняется DRY_RUN."""
        if not self._api_key:
            logger.warning("UON CRM GET: skipped %s — no API key", endpoint)
            return {"ok": False, "error": "no_api_key"}

        url = f"{_BASE_URL}/{self._api_key}/{endpoint}"

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    logger.error("UON CRM GET /%s: non-JSON response", endpoint)
                    return {"ok": False, "error": "non_json_response"}
                logger.info("UON CRM GET /%s => %d keys", endpoint, len(data) if isinstance(data, dict) else 0)
                return {"ok": True, "data": data}

            if resp.status_code == 404:
                logger.info("UON CRM GET /%s => 404 (not found)", endpoint)
                return {"ok": False, "error": "not_found", "status_code": 404}

            logger.error(
                "UON CRM GET /%s HTTP %d: %s",
                endpoint, resp.status_code, resp.text[:300],
            )
            return {"ok": False, "error": f"HTTP {resp.status_code}", "status_code": resp.status_code}

        except httpx.TimeoutException:
            logger.error("UON CRM GET /%s timeout after %.0fs", endpoint, _TIMEOUT)
            return {"ok": False, "error": "timeout"}
        except Exception as exc:
            logger.error("UON CRM GET /%s exception: %s", endpoint, exc, exc_info=True)
            return {"ok": False, "error": str(exc)}


def _normalize_phone(phone: str) -> str:
    """Привести телефон к формату 7XXXXXXXXXX (только цифры).

    Поддерживает форматы: +7 999 123-45-67, 8 (999) 123-45-67, 79991234567.
    Возвращает пустую строку если телефон невалиден (<10 цифр).
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 11 and digits.startswith("7"):
        pass
    elif len(digits) > 11:
        digits = digits[-11:]
        if not digits.startswith("7"):
            digits = "7" + digits[-10:]
    else:
        return ""
    return digits
