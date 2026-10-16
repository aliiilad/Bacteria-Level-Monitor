#!/usr/bin/env python3
"""Daily email alerts. Run by .github/workflows/alerts.yml every morning (about 5:30am HST).

Scores every beach from today's Open-Meteo forecast, then emails each confirmed subscriber whose
beach crossed their level since yesterday (see ui/alerts.py for the rules).

    python scripts/send_alerts.py            # real run: needs the five settings as env vars
    python scripts/send_alerts.py --dry-run  # prints the emails instead of sending them and
                                             # changes nothing (works without any settings)
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ui"))

import pandas as pd  # noqa: E402

import alerts  # noqa: E402
import risk_model  # noqa: E402


class DemoStore:
    """Two pretend subscribers, for --dry-run without a database. Nothing is saved."""

    def __init__(self):
        self.rows = [{"email": "demo1@example.com", "site_id": "777", "level": 0.30, "token": "demo-1",
                      "confirmed": True, "alerted": False},
                     {"email": "demo2@example.com", "site_id": "8894", "level": 0.60, "token": "demo-2",
                      "confirmed": True, "alerted": True}]

    def confirmed(self):
        return self.rows

    def set_alerted(self, token, alerted):
        pass


def print_email(settings, to, subject, text, html):
    print(f"\n----- to {to}\nSubject: {subject}\n\n{text}\n-----")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print emails, send and change nothing")
    args = ap.parse_args()

    settings = {name: os.environ.get(name, "") for name in alerts.SETTING_NAMES}
    missing = alerts.missing_settings(settings)
    if args.dry_run:
        settings["APP_URL"] = settings["APP_URL"] or "https://safebeachesoahu.streamlit.app"
        store = alerts.SupabaseStore(settings) if settings["SUPABASE_URL"] and settings["SUPABASE_SERVICE_KEY"] else DemoStore()
        if isinstance(store, alerts.SupabaseStore):
            store.set_alerted = lambda token, alerted: None   # read real subscribers, change nothing
        send = print_email
    else:
        if missing:
            sys.exit(f"Missing settings: {', '.join(missing)}. Add them as GitHub secrets.")
        store, send = alerts.SupabaseStore(settings), alerts.send_email

    model = risk_model.load_model()
    beaches = pd.read_csv(ROOT / "data" / "processed" / "beaches.csv").to_dict("records")
    alerts.run_daily(settings, store, model, beaches, send=send)


if __name__ == "__main__":
    main()
