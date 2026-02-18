# Google Sheets Setup Guide

This takes about 10–15 minutes. You only need to do it once.

---

## Step 1 — Create a Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com) and create a new blank spreadsheet
2. Name it something like **Experiment Log**
3. Copy the **Sheet ID** from the URL — it's the long string between `/d/` and `/edit`:
   ```
   https://docs.google.com/spreadsheets/d/THIS_PART_HERE/edit
   ```

---

## Step 2 — Create a Google Cloud Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. In the left menu go to **APIs & Services → Library**
4. Search for and enable both:
   - **Google Sheets API**
   - **Google Drive API**
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → Service Account**
7. Give it any name (e.g. `experiment-logger`) and click **Done**
8. Click on the service account you just created
9. Go to the **Keys** tab → **Add Key → Create new key → JSON**
10. Download the JSON file — keep it safe, you'll need the values inside

---

## Step 3 — Share the Sheet with the Service Account

1. Open your Google Sheet
2. Click **Share**
3. Paste the service account's email address (it looks like `name@project.iam.gserviceaccount.com` — it's in the JSON file as `client_email`)
4. Give it **Editor** access
5. Click **Send**

---

## Step 4 — Add Secrets to Streamlit Cloud

1. Go to your app on [share.streamlit.io](https://share.streamlit.io)
2. Click the **⋮** menu next to your app → **Settings → Secrets**
3. Paste the following, filling in values from your downloaded JSON file and your Sheet ID:

```toml
[gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = "-----BEGIN RSA PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END RSA PRIVATE KEY-----\n"
client_email = "YOUR_SERVICE_ACCOUNT@YOUR_PROJECT.iam.gserviceaccount.com"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CERT_URL"

[google_sheets]
sheet_id = "YOUR_GOOGLE_SHEET_ID"
```

> ⚠️ The `private_key` field needs literal `\n` characters (not actual newlines) — copy it exactly as it appears in the JSON file.

4. Click **Save** — the app will restart automatically

---

## Step 5 — For Local Development (optional)

If you want to run the app locally with Sheets access:

1. Create a `.streamlit/` folder in your project directory
2. Copy `secrets_template.toml` to `.streamlit/secrets.toml`
3. Fill in the values from your JSON credentials file
4. `.streamlit/secrets.toml` is already in `.gitignore` so it won't be committed

---

## Verification

Once set up, press **Log Run** — a new row should appear in your Google Sheet within a couple of seconds. The sheet will auto-create a header row on the first log.

If you see an error, the most common causes are:
- The sheet hasn't been shared with the service account email
- The Sheet ID in secrets is wrong
- The Google Sheets API hasn't been enabled in your project
