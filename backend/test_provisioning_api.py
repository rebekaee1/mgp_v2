import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import provisioning_api as prov
except ImportError:
    from backend import provisioning_api as prov

_apply_provisioning = prov._apply_provisioning
_validate_runtime_llm_access = prov._validate_runtime_llm_access
_should_block_provisioning_on_llm_validation = prov._should_block_provisioning_on_llm_validation
_llm_http_validation_error = prov._llm_http_validation_error


class ProvisioningValidationTestCase(unittest.TestCase):
    def test_openai_validation_rejects_invalid_credentials(self):
        with patch.object(prov.httpx, "Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.post.return_value = SimpleNamespace(
                status_code=401,
                text='{"error":{"message":"User not found.","code":401}}',
            )

            error = _validate_runtime_llm_access(
                llm_provider="openai",
                api_key="sk-invalid",
                model="openai/gpt-5-mini",
            )

        self.assertIsNotNone(error)
        self.assertEqual(error["code"], "llm_credentials_invalid")
        self.assertIn("401", error["message"])
        self.assertFalse(error["retryable"])
        self.assertTrue(_should_block_provisioning_on_llm_validation(error))

    def test_openai_validation_accepts_working_credentials(self):
        with patch.object(prov.httpx, "Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.post.return_value = SimpleNamespace(status_code=200, text="ok")

            error = _validate_runtime_llm_access(
                llm_provider="openai",
                api_key="sk-valid",
                model="openai/gpt-5-mini",
            )

        self.assertIsNone(error)

    def test_openai_validation_marks_provider_502_as_retryable_unavailable(self):
        with patch.object(prov.httpx, "Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.post.return_value = SimpleNamespace(
                status_code=502,
                text='{"error":{"message":"Provider returned error","code":502}}',
            )

            error = _validate_runtime_llm_access(
                llm_provider="openai",
                api_key="sk-valid",
                model="openai/gpt-5-mini",
            )

        self.assertIsNotNone(error)
        self.assertEqual(error["code"], "llm_validation_unavailable")
        self.assertTrue(error["retryable"])
        self.assertFalse(_should_block_provisioning_on_llm_validation(error))

    def test_yandex_validation_marks_502_as_retryable_unavailable(self):
        with patch.object(prov.settings, "yandex_folder_id", "b1gtestfolder"):
            with patch.object(prov.httpx, "Client") as client_cls:
                client = client_cls.return_value.__enter__.return_value
                client.post.return_value = SimpleNamespace(
                    status_code=502,
                    text="bad gateway",
                )

                error = _validate_runtime_llm_access(
                    llm_provider="yandex",
                    api_key="api-key",
                    model="yandexgpt",
                )

        self.assertIsNotNone(error)
        self.assertEqual(error["code"], "llm_validation_unavailable")
        self.assertTrue(error["retryable"])
        self.assertFalse(_should_block_provisioning_on_llm_validation(error))

    def test_llm_http_helper_matches_worker_retry_policy(self):
        """Same classification _apply_provisioning uses via _should_block_provisioning_on_llm_validation."""
        transient = _llm_http_validation_error("probe", 502, "")
        self.assertEqual(transient["code"], "llm_validation_unavailable")
        self.assertFalse(_should_block_provisioning_on_llm_validation(transient))

        permanent = _llm_http_validation_error("probe", 401, "")
        self.assertEqual(permanent["code"], "llm_credentials_invalid")
        self.assertTrue(_should_block_provisioning_on_llm_validation(permanent))

    def test_non_retryable_validation_error_blocks_provisioning(self):
        error = {
            "code": "llm_credentials_invalid",
            "message": "401 unauthorized",
            "retryable": False,
        }
        self.assertTrue(_should_block_provisioning_on_llm_validation(error))

    def test_apply_provisioning_continues_on_retryable_llm_validation(self):
        """Retryable LLM validation (502 и т.п.) не переводит запрос в failed — доходим до runtime_ready."""
        req_id = "test-retryable-llm-prov"
        assistant_uuid = str(uuid.uuid4())
        payload = {
            "tenant": {"company_name": "Co", "company_slug": f"slug-{assistant_uuid[:8]}"},
            "admin_user": {"email": f"u{assistant_uuid[:8]}@example.com", "name": "Admin"},
            "assistant": {
                "assistant_id": assistant_uuid,
                "name": "Bot",
                "llm_provider": "openai",
            },
            "runtime": {
                "service_auth": {
                    "secret": "s",
                    "header_name": "X-MGP-Service-Token",
                    "mode": "shared_secret",
                    "scope": "runtime",
                },
            },
        }
        req = SimpleNamespace(
            provisioning_request_id=req_id,
            idempotency_key="ik",
            control_plane_request_id="cp",
            callback_url=None,
            callback_token=None,
            status="accepted",
            company_id=None,
            assistant_id=None,
            request_payload=payload,
            latest_result=None,
            error_code=None,
            error_message=None,
            error_retryable=None,
            callback_delivery_status=None,
            callback_attempts=0,
            callback_last_status_code=None,
            callback_last_error=None,
            callback_last_attempt_at=None,
        )
        mock_db = MagicMock()
        mock_db.get.side_effect = lambda model, pk: req if pk == req_id else None
        mock_db.query.return_value.filter.return_value.first.return_value = None

        def _company(**kwargs):
            obj = SimpleNamespace(**kwargs)
            obj.id = uuid.uuid4()
            return obj

        @contextmanager
        def _fake_get_db():
            yield mock_db

        retryable_err = _llm_http_validation_error(
            "OpenAI/OpenRouter chat validation failed", 502, ""
        )

        with patch.object(prov, "is_db_available", return_value=True), patch.object(
            prov, "get_db", _fake_get_db
        ), patch.object(prov, "_start_callback"), patch.object(
            prov, "_validate_runtime_llm_access", return_value=retryable_err
        ), patch.object(prov, "hash_password", return_value="h"), patch.object(
            prov, "Company", side_effect=_company
        ), patch.object(prov, "User", side_effect=SimpleNamespace), patch.object(
            prov, "Assistant", side_effect=SimpleNamespace
        ):
            _apply_provisioning(req_id)

        self.assertEqual(req.status, "runtime_ready")
        self.assertIsNone(req.error_code)
        self.assertIsNotNone(req.company_id)
        self.assertIsNotNone(req.assistant_id)


if __name__ == "__main__":
    unittest.main()
