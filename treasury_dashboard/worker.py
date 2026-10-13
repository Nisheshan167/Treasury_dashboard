"""Optional always-on collector. Run on an always-on host, not inside GitHub cron."""
import time
from concurrent.futures import ThreadPoolExecutor
from treasury.config import Settings
from treasury.store import Store
from treasury.collector import collect, collect_quotes

if __name__ == "__main__":
    settings=Settings.load()
    store=Store(settings.database_url)
    if not store.durable:
        raise SystemExit("Set a persistent PostgreSQL DATABASE_URL before running the worker.")
    with ThreadPoolExecutor(max_workers=1) as pool:
        research_job = None
        while True:
            try:
                # Independent quote capture continues during slow AI/calendar calls.
                collect_quotes(settings,store)
                if research_job is None or research_job.done():
                    if research_job and research_job.exception():
                        print("Research cycle failed:",type(research_job.exception()).__name__,flush=True)
                    research_job = pool.submit(collect,settings,store)
            except Exception as error:
                print("Collector cycle failed:",type(error).__name__,flush=True)
            time.sleep(settings.quote_interval_seconds)
