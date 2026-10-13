# Put your dashboard on Streamlit

1. Extract **Treasury_Observatory_Streamlit.zip**.
2. Create a GitHub repository and upload everything **inside** `treasury_dashboard/`.
   Check that `app.py`, `requirements.txt`, `treasury/`, `.github/` and `.streamlit/`
   are present. Do not upload the ZIP itself as the application.
3. Go to **https://share.streamlit.io/** → Create app → select that repository →
   main file **app.py** → Python **3.12** → Deploy.
4. The daily-data preview can run immediately. For the full dashboard, open the app's
   **Settings → Secrets** and use `.streamlit/secrets.toml.example` as the template.

The three connections for the full version:

- **DATABASE_URL:** a persistent PostgreSQL database. This protects the history.
- **OPENAI_API_KEY:** enables web research for new release dates, consensus, actuals
  and the saved rate outlook. API usage is billed separately.
- **Treasury quote feed:** either Trading Economics with the necessary entitlements,
  or an HTTPS feed using the documented format. This supplies intraday yields.
  Without it, the app shows daily Treasury history and labels it accordingly.

Add the same secrets under **GitHub → Settings → Secrets and variables → Actions**,
then run **Actions → Collect Treasury observations → Run workflow**. That keeps data
collection running when the page is closed. GitHub's 15-minute schedule is best effort;
use the included `worker.py` on an always-on host for more frequent quote capture.

Unknown consensus and release dates stay **n.a.** until verified. The launch timestamp
is created when this database is first used; it survives later deployments. Start with
a separate test database if you want to choose the production launch day later.

The detailed connection instructions, data rules, API budget controls and methodology
are in **README.md**. **VALIDATION.md** explains what has and has not been tested.
