# BAMPR-II Experiment Logger

A Streamlit app for logging experimental runs on the Blown-powder Additive Manufacturing Process Replicator, version II. Built for multi-user, multi-machine use across beamtime sessions.

---

## Running Locally

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

Sheets access needs `.streamlit/secrets.toml` — see `SETUP_GOOGLE_SHEETS.md`.

---

## Deployment

Hosted on Streamlit Community Cloud. To redeploy:

1. Submit a pull request to the `main` branch of `h-e-chapman/bamprii-logging`
2. The app redeploys automatically at the shared URL

Google Sheets credentials live in Streamlit Cloud's secrets vault — never commit `.streamlit/secrets.toml`.

---

## Features

- **Persistent fields** — values stay between log presses; only change what differs from the last run
- **Toggleable equipment groups** — enable/disable variable sets per session via the sidebar; values survive toggling
- **⭐ Frequent card** — pick any fields in the sidebar to show them together at the top of the Log tab, or press one button to pin every field that changed in more than an adjustable share (default 10%) of the last 100 runs, then arrange them with ▲ ▼; they still log to their own group's column
- **Auto-incrementing fields** — Run ID and scan numbers advance on each log press, with manual override and re-sync from the sheet. If another user has already logged the next ID, the app skips past it and tells you
- **Google Sheets backend** — every log press appends a row to the shared sheet; reads are cached for a minute so several operators do not exhaust the shared API quota
- **Plot tab** — bubble chart with configurable X/Y axes, colour, point grouping and a filter panel, plus derived quantities (energy densities etc.) defined in `config.yaml`
- **Experiment Design tab** — comparative tests (Welch's t-test), screening designs (Plackett–Burman, fractional factorials) and response-surface designs (full factorial, CCD, Box–Behnken) with downloadable run tables
- **Calculators tab** — powder delivery rate from feeder rpm

---

## Configuring (`config.yaml`)

Everything the logger collects is defined in `config.yaml`. No code changes are needed to add, rename or reorder fields. The config is validated on start-up; mistakes (unknown types, select defaults not in their options) stop the app with a message naming the field.

### App-wide settings

| Key | Description |
|---|---|
| `timezone` | IANA name (e.g. `Europe/London`) used for the Timestamp column |
| `default_plot_x` / `default_plot_y` / `default_plot_colour` | Initial axis choices in the Plot tab, as `"Group: Variable"` column names |
| `default_filters` | Map of column name → list of values pre-selected in the filter panel |
| `derived` | Derived quantities for the Plot tab — see below |
| `powder_calibration` | Feeder calibration factor and default powder density for the calculator |

### Groups and variables

Variables are defined in **groups**. Some groups hold persistent values that change rarely (laser, optics), others change every run.

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
| `select` | Dropdown — requires an `options` list; omit `default` to start on a "Select…" placeholder (add `required: true` to block logging until a value is chosen) |
| `auto_increment` | Automatically increments on each log press — see below |

**Auto-increment options:**
```yaml
- name: Run ID
  type: auto_increment
  format: prefixed      # padded | prefixed
  prefix: "RUN"         # used when format: prefixed
  pad: 4                # zero-pad width → RUN0001
  start: 1              # starting number
```

**Other variable options:**
```yaml
- name: My Variable
  type: float
  default: 0.0
  help: "Shown as a tooltip"   # optional
  required: true               # blocks logging if empty
```

### Derived quantities

Each entry names a column that appears in the Plot tab when all of its source columns exist in the log. `inputs` maps a short alias to a `"Group: Variable"` column and `formula` is arithmetic over those aliases; the result must be one value per run:

```yaml
derived:
  - name: Linear Energy Density (J/mm)
    formula: power / speed
    inputs:
      power: "Laser Processing Parameters: Laser Power (W)"
      speed: "Laser Processing Parameters: Scan Speed (mm/s)"
    exclude_zero: [speed]          # optional: leave out runs where these are 0
    note: "Optional caveat shown under the definition"
```

---

## Google Sheets Setup

See `SETUP_GOOGLE_SHEETS.md` for creating a service account, enabling the API, and adding credentials to Streamlit Cloud secrets.

---

## File Structure

```
bamprii-logging/
├── app.py                  # Entry point: page config, session state, sidebar, tab layout
├── tab_log.py              # Log Scan tab: form state, input widgets, logging actions
├── tab_plot.py             # Plot Results tab: filters, derived quantities, bubble chart
├── tab_DoE.py              # Experiment Design tab: comparative, screening and RSM designs
├── tab_calc.py             # Calculators tab
├── sheets.py               # SheetLogger: cached Google Sheets read/write
├── config.py               # Config loading, validation and helpers
├── utility.py              # Pure helpers for auto-increment counters (no Streamlit)
├── config.yaml             # Variable groups, derived quantities, app settings
├── requirements.txt
├── MXI.png                 # Page icon
├── MXI_logo.png            # Sidebar logo
├── README.md
└── SETUP_GOOGLE_SHEETS.md  # Credentials setup guide
```

### Module responsibilities

`app.py` owns the Streamlit entry point: page config, loading config and the sheet connection, seeding session state, the sidebar, and delegating each tab to its module.

Each `tab_*.py` exposes `render_*_tab()`; `tab_log.py` additionally exposes `init_session_state()`, `render_pin_controls()` and `render_action_buttons()` because the sidebar hosts the Frequent-field picker and the logging actions.

`sheets.py` contains `SheetLogger`, instantiated once via `get_sheet_logger()` (`@st.cache_resource`). All reads go through `load()`, cached with a short TTL and cleared on every write.

`config.py` loads and validates the YAML (`@st.cache_data`) and provides helpers for column names and default values.

`utility.py` is pure Python with no Streamlit dependency.
