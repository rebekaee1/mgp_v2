"""
Sync engine: pulls new conversations, messages, and tour_searches from a remote
MGP bot PostgreSQL (accessed via SSH tunnel) into the local ЛК database.

Incremental sync: uses last_active_at / created_at watermarks stored in Redis
so only new/updated rows are fetched each cycle.

Usage:
    # One-shot (cron / manual):
    python sync_mgp.py

    # Integrated with APScheduler inside the ЛК backend (see scheduler.py).
"""

import logging
import os
import signal
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg

logger = logging.getLogger("mgp_bot.sync")

SYNC_STATE_KEY = "sync:mgp:watermarks"

_CONV_COLS_REMOTE = (
    "id", "session_id", "llm_provider", "model", "ip_address",
    "user_agent", "message_count", "search_count", "tour_cards_shown",
    "status", "started_at", "last_active_at",
)

_MSG_COLS = (
    "id", "conversation_id", "role", "content", "tool_call_id",
    "tool_calls", "tour_cards", "tokens_prompt", "tokens_completion",
    "latency_ms", "created_at",
)

_SEARCH_COLS = (
    "id", "conversation_id", "requestid", "search_type", "departure",
    "country", "regions", "date_from", "date_to", "nights_from",
    "nights_to", "adults", "children", "stars", "meal",
    "price_from", "price_to", "hotels_found", "tours_found",
    "min_price", "duration_ms", "created_at",
)


def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def remote_pg_connection():
    """Open SSH tunnel via ssh key (preferred) or sshpass fallback → remote PostgreSQL.
    Yields a psycopg3 connection."""
    ssh_host = _get_env("MGP_SSH_HOST", "")
    if not ssh_host:
        raise RuntimeError("MGP_SSH_HOST not configured — cannot open SSH tunnel")
    ssh_port = _get_env("MGP_SSH_PORT", "22")
    ssh_user = _get_env("MGP_SSH_USER", "root")
    ssh_pass = _get_env("MGP_SSH_PASSWORD", "")
    ssh_key = _get_env("MGP_SSH_KEY_PATH", "/tmp/sync_key")
    remote_pg_port = _get_env("MGP_PG_PORT", "5432")
    pg_user = _get_env("MGP_PG_USER", "mgp")
    pg_pass = _get_env("MGP_PG_PASSWORD", "mgp")
    pg_db = _get_env("MGP_PG_DB", "mgp")

    local_port = _find_free_port()

    use_key = os.path.isfile(ssh_key)
    if use_key:
        cmd = [
            "ssh",
            "-i", ssh_key,
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-N",
            "-L", f"{local_port}:127.0.0.1:{remote_pg_port}",
            "-p", ssh_port,
            f"{ssh_user}@{ssh_host}",
        ]
    else:
        cmd = [
            "sshpass", "-p", ssh_pass,
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-N",
            "-L", f"{local_port}:127.0.0.1:{remote_pg_port}",
            "-p", ssh_port,
            f"{ssh_user}@{ssh_host}",
        ]
    tunnel_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    # Wait for tunnel to be ready
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


def _load_watermarks(redis_client) -> dict:
    """Load last-sync timestamps from Redis."""
    if redis_client is None:
        return {}
    import json
    raw = redis_client.get(SYNC_STATE_KEY)
    if raw:
        return json.loads(raw)
    return {}


def _save_watermarks(redis_client, wm: dict):
    if redis_client is None:
        return
    import json
    redis_client.set(SYNC_STATE_KEY, json.dumps(wm), ex=86400 * 30)


