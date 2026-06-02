#!/usr/bin/env python3
"""Compare template vs LLM-polished re-outreach on REAL prod dialogues.

Pulls candidates (AnyTour), groups by bucket (focus 6/7 where text-only params
matter), generates BOTH the deterministic template and the LLM message, validates
each, and prints a side-by-side report + saves llm_report.json. NO sending.

Creds: /tmp/mgp_e2e_creds.env (prod, funded) overrides workspace .env.
PSQL_CMD env: how to run psql (defaults to ssh-wrapped, like gen_report).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from dotenv import load_dotenv

# prod creds (funded) override local
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
_CREDS = os.environ.get("MGP_E2E_CREDS", "/tmp/mgp_e2e_creds.env")
if os.path.exists(_CREDS):
    load_dotenv(_CREDS, override=True)

import reoutreach_lib as R          # noqa: E402
import reoutreach_llm as RL         # noqa: E402
from gen_report import collect      # noqa: E402

PER_BUCKET = int(os.environ.get("PER_BUCKET", "3"))
# how many dialogues per bucket; weight 6/7 higher
WEIGHTS = {"6_thin": 4, "7_incomplete": 4, "4_results": 2, "5_noresults": 2, "1_engaged": 2}


def main():
    recs = collect(silence_hours=24, lookback_days=12)
    by_bucket = defaultdict(list)
    for r in recs:
        b, reason = R.classify(r)
        if b == "skip":
            continue
        by_bucket[b].append(r)

    print(f"\n=== LLM-POLISH vs TEMPLATE — real AnyTour dialogues ===")
    print(f"pool by bucket: { {k: len(v) for k, v in sorted(by_bucket.items())} }\n")

    out = []
    stats = {"total": 0, "llm_ok": 0, "fallback": 0}
    for bucket in sorted(by_bucket):
        take = WEIGHTS.get(bucket, PER_BUCKET)
        sample = by_bucket[bucket][:take]
        print(f"\n{'='*78}\nBUCKET {bucket}  (showing {len(sample)})\n{'='*78}")
        for r in sample:
            brief = R.extract_brief(r)
            tpl = R.render_message(brief, bucket)
            llm_msg, fallback, errs = RL.generate_llm(r)
            stats["total"] += 1
            stats["fallback" if fallback else "llm_ok"] += 1
            src = (r.get("utext") or "")[:120]
            print(f"\n  SRC: {src}")
            print(f"  TEMPLATE: {tpl}")
            print(f"  LLM     : {llm_msg}" + ("   [FALLBACK→template]" if fallback else ""))
            if errs:
                print(f"  (llm errs: {errs})")
            out.append({"bucket": bucket, "src": src, "template": tpl,
                        "llm": llm_msg, "fallback": fallback, "errs": errs})

    print(f"\n\n=== SUMMARY ===")
    print(f"generated: {stats['total']} | LLM used: {stats['llm_ok']} | fell back to template: {stats['fallback']}")
    with open(os.path.join(os.path.dirname(__file__), "llm_report.json"), "w", encoding="utf-8") as fh:
        json.dump({"stats": stats, "items": out}, fh, ensure_ascii=False, indent=2)
    print("saved -> llm_report.json")


if __name__ == "__main__":
    main()
