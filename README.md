# BAMPR-II Experiment Logger

A Streamlit app for logging experimental runs on the Blown-powder Additive Manufacturing Process Replicator, version II. Built for multi-user, multi-machine use across beamtime sessions.

---

## Running Locally
```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

---

## Deployment

Hosted on Streamlit Community Cloud. To redeploy:

1. Push changes to the `main` branch of `h-e-chapman/bamprii-logging`
2. The app redeploys automatically at the shared URL

Google Sheets credentials are stored in Streamlit Cloud's secrets vault — never commit `.streamlit/secrets.toml` to the repo.

---

## Features

- **Persistent fields** — values stay between log presses; only change what's different from the last run
- **Toggleable equipment groups** — enable/disable variable sets per session via the sidebar
- **Auto-incrementing fields** — Run ID and scan numbers increment automatically on each log press, with manual override and re-sync from sheet
- **Google Sheets backend** — every log press appends a row to the shared sheet in real time; all users write to the same log
- **Plot tab** — bubble chart with configurable X/Y axes, colour, point grouping tolerance, and filter panel; data loaded on demand via a refresh button

---

## Configuring Variables (`config.yaml`)

Groups and variables are defined in `config.yaml`. No code changes are needed to add, rename, or reorder fields.

**Group flags:**

| Flag | Description |
|---|---|
| `always_on` | Group cannot be toggled off in the sidebar |
| `filterable` | Group's variables appear as filter and axis options in the Plot tab |

**Variable types:**

| Type | Description |
|---|---|
| `float` | Decimal number |
| `integer` | Whole number |
| `text` | Free text input |
| `select` | Dropdown — requires an `options` list and a `default` |
| `auto_increment` | Automatically increments on each log press — see below |

**Auto-increment options:**
```yaml
- name: Run ID
  type: auto_increment
  format: prefixed      # padded | prefixed
  prefix: "RUN"         # used when format: prefixed
  pad: 3                # zero-pad width → RUN001
  start: 1              # starting number
```

**Other variable options:**
```yaml
- name: My Variable
  type: float
  default: 0.0
  required: true        # blocks logging if empty
```

---

## Google Sheets Setup

See `SETUP_GOOGLE_SHEETS.md` for step-by-step instructions on creating a service account, enabling the API, and adding credentials to Streamlit Cloud secrets.

---

## File Structure
```
bamprii-logging/
├── app.py                      # Main Streamlit app
├── config.yaml                 # Variable groups and field definitions
├── requirements.txt
├── .gitignore
├── MXI.png                     # Page icon
├── README.md
└── SETUP_GOOGLE_SHEETS.md      # Credentials setup guide
```