"""Email alerts: subscribers, the daily decision, and the emails themselves. Plain Python, no
Streamlit, so both the app (sign-up, confirm, unsubscribe) and the daily job
(scripts/send_alerts.py) can import it.

How it works
- Someone signs up in the app with an email, a beach, and a level (30% or 60%). We store only
  those, plus a random token, in a Supabase table, and email them a confirmation link.
- Every morning a GitHub Actions job scores every beach, and emails each confirmed subscriber
  only when their beach CROSSES their level: one "turned risky" email, then one "back to
  lower risk" email when it drops below again. No repeats on the days in between.
- Every email carries an unsubscribe link (the same token).

Settings come from a dict (the app reads Streamlit secrets, the job reads environment
variables): SUPABASE_URL, SUPABASE_SERVICE_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, APP_URL.
"""
import re
import secrets
import smtplib
from email.message import EmailMessage

import requests

import recommend
import risk_model

LEVELS = {0.30: "caution or worse (30%+)", 0.60: "likely unsafe (60%+)"}
STAYING = {0.30: "at caution or worse", 0.60: "likely unsafe"}  # "...staying <this> through Sunday"
LOWER_RISK_BELOW = 0.30  # "lower-risk beaches nearby" = the app's green band, as on the website
SETTING_NAMES = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "APP_URL"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TABLE = "subscribers"


def missing_settings(settings):
    """Names of the settings that are not filled in (alerts stay off until this is empty)."""
    return [name for name in SETTING_NAMES if not settings.get(name)]


def valid_email(email):
    return bool(EMAIL_RE.match(email.strip())) and len(email) <= 254


# --------------------------------------------------------------------------- storage
class SupabaseStore:
    """The subscribers table, through Supabase's REST API. The service key stays on the server
    (Streamlit and GitHub secrets); the table has row-level security on and no public access."""

    def __init__(self, settings):
        self.url = settings["SUPABASE_URL"].rstrip("/") + f"/rest/v1/{TABLE}"
        key = settings["SUPABASE_SERVICE_KEY"]
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"}

    def _call(self, method, params=None, json=None, prefer=None):
        headers = dict(self.headers, **({"Prefer": prefer} if prefer else {}))
        resp = requests.request(method, self.url, params=params, json=json, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else []

    def add(self, email, site_id, level):
        """Create (or reset) an unconfirmed subscription and return its new token."""
        token = secrets.token_urlsafe(24)
        self._call("POST", params={"on_conflict": "email,site_id"},
                   json={"email": email, "site_id": str(site_id), "level": level, "token": token,
                         "confirmed": False, "alerted": False},
                   prefer="resolution=merge-duplicates,return=minimal")
        return token

    def confirm(self, token):
        """Mark a subscription confirmed. Returns the row, or None for an unknown token."""
        rows = self._call("PATCH", params={"token": f"eq.{token}"}, json={"confirmed": True},
                          prefer="return=representation")
        return rows[0] if rows else None

    def unsubscribe(self, token):
        """Delete a subscription. Returns the deleted row, or None for an unknown token."""
        rows = self._call("DELETE", params={"token": f"eq.{token}"}, prefer="return=representation")
        return rows[0] if rows else None

    def confirmed(self):
        return self._call("GET", params={"confirmed": "eq.true", "select": "*"})

    def set_alerted(self, token, alerted):
        self._call("PATCH", params={"token": f"eq.{token}"}, json={"alerted": alerted},
                   prefer="return=minimal")


# --------------------------------------------------------------------------- sending
def send_email(settings, to, subject, text, html):
    """Send one email from the team Gmail (SMTP with an app password)."""
    msg = EmailMessage()
    msg["From"] = f"Safe Beaches Oʻahu <{settings['GMAIL_ADDRESS']}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(settings["GMAIL_ADDRESS"], settings["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)


# --------------------------------------------------------------------------- forecast
def forecast_risks(model, beaches):
    """{site_id: [risk today, tomorrow, +2, +3]} and the matching dates, from one live fetch.
    Same steps as the app's 3-day outlook (fetch_live_features in ui/app.py)."""
    points = {str(b["site_id"]): tuple(model["weather_points"][str(b["site_id"])]) for b in beaches}
    daily = risk_model.fetch_daily_weather(list(points.values()))
    risks, dates = {site: [] for site in points}, []
    for days_ahead in range(1 + risk_model.OUTLOOK_DAYS):
        for site, pt in points.items():
            cut = risk_model.daily_until(daily[pt], days_ahead)
            risks[site].append(risk_model.predict(model, site, risk_model.features_from_daily(cut))[0])
        dates.append(cut["time"][-1])
    return risks, dates


# --------------------------------------------------------------------------- the daily decision
def decide(alerted, risk_today, level):
    """'risky' the first day the beach is at or over the level, 'clear' the first day it drops
    back under, None otherwise (no repeats on the days in between)."""
    if risk_today >= level and not alerted:
        return "risky"
    if risk_today < level and alerted:
        return "clear"
    return None


def risky_until(day_risks, dates, level):
    """How long the forecast keeps the beach at or over `level`, counting from today:
    (number of days, last such date). Runs to the end of the forecast at most."""
    days = 0
    for risk in day_risks:
        if risk < level:
            break
        days += 1
    return days, dates[days - 1] if days else None


# --------------------------------------------------------------------------- the emails
def _weekday(iso_date):
    from datetime import date
    return f"{date.fromisoformat(iso_date):%A}"


def _wrap(body_html, unsubscribe_url):
    return f"""<div style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #0b1d26; max-width: 560px;">
{body_html}
<p style="color: #555; font-size: 13px;">A forecast from weather, not a lab test or an official advisory. Always follow
posted Hawaiʻi Department of Health signs and advisories.<br>
<a href="{unsubscribe_url}">Unsubscribe from alerts for this beach</a></p></div>"""


