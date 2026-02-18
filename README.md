# 🧪 Experiment Logger

A Streamlit app for logging experimental runs across multiple people and machines.

## Features

- **Persistent fields** — values stay between log presses; only change what's different
- **Toggleable equipment groups** — enable/disable variable sets per session via the sidebar
- **Config-driven** — add/rename variables or groups by editing `config.yaml`, no code changes needed
- **CSV output** — all runs append to a single `experiment_log.csv`, downloadable from the sidebar
- **Run viewer** — see the last 20 runs inline

---

## Running Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Deploying to Streamlit Community Cloud (Free, Shared URL)

1. Push this repo to GitHub (make sure `experiment_log.csv` is in `.gitignore`)
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub
3. Click **New app**, select your repo and `app.py`
4. Click **Deploy** — you'll get a public URL to share with your team

> **Note on shared data:** Streamlit Community Cloud gives each app a persistent filesystem, but it resets on redeployment. For a shared log across multiple users/machines, see the Google Sheets backend option below.

---

## Configuring Variables (`config.yaml`)

Each group has a name, an `always_on` flag, and a list of variables:

```yaml
groups:
  - name: My Group
    always_on: false
    variables:
      - name: My Variable
        type: float        # float | integer | text | select
        default: 0.0
      - name: Category
        type: select
        options: [Option A, Option B, Option C]
        default: Option A
      - name: Run ID
        type: text
        default: ""
        required: true     # Blocks logging if empty
```

**Types:** `float`, `integer`, `text`, `select`

Add up to 5–6 groups with 5–6 variables each — the UI arranges them automatically in a 2-column grid.

---

## Shared Data: Google Sheets Backend (Optional)

For true multi-user shared logging (everyone writes to the same log in real time), you can replace the CSV backend with Google Sheets using the `gspread` library. Steps:

1. Create a Google Service Account and share a Sheet with it
2. Store credentials in `.streamlit/secrets.toml`
3. Replace the `load_log()` and `append_log()` functions in `app.py` with gspread calls

A drop-in replacement module can be added on request.

---

## File Structure

```
experiment_logger/
├── app.py              # Main Streamlit app
├── config.yaml         # Variable groups and field definitions
├── requirements.txt
├── .gitignore
└── README.md
```
