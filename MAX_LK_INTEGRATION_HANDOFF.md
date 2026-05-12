# MAX Messenger integration — handoff document for `lk_navylet`

> **Created:** 2026-05-12
> **Source repo:** `rebekaee1/mgp_v2` (this folder)
> **Target repo:** `rebekaee1/lk_navylet` (the LK / control-plane that
> already replicates conversations from MGP runtime)
> **Status:** mgp_v2 fully shipped to prod. LK side needs ~3 small changes.

---

## 0. TL;DR

The MGP runtime now persists **which channel** every conversation came
from (web widget or MAX Messenger) and forwards that attribution to LK via
the existing `conversation_snapshot` payload. The LK side currently
discards those new fields because it predates the contract bump. Three
small additions on the LK side surface the channel in the cabinet:

1. SQL migration: add `channel` + `external_user_id` columns.
2. Receiver: read those two keys from the payload.
3. UI: render a badge ("MAX" vs "Виджет") and (optional) filter.

No breaking changes. The LK can ship these in any order — the snapshot
already arrives, today it is just being thrown away.

---

## 1. What changed in `mgp_v2` (already in prod)

### 1.1 Database

Migration `j0k1l2m3n4o_add_conversation_channel.py` adds two columns to
`public.conversations`:

```sql
ALTER TABLE conversations
    ADD COLUMN channel varchar(16) NOT NULL DEFAULT 'widget',
    ADD COLUMN external_user_id varchar(64) NULL;

CREATE INDEX ix_conversations_channel_started
    ON conversations (channel, started_at);
```

Allowed values for `channel`: **`widget`** (web widget on the client's
site) and **`max`** (MAX Messenger bot). New channels (telegram, whatsapp,
vk) will reuse the same column.

`external_user_id` is the user identifier inside the source channel. For
MAX it's the numeric `user_id` MAX assigns to a chatter, stored as a
string. For widget it is `NULL`.

Both fields are set on the **first insert** of the conversation row and
**never overwritten** afterwards — the source channel is treated as an
immutable property of the session.

### 1.2 Snapshot payload (the data the LK already receives)

`backend/dialog_sender.py:_build_snapshot_payload` now includes two new
keys inside the existing `conversation` block:

```json
{
  "contract_version": "2026-03-09",
  "event_type": "conversation_snapshot",
  "assistant_id": "...",
  "conversation_id": "...",
  "occurred_at": "...",
  "conversation": {
    "id": "...",
    "session_id": "max-213771498-3a7b9c1f",
    "llm_provider": "openai",
    "model": "openai/gpt-5-mini",
    "ip_address": null,
    "user_agent": "curl/8.6",
    "message_count": 4,
    "search_count": 1,
    "tour_cards_shown": 3,
    "has_booking_intent": true,
    "status": "active",
    "started_at": "2026-05-12T...",
    "last_active_at": "2026-05-12T...",
    "channel": "max",                  // <-- NEW
    "external_user_id": "213771498"    // <-- NEW (NULL for widget)
  },
  "messages": [...],
  "tour_searches": [...],
  "api_calls": [...]
}
```

`contract_version` is **not** bumped — LK receivers older than this
change will silently drop the unknown keys (forward-compatible). The bump
is reserved for a future change that breaks consumers.

### 1.3 MAX bridge contract

`services/max_bridge` now sends two extra headers on every
`POST /api/v1/chat` call:

* `X-Channel: max`
* `X-External-User-Id: <MAX user_id>` (string)

The website widget never sets these, so its conversations default to
`channel = 'widget'`.

### 1.4 Multi-tenant routing (no env vars per client)

The bridge no longer reads `MAX_BOT_TOKEN_<SLUG>` /
`MAX_WEBHOOK_SECRET_<SLUG>` from its environment in production. It pulls
the list of active MAX-channel tenants from a new backend endpoint:

```
GET http://backend:8080/api/runtime/channels/max/bindings
→ {
    "available": true,
    "bindings": [
      {
        "slug": "mgp-tour",
        "assistant_id": "593471b7-...",
        "bot_token": "...",
        "webhook_secret": "l_DMup...",
        "bot_username": "mgp_tour_bot",
        "subscribed_at": null
      },
      ...
    ]
  }
```

The bindings come from
`assistants.runtime_metadata.channels.max` in the MGP postgres. The
bridge refreshes the directory every 60s (configurable via
`MAX_TENANT_REFRESH_INTERVAL_SECONDS`); rotating a secret in the DB is
picked up within a minute without a bridge restart. The endpoint is gated
by `_is_internal_request` (same gate as `/api/status`); reachable only
from inside the prod docker network.

Schema of `assistants.runtime_metadata.channels.max`:

```json
{
  "enabled": true,
  "bot_token": "...",                  // mandatory
  "webhook_secret": "...",             // mandatory, matches ^[A-Za-z0-9_-]{5,256}$
  "bot_username": "mgp_tour_bot",      // optional, cosmetic
  "bot_user_id": 123,                  // optional, returned by MAX /me
  "subscribed_at": "2026-05-12T...",   // optional, set by operator after POST /subscriptions
  "validated_at": "2026-05-12T..."     // last successful /me probe
}
```

