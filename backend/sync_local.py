#!/usr/bin/env python3
"""
One-time data pull from remote MGP bot PostgreSQL into local SQLite.
Uses paramiko for SSH tunnel directly (no sshtunnel/sshpass needed).
"""

import json
import logging
import os
import select
import socket
import threading
import uuid
from datetime import datetime, timezone

import paramiko
import psycopg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_local")

SSH_HOST = os.getenv("MGP_SSH_HOST", "")
SSH_PORT = int(os.getenv("MGP_SSH_PORT", "22"))
SSH_USER = os.getenv("MGP_SSH_USER", "root")
SSH_PASS = os.getenv("MGP_SSH_PASSWORD", "")
PG_USER = os.getenv("MGP_PG_USER", "mgp")
PG_PASS = os.getenv("MGP_PG_PASSWORD", "mgp")
PG_DB = os.getenv("MGP_PG_DB", "mgp")
PG_PORT = int(os.getenv("MGP_PG_PORT", "5432"))


class ForwardServer(threading.Thread):
    """Local TCP server that forwards connections through SSH channel."""
    daemon = True

    def __init__(self, local_port, transport, remote_host, remote_port):
        super().__init__()
        self.local_port = local_port
        self.transport = transport
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", local_port))
        self.server.listen(5)
        self.server.settimeout(1)
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                client_sock, addr = self.server.accept()
            except socket.timeout:
                continue
            t = threading.Thread(target=self._handle, args=(client_sock,), daemon=True)
            t.start()

    def _handle(self, client_sock):
        try:
            chan = self.transport.open_channel(
                "direct-tcpip",
                (self.remote_host, self.remote_port),
                client_sock.getpeername(),
            )
        except Exception as e:
            logger.error("SSH channel open failed: %s", e)
            client_sock.close()
            return

        while True:
            r, _, _ = select.select([client_sock, chan], [], [], 1)
            if client_sock in r:
                data = client_sock.recv(4096)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(4096)
                if not data:
                    break
                client_sock.sendall(data)
        chan.close()
        client_sock.close()

    def stop(self):
        self._stop.set()
        self.server.close()


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fetch_remote_data(conn):
    """Fetch all conversations, messages, and tour_searches from remote."""
    data = {}

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM conversations")
        total = cur.fetchone()[0]
        logger.info("Remote has %d conversations total", total)

        cur.execute("""
            SELECT id, session_id, llm_provider, model, ip_address,
                   user_agent, message_count, search_count, tour_cards_shown,
                   status, started_at, last_active_at
            FROM conversations ORDER BY started_at
        """)
        data["conversations"] = cur.fetchall()
        logger.info("Fetched %d conversations", len(data["conversations"]))

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM messages")
        logger.info("Remote has %d messages total", cur.fetchone()[0])

        cur.execute("""
            SELECT id, conversation_id, role, content, tool_call_id,
                   tool_calls, tour_cards, tokens_prompt, tokens_completion,
                   latency_ms, created_at
            FROM messages ORDER BY created_at
        """)
        data["messages"] = cur.fetchall()
        logger.info("Fetched %d messages", len(data["messages"]))

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM tour_searches")
        logger.info("Remote has %d tour_searches total", cur.fetchone()[0])

        cur.execute("""
            SELECT id, conversation_id, requestid, search_type, departure,
                   country, regions, date_from, date_to, nights_from,
                   nights_to, adults, children, stars, meal,
                   price_from, price_to, hotels_found, tours_found,
                   min_price, duration_ms, created_at
            FROM tour_searches ORDER BY created_at
        """)
        data["tour_searches"] = cur.fetchall()
        logger.info("Fetched %d tour_searches", len(data["tour_searches"]))

    return data


