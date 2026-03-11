import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from database import init_db, get_db
from dialog_sender import _payload_size_bytes, enqueue_conversation_snapshot, run_dialog_sender_once
from models import ApiCall, Assistant, Company, Conversation, Message, RuntimeEventOutbox, TourSearch


class DialogSenderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._db_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        cls._db_file.close()
        init_db(f"sqlite:///{cls._db_file.name}")

    def setUp(self):
        with get_db() as db:
            db.query(RuntimeEventOutbox).delete()
            db.query(ApiCall).delete()
            db.query(TourSearch).delete()
            db.query(Message).delete()
            db.query(Conversation).delete()
            db.query(Assistant).delete()
            db.query(Company).delete()

            company = Company(name="Test Company", slug=f"test-{uuid.uuid4().hex[:8]}")
            db.add(company)
            db.flush()

            assistant = Assistant(
                company_id=company.id,
                name="Test Assistant",
                llm_provider="openai",
                llm_model="gpt-5-mini",
                runtime_metadata={
                    "service_auth": {
                        "mode": "shared_secret",
                        "header_name": "X-MGP-Service-Token",
                        "secret": "svc-secret",
                        "scope": "runtime",
                    },
                    "reporting": {
                        "mode": "batch_snapshot",
                        "contract_version": "2026-03-09",
                        "endpoint_url": "https://lk.example/api/control-plane/runtime/events",
                        "accepted_event_types": ["conversation_snapshot"],
                        "auth": {
                            "type": "shared_secret",
                            "header_name": "X-MGP-Service-Token",
                            "secret": "report-secret",
                        },
                    },
                },
            )
            db.add(assistant)
            db.flush()
            self.assistant_id = assistant.id

            conversation = Conversation(
                assistant_id=assistant.id,
                session_id=f"sess-{uuid.uuid4().hex[:12]}",
                llm_provider="openai",
                model="gpt-5-mini",
                ip_address="127.0.0.1",
                user_agent="pytest",
                message_count=2,
                search_count=1,
                tour_cards_shown=1,
                has_booking_intent=True,
                status="active",
            )
            db.add(conversation)
            db.flush()
            self.conversation_id = conversation.id

            db.add(Message(
                conversation_id=conversation.id,
                role="user",
                content="Хочу тур в Турцию",
            ))
            db.add(Message(
                conversation_id=conversation.id,
                role="assistant",
                content="Вот варианты",
                tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "search_tours", "arguments": "{\"country\":4}"}}],
                tour_cards=[{
                    "hotel_name": "Hotel Test",
                    "image_url": "https://example.com/hotel.jpg",
                    "room_type": "DBL",
                    "date_from": "2026-04-01",
                    "date_to": "2026-04-10",
                    "price": 123456,
                    "operator": "Pegas",
                }],
                tokens_prompt=11,
                tokens_completion=22,
                latency_ms=1500,
            ))
            db.add(TourSearch(
                conversation_id=conversation.id,
                requestid="11767315205",
                search_type="regular",
                departure=1,
                country=4,
                regions="1,2",
                date_from="01.04.2026",
                date_to="10.04.2026",
                nights_from=7,
                nights_to=9,
                adults=2,
                children=0,
                stars=5,
                meal=7,
                price_from=100000,
                price_to=150000,
                hotels_found=20,
                tours_found=50,
                min_price=110000,
                duration_ms=9000,
            ))
            db.add(ApiCall(
                conversation_id=conversation.id,
                service="tourvisor",
                endpoint="search.php",
                response_code=200,
                response_bytes=2048,
                tokens_used=None,
                latency_ms=900,
            ))

    def test_enqueue_builds_lk_compatible_snapshot(self):
        with get_db() as db:
            enqueue_conversation_snapshot(db, self.conversation_id, self.assistant_id)
            outbox = db.query(RuntimeEventOutbox).one()
            payload = outbox.payload

            self.assertEqual(payload["assistant_id"], str(self.assistant_id))
            self.assertEqual(payload["conversation"]["search_count"], 1)
            self.assertEqual(payload["messages"][1]["id"], 2)
            self.assertEqual(payload["messages"][1]["remote_id"], 2)
            self.assertEqual(payload["messages"][1]["tour_cards"][0]["hotel_image"], "https://example.com/hotel.jpg")
            self.assertEqual(payload["messages"][1]["tour_cards"][0]["room"], "DBL")
            self.assertEqual(payload["messages"][1]["tour_cards"][0]["date"], "2026-04-01")
            self.assertEqual(payload["messages"][1]["tokens_prompt"], 11)
            self.assertEqual(payload["messages"][1]["tokens_completion"], 22)
            self.assertEqual(payload["tour_searches"][0]["id"], 1)
            self.assertEqual(payload["tour_searches"][0]["remote_id"], 1)
            self.assertEqual(payload["tour_searches"][0]["requestid"], "11767315205")
            self.assertEqual(payload["tour_searches"][0]["duration_ms"], 9000)
            self.assertEqual(payload["api_calls"][0]["external_id"], "api:1")

    def test_sender_marks_event_as_sent(self):
        with get_db() as db:
            enqueue_conversation_snapshot(db, self.conversation_id, self.assistant_id)

        with patch("dialog_sender.httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            response = client.post.return_value
            response.status_code = 200

            processed = run_dialog_sender_once(limit=10)
            self.assertEqual(processed, 1)

        with get_db() as db:
            outbox = db.query(RuntimeEventOutbox).one()
            self.assertEqual(outbox.status, "sent")
            self.assertIsNotNone(outbox.sent_at)

    def test_sender_compacts_payload_after_413(self):
        long_tool_output = "X" * 200000
        with get_db() as db:
            db.add(Message(
                conversation_id=self.conversation_id,
                role="tool",
                content=long_tool_output,
                tool_call_id="call-oversized",
            ))
            db.commit()
            enqueue_conversation_snapshot(db, self.conversation_id, self.assistant_id)
            outbox = db.query(RuntimeEventOutbox).one()
            original_size = _payload_size_bytes(dict(outbox.payload))

        with patch("dialog_sender.httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            client.post.side_effect = [
                SimpleNamespace(status_code=413),
                SimpleNamespace(status_code=200),
            ]

            processed = run_dialog_sender_once(limit=10)
            self.assertEqual(processed, 1)

        with get_db() as db:
            outbox = db.query(RuntimeEventOutbox).one()
            compacted_size = _payload_size_bytes(dict(outbox.payload))
            self.assertEqual(outbox.status, "sent")
            self.assertLess(compacted_size, original_size)
            self.assertLess(compacted_size, 64 * 1024)
            tool_messages = [msg for msg in outbox.payload["messages"] if msg.get("role") == "tool"]
            self.assertTrue(tool_messages)
            self.assertTrue(
                "truncated" in (tool_messages[-1]["content"] or "")
                or "omitted" in (tool_messages[-1]["content"] or "")
            )


if __name__ == "__main__":
    unittest.main()