A row with `enabled: false` is **excluded** from the endpoint (the bridge
will start returning 401 on its webhook within ~60s of the flip).

### 1.5 Operator workflow for onboarding a new MAX bot

```bash
# 1) Client registers a bot via @MasterBot, hands over bot_token.
# 2) Operator on the prod server:
export MAX_BOT_TOKEN_MGP_VYHINO="<from client>"
export MAX_WEBHOOK_SECRET_MGP_VYHINO="<we pick or auto-generated>"
./deploy/provision_clients.sh mgp-vyhino     # runs setup_max_channel
# OR call the CLI directly:
sudo docker exec mgp-backend-1 python /app/backend/cli.py \
    max-channel enable \
    --slug mgp-vyhino \
    --bot-token "..." \
    --webhook-secret "..."
# 3) Operator (manual): register the bridge webhook on MAX side
#    POST https://botapi.max.ru/subscriptions  (one-time per bot)
# 4) Wait ≤ 60s for the bridge to refresh; verify with:
sudo docker exec mgp-backend-1 python /app/backend/cli.py \
    max-channel status --slug mgp-vyhino
```

### 1.6 CRM and email marker (channel in lead body)

For every successful U-ON CRM lead / request the comment now starts with
`[Канал: MAX Messenger]` or `[Канал: Виджет]`. The email-copy that goes
to `online@mgp.ru` (for tenants with `widget_config.lead_email_enabled`)
inherits the same prefix automatically.

---

## 2. What needs to happen on the LK side (3 changes)

### 2.1 LK SQL migration

Run on the LK postgres (the replica that backs the cabinet UI). Mirror
the MGP migration:

```sql
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS channel varchar(16) NOT NULL DEFAULT 'widget',
    ADD COLUMN IF NOT EXISTS external_user_id varchar(64) NULL;

CREATE INDEX IF NOT EXISTS ix_conversations_channel_started
    ON conversations (channel, started_at);
```

`DEFAULT 'widget'` ensures historical rows (everything pre-`2026-05-12`)
get a sensible value. Strictly speaking those historical rows include
**a handful of test MAX conversations** that you said were yours and
disposable; they will land as `widget`. If you want them tagged
correctly, run this once after the migration:

```sql
UPDATE conversations SET channel = 'max'
WHERE session_id LIKE 'max-%' AND channel = 'widget';
```

### 2.2 LK receiver (`/api/control-plane/runtime/events`)

The endpoint already parses `payload['conversation']`. Add two reads:

```python
conv = payload["conversation"]
# ... existing extraction ...
channel = (conv.get("channel") or "widget").strip().lower()
if channel not in ("widget", "max"):
    channel = "widget"
external_user_id = (conv.get("external_user_id") or None)

# UPSERT into the LK conversations replica:
#   - on INSERT: include channel + external_user_id
#   - on UPDATE: leave them untouched (channel is immutable)
```

> **Why immutable on UPDATE:** snapshots are sent for every message in
> the conversation. If you let `UPDATE` overwrite the channel, a future
> bug elsewhere could flip the badge mid-conversation. Treating both new
> fields as set-once is symmetrical with MGP runtime.

If the LK also has a PULL-fallback (`sync_mgp.py`), extend its SELECT to
fetch the new columns:

```python
# WAS:
"SELECT id, session_id, llm_provider, model, ... FROM conversations"
# BECOMES:
"SELECT id, session_id, channel, external_user_id, llm_provider, model, ... FROM conversations"
```

…and map them into the same INSERT/UPDATE statement the receiver uses.

### 2.3 LK UI (badge + optional filter)

This is the only part that needs design taste. Recommended baseline:

* Conversation list row: small pill next to the title. `Виджет`
  (neutral blue) vs `MAX` (purple / brand). When you add Telegram /
  WhatsApp later, the same row scales without re-design.
* Conversation detail page: header line "Канал: MAX Messenger ·
  внешний ID 213771498" — clicking the ID could later deep-link into
  the MAX dev console.
* Optional filter on the top of the list: "Все каналы / Виджет / MAX".
  Backed by `?channel=max` in the LK API.
* Optional analytics: a per-tenant counter "Каналы за период" with
  pie chart `widget` vs `max`. Cheap to add once the column is indexed.

---

## 3. Verification plan after LK lands its 3 changes

```sql
-- 1) Distribution sanity (on the LK postgres, after the migration):
SELECT channel, COUNT(*) FROM conversations GROUP BY channel;
-- expected: a row for 'widget' and a row for 'max'

-- 2) Random MAX row carries the external_user_id:
SELECT session_id, channel, external_user_id
FROM conversations
WHERE channel = 'max'
ORDER BY started_at DESC
LIMIT 5;
-- expected: every row has a non-NULL external_user_id like '213771498'

-- 3) Latest snapshot from MGP contains the new keys (spot-check via
-- LK's raw event log if you keep one):
-- The "conversation" block should have "channel": "max" / "widget" and,
-- for MAX, "external_user_id": "<digits>".
```

