#!/usr/bin/env python3
"""
CLI utility to bootstrap the first company + user + assistant.

Usage:
    python cli.py create-user \
        --email admin@company.ru \
        --password secret \
        --company "My Company" \
        --name "Admin" \
        --role admin
"""

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from config import settings
from database import init_db, get_db
from models import Company, Assistant, User
from auth import hash_password


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text)[:64]


def _read_optional_text(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    try:
        return Path(path_value).read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        print(f"ERROR: cannot read file {path_value}: {exc}")
        sys.exit(1)


def _build_widget_config(args: argparse.Namespace) -> Optional[Dict[str, str]]:
    widget = {
        "title": args.widget_title,
        "subtitle": args.widget_subtitle,
        "primary_color": args.widget_primary_color,
        "position": args.widget_position,
        "logo_url": args.widget_logo_url,
    }
    widget = {k: v for k, v in widget.items() if v}
    return widget or None


def _parse_uuid(value: Optional[str], *, field_name: str) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value).strip())
    except ValueError:
        print(f"ERROR: invalid {field_name}: {value}")
        sys.exit(1)


def _parse_datetime(value: Optional[str], *, field_name: str) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        print(f"ERROR: invalid {field_name}: {value}. Use ISO-8601, e.g. 2026-03-16T10:00:00+00:00")
        sys.exit(1)


def _resolve_provisioning_payload(args: argparse.Namespace) -> Dict[str, Any]:
    llm_provider = args.llm_provider or settings.llm_provider
    llm_model = args.llm_model or (
        settings.openai_model if llm_provider == "openai" else settings.yandex_model
    )
    system_prompt = _read_optional_text(args.system_prompt_file)
    faq_content = _read_optional_text(args.faq_file)

    return {
        "company": {
            "name": args.company,
            "slug": args.slug or slugify(args.company),
            "logo_url": args.company_logo_url or None,
        },
        "user": {
            "email": args.email,
            "name": args.name or args.email.split("@")[0],
            "role": args.role,
        },
        "assistant": {
            "name": args.assistant_name or f"{args.company} AI Assistant",
            "allowed_domains": args.allowed_domains or None,
            "bot_server_url": args.bot_server_url or None,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "tourvisor_login_configured": bool(args.tourvisor_login or settings.tourvisor_auth_login),
            "tourvisor_pass_configured": bool(args.tourvisor_pass or settings.tourvisor_auth_pass),
            "system_prompt_loaded": bool(system_prompt),
            "faq_loaded": bool(faq_content),
            "widget_config": _build_widget_config(args),
        },
    }


