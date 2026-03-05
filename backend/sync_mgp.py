from __future__ import annotations

"""
Multi-tenant sync engine: pulls new conversations, messages, and tour_searches
from each assistant's remote PostgreSQL (accessed via SSH tunnel) into the
local ЛК database.

Incremental sync: uses per-assistant watermarks stored in Redis so only
new/updated rows are fetched each cycle.

Usage:
    # One-shot (cron / manual):
    python sync_mgp.py

    # Integrated with APScheduler inside the ЛК backend (see scheduler.py).
"""

import json
import logging
import os
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

logger = logging.getLogger("mgp_bot.sync")

_CONV_COLS_REMOTE = (
    "id", "session_id", "llm_provider", "model", "ip_address",
    "user_agent", "message_count", "search_count", "tour_cards_shown",
    "status", "started_at", "last_active_at",
)

_MSG_COLS_REMOTE = (
    "id", "conversation_id", "role", "content", "tool_call_id",
    "tool_calls", "tour_cards", "tokens_prompt", "tokens_completion",
    "latency_ms", "created_at",
)

_SEARCH_COLS_REMOTE = (
    "id", "conversation_id", "requestid", "search_type", "departure",
    "country", "regions", "date_from", "date_to", "nights_from",
    "nights_to", "adults", "children", "stars", "meal",
    "price_from", "price_to", "hotels_found", "tours_found",
    "min_price", "duration_ms", "created_at",
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def remote_pg_connection(cfg: dict):
    """Open SSH tunnel → remote PostgreSQL. Yields a psycopg3 connection.

    cfg keys: ssh_host, ssh_port, ssh_user, ssh_password,
              pg_port, pg_user, pg_password, pg_db
    """
    ssh_host = cfg["ssh_host"]
    if not ssh_host:
        raise RuntimeError("ssh_host not configured — cannot open SSH tunnel")
    ssh_port = str(cfg.get("ssh_port", 22))
    ssh_user = cfg.get("ssh_user", "root")
    ssh_pass = cfg.get("ssh_password", "")
    remote_pg_port = str(cfg.get("pg_port", 5432))
    pg_user = cfg.get("pg_user", "mgp")
    pg_pass = cfg.get("pg_password", "mgp")
    pg_db = cfg.get("pg_db", "mgp")

    local_port = _find_free_port()

    ssh_key = "/tmp/sync_key"
    use_key = os.path.isfile(ssh_key)

    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-N",
        "-L", f"{local_port}:127.0.0.1:{remote_pg_port}",
        "-p", ssh_port,
        f"{ssh_user}@{ssh_host}",
    ]
    if use_key:
        cmd = ["ssh", "-i", ssh_key] + ssh_opts
    else:
        cmd = ["sshpass", "-p", ssh_pass, "ssh"] + ssh_opts

    tunnel_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    for _ in range(30):
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=1):
                break
        except OSError:
            time.sleep(0.3)
    else:
        tunnel_proc.kill()
        stderr = tunnel_proc.stderr.read().decode(errors="replace") if tunnel_proc.stderr else ""
        raise RuntimeError(f"SSH tunnel failed to open: {stderr}")

    logger.info("SSH tunnel open → %s:%s (local :%d)", ssh_host, remote_pg_port, local_port)

    conninfo = f"host=127.0.0.1 port={local_port} user={pg_user} password={pg_pass} dbname={pg_db}"
    conn = psycopg.connect(conninfo, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()
        tunnel_proc.terminate()
        try:
            tunnel_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel_proc.kill()
        logger.info("SSH tunnel closed")


def _wm_key(assistant_id: uuid.UUID) -> str:
    return f"sync:wm:{assistant_id}"


def _load_watermarks(redis_client, assistant_id: uuid.UUID) -> dict:
    if redis_client is None:
        return {}
    raw = redis_client.get(_wm_key(assistant_id))
    if raw:
        return json.loads(raw)
    return {}


def _save_watermarks(redis_client, assistant_id: uuid.UUID, wm: dict):
    if redis_client is None:
        return
    redis_client.set(_wm_key(assistant_id), json.dumps(wm), ex=86400 * 30)


def _jsonb_safe(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return val


# ── Conversations ────────────────────────────────────────────────────────────

def sync_conversations(remote_conn, local_session, assistant_id: uuid.UUID, watermark: str | None):
    since_clause = ""
    params: dict = {}
    if watermark:
        since_clause = "WHERE last_active_at > %(since)s"
        params["since"] = watermark

    cols = ", ".join(_CONV_COLS_REMOTE)
    sql = f"SELECT {cols} FROM conversations {since_clause} ORDER BY last_active_at LIMIT 50000"

    with remote_conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        logger.info("[%s] Conversations: 0 new/updated", str(assistant_id)[:8])
        return watermark, 0

    from sqlalchemy import text as sa_text
    upsert_sql = sa_text("""
        INSERT INTO conversations (
            id, session_id, llm_provider, model, ip_address,
            user_agent, message_count, search_count, tour_cards_shown,
            status, started_at, last_active_at, assistant_id, has_booking_intent
        ) VALUES (
            :id, :session_id, :llm_provider, :model, :ip_address,
            :user_agent, :message_count, :search_count, :tour_cards_shown,
            :status, :started_at, :last_active_at, :assistant_id, false
        )
        ON CONFLICT (id) DO UPDATE SET
            message_count = EXCLUDED.message_count,
            search_count = EXCLUDED.search_count,
            tour_cards_shown = EXCLUDED.tour_cards_shown,
            status = EXCLUDED.status,
            last_active_at = EXCLUDED.last_active_at
    """)

    new_watermark = watermark
    skipped = 0
    for row in rows:
        data = dict(zip(_CONV_COLS_REMOTE, row))
        data["assistant_id"] = str(assistant_id).replace("-", "")
        for k, v in data.items():
            if isinstance(v, uuid.UUID):
                data[k] = v.hex
        try:
            sp = local_session.begin_nested()
            local_session.execute(upsert_sql, data)
            sp.commit()
        except Exception as e:
            sp.rollback()
            skipped += 1
            logger.debug("Conv skip %s: %s", data.get("id", "?")[:8], e)
            continue
        ts = data["last_active_at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        if not new_watermark or ts > new_watermark:
            new_watermark = ts
    if skipped:
        logger.warning("[%s] Conversations: skipped %d rows", str(assistant_id)[:8], skipped)

    local_session.flush()
    synced_count = len(rows) - skipped
    logger.info("[%s] Conversations: %d synced (wm → %s)", str(assistant_id)[:8], synced_count, new_watermark)
    return new_watermark, synced_count


# ── Messages ─────────────────────────────────────────────────────────────────

def sync_messages(remote_conn, local_session, watermark: str | None, assistant_tag: str = ""):
    since_clause = ""
    params: dict = {}
    if watermark:
        since_clause = "WHERE created_at > %(since)s"
        params["since"] = watermark

    cols = ", ".join(_MSG_COLS_REMOTE)
    sql = f"SELECT {cols} FROM messages {since_clause} ORDER BY created_at LIMIT 100000"

    with remote_conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        logger.info("[%s] Messages: 0 new", assistant_tag)
        return watermark, 0

    from sqlalchemy import text as sa_text
    jsonb_cols = {"tool_calls", "tour_cards"}

    local_cols = (
        "conversation_id", "remote_id", "role", "content", "tool_call_id",
        "tool_calls", "tour_cards", "tokens_prompt", "tokens_completion",
        "latency_ms", "created_at",
    )
    placeholders = ", ".join(
        f"CAST(:{c} AS jsonb)" if c in jsonb_cols else f":{c}"
        for c in local_cols
    )
    cols_str = ", ".join(local_cols)
    upsert_sql = sa_text(f"""
        INSERT INTO messages ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT (conversation_id, remote_id) DO NOTHING
    """)

    new_watermark = watermark
    inserted = 0
    for row in rows:
        data = dict(zip(_MSG_COLS_REMOTE, row))
        remote_id = data.pop("id")
        data["remote_id"] = remote_id
        for jc in jsonb_cols:
            data[jc] = _jsonb_safe(data[jc])
        for k, v in data.items():
            if isinstance(v, uuid.UUID):
                data[k] = v.hex
        try:
            sp = local_session.begin_nested()
            local_session.execute(upsert_sql, data)
            sp.commit()
            inserted += 1
        except Exception:
            sp.rollback()
        ts = data["created_at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        if not new_watermark or ts > new_watermark:
            new_watermark = ts

    local_session.flush()
    logger.info("[%s] Messages: %d synced (wm → %s)", assistant_tag, inserted, new_watermark)
    return new_watermark, inserted


# ── Tour searches ────────────────────────────────────────────────────────────

def sync_tour_searches(remote_conn, local_session, watermark: str | None, assistant_tag: str = ""):
    since_clause = ""
    params: dict = {}
    if watermark:
        since_clause = "WHERE created_at > %(since)s"
        params["since"] = watermark

    cols = ", ".join(_SEARCH_COLS_REMOTE)
    sql = f"SELECT {cols} FROM tour_searches {since_clause} ORDER BY created_at LIMIT 100000"

    with remote_conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        logger.info("[%s] TourSearches: 0 new", assistant_tag)
        return watermark, 0

    from sqlalchemy import text as sa_text

    local_cols = (
        "conversation_id", "remote_id", "requestid", "search_type", "departure",
        "country", "regions", "date_from", "date_to", "nights_from",
        "nights_to", "adults", "children", "stars", "meal",
        "price_from", "price_to", "hotels_found", "tours_found",
        "min_price", "duration_ms", "created_at",
    )
    placeholders = ", ".join(f":{c}" for c in local_cols)
    cols_str = ", ".join(local_cols)
    upsert_sql = sa_text(f"""
        INSERT INTO tour_searches ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT (conversation_id, remote_id) DO NOTHING
    """)

    new_watermark = watermark
    inserted = 0
    for row in rows:
        data = dict(zip(_SEARCH_COLS_REMOTE, row))
        remote_id = data.pop("id")
        data["remote_id"] = remote_id
        for k, v in data.items():
            if isinstance(v, uuid.UUID):
                data[k] = v.hex
        try:
            sp = local_session.begin_nested()
            local_session.execute(upsert_sql, data)
            sp.commit()
            inserted += 1
        except Exception:
            sp.rollback()
        ts = data["created_at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        if not new_watermark or ts > new_watermark:
            new_watermark = ts

    local_session.flush()
    logger.info("[%s] TourSearches: %d synced (wm → %s)", assistant_tag, inserted, new_watermark)
    return new_watermark, inserted


# ── Booking intent ───────────────────────────────────────────────────────────

def _recompute_booking_intent(local_session, assistant_id: uuid.UUID):
    from models import Conversation, Message
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from app import check_conversation_booking_intent

    convs = local_session.query(Conversation).filter(
        Conversation.has_booking_intent == False,  # noqa: E712
        Conversation.assistant_id == assistant_id,
    ).all()

    updated = 0
    for conv in convs:
        user_texts = [
            m.content for m in local_session.query(Message.content).filter(
                Message.conversation_id == conv.id,
                Message.role == "user",
            ).all()
        ]
        if check_conversation_booking_intent(user_texts):
            conv.has_booking_intent = True
            updated += 1

    if updated:
        local_session.flush()
    logger.info("[%s] Booking intent: %d updated", str(assistant_id)[:8], updated)


# ── Per-assistant update sync status in DB ───────────────────────────────────

def _update_sync_status(local_session, assistant_id: uuid.UUID, success: bool, error: str | None = None):
    from sqlalchemy import text as sa_text
    local_session.execute(
        sa_text("""
            UPDATE assistants
            SET last_sync_at = :ts,
                last_sync_status = :status,
                last_sync_error = :error
            WHERE id = :aid
        """),
        {
            "ts": datetime.now(timezone.utc),
            "status": "ok" if success else "error",
            "error": error[:500] if error else None,
            "aid": str(assistant_id).replace("-", ""),
        },
    )
    local_session.flush()


# ── Single assistant sync ────────────────────────────────────────────────────

def _sync_single_assistant(assistant, redis_client, get_db_fn):
    """Run incremental sync for one assistant. Isolated: exceptions don't leak."""
    aid = assistant.id
    tag = str(aid)[:8]
    logger.info("── Sync start: %s (%s) ──", assistant.name, tag)

    cfg = {
        "ssh_host": assistant.sync_ssh_host,
        "ssh_port": assistant.sync_ssh_port or 22,
        "ssh_user": assistant.sync_ssh_user or "root",
        "ssh_password": assistant.sync_ssh_password or "",
        "pg_port": assistant.sync_pg_port or 5432,
        "pg_user": assistant.sync_pg_user or "mgp",
        "pg_password": assistant.sync_pg_password or "mgp",
        "pg_db": assistant.sync_pg_db or "mgp",
    }

    watermarks = _load_watermarks(redis_client, aid)

    try:
        with remote_pg_connection(cfg) as remote_conn:
            with get_db_fn() as db:
                if db is None:
                    return

                wm_conv, n_conv = sync_conversations(
                    remote_conn, db, aid,
                    watermarks.get("conversations"),
                )
                wm_msg, n_msg = sync_messages(
                    remote_conn, db,
                    watermarks.get("messages"),
                    assistant_tag=tag,
                )
                wm_ts, n_ts = sync_tour_searches(
                    remote_conn, db,
                    watermarks.get("tour_searches"),
                    assistant_tag=tag,
                )

                if n_msg > 0:
                    _recompute_booking_intent(db, aid)

                watermarks["conversations"] = wm_conv
                watermarks["messages"] = wm_msg
                watermarks["tour_searches"] = wm_ts

                _update_sync_status(db, aid, success=True)

        _save_watermarks(redis_client, aid, watermarks)
        logger.info("── Sync done: %s (%d conv, %d msg, %d ts) ──", tag, n_conv, n_msg, n_ts)

    except Exception as exc:
        logger.exception("Sync failed for assistant %s", tag)
        try:
            with get_db_fn() as db:
                if db:
                    _update_sync_status(db, aid, success=False, error=str(exc))
        except Exception:
            logger.debug("Could not persist sync error for %s", tag)


# ── Main entry point (called by scheduler) ───────────────────────────────────

def _migrate_legacy_watermarks(redis_client, assistants):
    """One-time: move old `sync:mgp:watermarks` key to per-assistant keys."""
    if redis_client is None:
        return
    old_key = "sync:mgp:watermarks"
    raw = redis_client.get(old_key)
    if not raw:
        return
    try:
        old_wm = json.loads(raw)
    except Exception:
        return
    if not old_wm or not assistants:
        return
    first_id = assistants[0].id
    new_key = _wm_key(first_id)
    if redis_client.exists(new_key):
        return
    redis_client.set(new_key, json.dumps(old_wm), ex=86400 * 30)
    redis_client.delete(old_key)
    logger.info("Migrated legacy watermarks → %s", new_key)


def run_sync_all():
    """Iterate over all sync-enabled assistants and sync each one."""
    from database import init_db, get_db
    from config import settings

    init_db(settings.database_url)

    try:
        import redis as _redis
        redis_client = _redis.from_url(
            os.environ.get("REDIS_URL", settings.redis_url),
            decode_responses=True,
        )
        redis_client.ping()
    except Exception:
        redis_client = None
        logger.warning("Redis unavailable — watermarks will not persist")

    from models import Assistant

    with get_db() as db:
        if db is None:
            logger.error("Local DB unavailable — cannot sync")
            return
        assistants = db.query(Assistant).filter(
            Assistant.sync_enabled == True,  # noqa: E712
            Assistant.sync_ssh_host.isnot(None),
        ).all()

    _migrate_legacy_watermarks(redis_client, assistants)

    if not assistants:
        logger.info("No sync-enabled assistants found — nothing to do")
        return

    logger.info("Sync cycle: %d assistant(s) to sync", len(assistants))
    for ast in assistants:
        _sync_single_assistant(ast, redis_client, get_db)


# Backward-compat alias
run_sync = run_sync_all

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_sync_all()
