import unittest
from types import SimpleNamespace

try:
    from runtime_message_filters import (
        filter_runtime_message_rows,
        filter_runtime_snapshot_entries,
        is_internal_runtime_user_message,
    )
except ImportError:
    from backend.runtime_message_filters import (
        filter_runtime_message_rows,
        filter_runtime_snapshot_entries,
        is_internal_runtime_user_message,
    )


class RuntimeMessageFiltersTestCase(unittest.TestCase):
    def test_detects_internal_runtime_user_message(self):
        self.assertTrue(is_internal_runtime_user_message("user", "СИСТЕМНАЯ ОШИБКА: test"))
        self.assertTrue(is_internal_runtime_user_message("user", "Пожалуйста, продолжи помогать"))
        self.assertFalse(is_internal_runtime_user_message("assistant", "СИСТЕМНАЯ ОШИБКА: test"))
        self.assertFalse(is_internal_runtime_user_message("user", "обычный текст"))

    def test_filters_internal_user_and_preceding_assistant_from_snapshot(self):
        entries = [
            {"role": "user", "content": "реальный вопрос"},
            {"role": "assistant", "content": "ошибочный промежуточный ответ"},
            {"role": "user", "content": "СИСТЕМНАЯ ОШИБКА: служебная подсказка"},
            {"role": "assistant", "content": "исправленный ответ"},
        ]
        filtered = filter_runtime_snapshot_entries(entries)
        self.assertEqual(
            filtered,
            [
                {"role": "user", "content": "реальный вопрос"},
                {"role": "assistant", "content": "исправленный ответ"},
            ],
        )

    def test_filters_internal_user_and_preceding_assistant_from_rows(self):
        rows = [
            SimpleNamespace(role="user", content="реальный вопрос"),
            SimpleNamespace(role="assistant", content="ошибочный промежуточный ответ"),
            SimpleNamespace(role="user", content="СИСТЕМНАЯ ОШИБКА: служебная подсказка"),
            SimpleNamespace(role="assistant", content="исправленный ответ"),
        ]
        filtered = filter_runtime_message_rows(rows)
        self.assertEqual([row.content for row in filtered], ["реальный вопрос", "исправленный ответ"])


if __name__ == "__main__":
    unittest.main()
