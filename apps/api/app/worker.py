"""Background worker: `python -m app.worker [--queues content,maintenance] [--once]`.

Run one or more next to the API (any number is safe). SIGTERM stops after the current unit of
work and hands the job back to the queue; a second signal exits at once (the job is then
recovered by another worker's reaper once its heartbeat goes stale).
"""

import argparse
import logging
import signal
import sys

from app import models  # noqa: F401  (registers every table)
from app.jobs.worker import Worker, healthy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker", description=__doc__.splitlines()[0])
    parser.add_argument("--queues", help="comma-separated queues to serve (default: all)")
    parser.add_argument("--once", action="store_true", help="run every due job, then exit")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 if a worker touched EDU_JOBS_HEALTH_FILE recently")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return 0 if healthy() else 1

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    queues = [q.strip() for q in args.queues.split(",") if q.strip()] if args.queues else None
    worker = Worker(queues)

    def on_signal(signum, _frame):
        if worker.stopping:
            raise SystemExit(1)
        logging.getLogger("eduverse.worker").info("signal %s: finishing the current step, then stopping", signum)
        worker.stop()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    if args.once:
        worker.maintain()
        worker.drain()
        return 0
    worker.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
