"""
U-ON CRM API Client.

Два метода:
  create_lead  — обращение (клиент оставил контакт, тур не выбран)
  create_request — заявка (клиент выбрал конкретный тур)

Особенности U-ON API:
  - source — СТРОКА ("AI-Ассистент"), НЕ числовой ID
  - request/create автоматически создаёт клиента из u_name/u_phone
  - r_u_id (ID менеджера) НЕ передаётся — CRM назначит сама
  - IP whitelisting: запросы принимаются ТОЛЬКО с разрешённых IP
  - DRY_RUN: логирует payload, но не отправляет запрос
"""

import logging
import os
from typing import Any, Dict, Optional

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