End-to-end smoke:

1. Send a real message to the production MAX bot.
2. Wait < 30s.
3. Open the LK cabinet → conversations list. The new row should appear
   with the `MAX` badge.
4. Open the conversation → header shows the external_user_id.

---

## 4. Reference: file map for the mgp_v2 changes

| File | Phase | Purpose |
|---|---|---|
| `backend/alembic/versions/j0k1l2m3n4o_add_conversation_channel.py` | A | DB migration (channel + external_user_id) |
| `backend/models.py` | A | `Conversation.channel` / `Conversation.external_user_id` |
| `backend/app.py` (`chat_v1`, `_log_chat_to_db`, `get_handler`) | A + E | Reads `X-Channel` / `X-External-User-Id`, persists, propagates to handler |
| `backend/dialog_sender.py` (`_build_snapshot_payload`) | A | Adds the keys to the payload sent to LK |
| `backend/yandex_handler.py` (`_handle_submit_client_request`) | E | Prepends `[Канал: ...]` to the U-ON comment |
| `services/max_bridge/app/chat_proxy.py` | A (PR #1B) | Sets `X-Channel: max` + `X-External-User-Id` |
| `services/max_bridge/app/webhook.py` | A + B | Passes MAX user_id; resolves tenants via directory |
| `services/max_bridge/app/tenant_directory.py` | B | Async, refreshing cache of `{webhook_secret → TenantBinding}` |
| `services/max_bridge/app/config.py` / `main.py` | B | Wires the directory into lifespan and config |
| `backend/max_admin.py` | C | Enable / disable / status helpers |
| `backend/cli.py` (`max-channel`) | C | CLI wrapper around `max_admin` |
| `deploy/provision_clients.sh` (`setup_max_channel`) | C | Symmetric to `setup_reporting`; idempotent |
| `.test_results/channel_attribution/test_sanity.py` | A | Unit sanity for header normalisation |

### Commits

* `ea87794` — `feat(channel): per-conversation channel attribution (widget vs max)` (Phase A, backend only)
* `316b15d` — `feat(max-bridge): forward channel attribution to mgp-backend` (Phase A, bridge headers)
* `5295e8f` — merge of `main` into `feature/max-bridge`
* `06169a2` — `feat(max-bridge): dynamic tenant directory from backend (phase 3)` (Phase B)
* `60a6a2a` — `feat(max-channel): CLI + provisioning + CRM/email channel marker (phases C + E)` (Phases C + E)

---

## 5. FAQ

**Q. Will old LK code crash on the new payload?**
A. No. Unknown keys (`channel`, `external_user_id`) are silently
discarded by the existing parser. We deliberately did NOT bump
`contract_version`.

**Q. What if LK ships the migration but not the receiver change yet?**
A. New rows still get `channel = 'widget'` by default. Once the receiver
starts reading the payload key, future inserts will be tagged correctly.
Historical rows can be back-filled with the SQL snippet in section 2.1.

**Q. Can a tenant temporarily disable the MAX channel?**
A. Yes — `cli.py max-channel disable --slug X` flips
`enabled=false`. Within 60s the bridge stops resolving its webhook
secret and returns 401 to MAX. Re-enabling via `enable` restores it.

**Q. Where does the MAX `bot_token` live and is it sensitive?**
A. Stored in plain text in `assistants.runtime_metadata.channels.max.bot_token`
(same security model as `runtime_metadata.reporting.auth.secret`). DB
access = secret access. If you need at-rest encryption later, this is a
single place to bolt it on.

**Q. How is `external_user_id` produced for MAX?**
A. The bridge reads `message.sender.user_id` from the MAX webhook payload
and forwards it as a string in the `X-External-User-Id` header. It is
**never** a phone number / email; only MAX's opaque numeric id.

**Q. Future channels (Telegram, WhatsApp)?**
A. The schema scales: just emit `channel='telegram'` from the matching
bridge service and add `telegram` to the LK enum / badge styling. Allowed
values check is in two places — `backend/app.py:_log_chat_to_db` and the
LK receiver — both with `widget` as the safe default.

---

## 6. Open items intentionally left for LK side

* UI badge styling (colors / icon).
* Filter / facet in the conversations list.
* Per-tenant channel pie chart on the analytics dashboard (if any).
* Decision whether to back-fill historical `max-*` rows or leave them
  tagged `widget` (section 2.1 has the one-liner if you want).
* Decision whether the LK UI should hide `bot_token` / `webhook_secret`
  in the assistant settings page (today only the operator sees them via
  CLI; if LK later renders them, mask in UI).

Anything beyond that — design, deploy cadence, end-user-facing copy — is
yours.
