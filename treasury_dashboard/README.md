# Treasury Observatory

A GitHub-ready Streamlit dashboard for US 10-year and 30-year Treasury yields,
upcoming macro releases, consensus, observed market reactions and a retained outlook history.

## Start here

1. **Create a GitHub repository** and upload the contents of this folder to its root.
   `app.py` and `requirements.txt` must be at the repository root. Include the hidden
   `.streamlit` and `.github` folders. Do not upload a real secrets file.
2. **Deploy on Streamlit Community Cloud** at https://share.streamlit.io/.
   Select your repository, its main branch, and `app.py`. Select Python 3.12.
3. **Add Secrets** in Streamlit's app settings. The template is
   `.streamlit/secrets.toml.example`. For the intended persistent dashboard, set
   `DATABASE_URL` and `OPENAI_API_KEY`. A quote feed is a separate connection.
4. **Enable unattended updates.** Put the same secrets into GitHub → repository
   Settings → Secrets and variables → Actions. Run the included “Collect Treasury
   observations” workflow once. Its schedule then runs on weekdays every 15 minutes.

No credentials are bundled. The app is usable as a daily-data preview without keys,
but full research, consensus discovery, durable history and intraday charts require
the connections below. Nothing is seeded with fictional market data.

## What works with each connection

| Connection | Enables | Limitations |
|---|---|---|
| No key | FRED daily Treasury history; BLS, BEA and Fed calendar dates | Daily, not live; upstream availability/layout changes can interrupt pulls |
| `OPENAI_API_KEY` | Web research of new dates, actuals, market consensus and macro news; saved conditional outlooks | Paid, best effort, incomplete coverage possible; not a live Treasury quote feed |
| PostgreSQL `DATABASE_URL` | Shared durable event history and background collection | Use the same database for Streamlit and the scheduled collector |
| `TRADING_ECONOMICS_KEY` | Structured calendar/consensus/actuals and Treasury snapshots | Requires appropriate subscription entitlements; quotes may be delayed |
| `QUOTE_FEED_URL` | Custom timestamped intraday 10Y/30Y yield feed | Endpoint must match the contract below; provider controls data latency |
| `FRED_API_KEY` | FRED API instead of the public CSV endpoint | Still daily Treasury observations |

**No database configured:** SQLite is a local preview. Streamlit's local filesystem
does not provide durable shared history across restarts. The unattended workflow
refuses SQLite rather than pretending to retain a continuous record.

## Persistent database setup

Use a PostgreSQL provider (for example, a Supabase or Neon project). Create a database
and copy its connection string. For Supabase, use a supported session-pooler URL if
the direct connection is not reachable from your hosting environment. Require SSL.

