"""APScheduler-based async task scheduler."""

import asyncio
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from nocfo.scheduler.jobs import register_jobs

logger = structlog.get_logger()

HEARTBEAT_PATH = Path("data/scheduler_heartbeat")


class Scheduler:
    """Manages scheduled bookkeeping jobs."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            }
        )
        self._running = False

    def setup(self) -> None:
        """Register all scheduled jobs."""
        register_jobs(self._scheduler)
        logger.info("scheduler_jobs_registered", job_count=len(self._scheduler.get_jobs()))

    async def start(self) -> None:
        """Start the scheduler."""
        self.setup()
        self._scheduler.start()
        self._running = True
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        logger.info("scheduler_started")

        # Heartbeat loop
        try:
            while self._running:
                self._write_heartbeat()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass
        finally:
            self._scheduler.shutdown(wait=True)
            logger.info("scheduler_stopped")

    def stop(self) -> None:
        """Signal the scheduler to stop."""
        self._running = False

    def list_jobs(self) -> list[dict]:
        """List all registered jobs with their schedules."""
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else "paused",
                    "trigger": str(job.trigger),
                }
            )
        return jobs

    def _write_heartbeat(self) -> None:
        """Write heartbeat file for health monitoring."""
        import time

        HEARTBEAT_PATH.write_text(str(time.time()))
