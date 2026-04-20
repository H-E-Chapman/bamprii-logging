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

1. submit pull requests to the `main` branch of `h-e-chapman/bamprii-logging`, or create a branch
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

This logger collects experimental variables for experimental runs. It is centred on the assumption that there are persistent
variables, which are useful to collect, but change very infrequently, whilst other parameters might change everytime. 

**Variables** are defined in **Groups**, which can then be used to collect them.

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
  help: ""              # sets help text for info
  required: true        # blocks logging if empty
```

---

## Google Sheets Setup

See `SETUP_GOOGLE_SHEETS.md` for step-by-step instructions on creating a service account, enabling the API, and adding credentials to Streamlit Cloud secrets.

---

## File Structure

```
bamprii-logging/
├── app.py                      # Entry point: page config, session state, sidebar, tab layout
├── tab_log.py                  # Log Scan tab (tab 1): input form, validation, run logging
├── tab_plot.py            # Plot Results tab (tab 2): filters, axis config, bubble chart
├── sheets.py                   # SheetLogger class: all Google Sheets read/write logic
├── config.py                   # Config loading and derived helpers (col names, filterable cols)
├── utility.py                  # Pure formatting helpers for auto-increment counters
├── config.yaml                 # Variable groups and field definitions
├── requirements.txt
├── .gitignore
├── MXI.png                     # Page icon
├── MXI_logo.png                # Sidebar logo
├── README.md
└── SETUP_GOOGLE_SHEETS.md      # Credentials setup guide
```

### Module responsibilities

`app.py` owns the Streamlit entry point and nothing else — page config, session state initialisation, sidebar rendering, and delegating each tab to its module. It contains no function definitions.

`log_tab.py` and `visualisation.py` each expose a single public `render_*` function called from `app.py`. All internal logic is private to the module.

`sheets.py` contains a `SheetLogger` class that encapsulates all worksheet I/O. It is instantiated once via `get_sheet_logger()`, which is wrapped in `@st.cache_resource` to persist the connection across reruns.

`config.py` handles YAML loading (`@st.cache_data`) and provides helper functions for derived config values — column name formatting and filterable column resolution — so these are never computed inline.

`utility.py` contains only pure Python functions with no Streamlit dependency, making them independently testable. It handles counter formatting and parsing for `auto_increment` fields.