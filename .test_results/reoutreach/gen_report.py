#!/usr/bin/env python3
"""Dry-run re-outreach report: select candidates -> classify -> generate -> review.

NO sending. Reads prod via PSQL_CMD (default: ssh-wrapped psql for local use).
Outputs: console summary + per-bucket message samples + report.json.

Env:
  PSQL_CMD  shell cmd running psql -t -A from stdin
            (default: ssh-wrapped for local testing)
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from collections import Counter

import reoutreach_lib as R

HERE = os.path.dirname(os.path.abspath(__file__))
SQL = os.path.join(HERE, "select_candidates.sql")
DEFAULT_PSQL = ("ssh -o ConnectTimeout=25 -o ServerAliveInterval=10 mgp-prod "
                "sudo docker exec -i mgp-postgres-1 psql -U mgp -d mgp -t -A")


def collect(silence_hours: int, lookback_days: int) -> list:
    with open(SQL, encoding="utf-8") as fh:
        sql = (fh.read().replace("{SILENCE_HOURS}", str(int(silence_hours)))
                        .replace("{LOOKBACK_DAYS}", str(int(lookback_days))))
    cmd = os.environ.get("PSQL_CMD", DEFAULT_PSQL)
    proc = subprocess.run(shlex.split(cmd), input=sql.encode(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:500])
    out = []
    for ln in proc.stdout.decode("utf-8", "replace").splitlines():
        ln = ln.strip()
        if ln.startswith("{"):
            out.append(json.loads(ln))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--silence-hours", type=int, default=24)
    ap.add_argument("--lookback-days", type=int, default=10)
    ap.add_argument("--samples", type=int, default=3, help="messages to show per bucket")
    args = ap.parse_args()

    recs = collect(args.silence_hours, args.lookback_days)
    buckets = Counter()
    skips = Counter()
    invalid = []
    per_bucket_examples: dict[str, list] = {}
    sendable = 0

    for r in recs:
        bucket, reason = R.classify(r)
        if bucket == "skip":
            skips[reason] += 1
            continue
        buckets[bucket] += 1
        brief = R.extract_brief(r)
        msg = R.render_message(brief, bucket)
        ok, errs = R.validate(msg, brief)
        if not ok:
            invalid.append({"id": r.get("id"), "bucket": bucket, "errs": errs, "msg": msg})
            continue
        sendable += 1
        per_bucket_examples.setdefault(bucket, [])
        if len(per_bucket_examples[bucket]) < args.samples:
            per_bucket_examples[bucket].append({"src": (r.get("utext") or "")[:90], "msg": msg})

    print(f"\n=== RE-OUTREACH DRY-RUN (silence>={args.silence_hours}h, lookback {args.lookback_days}d) ===")
    print(f"candidates scanned : {len(recs)}")
    print(f"WRITE (sendable)   : {sendable}")
    print(f"by bucket          : {dict(sorted(buckets.items()))}")
    print(f"SKIPPED            : {dict(sorted(skips.items()))}  (total {sum(skips.values())})")
    if invalid:
        print(f"INVALID (need fix) : {len(invalid)} -> {invalid[:3]}")

    print("\n=== SAMPLE GENERATED MESSAGES ===")
    for bucket in sorted(per_bucket_examples):
        print(f"\n--- {bucket} ---")
        for ex in per_bucket_examples[bucket]:
            print(f"  src: {ex['src']}")
            print(f"  ->  {ex['msg']}\n")

    report = {
        "params": {"silence_hours": args.silence_hours, "lookback_days": args.lookback_days},
        "scanned": len(recs), "sendable": sendable,
        "buckets": dict(buckets), "skips": dict(skips),
        "invalid_count": len(invalid), "invalid": invalid[:20],
        "examples": per_bucket_examples,
    }
    with open(os.path.join(HERE, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"\nfull report -> {os.path.join(HERE, 'report.json')}")


if __name__ == "__main__":
    main()
