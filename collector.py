import argparse
import hashlib
from datetime import timedelta
from .config import Settings
from .domain import utcnow, iso, dt
from .store import Store
from .providers import daily_yields, intraday_quotes, parse_bls_schedule, parse_bea, parse_fed, get, BLS_SCHEDULES, BEA_URL, FED_URL, te_calendar
from .research import research_events, generate_outlook
from .analysis import released_since, latest_quotes, commentary


def ai_slot(store, settings, now):
    key = "ai_requests_" + now.date().isoformat()
    used = store.get("meta", key, 0)
    if used >= settings.ai_daily_request_limit:
        return False
    # Reserve before attempting the call, including failed calls in the budget.
    store.put("meta", key, used + 1)
    return True


def collect_quotes(settings, store, now=None):
    now = now or utcnow()
    if not (settings.quote_feed_url or settings.te_api_key) or not store.acquire(now, "quotes"):
        return
    try:
        if not store.due("Intraday yields", settings.quote_interval_seconds, now):
            return
        store.put("meta", "attempt_Intraday yields", iso(now))
        try:
            rows = intraday_quotes(settings, utcnow())
            if not rows:
                raise ValueError("No quote observations received")
            store.add_quotes(rows, utcnow())
            store.status("Intraday yields", True, f"{len(rows)} observations checked", utcnow())
        except Exception as error:
            store.status("Intraday yields", False, f"Update failed ({type(error).__name__}). Check quote feed availability and entitlements.", utcnow())
    finally:
        store.release("quotes")


def collect(settings, store=None, now=None):
    now = now or utcnow()
    store = store or Store(settings.database_url)
    if not store.acquire(now):
        return {"state": "Another collector is running"}
    summary = {}
    def run(name, interval, fn):
        previous = store.get("status", name, {})
        if previous.get("ok") is False and not any(code in previous.get("message", "") for code in ["HTTP 403", "HTTP 429"]):
            interval = min(interval, 120)
        if not store.due(name, interval, now):
            return
        store.put("meta", "attempt_" + name, iso(now))
        try:
            message = fn()
            store.status(name, True, message, utcnow())
            summary[name] = message
        except Exception as error:
            # Never expose exception strings: provider errors may contain secret query parameters.
            response = getattr(error, "response", None)
            code = getattr(response, "status_code", None)
            detail = f"HTTP {code}" if code else type(error).__name__
            if code == 403:
                message = "Update failed (HTTP 403). The publisher rejected this server's request. Date coverage from this source remains unavailable; existing records retained."
            elif code == 429:
                message = "Update failed (HTTP 429). Provider rate limit; regular retry interval retained."
            else:
                message = f"Update failed ({detail}). Existing records retained; retry eligible in 2 minutes."
            store.status(name, False, message, utcnow())
            summary[name] = message

    def save_quotes(rows):
        if not rows:
            raise ValueError("No quote observations received")
        store.add_quotes(rows, utcnow())
        return f"{len(rows)} observations checked"

    def save_events(rows):
        count = 0
        launch = dt(store.get("meta", "launch_at"))
        for row in rows:
            if row.get("release_at") and dt(row["release_at"]) < launch - timedelta(days=45):
                continue
            if row.get("date_only") and row["date_only"] < (launch-timedelta(days=45)).date().isoformat():
                continue
            store.merge_event(row, utcnow())
            count += 1
        if not count:
            raise ValueError("No recognized events returned")
        return f"{count} indicator dates checked"

    def research():
        if not ai_slot(store, settings, now):
            return "Daily AI request cap reached; next UTC day will reset it"
        rows, news, rejected = research_events(settings, utcnow(), store.get("meta", "launch_at"), store.all("event"))
        for row in rows:
            store.merge_event(row, utcnow())
        for item in news:
            key = hashlib.sha256((item["source"] + item["headline"]).encode()).hexdigest()
            store.put("news", key, item)
        return f"{len(rows)} sourced records checked; {rejected} invalid records skipped. Search coverage may be incomplete."

    def outlook():
        if not ai_slot(store, settings, now):
            return "Daily AI request cap reached; latest outlook retained"
        events = released_since(store.all("event"), store.get("meta", "launch_at"))[:40]
        compact = [{k: e.get(k) for k in ["id", "label", "reference", "release_at", "actual", "actual_text", "frozen_consensus", "unit", "first_actual_source", "frozen_consensus_source"]} for e in events]
        payload = dict(as_of=iso(utcnow()), launch_at=store.get("meta", "launch_at"), latest_yields=latest_quotes(store.all("quote")),
            events=compact, news=sorted(store.all("news"), key=lambda x: x["retrieved_at"], reverse=True)[:5])
        if not payload["latest_yields"]:
            return "Waiting for verified yields before generating an outlook"
        result = generate_outlook(settings, payload)
        result.update(as_of=payload["as_of"], horizon="Next 1–3 months", model=settings.openai_model,
            evidence_snapshot=payload, label="AI scenario analysis · uncalibrated")
        store.put("outlook", result["as_of"], result)
        return "A sourced scenario outlook was saved"

    try:
        run("Daily Treasury history", 6 * 3600, lambda: save_quotes(daily_yields(settings, utcnow())))
        collect_quotes(settings, store)
        for label, (slug, codes) in BLS_SCHEDULES.items():
            url = f"https://www.bls.gov/schedule/news_release/{slug}.htm"
            run(f"BLS {label} calendar", 6 * 3600, lambda url=url, codes=codes: save_events(parse_bls_schedule(get(url).text, codes, url)))
        run("BEA calendar", 6 * 3600, lambda: save_events(parse_bea(get(BEA_URL).text, utcnow())))
        run("Federal Reserve calendar", 6 * 3600, lambda: save_events(parse_fed(get(FED_URL).text)))
        if settings.te_api_key:
            run("Consensus & actuals feed", 300, lambda: save_events(te_calendar(settings, utcnow())))
        if settings.openai_api_key:
            pending = any(e.get("release_at") and now - timedelta(days=3) <= dt(e["release_at"]) <= now
                and dt(e["release_at"]) >= dt(store.get("meta", "launch_at")) and not e.get("actual_first_seen") for e in store.all("event"))
            interval = 1800 if pending else settings.research_interval_minutes * 60
            run("Release research", interval, research)
            run("Outlook analysis", 6 * 3600, outlook)
        events, quotes = store.all("event"), store.all("quote")
        for event in released_since(events, store.get("meta", "launch_at")):
            for window in ["15 min", "60 min", "Release-day close"]:
                text = commentary(event, quotes, events, window)
                key = hashlib.sha256(f"{event['id']}|{window}|{text}".encode()).hexdigest()
                if not store.get("commentary", key):
                    store.put("commentary", key, dict(event_id=event["id"], window=window, text=text, as_of=iso(utcnow()), method="Deterministic evidence-based template"))
        store.put("meta", "last_collector_at", iso(utcnow()))
        return summary
    finally:
        store.release()


def main():
    parser = argparse.ArgumentParser(description="Collect Treasury dashboard data once; safe for scheduled execution.")
    parser.add_argument("--require-durable", action="store_true", help="Reject ephemeral SQLite storage")
    args = parser.parse_args()
    settings = Settings.load()
    store = Store(settings.database_url)
    if args.require_durable and not store.durable:
        raise SystemExit("Set DATABASE_URL to the same PostgreSQL database used by Streamlit before scheduling.")
    result = collect(settings, store)
    for name, message in result.items():
        print(f"{name}: {message}")
    if any("Update failed" in msg for msg in result.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
