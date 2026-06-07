"""Unit tests for :mod:`max_subscription_watchdog`.

Network and DB access is fully mocked so the suite runs offline and in
sub-second time. Coverage focuses on:

* URL normalisation (the slash-tolerance that keeps us from re-subscribing
  a perfectly-fine ``…/webhook/`` vs ``…/webhook`` mismatch).
* Decision logic of :func:`run_subscription_watchdog_once` — heal vs.
  noop, error counting, missing webhook URL guard.

We intentionally avoid testing the live HTTP code paths; those are
exercised in production smoke-tests.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import max_subscription_watchdog as watchdog  # noqa: E402


class NormaliseUrlTests(unittest.TestCase):
    def test_strips_whitespace_and_trailing_slash(self):
        self.assertEqual(watchdog._normalise_url("  https://x.example/path/  "), "https://x.example/path")

    def test_empty(self):
        self.assertEqual(watchdog._normalise_url(""), "")
        self.assertEqual(watchdog._normalise_url(None), "")  # type: ignore[arg-type]


class WebhookPresentTests(unittest.TestCase):
    def test_finds_matching_url_slash_tolerant(self):
        subs = [{"url": "https://max.navilet.ru/max/webhook/", "time": 1}]
        self.assertTrue(watchdog._is_our_webhook_present(subs, "https://max.navilet.ru/max/webhook"))

    def test_returns_false_on_empty_list(self):
        self.assertFalse(watchdog._is_our_webhook_present([], "https://max.navilet.ru/max/webhook"))

    def test_returns_false_on_non_list(self):
        self.assertFalse(watchdog._is_our_webhook_present(None, "https://max.navilet.ru/max/webhook"))

    def test_returns_false_when_no_target(self):
        self.assertFalse(watchdog._is_our_webhook_present(
            [{"url": "https://other"}], "",
        ))


class PerTenantUrlTests(unittest.TestCase):
    def test_appends_bot_query_param(self):
        self.assertEqual(
            watchdog._per_tenant_url("https://max.navilet.ru/max/webhook", "mgp-tour"),
            "https://max.navilet.ru/max/webhook?bot=mgp-tour",
        )

    def test_strips_trailing_slash(self):
        self.assertEqual(
            watchdog._per_tenant_url("https://max.navilet.ru/max/webhook/", "mgp-belgorod"),
            "https://max.navilet.ru/max/webhook?bot=mgp-belgorod",
        )

    def test_returns_empty_when_base_missing(self):
        self.assertEqual(watchdog._per_tenant_url("", "mgp-foo"), "")


class StaleSubscriptionTests(unittest.TestCase):
    def test_returns_only_non_target_urls(self):
        subs = [
            {"url": "https://hook.example/max/webhook"},  # stale
            {"url": "https://hook.example/max/webhook?bot=mgp-foo"},  # canonical
            {"url": "https://hook.example/old-endpoint"},  # stale
        ]
        stale = watchdog._stale_subscription_urls(
            subs, "https://hook.example/max/webhook?bot=mgp-foo",
        )
        self.assertEqual(set(stale), {
            "https://hook.example/max/webhook",
            "https://hook.example/old-endpoint",
        })

    def test_empty_when_only_canonical(self):
        subs = [{"url": "https://hook.example/max/webhook?bot=mgp-foo"}]
        stale = watchdog._stale_subscription_urls(
            subs, "https://hook.example/max/webhook?bot=mgp-foo",
        )
        self.assertEqual(stale, [])


class RunWatchdogTests(unittest.TestCase):
    def setUp(self):
        self._env_patch = mock.patch.dict(
            os.environ,
            {
                "MAX_WEBHOOK_PUBLIC_URL": "https://hook.example/max/webhook",
                "MAX_API_BASE_URL": "https://botapi.example",
            },
            clear=False,
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_skipped_without_webhook_url(self):
        with mock.patch.dict(os.environ, {"MAX_WEBHOOK_PUBLIC_URL": ""}):
            result = watchdog.run_subscription_watchdog_once()
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "no_webhook_url")

    def _patch_bindings(self, bindings):
        return mock.patch.object(watchdog, "_collect_enabled_bindings", return_value=bindings)

    def _make_client_ctx(self, get_response, post_response=None, delete_response=None):
        """Build a ``httpx.Client`` context manager mock that returns the
        given canned GET / POST / DELETE httpx.Response objects."""
        client = mock.MagicMock()
        client.get.return_value = get_response
        if post_response is not None:
            client.post.return_value = post_response
        if delete_response is None:
            ok_delete = mock.MagicMock()
            ok_delete.status_code = 200
            ok_delete.text = '{"success":true}'
            client.delete.return_value = ok_delete
        else:
            client.delete.return_value = delete_response
        ctx = mock.MagicMock()
        ctx.__enter__.return_value = client
        ctx.__exit__.return_value = False
        return ctx, client

    def _ok_get(self, subscriptions):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"subscriptions": subscriptions}
        resp.text = ""
        return resp

    def _ok_post(self):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.text = '{"success":true}'
        return resp

    def test_healthy_when_per_tenant_webhook_already_present(self):
        bindings = [{
            "assistant_id": "00000000-0000-0000-0000-000000000001",
            "slug": "mgp-foo",
            "bot_token": "TOK_FOO",
            "webhook_secret": "SECRET_FOO",
        }]
        ctx, client = self._make_client_ctx(
            self._ok_get([{"url": "https://hook.example/max/webhook?bot=mgp-foo"}])
        )
        with self._patch_bindings(bindings), \
             mock.patch.object(watchdog.httpx, "Client", return_value=ctx):
            result = watchdog.run_subscription_watchdog_once()
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(result["resubscribed"], 0)
        self.assertEqual(result["errors"], 0)
        client.post.assert_not_called()
        client.delete.assert_not_called()

    def test_resubscribes_with_per_tenant_url_when_missing(self):
        bindings = [{
            "assistant_id": "00000000-0000-0000-0000-000000000002",
            "slug": "mgp-bar",
            "bot_token": "TOK_BAR",
            "webhook_secret": "SECRET_BAR",
        }]
        ctx, client = self._make_client_ctx(
            self._ok_get([]),  # empty list — subscription dropped
            self._ok_post(),
        )
        with self._patch_bindings(bindings), \
             mock.patch.object(watchdog.httpx, "Client", return_value=ctx), \
             mock.patch.object(watchdog, "_stamp_subscribed_at") as stamp:
            result = watchdog.run_subscription_watchdog_once()
        self.assertEqual(result["resubscribed"], 1)
        self.assertEqual(result["errors"], 0)
        client.post.assert_called_once()
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://botapi.example/subscriptions")
        # Critical: per-tenant query param so MAX does not silently evict
        # other bots subscribed on the same base URL.
        self.assertEqual(kwargs["json"]["url"], "https://hook.example/max/webhook?bot=mgp-bar")
        self.assertEqual(kwargs["json"]["secret"], "SECRET_BAR")
        stamp.assert_called_once_with("00000000-0000-0000-0000-000000000002")

    def test_deletes_stale_subscriptions(self):
        bindings = [{
            "assistant_id": "00000000-0000-0000-0000-000000000003",
            "slug": "mgp-foo",
            "bot_token": "TOK_FOO",
            "webhook_secret": "SECRET_FOO",
        }]
        # Bot already has the correct per-tenant URL AND a stale legacy URL
        # (the bare ``/max/webhook`` without ``?bot=`` from the pre-fix era).
        # Watchdog should delete the stale one and not re-subscribe.
        subs = [
            {"url": "https://hook.example/max/webhook"},
            {"url": "https://hook.example/max/webhook?bot=mgp-foo"},
        ]
        ctx, client = self._make_client_ctx(self._ok_get(subs))
        with self._patch_bindings(bindings), \
             mock.patch.object(watchdog.httpx, "Client", return_value=ctx):
            result = watchdog.run_subscription_watchdog_once()
        self.assertEqual(result["healthy"], 1)
        self.assertEqual(result["resubscribed"], 0)
        client.post.assert_not_called()
        # Exactly one DELETE for the stale URL.
        client.delete.assert_called_once()
        _, kwargs = client.delete.call_args
        self.assertEqual(kwargs["params"]["url"], "https://hook.example/max/webhook")

    def test_counts_post_error(self):
        bindings = [{
            "assistant_id": "x",
            "slug": "mgp-baz",
            "bot_token": "T",
            "webhook_secret": "S",
        }]
        bad_post = mock.MagicMock()
        bad_post.status_code = 500
        bad_post.text = "boom"
        ctx, _ = self._make_client_ctx(self._ok_get([]), bad_post)
        with self._patch_bindings(bindings), \
             mock.patch.object(watchdog.httpx, "Client", return_value=ctx), \
             mock.patch.object(watchdog, "_stamp_subscribed_at"):
            result = watchdog.run_subscription_watchdog_once()
        self.assertEqual(result["resubscribed"], 0)
        self.assertEqual(result["errors"], 1)


if __name__ == "__main__":
    unittest.main()
