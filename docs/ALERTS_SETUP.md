# Setting up email alerts

The code is done: the sign-up form and links (`ui/app.py`), the logic and emails (`ui/alerts.py`),
the daily job (`scripts/send_alerts.py`), and its schedule (`.github/workflows/alerts.yml`).
Until the steps below are done, the alerts section on the live site says "Coming soon"
and nothing is sent. Allow about 30 minutes.

**Who:** whoever owns these accounts is responsible for them. If you're under 18, a parent or
teacher may need to create or co-own the Gmail and Supabase accounts.

## 1. Team Gmail that sends the alerts
1. Create a new Gmail just for the app (e.g. `safebeachesoahu@gmail.com`). Don't use a personal one.
2. Turn on **2-Step Verification**: Google Account → Security → 2-Step Verification.
3. Create an **app password**: Google Account → Security → 2-Step Verification → App passwords.
   Name it "Safe Beaches". Google shows a 16-letter password **once**: copy it.
   (Gmail allows about 500 emails a day.)

## 2. Supabase table that stores subscribers
1. Sign up at supabase.com (free) → **New project** (any name, a strong database password, region
   "West US").
   Under the security options: **Enable Data API: on** (the app talks to the table through it),
   **Automatically expose new tables: off** (the SQL below grants access itself), **Enable
   automatic RLS: on**.
2. **SQL Editor → New query**, paste all of `scripts/alerts_schema.sql`, click **Run**. It creates
   the `subscribers` table with row-level security on, so the public can't read it.
3. **Project Settings → API**: copy the **Project URL** and the **service_role** key. The
   service_role key is a secret: never paste it in code, the repo, or a chat.

## 3. Give the app the five settings (Streamlit secrets)
Only the account that deployed the app can do this. On share.streamlit.io: the app's **⋮ →
Settings → Secrets**, paste and fill in:

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_SERVICE_KEY = "the service_role key"
GMAIL_ADDRESS = "safebeachesoahu@gmail.com"
GMAIL_APP_PASSWORD = "the 16-letter app password"
APP_URL = "https://safebeachesoahu.streamlit.app"
```

## 4. Give the daily job the same five (GitHub secrets)
GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**. Add each of
the five names above with the same values.

## 5. Test it
1. On the live site, sign up for a beach with your own email. Confirm from the email (check spam).
2. GitHub → **Actions → Daily beach alerts → Run workflow**, keep "dry run" ticked: the log prints
   the emails it *would* send, and nothing is sent or changed.
3. Run it again with "dry run" unticked to send for real. After that it runs by itself every
   morning at about 5:30am Hawaiʻi time. Scheduled runs only start once this file is on `main`.

## Rules the code follows
- Emails go only to confirmed addresses, and every email has an unsubscribe link.
- One email the morning a beach crosses your level, one when it drops back under. No repeats.
- Only the email, beach, level, and a random link token are stored. Unsubscribing deletes the row.
- Wording is always "forecast", never "the water is unsafe", and says it's not an official advisory.
