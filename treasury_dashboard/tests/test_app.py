from datetime import timedelta
from pathlib import Path
from streamlit.testing.v1 import AppTest
from treasury.store import Store
from treasury.domain import utcnow,iso,make_event

ROOT=Path(__file__).resolve().parents[1]


def test_empty_dashboard_renders_without_keys(tmp_path,monkeypatch):
    monkeypatch.setenv("DATABASE_URL","sqlite:///"+str(tmp_path/"empty.db"))
    monkeypatch.setenv("AUTO_COLLECT","false")
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
    assert not at.exception
    assert len(at.metric)==3
    assert at.metric[0].value=="n.a."
    assert len(at.dataframe[0].value)>=20


def test_populated_dashboard_and_controls(tmp_path,monkeypatch):
    url="sqlite:///"+str(tmp_path/"populated.db")
    monkeypatch.setenv("DATABASE_URL",url)
    monkeypatch.setenv("AUTO_COLLECT","false")
    store=Store(url)
    now=utcnow()
    release=now-timedelta(hours=3)
    store.put("meta","launch_at",iso(now-timedelta(days=10)))
    e=make_event("cpi_core",release.strftime("%Y-%m"),release_at=iso(release),consensus=.3,consensus_source="https://example.org/forecast")
    store.merge_event(e,release-timedelta(hours=1))
    store.merge_event({**e,"actual":.4,"actual_source":"https://bls.gov/release"},release+timedelta(seconds=20))
    for tenor,base in [("10Y",4),("30Y",4.5)]:
        for days in range(5):
            date=(now-timedelta(days=days+1)).date().isoformat()
            store.add_quote(dict(tenor=tenor,value=base+days*.01,as_of=date+"T00:00:00+00:00",observation_date=date,frequency="daily",source="FRED "+("DGS10" if tenor=="10Y" else "DGS30"),delay="Daily"),now)
        for minutes,value in [(-1,base),(15,base+.03),(60,base+.07)]:
            store.add_quote(dict(tenor=tenor,value=value,as_of=iso(release+timedelta(minutes=minutes)),frequency="intraday",source="Test",delay="Live"),now)
    at=AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
    assert not at.exception
    assert len(at.tabs)==3
    at.sidebar.radio[0].set_value("Intraday feed").run()
    assert not at.exception
    # Exercise missing daily reaction and relative yield-change paths.
    next(s for s in at.selectbox if s.label=="Reaction window").set_value("Release-day close").run()
    assert not at.exception
    next(r for r in at.radio if r.label=="Yield change display").set_value("Relative change (%)").run()
    assert not at.exception
