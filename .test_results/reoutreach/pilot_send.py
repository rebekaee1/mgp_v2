#!/usr/bin/env python3
"""Re-outreach PILOT sender for ONE tenant (default mgp-tour) — controlled test.

Safety:
  * targets a SINGLE assistant_id;
  * only conversations idle >= --silence-min AND active within --lookback-hours
    (a narrow window so a fresh test dialogue is isolated from old users);
  * --max-send caps how many messages can go out (default 1);
  * DRY-RUN by default — actually sends only with --send;
  * dedup ledger so the same conversation is never messaged twice.

Sends via MAX Bot API (botapi.max.ru POST /messages). Bot token is read from the
DB over ssh at runtime and never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error

import reoutreach_lib as R

HERE = os.path.dirname(os.path.abspath(__file__))
SQL = os.path.join(HERE, "select_candidates_generic.sql")
LEDGER = os.path.join(HERE, "pilot_ledger.sqlite")
MGP_TOUR = "593471b7-42da-4ae0-8499-904dcedd6a4b"
SSH = ["ssh", "-o", "ConnectTimeout=25", "-o", "ServerAliveInterval=10", "mgp-prod"]
PSQL = "sudo docker exec -i mgp-postgres-1 psql -U mgp -d mgp -t -A"
MAX_API = "https://botapi.max.ru"


def _psql(sql: str) -> str:
    proc = subprocess.run(SSH + [PSQL], input=sql.encode(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:400])
    return proc.stdout.decode("utf-8", "replace")


def fetch_token(assistant_id: str) -> str:
    sql = (f"SELECT a.runtime_metadata->'channels'->'max'->>'bot_token' "
           f"FROM assistants a WHERE a.id='{assistant_id}'")
    tok = _psql(sql).strip()
    if not tok:
        raise RuntimeError("no bot_token for assistant")
    return tok


def collect(assistant_id: str, silence_min: int, lookback_hours: int) -> list:
    with open(SQL, encoding="utf-8") as fh:
        sql = (fh.read().replace("{ASSISTANT_ID}", assistant_id)
                        .replace("{SILENCE_MINUTES}", str(int(silence_min)))
                        .replace("{LOOKBACK_HOURS}", str(int(lookback_hours))))
    out = []
    for ln in _psql(sql).splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            out.append(json.loads(ln))
    return out


def ledger():
    c = sqlite3.connect(LEDGER)
    c.execute("CREATE TABLE IF NOT EXISTS sent(conversation_id TEXT PRIMARY KEY, at REAL, msg TEXT)")
    c.commit()
    return c


def persist_history(conversation_id: str, text: str) -> None:
    """Record the re-outreach as an assistant message in the conversation so the
    backend loads it into context on the user's reply (fixes the 'amnesia' bug).
    Also bump last_active_at so the bot's turn is the latest activity."""
    sql = (
        "INSERT INTO messages (conversation_id, role, content, created_at) "
        f"VALUES ('{conversation_id}', 'assistant', $RO${text}$RO$, now()); "
        f"UPDATE conversations SET last_active_at = now() WHERE id = '{conversation_id}';"
    )
    _psql(sql)


def max_send(token: str, chat_id: str, text: str) -> dict:
    url = f"{MAX_API}/messages?chat_id={chat_id}"
    body = json.dumps({"text": text, "format": "markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assistant", default=MGP_TOUR)
    ap.add_argument("--silence-min", type=int, default=30)
    ap.add_argument("--lookback-hours", type=int, default=3)
    ap.add_argument("--phone", default="", help="manager phone for bucket-1 (empty=omit)")
    ap.add_argument("--max-send", type=int, default=1)
    ap.add_argument("--send", action="store_true", help="actually send (else dry-run)")
    ap.add_argument("--force", action="store_true", help="ignore dedup ledger (re-tests)")
    args = ap.parse_args()

    recs = collect(args.assistant, args.silence_min, args.lookback_hours)
    print(f"candidates (idle>={args.silence_min}m, within {args.lookback_hours}h): {len(recs)}")
    led = ledger()
    sent = 0
    token = None
    for r in recs:
        bucket, reason = R.classify(r)
        if bucket == "skip":
            print(f"  skip {r['id'][:8]} ({reason}) :: {(r.get('utext') or '')[:60]}")
            continue
        if not args.force and led.execute("SELECT 1 FROM sent WHERE conversation_id=?", (r["id"],)).fetchone():
            print(f"  already-sent {r['id'][:8]}")
            continue
        brief = R.extract_brief(r)
        msg = R.render_message(brief, bucket, manager_phone=(args.phone or None))
        ok, errs = R.validate(msg, brief)
        chat_id = r.get("chat_id") or r.get("uid")
        print(f"\n  [{bucket}] conv={r['id'][:8]} chat={chat_id} valid={ok} {errs if errs else ''}")
        print(f"  src: {(r.get('utext') or '')[:90]}")
        print(f"  ->  {msg}")
        if not ok:
            print("  (skip send: invalid)")
            continue
        if sent >= args.max_send:
            print("  (max-send reached, not sending more)")
            continue
        if not args.send:
            print("  (DRY-RUN: not sent)")
            continue
        if token is None:
            token = fetch_token(args.assistant)
        try:
            resp = max_send(token, str(chat_id), msg)
            persist_history(r["id"], msg)  # <- the fix: re-outreach now lives in conversation history
            led.execute("INSERT OR REPLACE INTO sent VALUES(?,?,?)", (r["id"], time.time(), msg))
            led.commit()
            sent += 1
            print(f"  SENT ok + persisted to history -> mid={resp.get('message',{}).get('body',{}).get('mid') or 'ok'}")
        except urllib.error.HTTPError as e:
            print(f"  SEND FAILED HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}")
        except Exception as e:  # noqa: BLE001
            print(f"  SEND FAILED: {e}")
    print(f"\nDONE. sent={sent} (dry_run={not args.send})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
