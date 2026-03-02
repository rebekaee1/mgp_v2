#!/usr/bin/env python3
"""
Auto-seed: creates initial Company + Admin User + Assistant on first deploy.

Reads configuration from environment variables:
  SEED_ADMIN_EMAIL     (default: admin@company.com)
  SEED_ADMIN_PASSWORD  (auto-generated if not set)
  SEED_COMPANY_NAME    (default: My Company)
  SEED_COMPANY_SLUG    (default: my-company)

Usage: python seed_data.py  (called by entrypoint.sh when companies table is empty)
"""

import os
import secrets
import logging

from config import settings
from database import init_db, get_db

logger = logging.getLogger("mgp_bot")


def seed():
    if not init_db(settings.database_url):
        print("ERROR: Cannot connect to database")
        return False

    from models import Company, User, Assistant
    from auth import hash_password

    with get_db() as db:
        if db is None:
            print("ERROR: DB session unavailable")
            return False

        if db.query(Company).count() > 0:
            print("Seed skipped: companies table is not empty")
            return True

        email = os.getenv("SEED_ADMIN_EMAIL", "admin@company.com")
        password = os.getenv("SEED_ADMIN_PASSWORD", "")
        company_name = os.getenv("SEED_COMPANY_NAME", "My Company")
        company_slug = os.getenv("SEED_COMPANY_SLUG", "my-company")

        if not password:
            password = secrets.token_urlsafe(16)
            print(f"\n{'='*50}")
            print(f"  AUTO-GENERATED ADMIN PASSWORD: {password}")
            print(f"  Email: {email}")
            print(f"  SAVE THIS — it won't be shown again!")
            print(f"{'='*50}\n")

        company = Company(name=company_name, slug=company_slug)
        db.add(company)
        db.flush()

        user = User(
            company_id=company.id,
            email=email,
            password_hash=hash_password(password),
            name="Admin",
            role="admin",
        )
        db.add(user)

        assistant = Assistant(
            company_id=company.id,
            name=f"{company_name} AI Assistant",
            tourvisor_login=os.getenv("TOURVISOR_AUTH_LOGIN", ""),
            tourvisor_pass=os.getenv("TOURVISOR_AUTH_PASS", ""),
            llm_provider=settings.llm_provider,
            llm_api_key=settings.openai_api_key or settings.yandex_api_key,
            llm_model=settings.openai_model if settings.llm_provider == "openai" else settings.yandex_model,
            is_active=True,
        )
        db.add(assistant)
        db.flush()

        print(f"Seed complete:")
        print(f"  Company: {company.name} (slug={company.slug}, id={company.id})")
        print(f"  Admin:   {user.email} (id={user.id})")
        print(f"  Assistant: {assistant.name} (id={assistant.id})")

        return True


if __name__ == "__main__":
    seed()