def _print_dry_run_summary(payload: Dict[str, Any], existing_user, company, assistant) -> None:
    summary = {
        "mode": "dry-run",
        "db_write": False,
        "would_fail_on_real_run": bool(existing_user),
        "existing": {
            "user_with_email": bool(existing_user),
            "company": bool(company),
            "assistant_for_company": bool(assistant),
        },
        "resolved_payload": payload,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Dry-run completed. No DB changes were written.")


def create_user(args: argparse.Namespace) -> None:
    if not init_db(settings.database_url):
        print("ERROR: Cannot connect to PostgreSQL")
        sys.exit(1)

    with get_db() as db:
        if db is None:
            print("ERROR: DB session unavailable")
            sys.exit(1)

        existing = db.query(User).filter_by(email=args.email).first()
        payload = _resolve_provisioning_payload(args)
        resolved_company = payload["company"]
        company_slug = resolved_company["slug"]
        company = (
            db.query(Company)
            .filter((Company.name == args.company) | (Company.slug == company_slug))
            .first()
        )
        assistant = db.query(Assistant).filter_by(company_id=company.id).first() if company else None

        if getattr(args, "dry_run", False):
            _print_dry_run_summary(payload, existing, company, assistant)
            db.rollback()
            return

        if existing:
            print(f"User {args.email} already exists")
            sys.exit(1)

        if not company:
            company = Company(
                name=args.company,
                slug=company_slug,
                logo_url=args.company_logo_url or None,
            )
            db.add(company)
            db.flush()
            print(f"Created company: {company.name} (id={company.id})")
        elif args.company_logo_url:
            company.logo_url = args.company_logo_url

        assistant = db.query(Assistant).filter_by(company_id=company.id).first()
        if not assistant:
            assistant = Assistant(
                company_id=company.id,
                name=args.assistant_name or f"{args.company} AI Assistant",
                tourvisor_login=args.tourvisor_login or settings.tourvisor_auth_login,
                tourvisor_pass=args.tourvisor_pass or settings.tourvisor_auth_pass,
                llm_provider=args.llm_provider or settings.llm_provider,
                llm_api_key=args.llm_api_key or settings.openai_api_key or settings.yandex_api_key,
                llm_model=payload["assistant"]["llm_model"],
                system_prompt=_read_optional_text(args.system_prompt_file),
                faq_content=_read_optional_text(args.faq_file),
                widget_config=payload["assistant"]["widget_config"],
                bot_server_url=args.bot_server_url or None,
                allowed_domains=args.allowed_domains or None,
            )
            db.add(assistant)
            db.flush()
            print(f"Created assistant: {assistant.name} (id={assistant.id})")
        else:
            updated = False
            field_updates = {
                "name": args.assistant_name,
                "tourvisor_login": args.tourvisor_login,
                "tourvisor_pass": args.tourvisor_pass,
                "llm_provider": args.llm_provider,
                "llm_api_key": args.llm_api_key,
                "llm_model": args.llm_model,
                "bot_server_url": args.bot_server_url,
                "allowed_domains": args.allowed_domains,
            }
            for field, value in field_updates.items():
                if value:
                    setattr(assistant, field, value)
                    updated = True
            system_prompt = _read_optional_text(args.system_prompt_file)
            faq_content = _read_optional_text(args.faq_file)
            if system_prompt:
                assistant.system_prompt = system_prompt
                updated = True
            if faq_content:
                assistant.faq_content = faq_content
                updated = True
            widget_config = _build_widget_config(args)
            if widget_config:
                assistant.widget_config = widget_config
                updated = True
            if updated:
                print(f"Updated assistant: {assistant.name} (id={assistant.id})")

        user = User(
            company_id=company.id,
            email=args.email,
            password_hash=hash_password(args.password),
            name=args.name or args.email.split("@")[0],
            role=args.role,
        )
        db.add(user)
        db.flush()
        print(f"Created user: {user.email} role={user.role} (id={user.id})")

    print("Done.")


def replay_outbox(args: argparse.Namespace) -> None:
    from dialog_sender import replay_conversation_snapshots, run_dialog_sender_once

    if not init_db(settings.database_url):
        print("ERROR: Cannot connect to PostgreSQL")
        sys.exit(1)

    assistant_id = _parse_uuid(args.assistant_id, field_name="assistant_id")
    conversation_id = _parse_uuid(args.conversation_id, field_name="conversation_id")
    occurred_from = _parse_datetime(args.from_ts, field_name="from")
    occurred_to = _parse_datetime(args.to_ts, field_name="to")

    if not any([assistant_id, conversation_id, occurred_from, occurred_to]):
        print("ERROR: specify at least one filter: --assistant-id, --conversation-id, --from, --to")
        sys.exit(1)

    if occurred_from and occurred_to and occurred_from > occurred_to:
        print("ERROR: --from must be <= --to")
        sys.exit(1)

    with get_db() as db:
        if db is None:
            print("ERROR: DB session unavailable")
            sys.exit(1)

        result = replay_conversation_snapshots(
            db,
            assistant_id=assistant_id,
            conversation_id=conversation_id,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            limit=max(1, int(args.limit)),
        )

    delivered_now = 0
    if getattr(args, "deliver_now", False):
        delivered_now = run_dialog_sender_once(limit=max(1, int(args.limit)))

    summary = {
        "mode": "replay-outbox",
        **result,
        "deliver_now": bool(getattr(args, "deliver_now", False)),
        "delivered_now": delivered_now,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Replay completed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AIMPACT Dashboard CLI")
    sub = parser.add_subparsers(dest="command")

    cu = sub.add_parser("create-user", help="Create company + user + assistant")
    cu.add_argument("--email", required=True)
    cu.add_argument("--password", required=True)
    cu.add_argument("--company", required=True, help="Company name")
    cu.add_argument("--slug", default=None, help="Company slug")
    cu.add_argument("--name", default=None, help="User display name")
    cu.add_argument("--role", default="admin", choices=["admin", "viewer"])
    cu.add_argument("--company-logo-url", default=None)
    cu.add_argument("--assistant-name", default=None)
    cu.add_argument("--allowed-domains", default=None)
    cu.add_argument("--bot-server-url", default=None)
    cu.add_argument("--llm-provider", default=None, choices=["openai", "yandex"])
    cu.add_argument("--llm-api-key", default=None)
    cu.add_argument("--llm-model", default=None)
    cu.add_argument("--tourvisor-login", default=None)
    cu.add_argument("--tourvisor-pass", default=None)
    cu.add_argument("--system-prompt-file", default=None)
    cu.add_argument("--faq-file", default=None)
    cu.add_argument("--widget-title", default=None)
    cu.add_argument("--widget-subtitle", default=None)
    cu.add_argument("--widget-primary-color", default=None)
    cu.add_argument("--widget-position", default=None)
    cu.add_argument("--widget-logo-url", default=None)
    cu.add_argument("--dry-run", action="store_true", help="Validate provisioning without DB writes")

    pt = sub.add_parser("provision-tenant", help="Provision tenant runtime from template defaults")
    for action in cu._actions[1:]:
        if not any(existing.dest == action.dest for existing in pt._actions):
            pt._add_action(action)

    ro = sub.add_parser("replay-outbox", help="Queue replay/backfill snapshots into runtime_event_outbox")
    ro.add_argument("--assistant-id", dest="assistant_id", default=None)
    ro.add_argument("--conversation-id", dest="conversation_id", default=None)
    ro.add_argument("--from", dest="from_ts", default=None, help="ISO-8601 lower bound for conversation activity time")
    ro.add_argument("--to", dest="to_ts", default=None, help="ISO-8601 upper bound for conversation activity time")
    ro.add_argument("--limit", type=int, default=500)
    ro.add_argument("--deliver-now", action="store_true", help="Immediately run sender after queueing replay events")

    args = parser.parse_args()
    if args.command in {"create-user", "provision-tenant"}:
        create_user(args)
    elif args.command == "replay-outbox":
        replay_outbox(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
