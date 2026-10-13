# Validation of this delivery

- Python compilation: passed for the app, modules and worker.
- Automated suite: **21 tests passed**.
- Streamlit AppTest: empty and populated dashboards executed without app exceptions;
  intraday/daily, reaction-window and relative-change controls exercised.
- Point-in-time tests: late consensus exclusion, frozen pre-release consensus,
  original actual preservation, revisions and rescheduled/withdrawn dates.
- Reaction tests: basis-point/percentage-point/relative arithmetic, same-source pairing,
  strict sampling windows, no daily-to-intraday substitution and launch cutoff.
- Data validation: missing/uncited values, incompatible units, future/NaN quotes,
  quote deduplication and the collector lease.
- Calendar tests: daylight-saving conversion, known dates with unknown times,
  GDP estimate vintages and FOMC dates without guessed release times.
- Public-source checks during development: FRED returned **546** daily observations
  across the two maturities; BEA returned **9** parsed indicator entries; the Fed
  calendar returned **54** meeting-date entries before historical filtering; BLS CPI
  returned **28** indicator entries. Counts are snapshots, not future guarantees.

Not exercised with credentials: OpenAI paid web research/outlook calls, Trading Economics
entitlements, a custom intraday feed and a hosted PostgreSQL deployment. Their adapters
and source/record validation are implemented, but require a live connection test with
your accounts. End-to-end unattended collection has not run on your GitHub repository.

UI verification used Streamlit's application test framework. A browser screenshot/pixel
review was not performed in this environment. No sample market data, database contents,
real credentials or temporary test files are included in the delivery.

This is a functional first version with explicit setup dependencies. Run it through a
real economic release and check its sources and timestamps before operational reliance.