def confirmation_email(beach_name, level, confirm_url):
    subject = f"Confirm your alerts for {beach_name}"
    text = (f"Click to start alerts for {beach_name} ({LEVELS[level]}):\n{confirm_url}\n\n"
            "If you didn't sign up, ignore this email and nothing will be sent.")
    html = f"""<div style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #0b1d26;">
<p>Click to start email alerts for <b>{beach_name}</b> when its risk is {LEVELS[level]}:</p>
<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr><td style="border-radius: 999px; background: #d2562e;">
<a href="{confirm_url}" target="_blank" style="display: inline-block; padding: 12px 22px; border-radius: 999px; background: #d2562e; color: #ffffff; text-decoration: none; font-weight: bold;">Confirm alerts</a>
</td></tr></table>
<p style="color: #555; font-size: 13px;">Button not working? Copy this link into your browser:<br>
<a href="{confirm_url}" style="color: #a9411f; word-break: break-all;">{confirm_url}</a></p>
<p style="color: #555; font-size: 13px;">If you didn't sign up, ignore this email and nothing will be sent.</p></div>"""
    return subject, text, html


def risky_email(beach_name, risk, level, days, last_date, nearby, app_url, unsubscribe_url):
    """The 'turned risky' alert, with how long it may last and lower-risk beaches nearby."""
    if days >= 1 + risk_model.OUTLOOK_DAYS:
        how_long = f"Our forecast shows it staying {STAYING[level]} for at least the next {days} days."
    elif days > 1:
        how_long = f"Our forecast shows it staying {STAYING[level]} through {_weekday(last_date)}."
    else:
        how_long = "Our forecast shows it dropping back below your level tomorrow."
    if nearby:
        lines = [f"{b['beach_name']}: {b['risk']:.0%}, {b['km']:.0f} km away" for b in nearby]
        near_text = "Lower-risk beaches nearby today:\n" + "\n".join(f"  - {line}" for line in lines)
        near_html = "<p><b>Lower-risk beaches nearby today:</b></p><ul>" + "".join(f"<li>{line}</li>" for line in lines) + "</ul>"
    else:
        near_text = near_html = "No beach we track is lower risk today."
    subject = f"Forecast: high bacteria risk at {beach_name} today ({risk:.0%})"
    text = (f"{beach_name} is at {risk:.0%} today, {LEVELS[level]}.\n{how_long}\n\n{near_text}\n\n"
            f"Check any beach: {app_url}\n\nA forecast, not an official advisory.\n"
            f"Unsubscribe: {unsubscribe_url}")
    html = _wrap(f"""<p><b>{beach_name}</b> is at <b>{risk:.0%}</b> today: {LEVELS[level]}.</p>
<p>{how_long}</p>{near_html if nearby else f"<p>{near_html}</p>"}
<p><a href="{app_url}">Check any beach on Safe Beaches Oʻahu</a></p>""", unsubscribe_url)
    return subject, text, html


def clear_email(beach_name, risk, level, app_url, unsubscribe_url):
    subject = f"Forecast: {beach_name} is back to lower risk ({risk:.0%})"
    text = (f"{beach_name} is at {risk:.0%} today, back under your alert level ({level:.0%}).\n"
            "Still skip brown or murky water and stay away from stream mouths.\n\n"
            f"Check any beach: {app_url}\nUnsubscribe: {unsubscribe_url}")
    html = _wrap(f"""<p><b>{beach_name}</b> is at <b>{risk:.0%}</b> today, back under your alert level ({level:.0%}).</p>
<p>Still skip brown or murky water and stay away from stream mouths.</p>
<p><a href="{app_url}">Check any beach on Safe Beaches Oʻahu</a></p>""", unsubscribe_url)
    return subject, text, html


def base_url(app_url):
    """APP_URL cleaned up, with https:// added when the setting leaves it out: email apps
    (Gmail) drop links that don't start with it, leaving a button you can't click."""
    url = app_url.strip().rstrip("/")
    return url if url.startswith(("https://", "http://")) else "https://" + url


def link(app_url, **params):
    """APP_URL with query parameters, e.g. link(url, confirm=token)."""
    from urllib.parse import urlencode
    return f"{base_url(app_url)}/?{urlencode(params)}"


# --------------------------------------------------------------------------- the daily job
def run_daily(settings, store, model, beaches, send=send_email, risks=None, dates=None, log=print):
    """Score every beach and email the subscribers whose beach crossed their level today.
    `send`, `risks` and `dates` can be replaced for a dry run or a test."""
    if risks is None:
        risks, dates = forecast_risks(model, beaches)
    names = {str(b["site_id"]): b["beach_name"] for b in beaches}
    app_url = base_url(settings["APP_URL"])
    today = {site: day_risks[0] for site, day_risks in risks.items()}
    sent = 0
    for sub in store.confirmed():
        site, level = str(sub["site_id"]), float(sub["level"])
        action = decide(sub["alerted"], today[site], level)
        if action is None:
            continue
        unsubscribe_url = link(settings["APP_URL"], unsubscribe=sub["token"])
        if action == "risky":
            days, last = risky_until(risks[site], dates, level)
            nearby = recommend.safer_beaches(site, beaches, today, below=LOWER_RISK_BELOW)
            email = risky_email(names[site], today[site], level, days, last, nearby,
                                app_url, unsubscribe_url)
        else:
            email = clear_email(names[site], today[site], level, app_url, unsubscribe_url)
        send(settings, sub["email"], *email)
        store.set_alerted(sub["token"], action == "risky")
        sent += 1
        log(f"{action:5s} -> {names[site]} ({today[site]:.0%}, level {level:.0%})")
    log(f"{sent} email(s) sent")
    return sent
