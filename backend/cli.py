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
import re
import sys

from config import settings
from database import init_db, get_db
from models import Company, Assistant, User
from auth import hash_password


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text)[:64]


def create_user(args: argparse.Namespace) -> None:
    if not init_db(settings.database_url):
        print("ERROR: Cannot connect to PostgreSQL")
        sys.exit(1)

    with get_db() as db:
        if db is None:
            print("ERROR: DB session unavailable")
            sys.exit(1)

        existing = db.query(User).filter_by(email=args.email).first()
        if existing:
            print(f"User {args.email} already exists")
            sys.exit(1)

        company = db.query(Company).filter_by(name=args.company).first()
        if not company:
            company = Company(name=args.company, slug=slugify(args.company))
            db.add(company)
            db.flush()
            print(f"Created company: {company.name} (id={company.id})")

        assistant = db.query(Assistant).filter_by(company_id=company.id).first()
        if not assistant:
            assistant = Assistant(
                company_id=company.id,
                name=f"{args.company} AI Assistant",
                tourvisor_login=settings.tourvisor_auth_login,
                tourvisor_pass=settings.tourvisor_auth_pass,
                llm_provider=settings.llm_provider,
                llm_api_key=settings.openai_api_key or settings.yandex_api_key,
                llm_model=(settings.openai_model
                           if settings.llm_provider == "openai"
                           else settings.yandex_model),
            )
            db.add(assistant)
            db.flush()
            print(f"Created assistant: {assistant.name} (id={assistant.id})")

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


def main() -> None:
    parser = argparse.ArgumentParser(description="AIMPACT Dashboard CLI")
    sub = parser.add_subparsers(dest="command")

    cu = sub.add_parser("create-user", help="Create company + user + assistant")
    cu.add_argument("--email", required=True)
    cu.add_argument("--password", required=True)
    cu.add_argument("--company", required=True, help="Company name")
    cu.add_argument("--name", default=None, help="User display name")
    cu.add_argument("--role", default="admin", choices=["admin", "viewer"])

    args = parser.parse_args()
    if args.command == "create-user":
        create_user(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
