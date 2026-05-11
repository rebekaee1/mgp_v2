"""Tests for MaxApiClient.send_message + upload_image_bytes (Stage 2).

Uses respx to intercept httpx calls. respx auto-installs as an asyncio fixture
``respx_mock`` (mode=BASE_URL by default for httpx clients with base_url).
"""

import json

import httpx
import pytest
import respx

from app.max_api import MaxApiClient, MaxApiError


@pytest.mark.asyncio
async def test_send_message_with_text_only_uses_markdown_format():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://botapi.test/messages").respond(
            200, json={"message": {"mid": "mid.X"}}
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            result = await c.send_message(chat_id=42, text="hi")
        assert result == {"message": {"mid": "mid.X"}}
        body = json.loads(route.calls.last.request.content)
        assert body["text"] == "hi"
        assert body["format"] == "markdown"
        assert "attachments" not in body
        assert route.calls.last.request.url.params["chat_id"] == "42"


@pytest.mark.asyncio
async def test_send_message_includes_attachments_and_keeps_format():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://botapi.test/messages").respond(
            200, json={"ok": True}
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            await c.send_message(
                user_id=7,
                text="caption",
                attachments=[
                    {"type": "image", "payload": {"token": "TOK"}},
                    {"type": "inline_keyboard", "payload": {"buttons": [[{"type": "link", "text": "a", "url": "https://x"}]]}},
                ],
            )
        body = json.loads(route.calls.last.request.content)
        assert len(body["attachments"]) == 2
        assert body["attachments"][0]["type"] == "image"
        assert route.calls.last.request.url.params["user_id"] == "7"


@pytest.mark.asyncio
async def test_send_message_retries_on_attachment_not_ready():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://botapi.test/messages")
        route.side_effect = [
            httpx.Response(400, json={"code": "attachment.not.ready", "message": "wait"}),
            httpx.Response(400, json={"code": "attachment.not.ready", "message": "wait"}),
            httpx.Response(200, json={"message": {"mid": "ok"}}),
        ]
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            result = await c.send_message(
                chat_id=1, text="x",
                attachments=[{"type": "image", "payload": {"token": "T"}}],
            )
        assert result == {"message": {"mid": "ok"}}
        assert len(route.calls) == 3


@pytest.mark.asyncio
async def test_send_message_does_not_retry_other_errors():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://botapi.test/messages").respond(
            400, json={"code": "validation.failed", "message": "bad"}
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            with pytest.raises(MaxApiError) as ei:
                await c.send_message(chat_id=1, text="x")
        assert ei.value.code == "validation.failed"
        assert len(route.calls) == 1


@pytest.mark.asyncio
async def test_send_message_eventually_raises_after_retries():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://botapi.test/messages").respond(
            400, json={"code": "attachment.not.ready", "message": "wait"}
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            with pytest.raises(MaxApiError) as ei:
                await c.send_message(
                    chat_id=1, text="x",
                    attachments=[{"type": "image", "payload": {"token": "T"}}],
                )
        assert ei.value.code == "attachment.not.ready"
        assert len(route.calls) == 3


@pytest.mark.asyncio
async def test_send_text_still_works_as_thin_wrapper():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://botapi.test/messages").respond(
            200, json={"ok": True}
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            await c.send_text(chat_id=99, text="hello", markdown=True)
        body = json.loads(route.calls.last.request.content)
        assert body["text"] == "hello"
        assert body["format"] == "markdown"


@pytest.mark.asyncio
async def test_upload_image_bytes_two_step_returns_token():
    """Real shape captured from prod on 2026-05-11:
    {"photos": {"<id>": {"token": "..."}}}"""
    upload_url = "https://upload.cdn.max.test/upload?sig=abc&expires=1"
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://botapi.test/uploads").respond(
            200, json={"url": upload_url}
        )
        cdn_route = mock.post(upload_url).respond(
            200,
            json={"photos": {"abc123==": {"token": "U1xMZmMqp"}}},
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            token = await c.upload_image_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
        assert token == "U1xMZmMqp"
        cdn_call = cdn_route.calls.last
        assert "authorization" not in {k.lower() for k in cdn_call.request.headers.keys()} or \
               cdn_call.request.headers.get("authorization") != "BOT_TOKEN"


@pytest.mark.asyncio
async def test_upload_image_bytes_legacy_inline_token_shape():
    """Backward compatibility: if MAX ever inlines the token at top level
    (the shape we originally coded for), still works."""
    upload_url = "https://upload.cdn.max.test/upload?sig=abc"
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://botapi.test/uploads").respond(
            200, json={"url": upload_url}
        )
        mock.post(upload_url).respond(200, json={"token": "LEGACY_TOK"})
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            token = await c.upload_image_bytes(b"jpeg")
        assert token == "LEGACY_TOK"


@pytest.mark.asyncio
async def test_upload_image_bytes_raises_on_cdn_error_envelope():
    """CDN returns HTTP 200 but with {"error_code", "error_data"} on bad input."""
    upload_url = "https://upload.cdn.max.test/upload?sig=abc"
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://botapi.test/uploads").respond(
            200, json={"url": upload_url}
        )
        mock.post(upload_url).respond(
            200,
            json={"error_code": "503", "error_data": "IMAGE_INVALID_FORMAT"},
        )
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            with pytest.raises(MaxApiError) as ei:
                await c.upload_image_bytes(b"jpeg")
        assert ei.value.code == "upload.cdn_503"
        assert "IMAGE_INVALID_FORMAT" in ei.value.message


@pytest.mark.asyncio
async def test_upload_image_bytes_raises_when_photos_empty():
    """If MAX returns photos:{} or photos:null we must surface no_token."""
    upload_url = "https://upload.cdn.max.test/upload?sig=abc"
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://botapi.test/uploads").respond(
            200, json={"url": upload_url}
        )
        mock.post(upload_url).respond(200, json={"photos": {}})
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            with pytest.raises(MaxApiError) as ei:
                await c.upload_image_bytes(b"jpeg")
        assert ei.value.code == "upload.no_token"


@pytest.mark.asyncio
async def test_upload_image_bytes_rejects_empty():
    async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
        with pytest.raises(ValueError):
            await c.upload_image_bytes(b"")


@pytest.mark.asyncio
async def test_upload_image_bytes_raises_on_cdn_error():
    upload_url = "https://upload.cdn.max.test/upload?sig=abc"
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://botapi.test/uploads").respond(
            200, json={"url": upload_url}
        )
        mock.post(upload_url).respond(503, json={"code": "upstream", "message": "busy"})
        async with MaxApiClient("https://botapi.test", "BOT_TOKEN") as c:
            with pytest.raises(MaxApiError) as ei:
                await c.upload_image_bytes(b"jpeg-bytes")
        assert ei.value.status_code == 503
