from datetime import datetime, timedelta, timezone
import pytest
from treasury.store import Store
from treasury.domain import make_event, surprise, dt, iso
from treasury.analysis import reaction, released_since, commentary
from treasury.providers import parse_bls, parse_bea, parse_bls_schedule, parse_fed, numeric_te
from treasury.research import validate_research
from treasury.config import Settings

UTC=timezone.utc
T=datetime(2026,10,14,12,30,tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return Store("sqlite:///"+str(tmp_path/"test.db"))


def event(**kwargs):
    return make_event("cpi_core","2026-09",release_at=iso(T),**kwargs)


def quote(tenor,stamp,value,**kwargs):
    return dict(tenor=tenor,as_of=iso(stamp),value=value,frequency="intraday",source="Test provider",delay="Live",**kwargs)


def test_consensus_is_frozen_before_release_and_original_actual_survives(store):
    store.merge_event(event(consensus=.3,consensus_source="https://example.org/forecast"),T-timedelta(hours=1))
    e=store.merge_event(event(consensus=.4,consensus_source="https://example.org/forecast",actual=.4,actual_source="https://bls.gov/release"),T+timedelta(minutes=2))
    assert e["frozen_consensus"]==.3
    assert surprise(e)==pytest.approx(.1)
    e=store.merge_event(event(actual=.5,actual_source="https://bls.gov/revised"),T+timedelta(days=1))
    assert e["actual"]==.4
    assert e["revisions"][-1]["value"]==.5


def test_late_forecast_is_not_backfilled_as_prerelease(store):
    e=store.merge_event(event(consensus=.3,consensus_source="https://example.org/forecast",actual=.4,actual_source="https://bls.gov/release"),T+timedelta(minutes=1))
    assert e["consensus"]==.3
    assert e["frozen_consensus"] is None
    assert surprise(e) is None


def test_actual_cannot_appear_before_publication(store):
    e=store.merge_event(event(actual=.4,actual_source="https://bls.gov/release"),T-timedelta(minutes=1))
    assert e["actual"] is None


def test_unknowns_do_not_erase_known_fields(store):
    store.merge_event(event(consensus=.3,consensus_source="https://example.org/forecast"),T-timedelta(days=1))
    e=store.merge_event(make_event("cpi_core","2026-09"),T-timedelta(hours=1))
    assert e["release_at"]==iso(T)
    assert e["consensus"]==.3


def test_postponed_release_rechecks_consensus_eligibility(store):
    store.merge_event(event(consensus=.3,consensus_source="https://example.org/forecast"),T-timedelta(minutes=1))
    moved=event(); moved["release_at"]=iso(T-timedelta(hours=1))
    e=store.merge_event(moved,T)
    assert e["frozen_consensus"] is None


def test_withdrawn_schedule_removes_exact_date(store):
    store.merge_event(event(),T-timedelta(days=1))
    e=store.merge_event(make_event("cpi_core","2026-09",schedule_withdrawn=True),T)
    assert e["release_at"] is None


def test_yield_changes_units_and_timestamps():
    rows=[quote("10Y",T-timedelta(minutes=1),4.0),quote("10Y",T+timedelta(minutes=60),4.1)]
    r=reaction(event(),rows,"10Y")
    assert r["bp"]==pytest.approx(10)
    assert r["pp"]==pytest.approx(.1)
    assert r["relative_pct"]==pytest.approx(2.5)


def test_no_interpolation_and_no_mixing_sources():
    rows=[quote("10Y",T-timedelta(minutes=10),4),quote("10Y",T+timedelta(minutes=60),4.1)]
    assert reaction(event(),rows,"10Y") is None
    rows[0]["as_of"]=iso(T-timedelta(minutes=1))
    rows[1]["source"]="Other provider"
    assert reaction(event(),rows,"10Y") is None


def test_daily_history_is_not_intraday_reaction():
    rows=[dict(tenor="10Y",frequency="daily",observation_date="2026-10-13",as_of="2026-10-13T00:00:00+00:00",value=4,source="FRED"),
          dict(tenor="10Y",frequency="daily",observation_date="2026-10-14",as_of="2026-10-14T00:00:00+00:00",value=4.1,source="FRED")]
    assert reaction(event(),rows,"10Y","60 min") is None
    assert reaction(event(),rows,"10Y","Release-day close")["bp"]==pytest.approx(10)


def test_launch_cutoff(store):
    e=store.merge_event(event(actual=.4,actual_source="https://bls.gov/release"),T+timedelta(minutes=1))
    assert not released_since([e],iso(T+timedelta(seconds=1)))
    assert released_since([e],iso(T-timedelta(days=1)))


def test_quotes_deduplicated_and_future_nan_rejected(store):
    q=quote("10Y",T,4)
    store.add_quote(q,T);store.add_quote(q,T)
    assert len(store.all("quote"))==1
    with pytest.raises(ValueError):store.add_quote(quote("10Y",T,float("nan")),T)
    with pytest.raises(ValueError):store.add_quote(quote("10Y",T+timedelta(hours=1),4),T)


def test_collector_lock(store):
    assert store.acquire(T)
    assert not store.acquire(T)
    store.release()
    assert store.acquire(T)


def test_bls_dst_and_month_reference():
    text="""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Consumer Price Index for September 2026
DTSTART;TZID=America/New_York:20261014T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Consumer Price Index for November 2026
DTSTART;TZID=America/New_York:20261210T083000
END:VEVENT
END:VCALENDAR"""
    rows=parse_bls(text)
    assert len(rows)==4
    assert rows[0]["release_at"]=="2026-10-14T12:30:00+00:00"
    assert rows[2]["release_at"]=="2026-12-10T13:30:00+00:00"


def test_bea_vintages():
    text='<div>Year 2026</div><table><tr><td>October 29 8:30 AM</td><td>GDP (Advance Estimate), 3rd Quarter 2026</td></tr><tr><td>October 29 8:30 AM</td><td>Personal Income and Outlays, September 2026</td></tr></table>'
    rows=parse_bea(text,T)
    assert rows[0]["indicator"]=="gdp_advance"
    assert rows[0]["reference"]=="2026-Q3"
    assert rows[1]["reference"]=="2026-09"


def test_research_rejects_uncited_sources_and_wrong_units():
    row=dict(indicator="cpi_core",reference="2026-09",unit="%",release_at=iso(T),date_source="https://bls.gov/release",actual=.4,actual_source="https://bls.gov/release",consensus=.3,consensus_source="https://reuters.com/forecast")
    rows,_,_=validate_research({"events":[row]},set(),T+timedelta(minutes=1))
    assert rows[0]["actual"] is None and rows[0]["consensus"] is None and rows[0]["release_at"] is None
    rows,_,_=validate_research({"events":[row]},{row["date_source"],row["consensus_source"]},T+timedelta(minutes=1))
    assert rows[0]["actual"]==.4
    row["unit"]="index"
    rows,_,rejected=validate_research({"events":[row]},set(),T)
    assert not rows and rejected==1


def test_vendor_number_scales():
    assert numeric_te("123K","thousand")==123
    assert numeric_te("8.1M","million")==8.1
    assert numeric_te("0.3%","%")==.3
    assert numeric_te("","%") is None


def test_empty_database_setting_uses_preview():
    assert Settings.load({"DATABASE_URL":""}).database_url=="sqlite:///treasury.db"


def test_bls_schedule_uses_published_reference_and_unknown_time():
    text='<table class="release-list"><tbody><tr><td>October 2026</td><td>Nov. 10, 2026</td><td>08:30 AM</td></tr><tr><td>November 2026</td><td>Dec. 10, 2026</td><td>TBA</td></tr></tbody></table>'
    rows=parse_bls_schedule(text,["cpi_core"],"https://bls.gov/calendar")
    assert rows[0]["reference"]=="2026-10"
    assert rows[0]["release_at"]=="2026-11-10T13:30:00+00:00"
    assert rows[1]["release_at"] is None and rows[1]["date_only"]=="2026-12-10"


def test_fed_date_is_not_assigned_a_guessed_time():
    content='<div class="panel"><div class="panel-heading">2026 FOMC Meetings</div><div class="fomc-meeting"><div class="fomc-meeting__month">October</div><div class="fomc-meeting__date">27-28</div></div></div>'
    rows=parse_fed(content)
    assert rows[0]["date_only"]=="2026-10-28"
    assert rows[0]["release_at"] is None
