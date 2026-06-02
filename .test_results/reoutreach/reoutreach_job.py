#!/usr/bin/env python3
"""AnyTour re-outreach job (Feature 1) — production runner.

ONE reminder per CLIENT, ever, ~{SILENCE_HOURS}h after their last message, then
never again. Designed to run hourly on the server (systemd timer).

Pipeline each run:
  1. collect candidates: AnyTour, channel=max, ONE per uid (latest dialogue),
     last_active in [now-{LOOKBACK_DAYS}d, now-{SILENCE_HOURS}h];
  2. drop uids already processed (sent/opt-out) — one-shot ledger;
  3. drop opt-out / explicit decline (mark optout, never again);
  4. classify; SKIP handoff / no-destination (transient — re-evaluated later);
  5. send-window 10–20 by departure-city TZ (transient skip outside window);
  6. generate: LLM for buckets 6/7, template for 1/4/5; validate;
  7. SEND via MAX -> persist re-outreach into history -> RE-POINT Redis session
     (so a reply even days later maps to the SAME dialogue, with memory) ->
     mark ledger 'sent' -> metrics. Throttled.

Safety: DRY-RUN by default; sends only with --send; --max-send caps volume.
Env REO_EXEC: prefix for docker commands ("" on server; ssh-wrapped for local dry-run).
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
from collections import Counter
from datetime import datetime, timezone

import reoutreach_lib as R
import reoutreach_llm as RL

HERE = os.path.dirname(os.path.abspath(__file__))
ASSISTANT_ID = "64fea0d3-2605-4c4c-be67-62258ebfa7a9"
SLUG = "anytour-pyatkoff"
SQL_FILE = os.path.join(HERE, "job_candidates.sql")

# departure code -> UTC offset (for local send-window). Default MSK(+3).
TZ_OFFSET = {1: 3, 2: 5, 3: 5, 4: 5, 5: 3, 6: 5, 7: 4, 8: 3, 9: 7,
             10: 3, 11: 3, 12: 7, 18: 3, 56: 3, 99: 3}
SEND_FROM, SEND_TO = 10, 20          # local hour window [10:00, 20:00)
LLM_BUCKETS = {"6_thin", "7_incomplete"}
REDIS_SESSION_TTL = 7 * 24 * 3600     # re-point sessions for 7 days
MAX_API = "https://botapi.max.ru"

EXEC = os.environ.get("REO_EXEC", "")  # "" on server; ssh-wrapped prefix for local
LEDGER = os.environ.get("REO_LEDGER", os.path.join(HERE, "job_ledger.sqlite"))
LOG = os.environ.get("REO_LOG", os.path.join(HERE, "reoutreach_job.log"))


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _run(cmd: str, inp: bytes = None, timeout: int = 120) -> str:
    proc = subprocess.run(shlex.split(cmd), input=inp,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"cmd failed rc={proc.returncode}: {proc.stderr.decode('utf-8','replace')[:300]}")
    return proc.stdout.decode("utf-8", "replace")


def _psql(sql: str) -> str:
    return _run(f"{EXEC} docker exec -i mgp-postgres-1 psql -U mgp -d mgp -t -A", inp=sql.encode("utf-8"))


def fetch_bot_token() -> str:
    out = _run(f"{EXEC} docker exec mgp-postgres-1 psql -U mgp -d mgp -t -A -c "
               f"\"SELECT runtime_metadata->'channels'->'max'->>'bot_token' FROM assistants WHERE id='{ASSISTANT_ID}'\"")
    tok = out.strip()
    if not tok:
        raise RuntimeError("no bot_token for AnyTour")
    return tok


def collect(silence_hours: int, lookback_days: int) -> list:
    with open(SQL_FILE, encoding="utf-8") as fh:
        sql = (fh.read().replace("{SILENCE_HOURS}", str(int(silence_hours)))
                        .replace("{LOOKBACK_DAYS}", str(int(lookback_days))))
    recs = []
    for ln in _psql(sql).splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            recs.append(json.loads(ln))
    return recs


def send_window_ok(departure) -> bool:
    off = TZ_OFFSET.get(departure, 3)
    local_h = (datetime.now(timezone.utc).hour + off) % 24
    return SEND_FROM <= local_h < SEND_TO


def generate(rec: dict, bucket: str):
    """Return (message, used_llm_bool). Always a valid, send-ready message."""
    if bucket in LLM_BUCKETS:
        msg, fallback, _ = RL.generate_llm(rec)
        return msg, (not fallback)
    brief = R.extract_brief(rec)
    return R.render_message(brief, bucket), False


def max_send(token: str, chat_id: str, text: str) -> dict:
    url = f"{MAX_API}/messages?chat_id={chat_id}"
    body = json.dumps({"text": text, "format": "markdown"}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def persist_history(conv_id: str, text: str):
    sql = (f"INSERT INTO messages (conversation_id, role, content, created_at) "
           f"VALUES ('{conv_id}', 'assistant', $RO${text}$RO$, now()); "
           f"UPDATE conversations SET last_active_at = now() WHERE id = '{conv_id}';")
    _psql(sql)


def redis_repoint(uid: str, session_id: str):
    """Re-point the MAX session so the client's reply (even days later) maps to the
    SAME dialogue with full memory. Bridge Redis = mgp-redis-1 db1, password-auth."""
    pw = _run(f"{EXEC} docker exec mgp-max_bridge-1 sh -c 'echo $REDIS_PASSWORD'").strip()
    key = f"max:user:{uid}:tenant:{SLUG}:session"
    _run(f"{EXEC} docker exec mgp-redis-1 redis-cli -a {pw} -n 1 SET {key} {session_id} EX {REDIS_SESSION_TTL}")


def _ledger():
    c = sqlite3.connect(LEDGER)
    c.execute("CREATE TABLE IF NOT EXISTS done(uid TEXT PRIMARY KEY, status TEXT, at REAL, conv_id TEXT, msg TEXT)")
    c.commit()
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--silence-hours", type=int, default=20)
    ap.add_argument("--lookback-days", type=int, default=7)
    ap.add_argument("--max-send", type=int, default=25, help="cap sends per run (ramp safely)")
    ap.add_argument("--throttle-sec", type=float, default=3.0)
    ap.add_argument("--send", action="store_true", help="actually send (else dry-run)")
    ap.add_argument("--ignore-window", action="store_true", help="bypass send-window (testing)")
    ap.add_argument("--samples", type=int, default=6)
    args = ap.parse_args()

    recs = collect(args.silence_hours, args.lookback_days)
    led = _ledger()
    done = {r[0] for r in led.execute("SELECT uid FROM done").fetchall()}
    m = Counter()
    samples = []
    sent = 0
    token = None

    for rec in recs:
        uid = str(rec.get("uid") or "")
        m["candidates"] += 1
        if uid in done:
            m["skip_already_done"] += 1
            continue
        if rec.get("optout") or rec.get("decline"):
            m["optout"] += 1
            if args.send:
                led.execute("INSERT OR REPLACE INTO done VALUES(?,?,?,?,?)",
                            (uid, "optout", time.time(), rec.get("id"), None))
                led.commit()
            continue
        bucket, reason = R.classify(rec)
        if bucket == "skip":
            m[f"skip_{reason}"] += 1
            continue
        if not args.ignore_window and not send_window_ok((rec.get("search_meta") or {}).get("departure")):
            m["skip_window"] += 1
            continue
        m["eligible"] += 1
        is_llm = bucket in LLM_BUCKETS
        m["llm" if is_llm else "template"] += 1
        # Bound LLM/generation cost: only generate for samples (dry-run) or up to
        # the send cap (live). Counting above is by bucket, no model call.
        need_msg = (len(samples) < args.samples) or (args.send and sent < args.max_send)
        if not need_msg:
            if args.send:
                m["capped"] += 1
            continue
        msg, used_llm = generate(rec, bucket)
        ok, verrs = R.validate(msg, R.extract_brief(rec), forbid_stale_price=not is_llm)
        if not ok or not msg:
            m["invalid"] += 1
            log(f"INVALID uid={uid} bucket={bucket} errs={verrs} msg={msg!r}")
            continue
        if len(samples) < args.samples:
            samples.append({"uid": uid, "bucket": bucket, "llm": used_llm,
                            "src": (rec.get("utext") or "")[:90], "msg": msg})
        if not args.send:
            continue
        if sent >= args.max_send:
            m["capped"] += 1
            continue
        chat_id = rec.get("chat_id") or uid
        try:
            if token is None:
                token = fetch_bot_token()
            max_send(token, str(chat_id), msg)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            # bot blocked / dialog suspended / chat denied / not found => permanent,
            # never retry (mark undeliverable). MAX uses denied/suspended wording.
            undeliverable = any(mk in body.lower() for mk in
                                ("block", "forbidden", "denied", "suspend", "not found", "chat.not"))
            if e.code in (400, 403, 404) and undeliverable:
                led.execute("INSERT OR REPLACE INTO done VALUES(?,?,?,?,?)",
                            (uid, "undeliverable", time.time(), rec.get("id"), None))
                led.commit()
                m["undeliverable"] += 1
            else:
                m["send_error"] += 1
                log(f"SEND ERROR uid={uid} http={e.code} {body}")
            continue
        except Exception as e:  # noqa: BLE001
            m["send_error"] += 1
            log(f"SEND ERROR uid={uid} {e}")
            continue
        # success: persist into history + re-point session + record one-shot
        try:
            persist_history(rec["id"], msg)
            redis_repoint(uid, rec["session_id"])
        except Exception as e:  # noqa: BLE001
            log(f"POST-SEND WARN uid={uid} (sent ok, persist/redis failed): {e}")
        led.execute("INSERT OR REPLACE INTO done VALUES(?,?,?,?,?)",
                    (uid, "sent", time.time(), rec.get("id"), msg))
        led.commit()
        sent += 1
        m["sent"] += 1
        time.sleep(args.throttle_sec)

    summary = {"mode": "SEND" if args.send else "DRY-RUN", "params": vars(args),
               "metrics": dict(m), "sent": sent}
    log("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    print("\n=== SAMPLE MESSAGES ===")
    for s in samples:
        print(f"  [{s['bucket']}{' LLM' if s['llm'] else ' tpl'}] {s['src']}\n   -> {s['msg']}\n")
    with open(os.path.join(HERE, "job_report.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "samples": samples}, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
