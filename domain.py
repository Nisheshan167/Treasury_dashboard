import hashlib
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

UTC = timezone.utc


def utcnow():
    return datetime.now(UTC)


def iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A timestamp must include a timezone")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def dt(value):
    return datetime.fromisoformat(iso(value)) if value else None


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def web_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname else None


# Labels encode exactly what a consensus is predicting; incompatible units are rejected.
CATALOG = {
    "cpi_core": ("Core CPI · MoM", "%", "Inflation", "Highest", "CPI", "bls.gov"),
    "cpi_headline": ("CPI · MoM", "%", "Inflation", "Highest", "CPI", "bls.gov"),
    "pce_core": ("Core PCE · MoM", "%", "Inflation", "Highest", "PCE", "bea.gov"),
    "pce_headline": ("PCE · MoM", "%", "Inflation", "High", "PCE", "bea.gov"),
    "payrolls": ("Nonfarm payrolls · change", "thousand", "Employment", "Highest", "Jobs report", "bls.gov"),
    "unemployment": ("Unemployment rate", "%", "Employment", "Highest", "Jobs report", "bls.gov"),
    "wages": ("Average hourly earnings · MoM", "%", "Employment", "High", "Jobs report", "bls.gov"),
    "fed_rate": ("Fed target range · upper bound", "%", "Federal Reserve", "Highest", "FOMC", "federalreserve.gov"),
    "fed_press": ("FOMC press conference", "text", "Federal Reserve", "Highest", "FOMC press", "federalreserve.gov"),
    "fed_minutes": ("FOMC minutes", "text", "Federal Reserve", "High", "FOMC minutes", "federalreserve.gov"),
    "ism_mfg": ("ISM manufacturing PMI", "index", "Growth", "High", "ISM manufacturing", "ismworld.org"),
    "ism_services": ("ISM services PMI", "index", "Growth", "High", "ISM services", "ismworld.org"),
    "retail": ("Retail sales · MoM", "%", "Growth", "High", "Retail sales", "census.gov"),
    "ppi": ("PPI final demand · MoM", "%", "Inflation", "High", "PPI", "bls.gov"),
    "claims": ("Initial jobless claims", "thousand", "Employment", "High", "Jobless claims", "dol.gov"),
    "gdp_advance": ("Real GDP · advance · QoQ annualized", "%", "Growth", "High", "GDP advance", "bea.gov"),
    "gdp_second": ("Real GDP · second · QoQ annualized", "%", "Growth", "Supporting", "GDP second", "bea.gov"),
    "gdp_final": ("Real GDP · third · QoQ annualized", "%", "Growth", "Supporting", "GDP third", "bea.gov"),
    "jolts": ("JOLTS job openings", "million", "Employment", "Supporting", "JOLTS", "bls.gov"),
    "eci": ("Employment Cost Index · QoQ", "%", "Employment", "High", "ECI", "bls.gov"),
    "michigan_prelim": ("Michigan 5–10Y inflation expectations · preliminary", "%", "Inflation", "High", "Michigan preliminary", "umich.edu"),
    "michigan_final": ("Michigan 5–10Y inflation expectations · final", "%", "Inflation", "Supporting", "Michigan final", "umich.edu"),
    "auction_10y": ("10Y Treasury auction · high yield", "%", "Treasury supply", "High", "10Y auction", "treasurydirect.gov"),
    "auction_30y": ("30Y Treasury auction · high yield", "%", "Treasury supply", "High", "30Y auction", "treasurydirect.gov"),
    "refunding": ("Quarterly refunding announcement", "text", "Treasury supply", "High", "Refunding", "treasury.gov"),
}


def event_key(indicator, reference):
    return hashlib.sha256(f"{indicator}|{reference}".encode()).hexdigest()[:24]


def make_event(indicator, reference, **values):
    label, unit, category, priority, group, _ = CATALOG[indicator]
    if not re.fullmatch(r"\d{4}-(?:\d{2}(?:-\d{2})?|Q[1-4])", reference):
        raise ValueError("Reference must be YYYY-MM, YYYY-MM-DD or YYYY-QN")
    result = dict(id=event_key(indicator, reference), indicator=indicator,
                  reference=reference, label=label, unit=unit, category=category,
                  priority=priority, group=group, release_at=None, date_only=None,
                  consensus=None, consensus_source=None, previous=None,
                  actual=None, actual_text=None, actual_source=None, date_source=None)
    result.update(values)
    return result


def fmt(value, unit="%"):
    val = number(value)
    if val is None:
        return "n.a."
    return f"{val:,.2f}" + {"%": "%", "thousand": "k", "million": "m", "index": ""}.get(unit, "")


def event_status(event, now=None):
    if event.get("actual") is not None or event.get("actual_text"):
        return "Released"
    if not event.get("release_at"):
        return "Date/time pending"
    return "Awaiting actual" if dt(event["release_at"]) <= (now or utcnow()) else "Upcoming"


def surprise(event):
    actual, forecast = event.get("actual"), event.get("frozen_consensus")
    return actual - forecast if actual is not None and forecast is not None else None
