import hashlib
import json
from datetime import timedelta
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, select, update, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from .domain import iso, dt, utcnow, number


class Store:
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.durable = not url.startswith("sqlite")
        args = {"check_same_thread": False, "timeout": 30} if not self.durable else {}
        self.engine = create_engine(url, pool_pre_ping=True, connect_args=args)
        md = MetaData()
        self.records = Table("treasury_records", md,
            Column("kind", String(32), primary_key=True),
            Column("id", String(160), primary_key=True), Column("payload", Text, nullable=False))
        self.locks = Table("treasury_locks", md, Column("id", String(32), primary_key=True), Column("until_at", String(40)))
        md.create_all(self.engine)
        with self.engine.begin() as con:
            self._insert(con, self.locks, dict(id="collector", until_at="1970"), ignore=True)
            self._insert(con, self.locks, dict(id="quotes", until_at="1970"), ignore=True)
            self._insert(con, self.records, dict(kind="meta", id="launch_at", payload=json.dumps(iso(utcnow()))), ignore=True)

    def _insert(self, con, table, values, ignore=False):
        factory = pg_insert if self.durable else sqlite_insert
        stmt = factory(table).values(**values)
        stmt = stmt.on_conflict_do_nothing() if ignore else stmt.on_conflict_do_update(
            index_elements=[c.name for c in table.primary_key],
            set_={k: v for k, v in values.items() if k not in [c.name for c in table.primary_key]})
        con.execute(stmt)

    def get(self, kind, key, default=None):
        with self.engine.connect() as con:
            row = con.execute(select(self.records.c.payload).where(self.records.c.kind == kind, self.records.c.id == key)).scalar()
        return json.loads(row) if row else default

    def all(self, kind):
        with self.engine.connect() as con:
            rows = con.execute(select(self.records.c.payload).where(self.records.c.kind == kind)).scalars().all()
        return [json.loads(x) for x in rows]

    def put(self, kind, key, data):
        with self.engine.begin() as con:
            self._insert(con, self.records, dict(kind=kind, id=str(key), payload=json.dumps(data, allow_nan=False)))

    def acquire(self, now, name="collector"):
        with self.engine.begin() as con:
            result = con.execute(update(self.locks).where(self.locks.c.id == name, self.locks.c.until_at < iso(now)).values(until_at=iso(now + timedelta(minutes=15))))
            return result.rowcount == 1

    def release(self, name="collector"):
        with self.engine.begin() as con:
            con.execute(update(self.locks).where(self.locks.c.id == name).values(until_at="1970"))

    def due(self, task, seconds, now):
        last = self.get("meta", "attempt_" + task)
        return not last or (now - dt(last)).total_seconds() >= seconds

    def status(self, task, ok, message, now):
        previous = self.get("status", task, {})
        self.put("status", task, dict(task=task, ok=ok, message=message,
            checked_at=iso(now), last_success_at=iso(now) if ok else previous.get("last_success_at")))

    def merge_event(self, incoming, now):
        old = self.get("event", incoming["id"], {})
        event = {**incoming, **old} if old else dict(incoming)
        if not old:
            event.update(actual=None, actual_text=None, consensus=None)
        # Unknown fields never erase previously verified facts. Cancelled schedules can
        # explicitly clear date/time, while preserving the original audit trail.
        for key, val in incoming.items():
            if val is not None and key not in {"actual", "actual_text", "consensus", "release_at", "date_only"}:
                event[key] = val
        release = incoming.get("release_at")
        if release and not old.get("actual_first_seen"):
            event["release_at"] = iso(release)
            event["date_only"] = incoming.get("date_only")
        elif incoming.get("date_only") and not old.get("actual_first_seen"):
            event["date_only"] = incoming["date_only"]
            if old.get("release_at") and dt(old["release_at"]).date().isoformat() != incoming["date_only"]:
                event["release_at"] = None
        if incoming.get("schedule_withdrawn") and not old.get("actual_first_seen"):
            event["release_at"] = None
            event["date_only"] = None
        release_dt = dt(event.get("release_at"))
        forecast = number(incoming.get("consensus"))
        if forecast is not None and incoming.get("consensus_source"):
            event["consensus"] = forecast
            event["consensus_seen_at"] = iso(now)
            snapshot = dict(value=forecast, captured_at=iso(now), source=incoming["consensus_source"])
            history = event.setdefault("consensus_history", [])
            if not history or (history[-1]["value"], history[-1]["source"]) != (forecast, snapshot["source"]):
                history.append(snapshot)
        actual = number(incoming.get("actual"))
        actual_text = incoming.get("actual_text")
        if release_dt and release_dt <= now and incoming.get("actual_source") and (actual is not None or actual_text):
            if not old.get("actual_first_seen"):
                event["actual"] = actual
                event["actual_text"] = actual_text
                event["actual_first_seen"] = iso(now)
                event["first_actual_source"] = incoming["actual_source"]
            elif (actual is not None and actual != old.get("actual")) or (actual_text and actual_text != old.get("actual_text")):
                revisions = event.setdefault("revisions", [])
                rev = dict(value=actual, text=actual_text, seen_at=iso(now), source=incoming["actual_source"])
                if not revisions or (revisions[-1]["value"], revisions[-1]["text"]) != (actual, actual_text):
                    revisions.append(rev)
        # Re-evaluate eligibility when the publisher corrects or moves a release time.
        if release_dt:
            eligible = [h for h in event.get("consensus_history", []) if dt(h["captured_at"]) < release_dt]
            event["frozen_consensus"] = eligible[-1]["value"] if eligible else None
            event["frozen_consensus_source"] = eligible[-1]["source"] if eligible else None
            event["frozen_consensus_at"] = eligible[-1]["captured_at"] if eligible else None
        else:
            event["frozen_consensus"] = None
        event["first_seen_at"] = old.get("first_seen_at", iso(now))
        event["updated_at"] = iso(now)
        self.put("event", event["id"], event)
        if incoming != old:
            audit = dict(event_id=event["id"], captured_at=iso(now), input=incoming)
            digest = hashlib.sha256(json.dumps(audit, sort_keys=True).encode()).hexdigest()
            self.put("audit", digest, audit)
        return event

    def add_quote(self, quote, now):
        self.add_quotes([quote], now)

    def add_quotes(self, quotes, now):
        rows = []
        for quote in quotes:
            quote = self.normalize_quote(quote, now)
            key = hashlib.sha256(f"{quote['tenor']}|{quote['source']}|{quote['as_of']}|{quote['frequency']}".encode()).hexdigest()
            rows.append(dict(kind="quote", id=key, payload=json.dumps(quote, allow_nan=False)))
        if rows:
            with self.engine.begin() as con:
                factory = pg_insert if self.durable else sqlite_insert
                # Executemany uses one transaction and avoids a round trip per quote.
                con.execute(factory(self.records).on_conflict_do_nothing(), rows)

    @staticmethod
    def normalize_quote(quote, now):
        val = number(quote.get("value"))
        if val is None or not -5 <= val <= 30 or quote.get("tenor") not in {"10Y", "30Y"}:
            raise ValueError("Invalid Treasury yield quote")
        if dt(quote["as_of"]) > now + timedelta(minutes=2):
            raise ValueError("Future quote rejected")
        if quote.get("frequency") not in {"daily", "intraday"}:
            raise ValueError("Missing quote frequency")
        return {**quote, "value": val, "as_of": iso(quote["as_of"]), "received_at": iso(now)}

    def export(self):
        return dict(schema_version=1, launch_at=self.get("meta", "launch_at"),
            events=self.all("event"), quotes=self.all("quote"), outlooks=self.all("outlook"),
            commentary=self.all("commentary"), audit=self.all("audit"), status=self.all("status"))