def sync_conversations(remote_conn, local_session, assistant_id: uuid.UUID, watermark: str | None):
    """Sync conversations: UPSERT by id, link to assistant_id."""
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
        logger.info("Conversations: 0 new/updated")
        return watermark

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
        data["assistant_id"] = str(assistant_id)
        try:
            sp = local_session.begin_nested()
            local_session.execute(upsert_sql, data)
            sp.commit()
        except Exception:
            sp.rollback()
            skipped += 1
            continue
        ts = data["last_active_at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        if not new_watermark or ts > new_watermark:
            new_watermark = ts
    if skipped:
        logger.warning("Conversations: skipped %d rows (unique constraint)", skipped)

    local_session.flush()
    logger.info("Conversations: %d synced (watermark → %s)", len(rows), new_watermark)
    return new_watermark


def _jsonb_safe(val):
    """Convert dict/list to JSON string for raw SQL JSONB insert via psycopg3."""
    if val is None:
        return None
    import json
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return val


def sync_messages(remote_conn, local_session, watermark: str | None):
    """Sync messages: INSERT new only (messages are immutable)."""
    since_clause = ""
    params: dict = {}
    if watermark:
        since_clause = "WHERE created_at > %(since)s"
        params["since"] = watermark

    cols = ", ".join(_MSG_COLS)
    sql = f"SELECT {cols} FROM messages {since_clause} ORDER BY created_at LIMIT 100000"

    with remote_conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        logger.info("Messages: 0 new")
        return watermark

    from sqlalchemy import text as sa_text
    jsonb_cols = {"tool_calls", "tour_cards"}
    placeholders = ", ".join(
        f"CAST(:{c} AS jsonb)" if c in jsonb_cols else f":{c}"
        for c in _MSG_COLS
    )
    cols_str = ", ".join(_MSG_COLS)
    upsert_sql = sa_text(f"""
        INSERT INTO messages ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT (id) DO NOTHING
    """)

    new_watermark = watermark
    for row in rows:
        data = dict(zip(_MSG_COLS, row))
        for jc in jsonb_cols:
            data[jc] = _jsonb_safe(data[jc])
        local_session.execute(upsert_sql, data)
        ts = data["created_at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        if not new_watermark or ts > new_watermark:
            new_watermark = ts

    local_session.flush()
    logger.info("Messages: %d synced (watermark → %s)", len(rows), new_watermark)
    return new_watermark


def sync_tour_searches(remote_conn, local_session, watermark: str | None):
    """Sync tour_searches: INSERT new only."""
    since_clause = ""
    params: dict = {}
    if watermark:
        since_clause = "WHERE created_at > %(since)s"
        params["since"] = watermark

    cols = ", ".join(_SEARCH_COLS)
    sql = f"SELECT {cols} FROM tour_searches {since_clause} ORDER BY created_at LIMIT 100000"

    with remote_conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        logger.info("TourSearches: 0 new")
        return watermark

    from sqlalchemy import text as sa_text
    cols_str = ", ".join(_SEARCH_COLS)
    placeholders = ", ".join(f":{c}" for c in _SEARCH_COLS)
    upsert_sql = sa_text(f"""
        INSERT INTO tour_searches ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT (id) DO NOTHING
    """)

    new_watermark = watermark
    for row in rows:
        data = dict(zip(_SEARCH_COLS, row))
        local_session.execute(upsert_sql, data)
        ts = data["created_at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        if not new_watermark or ts > new_watermark:
            new_watermark = ts

    local_session.flush()
    logger.info("TourSearches: %d synced (watermark → %s)", len(rows), new_watermark)
    return new_watermark


_SEQ_OFFSET = 10_000_000


def _ensure_sequence_offset(local_session):
    """Ensure local auto-increment sequences start above _SEQ_OFFSET to avoid
    ID collisions with synced remote data (remote IDs are < _SEQ_OFFSET)."""
    from sqlalchemy import text as sa_text
    for seq in ("messages_id_seq", "tour_searches_id_seq", "api_calls_id_seq"):
        try:
            row = local_session.execute(sa_text(f"SELECT last_value FROM {seq}")).fetchone()
            if row and row[0] < _SEQ_OFFSET:
                local_session.execute(sa_text(f"SELECT setval('{seq}', {_SEQ_OFFSET}, false)"))
                logger.info("Sequence %s advanced to %d", seq, _SEQ_OFFSET)
        except Exception:
            logger.debug("Sequence %s not found, skipping", seq)


def run_sync():
    """Full incremental sync: remote MGP → local ЛК database."""
    from database import init_db, get_db
    from config import settings

    init_db(settings.database_url)

    try:
        import redis as _redis
        redis_client = _redis.from_url(
            _get_env("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        redis_client.ping()
    except Exception:
        redis_client = None
        logger.warning("Redis unavailable — watermarks will not persist between runs")

    watermarks = _load_watermarks(redis_client)

    with get_db() as db:
        if db is None:
            logger.error("Local DB unavailable — cannot sync")
            return

        from models import Assistant
        assistant = db.query(Assistant).first()
        if assistant is None:
            logger.error("No assistant found — run seed_data.py first")
            return
        assistant_id = assistant.id

    try:
        with remote_pg_connection() as remote_conn:
            with get_db() as db:
                if db is None:
                    return

                _ensure_sequence_offset(db)

                wm_conv = sync_conversations(
                    remote_conn, db, assistant_id,
                    watermarks.get("conversations"),
                )
                wm_msg = sync_messages(
                    remote_conn, db,
                    watermarks.get("messages"),
                )
                wm_ts = sync_tour_searches(
                    remote_conn, db,
                    watermarks.get("tour_searches"),
                )

                watermarks["conversations"] = wm_conv
                watermarks["messages"] = wm_msg
                watermarks["tour_searches"] = wm_ts

        _save_watermarks(redis_client, watermarks)
        logger.info("Sync complete ✓")

    except Exception:
        logger.exception("Sync failed")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    run_sync()