def json_safe(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def insert_into_sqlite(data):
    """Insert fetched data into local SQLite via SQLAlchemy ORM."""
    from config import settings
    from database import init_db, get_db

    init_db(settings.database_url)

    from models import Assistant, Conversation, Message, TourSearch

    with get_db() as db:
        if db is None:
            logger.error("Local DB unavailable")
            return

        assistant = db.query(Assistant).first()
        if not assistant:
            logger.error("No assistant — run seed_data.py first")
            return
        assistant_id = assistant.id

        existing_convs = {str(c.id) for c in db.query(Conversation.id).all()}
        logger.info("Existing local conversations: %d", len(existing_convs))

        conv_count = 0
        for row in data["conversations"]:
            (cid, session_id, llm_provider, model, ip_address,
             user_agent, message_count, search_count, tour_cards_shown,
             status, started_at, last_active_at) = row
            has_booking_intent = False

            cid_str = str(cid)
            if cid_str in existing_convs:
                continue

            conv = Conversation(
                id=cid,
                session_id=session_id,
                assistant_id=assistant_id,
                llm_provider=llm_provider or "openai",
                model=model or "unknown",
                ip_address=ip_address,
                user_agent=str(user_agent)[:500] if user_agent else None,
                message_count=message_count or 0,
                search_count=search_count or 0,
                tour_cards_shown=tour_cards_shown or 0,
                has_booking_intent=bool(has_booking_intent),
                status=status or "active",
                started_at=started_at,
                last_active_at=last_active_at,
            )
            db.add(conv)
            existing_convs.add(cid_str)
            conv_count += 1

        db.flush()
        logger.info("Inserted %d conversations", conv_count)

        existing_msg_ids = {m[0] for m in db.query(Message.id).all()}
        msg_count = 0
        for row in data["messages"]:
            (mid, conversation_id, role, content, tool_call_id,
             tool_calls, tour_cards, tokens_prompt, tokens_completion,
             latency_ms, created_at) = row

            if mid in existing_msg_ids:
                continue
            if str(conversation_id) not in existing_convs:
                continue

            msg = Message(
                id=mid,
                conversation_id=conversation_id,
                role=role or "user",
                content=content[:10000] if content else None,
                tool_call_id=tool_call_id,
                tool_calls=json_safe(tool_calls),
                tour_cards=json_safe(tour_cards),
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
                latency_ms=latency_ms,
                created_at=created_at,
            )
            db.add(msg)
            msg_count += 1

            if msg_count % 5000 == 0:
                db.flush()
                logger.info("  ... %d messages so far", msg_count)

        db.flush()
        logger.info("Inserted %d messages", msg_count)

        existing_ts_ids = {t[0] for t in db.query(TourSearch.id).all()}
        ts_count = 0
        for row in data["tour_searches"]:
            (tid, conversation_id, requestid, search_type, departure,
             country, regions, date_from, date_to, nights_from,
             nights_to, adults, children, stars, meal,
             price_from, price_to, hotels_found, tours_found,
             min_price, duration_ms, created_at) = row

            if tid in existing_ts_ids:
                continue
            if str(conversation_id) not in existing_convs:
                continue

            ts = TourSearch(
                id=tid,
                conversation_id=conversation_id,
                requestid=requestid,
                search_type=search_type or "regular",
                departure=departure,
                country=country,
                regions=regions,
                date_from=date_from,
                date_to=date_to,
                nights_from=nights_from,
                nights_to=nights_to,
                adults=adults,
                children=children,
                stars=stars,
                meal=meal,
                price_from=price_from,
                price_to=price_to,
                hotels_found=hotels_found,
                tours_found=tours_found,
                min_price=min_price,
                duration_ms=duration_ms,
                created_at=created_at,
            )
            db.add(ts)
            ts_count += 1

        db.flush()
        logger.info("Inserted %d tour_searches", ts_count)

    logger.info("=== Sync complete! ===")
    logger.info("  Conversations: %d", conv_count)
    logger.info("  Messages: %d", msg_count)
    logger.info("  Tour searches: %d", ts_count)


def main():
    if not SSH_HOST:
        logger.error("MGP_SSH_HOST not set in .env")
        return

    local_port = find_free_port()

    logger.info("Connecting SSH to %s@%s:%d ...", SSH_USER, SSH_HOST, SSH_PORT)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASS, timeout=15)
    logger.info("SSH connected!")

    fwd = ForwardServer(local_port, ssh.get_transport(), "127.0.0.1", PG_PORT)
    fwd.start()
    logger.info("Local port forward 127.0.0.1:%d → remote 127.0.0.1:%d", local_port, PG_PORT)

    try:
        conninfo = f"host=127.0.0.1 port={local_port} user={PG_USER} password={PG_PASS} dbname={PG_DB}"
        logger.info("Connecting to remote PostgreSQL ...")
        conn = psycopg.connect(conninfo, autocommit=True)
        logger.info("Connected to remote PostgreSQL!")

        data = fetch_remote_data(conn)
        conn.close()

        insert_into_sqlite(data)

    except Exception:
        logger.exception("Sync failed")
    finally:
        fwd.stop()
        ssh.close()
        logger.info("SSH closed. Done!")


if __name__ == "__main__":
    main()
