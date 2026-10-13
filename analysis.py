from datetime import timedelta
from .domain import dt, iso, fmt, surprise, CATALOG


def latest_quotes(quotes):
    result = []
    for tenor in ["10Y", "30Y"]:
        rows = sorted([q for q in quotes if q["tenor"] == tenor], key=lambda q: q["as_of"])
        if rows:
            result.append(rows[-1])
    return result


def released_since(events, launch_at):
    return sorted([e for e in events if e.get("release_at") and dt(e["release_at"]) >= dt(launch_at)
                   and e.get("actual_first_seen")], key=lambda e: e["release_at"], reverse=True)


def reaction(event, quotes, tenor, window="60 min"):
    if not event.get("release_at"):
        return None
    release = dt(event["release_at"])
    if window == "Release-day close":
        from zoneinfo import ZoneInfo
        day = release.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        daily = [q for q in quotes if q["tenor"] == tenor and q["frequency"] == "daily"]
        before = sorted([q for q in daily if q["observation_date"] < day], key=lambda q: q["observation_date"])
        after = [q for q in daily if q["observation_date"] == day]
        if not before or not after:
            return None
        pre, post = before[-1], after[-1]
        if (release.date() - dt(pre["as_of"]).date()).days > 5:
            return None
    else:
        minutes = {"15 min": 15, "60 min": 60}[window]
        target = release + timedelta(minutes=minutes)
        intraday = [q for q in quotes if q["tenor"] == tenor and q["frequency"] == "intraday"]
        # Keep provider and delay regime consistent across the event window.
        candidates = []
        for source in sorted({(q["source"], q.get("delay")) for q in intraday}):
            rows = [q for q in intraday if (q["source"], q.get("delay")) == source]
            before = sorted([q for q in rows if release - timedelta(minutes=5) <= dt(q["as_of"]) < release], key=lambda q: q["as_of"])
            after = sorted([q for q in rows if target <= dt(q["as_of"]) <= target + timedelta(minutes=10)], key=lambda q: q["as_of"])
            if before and after:
                candidates.append((before[-1], after[0]))
        if not candidates:
            return None
        pre, post = min(candidates, key=lambda p: (release-dt(p[0]["as_of"])).total_seconds() + (dt(p[1]["as_of"])-target).total_seconds())
    change = post["value"] - pre["value"]
    return dict(before=pre["value"], after=post["value"], pp=change, bp=change * 100,
        relative_pct=change / pre["value"] * 100 if pre["value"] else None,
        before_at=pre["as_of"], after_at=post["as_of"], source=pre["source"], delay=pre.get("delay"), window=window)


def commentary(event, quotes, all_events, window="60 min"):
    delta = surprise(event)
    if event.get("actual") is not None:
        words = f"{event['label']} for {event['reference']} was first observed at {fmt(event['actual'], event['unit'])}. "
        if delta is not None:
            unit = "percentage points" if event["unit"] == "%" else event["unit"]
            words += f"It was {abs(delta):.2f} {unit} {'above' if delta > 0 else 'below' if delta < 0 else 'away from'} the pre-release consensus of {fmt(event['frozen_consensus'], event['unit'])}. "
        else:
            words += "A consensus captured before publication is unavailable, so the surprise is n.a. "
    else:
        words = str(event.get("actual_text") or "The event has been published.") + " "
    moves = []
    for tenor in ["10Y", "30Y"]:
        r = reaction(event, quotes, tenor, window)
        if r:
            moves.append(f"{tenor} {'rose' if r['bp'] > 0 else 'fell' if r['bp'] < 0 else 'was unchanged by'} {abs(r['bp']):.1f} bp ({r['pp']:+.3f} percentage points), from {r['before']:.3f}% to {r['after']:.3f}%")
    if moves:
        words += f"Observed {window.lower()} movement: " + "; ".join(moves) + ". "
    else:
        words += f"The {window.lower()} yield reaction is n.a.; suitable timestamped observations are not yet available. "
    if delta is not None and abs(delta) > 1e-10 and event["category"] in {"Inflation", "Employment", "Growth"}:
        stronger = delta > 0
        if event["indicator"] in {"claims", "unemployment"}:
            stronger = not stronger
        words += ("The surprise could support higher yields through stronger activity, inflation or tighter-policy expectations. " if stronger else "The surprise could support lower yields through softer activity, inflation or easier-policy expectations. ")
        words += "This is a possible mechanism, not an estimate of this release's isolated effect. "
    if event.get("release_at"):
        near = {e["group"] for e in all_events if e["id"] != event["id"] and e.get("release_at")
                and abs((dt(e["release_at"]) - dt(event["release_at"])).total_seconds()) <= 3600}
        if near:
            words += "Other releases within an hour: " + ", ".join(sorted(near)) + ". "
    if event.get("revisions"):
        words += "Later revisions are recorded separately; this comparison preserves the first observed value. "
    words += "Simultaneous releases, positioning and unrelated news may explain some or all of the move."
    return words


def fallback_outlook(quotes, events, launch_at):
    latest = latest_quotes(quotes)
    levels = "; ".join(f"{q['tenor']} {q['value']:.3f}% ({q['as_of'][:10]}, {q['frequency']})" for q in latest) or "no verified Treasury observations yet"
    count = len(released_since(events, launch_at))
    return (f"The current verified reference levels are {levels}. The post-launch record contains {count} released indicator observations. "
        "The next one to three months should be assessed conditionally: persistently firmer inflation, stronger activity, a higher expected policy path or greater long-dated supply pressure could push yields higher; "
        "softer inflation and employment or increased demand for safe assets could support lower yields. The 30-year maturity also reflects long-run inflation uncertainty and the compensation investors require for holding duration. "
        "A Fed cut alone would not establish the direction of the 10-year or 30-year yield. This panel has not produced a numerical forecast: scenario ranges remain n.a. until the analysis service has sufficient sourced evidence. "
        "Use the release ledger to distinguish actual surprises from revisions and to check whether a reported yield reaction has valid observations on both sides of publication.")
