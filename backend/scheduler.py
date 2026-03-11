from __future__ import annotations

"""
APScheduler integration for the ЛК backend.

Periodic jobs:
  1. sync_mgp   — pull new data from remote MGP bot (every 5 min)
  2. daily_stats — aggregate daily analytics (daily at 00:30 UTC)
  3. dialog_sender — deliver MGP -> LK runtime snapshots

Integrates with Flask app via `init_scheduler(app)`.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("mgp_bot.scheduler")

_scheduler: BackgroundScheduler | None = None


def _job_sync_mgp():
    """Pull new conversations/messages/tour_searches from all sync-enabled assistants."""
    try:
        from sync_mgp import run_sync_all
        run_sync_all()
    except Exception:
        logger.exception("sync_mgp job failed")


def _job_daily_stats():
    """Aggregate daily statistics into daily_stats table."""
    try:
        from database import get_db
        from models import Conversation, Message, TourSearch, DailyStat
        from sqlalchemy import func, distinct, text as sa_text
        from datetime import datetime, timedelta, timezone

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        with get_db() as db:
            if db is None:
                return

            existing = db.query(DailyStat).filter(DailyStat.date == yesterday).first()
            if existing:
                logger.info("DailyStat for %s already exists, skipping", yesterday)
                return

            day_start = f"{yesterday}T00:00:00+00:00"
            day_end = f"{yesterday}T23:59:59.999999+00:00"

            conversations_total = db.query(func.count(Conversation.id)).filter(
                Conversation.started_at >= day_start,
                Conversation.started_at <= day_end,
            ).scalar() or 0

            messages_total = db.query(func.count(Message.id)).filter(
                Message.created_at >= day_start,
                Message.created_at <= day_end,
            ).scalar() or 0

            searches_total = db.query(func.count(TourSearch.id)).filter(
                TourSearch.created_at >= day_start,
                TourSearch.created_at <= day_end,
            ).scalar() or 0

            tours_shown = db.query(func.coalesce(func.sum(Conversation.tour_cards_shown), 0)).filter(
                Conversation.started_at >= day_start,
                Conversation.started_at <= day_end,
            ).scalar() or 0

            avg_response = db.query(func.coalesce(func.avg(Message.latency_ms), 0)).filter(
                Message.created_at >= day_start,
                Message.created_at <= day_end,
                Message.role == "assistant",
                Message.latency_ms.isnot(None),
            ).scalar() or 0

            tokens_total = db.query(
                func.coalesce(func.sum(Message.tokens_prompt), 0) +
                func.coalesce(func.sum(Message.tokens_completion), 0)
            ).filter(
                Message.created_at >= day_start,
                Message.created_at <= day_end,
            ).scalar() or 0

            unique_ips = db.query(func.count(distinct(Conversation.ip_address))).filter(
                Conversation.started_at >= day_start,
                Conversation.started_at <= day_end,
            ).scalar() or 0

            stat = DailyStat(
                date=yesterday,
                conversations_total=conversations_total,
                messages_total=messages_total,
                searches_total=searches_total,
                tours_shown=int(tours_shown),
                avg_response_ms=int(avg_response),
                tokens_total=int(tokens_total),
                unique_ips=unique_ips,
            )
            db.add(stat)

        logger.info("DailyStat aggregated for %s: %d convs, %d msgs",
                     yesterday, conversations_total, messages_total)

    except Exception:
        logger.exception("daily_stats job failed")


def _job_dialog_sender():
    """Deliver pending runtime event snapshots to LK."""
    try:
        from dialog_sender import run_dialog_sender_once
        processed = run_dialog_sender_once()
        if processed:
            logger.info("dialog_sender processed=%d", processed)
    except Exception:
        logger.exception("dialog_sender job failed")


def _is_main_process() -> bool:
    """With Gunicorn pre-fork, only the FIRST worker (or the dev server) should run the scheduler.
    Uses a file lock so that only one process wins."""
    import fcntl
    import os
    lock_path = os.path.join(os.path.dirname(__file__), "..", "logs", ".scheduler.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        _is_main_process._fd = open(lock_path, "w")
        fcntl.flock(_is_main_process._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, BlockingIOError):
        return False


def init_scheduler(app=None):
    """Start the background scheduler. Call once at app startup.
    With Gunicorn multi-worker, only one process acquires the lock."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running")
        return _scheduler

    if not _is_main_process():
        logger.info("Scheduler skipped — another worker owns the lock")
        return None

    import os
    from config import settings
    sync_enabled = os.environ.get("SYNC_MGP_ENABLED", "true").lower() in ("1", "true", "yes")
    sync_interval = int(os.environ.get("SYNC_MGP_INTERVAL_MINUTES", "5"))

    _scheduler = BackgroundScheduler(daemon=True)

    if sync_enabled:
        _scheduler.add_job(
            _job_sync_mgp,
            trigger=IntervalTrigger(minutes=sync_interval),
            id="sync_mgp",
            name="Sync from MGP bot",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("MGP sync job scheduled: every %d min", sync_interval)
    else:
        logger.info("MGP sync disabled (SYNC_MGP_ENABLED=false)")

    _scheduler.add_job(
        _job_daily_stats,
        trigger=CronTrigger(hour=0, minute=30),
        id="daily_stats",
        name="Aggregate daily stats",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Daily stats job scheduled: 00:30 UTC")

    if settings.runtime_dialog_sender_enabled:
        _scheduler.add_job(
            _job_dialog_sender,
            trigger=IntervalTrigger(seconds=max(2, int(settings.runtime_dialog_sender_interval_seconds))),
            id="dialog_sender",
            name="Deliver runtime event snapshots",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Dialog sender job scheduled: every %d sec",
            max(2, int(settings.runtime_dialog_sender_interval_seconds)),
        )
    else:
        logger.info("Dialog sender disabled (RUNTIME_DIALOG_SENDER_ENABLED=false)")

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
