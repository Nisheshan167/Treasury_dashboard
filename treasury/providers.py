"""External adapters. Network errors are isolated by the collector, never fabricated."""
import io
import re
import xml.etree.ElementTree as ET_XML
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from icalendar import Calendar
from .domain import CATALOG, make_event, iso, number, web_url

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
HEADERS = {"User-Agent": "TreasuryObservatory/1.0 (research dashboard; scheduled requests)", "Accept": "application/json,text/plain,text/html,text/calendar,*/*"}
BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule"
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_SCHEDULES = {
    "CPI": ("cpi", ["cpi_core", "cpi_headline"]),
    "Employment": ("empsit", ["payrolls", "unemployment", "wages"]),
    "PPI": ("ppi", ["ppi"]), "JOLTS": ("jolts", ["jolts"]), "ECI": ("eci", ["eci"]),
}


def get(url, **kwargs):
    response = requests.get(url, timeout=(10, 35), headers=kwargs.pop("headers", HEADERS), **kwargs)
    response.raise_for_status()
    return response


def fred_daily_yields(settings, now):
    output = []
    start = (now - timedelta(days=400)).date().isoformat()
    for series, tenor in [("DGS10", "10Y"), ("DGS30", "30Y")]:
        if settings.fred_api_key:
            rows = get("https://api.stlouisfed.org/fred/series/observations", params={
                "series_id": series, "api_key": settings.fred_api_key, "file_type": "json", "observation_start": start}).json()["observations"]
        else:
            text = get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series, "cosd": start}).text
            frame = pd.read_csv(io.StringIO(text))
            rows = [{"date": str(r.iloc[0]), "value": r[series]} for _, r in frame.iterrows()]
        for row in rows:
            value = number(row["value"])
            if value is None:
                continue
            output.append(dict(tenor=tenor, value=value, as_of=f"{row['date']}T00:00:00+00:00",
                observation_date=row["date"], frequency="daily", delay="End-of-day series",
                source=f"FRED {series}", source_url=f"https://fred.stlouisfed.org/series/{series}"))
    return output


TREASURY_XML = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"