Example shape (replace with your provider's actual value):

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
OPENAI_API_KEY = "YOUR_OPENAI_KEY"
OPENAI_MODEL = "gpt-4.1"
AUTO_COLLECT = true
RESEARCH_INTERVAL_MINUTES = 360
AI_DAILY_REQUEST_LIMIT = 8
```

URL-encode special characters in the username/password when your provider requires it.
The app creates `treasury_records` and `treasury_locks` tables; it does not alter other
tables. Keep database credentials server-side in Secrets. Never paste them into `app.py`.
Restrict access to the Streamlit app if the research is intended only for your team.

**Launch time** is set once, when the app or collector first connects to this database.
It survives restarts and deploys. Use a separate database for testing and production
if you want the production launch date to start only when Lopa begins using it.

## Reading the page

- The two upper charts show 10Y and 30Y yield history. Choose daily reference or
  intraday in the sidebar. The two series types are never spliced together.
- The calendar shows confirmed dates/times, reference periods, consensus and previous
  readings. Every tracked indicator stays visible even if its next release is unknown.
- Unknowns display **n.a.**. The scheduled collector checks again later.
- The outlook is a substantial, timestamped 1–3 month scenario analysis. It uses a saved
  evidence snapshot and retains every prior version. Any ranges are illustrative AI
  judgments, not calibrated forecasts. No AI connection means a clearly labelled
  framework paragraph with no invented numerical target.
- The post-launch ledger records actuals, pre-release consensus and observed yield moves.
  Charts compare actual with consensus and plot the 10Y/30Y reaction to every eligible
  release. Missing observations remain in the table as n.a.
- Commentary updates when valid yield pairs become available, with its versions retained.
  It gives a possible economic mechanism and flags overlapping releases, rather than
  claiming the entire move was caused by a single data point.
- JSON export includes the events, quote history, revisions, outlook evidence, commentary
  versions and audit trail. CSV export provides the displayed release ledger.

## Collection schedule and freshness

| Task | Default check frequency |
|---|---|
| Visible dashboard | Every 60 seconds |
| Intraday feed | At most once per 60 seconds when a collector is running |
| Official daily history and calendar pages | Every 6 hours |
| Trading Economics calendar | At most once per 5 minutes |
| AI calendar/actual/consensus research | Every 6 hours, or every 30 minutes for a recently due release missing its actual |
| AI outlook | Every 6 hours |
| GitHub Actions | Every 15 minutes on weekdays, subject to GitHub scheduling delays |

The refresh button checks due tasks; it does not bypass rate limits or the AI cap.
The page starts collection in a background thread, so a slow source does not freeze
the entire interface. Tasks and failures are shown under source health. A database
lease prevents the page and scheduled job collecting the same cycle concurrently.

**For minute-level event capture:** run `python worker.py` on an always-on host with
the same environment variables and a quote feed. GitHub cron can be delayed and does
not guarantee a pre-release sample within five minutes. A sleeping Streamlit app is
not an always-on collector. The worker captures quotes independently of background
research, so AI/calendar requests do not block quote capture. Its cadence is still
best effort; provider/network delays can affect it. Institutional low-latency capture
requires a streaming data provider and monitored infrastructure.

## Consensus and revision rules

The app stores every change to consensus, including source and capture time.
The surprise calculation uses the latest consensus **captured before the release**.
A consensus found afterwards is retained but is never backfilled into the prerelease
comparison. This avoids hindsight bias. `TEForecast` is deliberately excluded because
it is a provider forecast, not market consensus.

The first actual observed by this app is preserved, and subsequent differences are
recorded as revisions. If the initial pull was delayed, this first observed number
may already contain a publisher revision; the app cannot reconstruct a missed vintage.
It records the observation time so that limitation remains visible.

Each indicator has a precise unit and reference period. GDP advance/second/third
estimates and Michigan preliminary/final estimates have separate identities. Publication
dates are not substituted for observation months. Unknown release times are not
manufactured from the usual release pattern. Dates can be updated or explicitly withdrawn.

OpenAI research only accepts source URLs returned by its search tool. Actuals require
the indicator's official publisher; consensus uses retrieved Reuters or Trading Economics
pages. This reduces unsupported values but cannot guarantee that AI extracts every figure
correctly. Review source links before acting. Publication time and feed receipt time are
separate. No scraped consensus is assumed to be licensed for public redistribution.

## Yield-reaction methodology

For 15- or 60-minute reactions, the app requires:

- An intraday yield observation in the five minutes strictly **before** publication.
- A post-release observation at or after the target time, no more than ten minutes later.
- The same maturity, provider and delay regime on both sides.

No interpolation, daily substitution, or invented before/after prices. The actual sample
times are visible in the audit. Delayed feeds can only produce reactions after the relevant
observations have arrived.

The release-day-close option compares the preceding daily reference with the release-day
reference. It includes the day's other developments and is not an intraday event study.
FRED's date is an observation date, not an exact quote time. A 10Y/30Y auction's high yield
is a release metric, not a replacement for the secondary-market benchmark.

Formulas, with yields expressed in percent units (e.g. 4.00):

```
Percentage-point change = yield_after - yield_before
Basis-point change      = percentage_point_change * 100
Relative yield change % = (yield_after / yield_before - 1) * 100
Surprise                = actual - pre_release_consensus
```

4.00% → 4.10% is +0.10 percentage points, +10 bp, or +2.5% relative yield change.
None of these is the bond-price return. Concurrent releases share the same yield movement;
their impacts must not be added together. This app does not estimate a causal counterfactual.

## Quote feed contract

Set `QUOTE_FEED_URL` to an HTTPS endpoint you control or obtain from your provider.
Optional `QUOTE_FEED_TOKEN` is sent as an Authorization Bearer header. Do not put secrets
in the URL. The endpoint must return Treasury **yields**, not bond prices or futures prices:

```json
{
  "quotes": [
    {
      "tenor": "10Y",
      "instrument": "treasury_yield",
      "unit": "percent",
      "value": 4.25,
      "as_of": "2026-10-13T14:31:00Z",
      "source": "Your licensed provider",
      "source_url": "https://your-provider.example/treasury-yields",
      "delay": "15 minutes"
    }
  ]
}
```

This JSON is a **format example**, not market data. Return both 10Y and 30Y observations.
`as_of` must be the underlying market observation timestamp with a timezone, not the
time your API request ran. Return delayed timestamps honestly. Include the source's
instrument definition in your provider documentation. Values must be percentage units,
not fractions (4.25 rather than 0.0425). The adapter rejects invalid/future observations.

Trading Economics is already integrated as an optional alternative. Verify the configured
symbols and entitlements with the provider. The defaults are `USGG10YR:IND` and
`USGG30Y:IND`; override `TE_10Y_SYMBOL` / `TE_30Y_SYMBOL` if needed.

## AI budget

`AI_DAILY_REQUEST_LIMIT` counts attempted AI requests across the app and worker, with a
UTC daily reset. Both research and outlook calls count, including failures. Each research
request allows at most three web tool calls. Token charges are additional. The default
cap of 8 requests is deliberately conservative and can be exhausted on a busy release day;
later updates then wait until the next day. Adjust it and OpenAI project spend limits to
your chosen budget. A request-count cap is not a dollar cap.

Research and outlook are independent tasks. At the cap, the dashboard still refreshes
market feeds and official calendars, while retaining the previous AI output and timestamp.
Search cannot guarantee second-by-second market data or comprehensive consensus coverage.

## Run locally and test

```bash
python -m venv .venv
# Activate the virtual environment for your operating system.
pip install -r requirements.txt
streamlit run app.py
```

Use `.streamlit/secrets.toml` locally, or environment variables for the command-line
collector. The collector does not read Streamlit Secrets; GitHub supplies its own secrets.

```bash
python -m treasury.collector
pip install pytest
python -m pytest -q
```

Tests use synthetic fixtures in temporary databases; no fictional data ships in the app.
They check revision handling, look-ahead bias, unknowns, event timing, reaction units,
quote validation, source validation and UI execution. Live paid integrations require your
credentials and entitlements and should be checked on a real release before relying on them.

## Source references

- Streamlit deployment: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Streamlit Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- FRED daily Treasury series: https://fred.stlouisfed.org/series/DGS10 and https://fred.stlouisfed.org/series/DGS30
- BLS schedules: https://www.bls.gov/schedule/news_release/ (individual CPI, employment, PPI, JOLTS and ECI tables include the reference periods that the ICS feed can omit)
- BEA calendar: https://www.bea.gov/news/schedule
- Fed calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- OpenAI web search: https://developers.openai.com/api/docs/guides/tools-web-search
- Trading Economics calendar: https://docs.tradingeconomics.com/economic_calendar/country/
- Trading Economics quotes: https://docs.tradingeconomics.com/markets/symbols/
