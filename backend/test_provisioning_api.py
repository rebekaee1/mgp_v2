import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from provisioning_api import (
        _should_block_provisioning_on_llm_validation,
        _validate_runtime_llm_access,
    )
except ImportError:
    from backend.provisioning_api import (
        _should_block_provisioning_on_llm_validation,
        _validate_runtime_llm_access,
    )


class ProvisioningValidationTestCase(unittest.TestCase):
    def test_openai_validation_rejects_invalid_credentials(self):
        with patch("provisioning_api.httpx.Client") as client_cls:
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

    def test_openai_validation_accepts_working_credentials(self):
        with patch("provisioning_api.httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.post.return_value = SimpleNamespace(status_code=200, text="ok")

            error = _validate_runtime_llm_access(
                llm_provider="openai",
                api_key="sk-valid",
                model="openai/gpt-5-mini",
            )

        self.assertIsNone(error)

    def test_openai_validation_marks_provider_502_as_retryable_unavailable(self):
        with patch("provisioning_api.httpx.Client") as client_cls:
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

    def test_non_retryable_validation_error_blocks_provisioning(self):
        error = {
            "code": "llm_credentials_invalid",
            "message": "401 unauthorized",
            "retryable": False,
        }
        self.assertTrue(_should_block_provisioning_on_llm_validation(error))


if __name__ == "__main__":
    unittest.main()