def parse_treasury_xml(content, start=None):
    """Treasury's public par-yield feed: retain its own source and series definition."""
    root = ET_XML.fromstring(content)
    output = []
    for properties in root.findall(".//{*}properties"):
        fields = {node.tag.rsplit("}", 1)[-1]: node.text for node in properties}
        date = (fields.get("NEW_DATE") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or (start and date < start):
            continue
        for key, tenor in [("BC_10YEAR", "10Y"), ("BC_30YEAR", "30Y")]:
            val = number(fields.get(key))
            if val is not None:
                output.append(dict(tenor=tenor, value=val, as_of=date+"T00:00:00+00:00",
                    observation_date=date, frequency="daily", delay="End-of-day series",
                    source="US Treasury par yields", source_url="https://home.treasury.gov/treasury-daily-interest-rate-xml-feed"))
    return output


def treasury_daily_yields(now):
    start = now - timedelta(days=400)
    output = []
    errors = []
    for year in range(now.year, start.year-1, -1):
        try:
            response = get(TREASURY_XML, params={"data": "daily_treasury_yield_curve", "field_tdr_date_value": str(year)})
            output.extend(parse_treasury_xml(response.content, start.date().isoformat()))
        except (requests.RequestException, ET_XML.ParseError, ValueError) as error:
            errors.append(error)
    if not output:
        if errors:
            raise errors[0]
        raise ValueError("Treasury returned no recognized par-yield observations")
    return output


def daily_yields(settings, now):
    """Independent official fallback when FRED is unavailable from the hosting server."""
    try:
        rows = fred_daily_yields(settings, now)
        if not rows or {r["tenor"] for r in rows} != {"10Y", "30Y"}:
            raise ValueError("FRED returned incomplete Treasury history")
        return rows
    except (requests.RequestException, ValueError, KeyError, pd.errors.ParserError):
        return treasury_daily_yields(now)


def reference_from_title(title):
    match = re.search(r"(?:for |, )?([A-Za-z]+)\s+(20\d{2})", title)
    if match:
        try:
            return datetime.strptime(" ".join(match.groups()), "%B %Y").strftime("%Y-%m")
        except ValueError:
            pass
    match = re.search(r"([1-4])(?:st|nd|rd|th) Quarter (20\d{2})", title, re.I)
    return f"{match[2]}-Q{match[1]}" if match else None


def indicators_for_title(title):
    low = title.lower()
    if "consumer price index" in low:
        return ["cpi_core", "cpi_headline"]
    if "employment situation" in low and "state" not in low:
        return ["payrolls", "unemployment", "wages"]
    if "producer price" in low:
        return ["ppi"]
    if "job openings" in low and "state" not in low:
        return ["jolts"]
    if "employment cost" in low:
        return ["eci"]
    if "personal income and outlays" in low:
        return ["pce_core", "pce_headline"]
    if "gdp" in low or "gross domestic product" in low:
        if "advance" in low:
            return ["gdp_advance"]
        if "second" in low:
            return ["gdp_second"]
        if "third" in low:
            return ["gdp_final"]
    return []


def parse_bls(content):
    events = []
    for component in Calendar.from_ical(content).walk("VEVENT"):
        title = str(component.get("SUMMARY", ""))
        reference = reference_from_title(title + " " + str(component.get("DESCRIPTION", "")))
        if not reference or not component.get("DTSTART"):
            continue
        stamp = component.decoded("DTSTART")
        release, date_only = None, None
        if isinstance(stamp, datetime):
            release = iso(stamp.replace(tzinfo=ET) if stamp.tzinfo is None else stamp)
        else:
            date_only = stamp.isoformat()
        for indicator in indicators_for_title(title):
            # ECI uses a quarter reference, not the publication month's name.
            ref = reference
            if indicator == "eci" and re.fullmatch(r"\d{4}-\d{2}", ref):
                ref = f"{ref[:4]}-Q{(int(ref[-2:]) - 1) // 3 + 1}"
            events.append(make_event(indicator, ref, release_at=release, date_only=date_only,
                date_source=BLS_URL, provider="BLS calendar", schedule_withdrawn=str(component.get("STATUS", "")) == "CANCELLED"))
    return events


def parse_bls_schedule(content, codes, source):
    soup = BeautifulSoup(content, "html.parser")
    events = []
    for row in soup.select("table.release-list tbody tr"):
        cells = [c.get_text(" ", strip=True) for c in row.select("td")]
        if len(cells) < 3:
            continue
        ref = reference_from_title(cells[0])
        if not ref:
            continue
        release = None
        date_only = None
        date_text = cells[1].replace(".", "").replace("Sept ", "Sep ")
        parsed = None
        for pattern in ["%b %d, %Y", "%B %d, %Y"]:
            try:
                parsed = datetime.strptime(date_text, pattern)
                break
            except ValueError:
                pass
        if parsed:
            date_only = parsed.date().isoformat()
            try:
                time = datetime.strptime(cells[2], "%I:%M %p").time()
                release = iso(datetime.combine(parsed.date(), time, tzinfo=ET))
                date_only = None
            except ValueError:
                pass
        for code in codes:
            reference = ref
            if code == "eci" and re.fullmatch(r"\d{4}-\d{2}", ref):
                reference = f"{ref[:4]}-Q{(int(ref[-2:])-1)//3+1}"
            events.append(make_event(code, reference, release_at=release, date_only=date_only,
                date_source=source, provider="BLS release schedule"))
    return events


def parse_bea(content, now):
    soup = BeautifulSoup(content, "html.parser")
    text = soup.get_text(" ", strip=True)
    year_match = re.search(r"Year\s*(20\d{2})", text)
    year = int(year_match[1]) if year_match else now.year
    events = []
    for row in soup.select("tr"):
        title = row.get_text(" ", strip=True)
        codes = indicators_for_title(title)
        if not codes:
            continue
        ref = reference_from_title(title)
        match = re.search(r"([A-Z][a-z]+ \d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]M)", title)
        if not ref:
            continue
        release = None
        if match:
            release = iso(datetime.strptime(f"{year} {match[1]} {match[2]}", "%Y %B %d %I:%M %p").replace(tzinfo=ET))
        for code in codes:
            events.append(make_event(code, ref, release_at=release, date_source=BEA_URL, provider="BEA calendar"))
    return events


def parse_fed(content):
    soup = BeautifulSoup(content, "html.parser")
    events = []
    for panel in soup.select(".panel"):
        heading = panel.select_one(".panel-heading")
        match = re.search(r"(20\d{2}) FOMC Meetings", heading.get_text(" ", strip=True) if heading else "")
        if not match:
            continue
        year = int(match[1])
        for row in panel.select(".fomc-meeting"):
            month, day = row.select_one(".fomc-meeting__month"), row.select_one(".fomc-meeting__date")
            if not month or not day:
                continue
            month_text, day_text = month.get_text(strip=True), day.get_text(strip=True)
            # Joint-month and emergency meetings require explicit research; no guesswork.
            if "/" in month_text or "unscheduled" in day_text.lower():
                continue
            days = re.findall(r"\d+", day_text)
            if not days:
                continue
            try:
                date = datetime.strptime(f"{year} {month_text} {days[-1]}", "%Y %B %d").date().isoformat()
            except ValueError:
                continue
            # This source confirms the date only. Exact release times arrive from research/feed.
            events.append(make_event("fed_rate", date, date_only=date, date_source=FED_URL, provider="Federal Reserve calendar"))
    return events


def numeric_te(value, unit):
    if value is None or value == "":
        return None
    if isinstance(value, (float, int)):
        return number(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    match = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)([KkMmBb])?", text)
    if not match:
        return None
    val = float(match[1])
    if match[2]:
        val *= {"k": 1e3, "m": 1e6, "b": 1e9}[match[2].lower()]
        val /= {"thousand": 1e3, "million": 1e6}.get(unit, 1)
    return val


TE_NAMES = {
    "core inflation rate mom": "cpi_core", "inflation rate mom": "cpi_headline",
    "core pce price index mom": "pce_core", "pce price index mom": "pce_headline",
    "non farm payrolls": "payrolls", "nonfarm payrolls": "payrolls",
    "unemployment rate": "unemployment", "average hourly earnings mom": "wages",
    "fed interest rate decision": "fed_rate", "ism manufacturing pmi": "ism_mfg",
    "ism services pmi": "ism_services", "retail sales mom": "retail", "ppi mom": "ppi",
    "initial jobless claims": "claims", "jolts job openings": "jolts",
    "employment cost index qoq": "eci", "gdp growth rate qoq adv": "gdp_advance",
    "gdp growth rate qoq 2nd est": "gdp_second", "gdp growth rate qoq final": "gdp_final",
    "10-year note auction": "auction_10y", "30-year bond auction": "auction_30y",
    "michigan 5 year inflation expectations prelim": "michigan_prelim",
    "michigan 5 year inflation expectations final": "michigan_final",
}


def te_calendar(settings, now):
    begin, end = (now - timedelta(days=45)).date(), (now + timedelta(days=120)).date()
    data = get(f"https://api.tradingeconomics.com/calendar/country/united%20states/{begin}/{end}", params={"c": settings.te_api_key, "f": "json"}).json()
    if not isinstance(data, list):
        raise ValueError("Calendar subscription did not return events")
    events = []
    for row in data:
        code = TE_NAMES.get(str(row.get("Event", "")).lower())
        if not code:
            continue
        raw_date = row.get("Date")
        if not raw_date:
            continue
        stamp = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
        raw_ref = row.get("ReferenceDate")
        if code.startswith("auction") or code == "fed_rate":
            reference = stamp.astimezone(ET).date().isoformat()
        elif raw_ref:
            ref_date = datetime.fromisoformat(raw_ref.replace("Z", "+00:00"))
            reference = ref_date.strftime("%Y-%m-%d" if code == "claims" else "%Y-%m")
            if code.startswith("gdp") or code == "eci":
                reference = f"{ref_date.year}-Q{(ref_date.month - 1) // 3 + 1}"
        else:
            continue  # Never guess the reference period from a release month.
        source = "https://tradingeconomics.com" + str(row.get("URL", "/calendar"))
        unit = CATALOG[code][1]
        exact = str(row.get("DateSpan", "0")) == "0"
        events.append(make_event(code, reference, release_at=iso(stamp) if exact else None,
            date_only=stamp.date().isoformat() if not exact else None,
            actual=numeric_te(row.get("Actual"), unit), previous=numeric_te(row.get("Previous"), unit),
            consensus=numeric_te(row.get("Forecast"), unit),  # TEForecast is NOT consensus.
            consensus_source=source, actual_source=source, date_source=source, provider="Trading Economics"))
    return events


def intraday_quotes(settings, now):
    if settings.quote_feed_url:
        if not settings.quote_feed_url.startswith("https://"):
            raise ValueError("Quote feed must use HTTPS")
        headers = {**HEADERS}
        if settings.quote_feed_token:
            headers["Authorization"] = "Bearer " + settings.quote_feed_token
        data = get(settings.quote_feed_url, headers=headers).json()
        if not isinstance(data.get("quotes"), list):
            raise ValueError("Quote endpoint must return a quotes array")
        output = []
        for row in data["quotes"]:
            if row.get("unit") != "percent" or row.get("instrument") != "treasury_yield":
                raise ValueError("Quote must explicitly be a Treasury yield in percent units")
            if not row.get("source") or not web_url(row.get("source_url")):
                raise ValueError("Quote requires a source and HTTPS source URL")
            output.append({**row, "as_of": iso(row["as_of"]), "frequency": "intraday", "delay": row.get("delay", "Unknown delay")})
        return output
    if not settings.te_api_key:
        return []
    symbols = {settings.te_10y_symbol: "10Y", settings.te_30y_symbol: "30Y"}
    data = get("https://api.tradingeconomics.com/markets/symbol/" + ",".join(symbols), params={"c": settings.te_api_key, "f": "json"}).json()
    if not isinstance(data, list):
        raise ValueError("Quote subscription did not return a quote array")
    output = []
    for row in data:
        if row.get("Symbol") not in symbols or not row.get("Date"):
            continue
        if str(row.get("Unit", "")).lower() not in {"percent", "%"}:
            raise ValueError("Provider did not identify quote units as percent")
        stamp = datetime.fromisoformat(row["Date"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        # LastUpdate is vendor ingestion time; Date is the observation's timestamp.
        output.append(dict(tenor=symbols[row["Symbol"]], value=number(row.get("Last")),
            as_of=iso(stamp), frequency="intraday", delay=row.get("Type", "Unknown delay"),
            source="Trading Economics", source_url="https://tradingeconomics.com" + row.get("URL", "/")))
    return output
