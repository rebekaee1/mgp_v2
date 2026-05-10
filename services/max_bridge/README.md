# mgp-max-bridge

Sidecar service that connects the **MAX Messenger Bot API** to the existing
`mgp-backend` runtime (`POST /api/v1/chat`). The main backend stays untouched —
this service is a thin protocol adapter that lives in the same
`docker-compose.yml` and the same docker network.

```
MAX Messenger ──webhook──▶ mgp-max-bridge ──/api/v1/chat──▶ mgp-backend
                  ◀──/messages──┘                ◀──{reply,tour_cards}──┘
```

See `MAX_AGENT_HANDOFF.md` (repo root) for the full architectural rationale,
phase plan, and acceptance criteria. This README only documents how to run /
test the service.

## Phase 1 scope (MVP)

* Inbound `/max/webhook` parses `message_created` updates from MAX.
* Looks up / creates a `session_id` keyed by `max:user:<id>` in Redis.
* Calls `mgp-backend` `/api/v1/chat` with `X-Assistant-Id` and
  `X-MGP-Service-Token`.
* Splits replies > 4000 chars into safe chunks and sends them back via
  `POST /messages`.
* `tour_cards` are received but **not yet rendered** as native MAX cards —
  that is phase 2 (`renderers.py`).

## Layout

```
services/max_bridge/
├── Dockerfile
├── requirements.txt
├── pytest.ini
├── README.md
└── app/
    ├── main.py            # FastAPI app + lifespan + /health
    ├── config.py          # pydantic-settings, tenant routing
    ├── max_api.py         # botapi.max.ru async client
    ├── chat_proxy.py      # mgp-backend /api/v1/chat client
    ├── session_store.py   # redis async wrapper
    ├── text_splitter.py   # 4000-char safe splitter
    ├── webhook.py         # POST /max/webhook router
    └── observability.py   # structlog + correlation id
```

## Local development

> All commands assume the repository root as the working directory.

1. Make sure the relevant `MAX_*` env vars are set in `./.env` (see
   `MAX_AGENT_HANDOFF.md` §5.4).
2. Start the whole stack — postgres, redis, backend, plus the bridge:

   ```bash
   docker compose up -d --build
   ```

3. Smoke-check the bridge:

   ```bash
   curl -fsS http://127.0.0.1:8090/health
   ```

4. (Optional) verify the MAX Bot token interactively:

   ```bash
   curl -H "Authorization: $MAX_BOT_TOKEN_MGP_TOUR" https://botapi.max.ru/me
   ```

5. To accept real MAX webhooks from your laptop, expose the local port via
   ngrok / cloudflared, then register the URL once:

   ```bash
   curl -X POST https://botapi.max.ru/subscriptions \
        -H "Authorization: $MAX_BOT_TOKEN_MGP_TOUR" \
        -H "Content-Type: application/json" \
        -d '{"url":"https://<your-tunnel>.ngrok.io/max/webhook"}'
   ```

   The same shape works for production — only the URL changes.

## Tests

```bash
cd services/max_bridge
pip install -r requirements.txt
pytest
```

The suite covers the text splitter, the redis-backed session store, and the
webhook router (auth, parser, background dispatch). Network-bound tests
(`MaxApiClient`, `ChatProxy`) are intentionally not part of the unit suite —
they belong to the e2e flow described above.

## Notes on MAX Bot API quirks

* Authorization header value is the **raw** token without a `Bearer ` prefix
  (verified empirically on 2026-05-08; `Bearer` returns 401).
* `Authorization: <token>` as a query parameter (`?access_token=...`) is
  deprecated and rejected by botapi.max.ru.
* Per-message limit is **4000 chars**. We split on a safe envelope of 3900.
* Outbound rate limit is 30 RPS per bot. Phase 1 sends sequentially; an
  explicit throttle (`throttle.py`) is reserved for phase 2 / phase 4.
