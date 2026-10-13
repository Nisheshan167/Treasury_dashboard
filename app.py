"""Run with: streamlit run app.py"""
import html
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from treasury.config import Settings
from treasury.store import Store
from treasury.collector import collect
from treasury.domain import CATALOG, utcnow, dt, fmt, surprise, event_status
from treasury.analysis import latest_quotes, released_since, reaction, commentary, fallback_outlook

st.set_page_config(page_title="Treasury Observatory", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
try:
    secrets = dict(st.secrets)
except Exception:
    secrets = {}
settings = Settings.load(secrets)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp {font-family:'DM Sans',sans-serif;}
.block-container {padding-top:2.2rem;max-width:1520px;padding-bottom:4rem;}
h1,h2,h3 {font-family:'Manrope',sans-serif!important;letter-spacing:-.045em;}
h1 {font-size:2.65rem!important;font-weight:800!important;line-height:1.1!important;}
h2 {font-size:1.45rem!important;margin-top:1.2rem!important;}
h3 {font-size:1.05rem!important;letter-spacing:-.015em;}
[data-testid="stSidebar"] {background:#0d1623;border-right:1px solid #223044;}
[data-testid="stMetric"] {background:linear-gradient(130deg,#142334,#101a28);border:1px solid #25364b;border-radius:14px;padding:20px 22px;}
[data-testid="stMetricLabel"] {color:#9eafc3;text-transform:uppercase;letter-spacing:.10em;font-size:.75rem;}
[data-testid="stMetricValue"] {font-family:'Manrope',sans-serif;font-weight:700;letter-spacing:-.04em;}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-color:#26364b!important;border-radius:14px!important;}
.eyebrow {color:#66e0bd;font-size:.72rem;letter-spacing:.18em;font-weight:700;text-transform:uppercase;margin-bottom:13px;}
.subtitle {color:#97a8bc;font-size:1rem;max-width:750px;line-height:1.6;margin-bottom:1.4rem;}
.brand {font-family:'Manrope',sans-serif;font-size:1.28rem;font-weight:800;line-height:1.35;margin:5px 0 10px;}
.brand span {color:#66e0bd;}
.side-note {font-size:.78rem;line-height:1.6;color:#8194ac;}
.section-kicker {color:#758ca7;font-size:.70rem;letter-spacing:.17em;text-transform:uppercase;margin-top:26px;}
.next-card {background:#121e2b;border:1px solid #2b4051;border-top:2px solid #66e0bd;border-radius:12px;padding:17px;min-height:166px;}
.next-title {font-size:.95rem;color:#e7edf5;font-weight:700;margin:8px 0;}
.next-meta {color:#9eafc3;font-size:.8rem;line-height:1.65;}
.pill {font-size:.65rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;border:1px solid #355363;border-radius:30px;padding:3px 7px;color:#91d7c6;}
.outlook {border-left:3px solid #66e0bd;padding:9px 0 9px 22px;line-height:1.85;color:#c9d4e2;font-size:1rem;}
.empty {padding:35px;border:1px dashed #31465e;border-radius:12px;color:#92a6bd;line-height:1.8;background:#101b29;}
.foot {color:#6f849f;font-size:.75rem;line-height:1.7;margin-top:25px;border-top:1px solid #203044;padding-top:16px;}
div[data-testid="stTabs"] button {font-weight:600;}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def resources(database_url):
    return Store(database_url), ThreadPoolExecutor(max_workers=1), {"future": None}


try:
    store, executor, job = resources(settings.database_url)
except Exception:
    st.error("The database could not be opened. Check DATABASE_URL in Streamlit Secrets. Use the PostgreSQL session-pooler connection string with SSL, or omit DATABASE_URL for a local preview.")
    st.stop()


def start_collection():
    future = job["future"]
    if future is None or future.done():
        job["future"] = executor.submit(collect, settings, store)


def time_label(value, zone="America/New_York"):
    return dt(value).astimezone(ZoneInfo(zone)).strftime("%d %b %Y · %I:%M %p %Z") if value else "n.a."


def plot_style(fig, height=310):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", color="#9eafc3", size=11), height=height,
        margin=dict(l=12, r=18, t=18, b=12), hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0),
        xaxis=dict(showgrid=False, zeroline=False), yaxis=dict(gridcolor="#213044", zerolinecolor="#3b5067"))
    return fig


with st.sidebar:
    st.markdown('<div class="brand"><span>◈</span> Treasury<br>Observatory</div><div class="side-note">MACRO DATA · DURATION · DECISIONS</div>', unsafe_allow_html=True)
    st.divider()
    st.caption("DISPLAY")
    zone = st.selectbox("Time zone", ["America/New_York", "Asia/Kolkata", "UTC"], format_func=lambda x: {"America/New_York": "US Eastern", "Asia/Kolkata": "India (IST)", "UTC": "UTC"}[x])
    history_days = st.select_slider("Chart history", options=[7, 30, 90, 180, 365], value=90, format_func=lambda x: f"{x} days")
    chart_mode = st.radio("Yield observations", ["Daily reference", "Intraday feed"], help="Daily constant-maturity yields and intraday benchmarks may have different instrument definitions; they are never spliced into a single series.")
    st.divider()
    st.caption("CONNECTIONS")
    st.write("🟢 Persistent database" if store.durable else "🟠 Local preview storage")
    st.write("🟢 AI research connected" if settings.openai_api_key else "⚪ AI research not connected")
    st.write("🟢 Quote feed configured" if settings.quote_feed_url or settings.te_api_key else "⚪ Intraday feed not connected")
    st.caption("Configured does not mean verified. See source health below.")
    st.divider()
    st.caption("TRACKING STARTED")
    st.write(time_label(store.get("meta", "launch_at"), zone))
    st.markdown('<div class="side-note">The release ledger starts here. Earlier daily yield history provides context and is excluded from post-launch event analysis.</div>', unsafe_allow_html=True)


@st.fragment(run_every="60s")
def dashboard():
    now = utcnow()
    if settings.auto_collect:
        start_collection()
    quotes, events = store.all("quote"), store.all("event")
    launch = store.get("meta", "launch_at")
    released = released_since(events, launch)
    header, controls = st.columns([5, 1])
    with header:
        st.markdown('<div class="eyebrow">US RATES INTELLIGENCE</div>', unsafe_allow_html=True)
        st.title("A clearer view of what moves yields.")
        st.markdown('<div class="subtitle">Follow the curve. Anticipate the next release. Keep an evidence trail of what the market did next.</div>', unsafe_allow_html=True)
    with controls:
        if st.button("↻ Check for updates", use_container_width=True):
            start_collection()
        future = job["future"]
        if future and not future.done():
            st.caption("● Collecting in background")
        elif future and future.done() and future.exception():
            st.caption("Collector interrupted · see setup")
        else:
            st.caption("Refreshes every 60 seconds")
        st.caption("Collector: " + time_label(store.get("meta", "last_collector_at"), zone))

    if not store.durable:
        st.warning("Preview storage: connect PostgreSQL before launch to preserve history through Streamlit restarts and enable unattended collection.")
    if not settings.openai_api_key and not settings.te_api_key:
        st.info("Calendar dates and daily yields can load without paid keys. Connect OpenAI web research or a calendar feed for automatic consensus and released figures. Unknown values remain n.a.")

    cards = st.columns(3)
    latest = {q["tenor"]: q for q in latest_quotes(quotes)}
    for tenor, column in zip(["10Y", "30Y"], cards):
        q = latest.get(tenor)
        with column:
            prior = [] if not q else sorted([x for x in quotes if x["tenor"] == tenor and x["frequency"] == "daily" and x["as_of"][:10] < q["as_of"][:10]], key=lambda x: x["as_of"])
            change = (q["value"] - prior[-1]["value"]) * 100 if q and prior else None
            st.metric(f"{tenor} Treasury yield", f"{q['value']:.3f}%" if q else "n.a.", f"{change:+.1f} bp vs prior daily reference" if change is not None else None, delta_color="off")
            if q:
                if q["frequency"] == "daily":
                    st.caption(f"Daily observation · {q['as_of'][:10]} · {q['source']}")
                else:
                    age = (now - dt(q["as_of"])).total_seconds() / 60
                    st.caption(f"{q.get('delay', 'Unknown delay')} · {time_label(q['as_of'], zone)}" + (" · STALE > 15 min" if age > 15 else ""))
            else:
                st.caption("Waiting for a verified observation")
    with cards[2]:
        comparable = latest.get("10Y") and latest.get("30Y") and latest["10Y"]["frequency"] == latest["30Y"]["frequency"] and latest["10Y"]["source"].split(" DGS")[0] == latest["30Y"]["source"].split(" DGS")[0] and abs((dt(latest["10Y"]["as_of"]) - dt(latest["30Y"]["as_of"])).total_seconds()) <= 300
        spread = (latest["30Y"]["value"] - latest["10Y"]["value"]) * 100 if comparable else None
        st.metric("30Y minus 10Y", f"{spread:.1f} bp" if spread is not None else "n.a.")
        st.caption("Matched source, frequency and observation time")

    frequency = "daily" if chart_mode == "Daily reference" else "intraday"
    chart_cols = st.columns(2)
    for tenor, color, column in zip(["10Y", "30Y"], ["#66e0bd", "#97acff"], chart_cols):
        with column:
            st.subheader(f"{tenor} yield path")
            points = sorted([q for q in quotes if q["tenor"] == tenor and q["frequency"] == frequency and dt(q["as_of"]) >= now - timedelta(days=history_days)], key=lambda q: q["as_of"])
            if points:
                fig = go.Figure()
                for source in sorted({q["source"] for q in points}):
                    data = [q for q in points if q["source"] == source]
                    fig.add_trace(go.Scatter(x=[q["as_of"] for q in data], y=[q["value"] for q in data], mode="lines" if len(data)>1 else "markers", name=source,
                        line=dict(color=color, width=2.5), fill="tozeroy", fillcolor="rgba(102,224,189,0.035)" if tenor=="10Y" else "rgba(151,172,255,0.035)",
                        hovertemplate="%{x}<br>Yield %{y:.3f}%<extra>%{fullData.name}</extra>"))
                low,high=min(q["value"] for q in points),max(q["value"] for q in points)
                padding=max(.025,(high-low)*.15)
                fig.update_yaxes(title="Yield (%)", ticksuffix="%", range=[low-padding,high+padding])
                fig.update_xaxes(title="Observation date / time (UTC)")
                st.plotly_chart(plot_style(fig), use_container_width=True, key="yield_"+tenor)
            else:
                st.markdown('<div class="empty">No '+frequency+' observations yet.<br>'+('Connect a timestamped Treasury yield feed in Secrets. Daily history remains available in the sidebar.' if frequency=="intraday" else 'The collector is fetching official daily history. Check source health if this remains empty.')+'</div>', unsafe_allow_html=True)
    st.caption("Yield is shown in percent. A 0.10 percentage-point move equals 10 basis points. Intraday benchmarks can differ from daily constant-maturity series.")

    st.markdown('<div class="section-kicker">01 / THE NEXT CATALYST</div>', unsafe_allow_html=True)
    st.header("What’s coming next")
    upcoming = sorted([e for e in events if event_status(e, now) != "Released" and (not e.get("release_at") or dt(e["release_at"]) >= dt(launch)) and (not e.get("date_only") or e["date_only"] >= dt(launch).astimezone(ZoneInfo("America/New_York")).date().isoformat())], key=lambda e: e.get("release_at") or e.get("date_only") or "9999")
    exact_next = [e for e in upcoming if e.get("release_at") and dt(e["release_at"]) > now]
    unique = []
    for e in exact_next:
        if not any(x["group"] == e["group"] and x["release_at"] == e["release_at"] for x in unique):
            unique.append(e)
    if unique:
        for column, e in zip(st.columns(3), unique[:3]):
            with column:
                hours = (dt(e["release_at"])-now).total_seconds()/3600
                countdown = f"In {hours:.0f} hours" if hours < 48 else f"In {hours/24:.0f} days"
                st.markdown(f'<div class="next-card"><span class="pill">{html.escape(countdown)}</span><div class="next-title">{html.escape(e["label"])}</div><div class="next-meta">{html.escape(time_label(e["release_at"], zone))}<br>Consensus <b>{fmt(e.get("consensus"), e["unit"])}</b> · Previous {fmt(e.get("previous"), e["unit"])}</div></div>', unsafe_allow_html=True)
    calendar_rows = []
    for e in upcoming:
        calendar_rows.append({"Release":e["label"],"Period":e["reference"],"Date / time":time_label(e.get("release_at"),zone) if e.get("release_at") else (e.get("date_only")+" · time n.a." if e.get("date_only") else "n.a."),
            "Consensus":fmt(e.get("consensus"),e["unit"]),"Previous":fmt(e.get("previous"),e["unit"]),"Priority":e["priority"],"Status":event_status(e,now),"Source":e.get("date_source"),"Consensus source":e.get("consensus_source")})
    known = {e["indicator"] for e in upcoming}
    for code,spec in CATALOG.items():
        if code not in known:
            calendar_rows.append({"Release":spec[0],"Period":"n.a.","Date / time":"n.a.","Consensus":"n.a.","Previous":"n.a.","Priority":spec[3],"Status":"Next release not yet verified","Source":None,"Consensus source":None})
    st.dataframe(pd.DataFrame(calendar_rows), hide_index=True, use_container_width=True,
        column_config={"Source":st.column_config.LinkColumn("Calendar source",display_text="Open"),"Consensus source":st.column_config.LinkColumn(display_text="Open")}, height=360)
    st.caption("Unknown dates and consensus stay n.a. and are checked again automatically. An overdue release without a verified actual remains ‘Awaiting actual’. Search-based coverage is best effort.")

    st.markdown('<div class="section-kicker">02 / THE FORWARD VIEW</div>', unsafe_allow_html=True)
    st.header("Where yields could go from here")
    outlooks = sorted(store.all("outlook"), key=lambda x:x["as_of"], reverse=True)
    current = outlooks[0] if outlooks else None
    st.caption(("Next 1–3 months · AI scenario analysis · Updated "+time_label(current["as_of"],zone)) if current else "Next 1–3 months · Framework only · AI outlook pending")
    paragraph = current["paragraph"] if current else fallback_outlook(quotes,events,launch)
    st.markdown('<div class="outlook">'+html.escape(paragraph)+'</div>',unsafe_allow_html=True)
    if current and current.get("scenarios"):
        for column, row in zip(st.columns(3),current["scenarios"]):
            with column:
                st.subheader(row.get("name","Scenario"))
                a,b=row.get("ten_year_low"),row.get("ten_year_high")
                c,d=row.get("thirty_year_low"),row.get("thirty_year_high")
                st.write("10Y: "+(f"{a:.2f}–{b:.2f}%" if a is not None and b is not None else "n.a."))
                st.write("30Y: "+(f"{c:.2f}–{d:.2f}%" if c is not None and d is not None else "n.a."))
                st.caption(row.get("condition",""))
        st.caption("Ranges are conditional AI judgments, not calibrated forecasts or confidence intervals. The outlook updates separately from the yield charts.")
    with st.expander("Outlook evidence and previous snapshots"):
        if current:
            snap=current.get("evidence_snapshot",{})
            st.write("Evidence through "+time_label(snap.get("as_of"),zone))
            for e in snap.get("events",[]):
                if e.get("first_actual_source"):
                    st.link_button(e["label"]+" · "+e["reference"],e["first_actual_source"])
            for n in snap.get("news",[]):
                st.link_button(n["headline"],n["source"])
            for old in outlooks[1:8]:
                st.caption(time_label(old["as_of"],zone))
                st.write(old["paragraph"])
        else:
            st.write("Connect OPENAI_API_KEY to enable sourced outlook snapshots. Every generated version is retained.")

    st.markdown('<div class="section-kicker">03 / SINCE LAUNCH</div>', unsafe_allow_html=True)
    st.header("The release & reaction ledger")
    st.caption(f"Tracking from {time_label(launch,zone)} · {len(released)} released indicator observations · simultaneous indicators share market reactions")
    if not released:
        st.markdown('<div class="empty">Your event history begins with the first verified release after launch.<br>Actuals, pre-release consensus, observed yield changes and commentary will appear here as they become available.</div>',unsafe_allow_html=True)
    else:
        window=st.selectbox("Reaction window",["60 min","15 min","Release-day close"],help="Intraday: pre-release observation within 5 minutes; post-window observation within 10 minutes. Daily: previous business-day reference to release-day reference. No interpolation.")
        measure=st.radio("Yield change display",["Basis points","Percentage points","Relative change (%)"],horizontal=True)
        metric={"Basis points":"bp","Percentage points":"pp","Relative change (%)":"relative_pct"}[measure]
        ledger=[]
        for e in released:
            r10,r30=reaction(e,quotes,"10Y",window),reaction(e,quotes,"30Y",window)
            ledger.append({"Release":e["label"],"Period":e["reference"],"Released":time_label(e["release_at"],zone),
                "Actual":fmt(e.get("actual"),e["unit"]) if e["unit"]!="text" else "Published",
                "Pre-release consensus":fmt(e.get("frozen_consensus"),e["unit"]),
                "Surprise":f"{surprise(e):+.2f} {'pp' if e['unit']=='%' else e['unit']}" if surprise(e) is not None else "n.a.",
                "10Y change":f"{r10[metric]:+.3f}" if r10 and r10[metric] is not None else "n.a.",
                "30Y change":f"{r30[metric]:+.3f}" if r30 and r30[metric] is not None else "n.a.",
                "Actual source":e.get("first_actual_source")})
        tab1,tab2,tab3=st.tabs(["Yield reactions","Actual vs consensus","Commentary & audit"])
        with tab1:
            fig=go.Figure()
            for tenor,color in [("10Y","#66e0bd"),("30Y","#97acff")]:
                data=[(e,reaction(e,quotes,tenor,window)) for e in released]
                data=[(e,r) for e,r in data if r and r[metric] is not None]
                if data:
                    fig.add_trace(go.Scatter(x=[e["release_at"] for e,r in data],y=[r[metric] for e,r in data],mode="markers",name=tenor,
                        marker=dict(color=color,size=10,line=dict(width=1,color="#0b111b")),
                        customdata=[[e["label"],e["reference"],r["before_at"],r["after_at"]] for e,r in data],
                        hovertemplate="%{customdata[0]} · %{customdata[1]}<br>Change %{y:.3f}<br>Before %{customdata[2]}<br>After %{customdata[3]}<extra>%{fullData.name}</extra>"))
            if fig.data:
                fig.update_yaxes(title=measure)
                st.plotly_chart(plot_style(fig,360),use_container_width=True)
            else:
                st.info("No valid before/after pairs for this window yet. Daily history cannot reconstruct a 15-minute or 60-minute reaction. Try release-day close once that day's observation is available.")
            st.caption("Each point is the movement around a release, not its isolated causal effect. Simultaneous releases can overlap. Relative yield change is not a bond-price return.")
        with tab2:
            units=sorted({e["unit"] for e in released if e["unit"]!="text"})
            if units:
                unit=st.selectbox("Compare indicators with the same unit",units)
                comparisons=[e for e in released if e["unit"]==unit and e.get("actual") is not None]
                labels=[e["label"]+" · "+e["reference"] for e in comparisons]
                fig=go.Figure()
                fig.add_trace(go.Bar(y=labels,x=[e["actual"] for e in comparisons],name="First observed actual",orientation="h",marker_color="#66e0bd"))
                fig.add_trace(go.Bar(y=labels,x=[e.get("frozen_consensus") for e in comparisons],name="Pre-release consensus",orientation="h",marker_color="#63748c"))
                fig.update_layout(barmode="group")
                fig.update_xaxes(title="Reported value ("+unit+")")
                st.plotly_chart(plot_style(fig,max(300,min(1200,len(labels)*58))),use_container_width=True)
                st.caption("Missing consensus produces no consensus bar. The complete ledger below preserves every release, including observations without yield pairs.")
            else:
                st.info("The recorded events are qualitative; numerical surprises are n.a.")
        with tab3:
            event=st.selectbox("Inspect a release",released,format_func=lambda e:e["label"]+" · "+e["reference"])
            st.write(commentary(event,quotes,events,window))
            st.caption("First observed: "+time_label(event.get("actual_first_seen"),zone)+" · Consensus captured: "+time_label(event.get("frozen_consensus_at"),zone))
            if event.get("first_actual_source"):
                st.link_button("Open actual release source",event["first_actual_source"])
            if event.get("frozen_consensus_source"):
                st.link_button("Open consensus source",event["frozen_consensus_source"])
            if event.get("consensus") is not None and event.get("frozen_consensus") is None:
                st.caption("A consensus was found after publication. It is retained for reference but excluded from the surprise calculation.")
            st.json({"revisions":event.get("revisions",[]),"consensus_history":event.get("consensus_history",[]),
                "10Y_pair":reaction(event,quotes,"10Y",window),"30Y_pair":reaction(event,quotes,"30Y",window)},expanded=False)
        st.dataframe(pd.DataFrame(ledger),hide_index=True,use_container_width=True,column_config={"Actual source":st.column_config.LinkColumn(display_text="Open")})
        st.download_button("Download release ledger · CSV",pd.DataFrame(ledger).to_csv(index=False),"treasury_release_ledger.csv","text/csv")

    with st.expander("Source health, setup & full archive"):
        status=store.all("status")
        if status:
            st.dataframe(pd.DataFrame(status),hide_index=True,use_container_width=True)
        else:
            st.write("No collection attempts yet.")
        used=store.get("meta","ai_requests_"+now.date().isoformat(),0)
        st.caption(f"AI requests attempted today (UTC): {used}/{settings.ai_daily_request_limit}. Web research can use up to three search calls per request; token charges also apply.")
        st.write("For unattended updates: use the included GitHub Actions workflow with the same PostgreSQL DATABASE_URL. GitHub scheduling may be delayed; minute-accurate capture requires an always-on collector.")
        st.download_button("Download complete history · JSON",json.dumps(store.export(),indent=2),"treasury_observatory_archive.json","application/json")
    st.markdown('<div class="foot">TREASURY OBSERVATORY · Sources and observation times travel with every number.<br>Daily and intraday series are kept separate. Commentary describes observed associations. Scenario analysis is conditional and uncalibrated.</div>',unsafe_allow_html=True)


dashboard()
