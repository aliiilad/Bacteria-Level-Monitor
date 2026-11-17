"""Email alerts: subscribers, the daily decision, and the emails themselves. Plain Python, no
Streamlit, so both the app (sign-up, confirm, unsubscribe) and the daily job
(scripts/send_alerts.py) can import it.

How it works
- Someone signs up in the app with an email, one or more beaches, and a level (30% or 60%). We
  store only those, plus a random token, in a Supabase table, and email them a confirmation link.
  Nothing is sent, and nothing about an existing subscription changes, until that link is clicked.
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
import time
from email.message import EmailMessage
from html import escape

import requests

import recommend
import risk_model

LEVELS = {0.30: "caution or worse (30%+)", 0.60: "likely unsafe (60%+)"}
STAYING = {0.30: "at caution or worse", 0.60: "likely unsafe"}  # "...staying <this> through Sunday"
LOWER_RISK_BELOW = 0.30  # "lower-risk beaches nearby" = the app's green band, as on the website
SETTING_NAMES = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "APP_URL"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TABLE = "subscribers"
PAUSED = 540  # Supabase's status code for a paused project


def missing_settings(settings):
    """Names of the settings that are not filled in (alerts stay off until this is empty)."""
    return [name for name in SETTING_NAMES if not settings.get(name)]


def valid_email(email):
    return bool(EMAIL_RE.match(email.strip())) and len(email) <= 254


def level_from_link(text):
    """The level a confirm link carries (?level=0.6), or None when it has none or it isn't one
    of ours (links from older emails have no level)."""
    try:
        return float(text) if float(text) in LEVELS else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- storage
class DatabaseError(Exception):
    """The subscribers table couldn't be read or changed. The message says why, and is safe to
    log: it never holds an email or a link token."""


def _reason(resp):
    """Supabase's own error code and message. Its "details" are left out (they can quote an email)."""
    try:
        err = resp.json()
        return f"{err.get('code', '')} {err.get('message', '')}".strip()
    except (ValueError, AttributeError):  # not JSON, or not a JSON object
        return resp.text[:200].strip()


class SupabaseStore:
    """The subscribers table, through Supabase's REST API. The service key stays on the server
    (Streamlit and GitHub secrets); the table has row-level security on and no public access."""

    def __init__(self, settings):
        self.url = settings["SUPABASE_URL"].strip().rstrip("/") + f"/rest/v1/{TABLE}"
        key = settings["SUPABASE_SERVICE_KEY"].strip()
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json"}

    def _call(self, method, params=None, json=None, prefer=None, tries=3, timeout=10):
        """One REST call. Network errors and 5xx answers (e.g. the database still waking up) are
        retried a few times; every call here is safe to repeat. 4xx errors are raised at once, and
        so is a paused project: waiting doesn't help, someone has to restore it by hand.
        Every failure becomes a DatabaseError that says what went wrong but leaves out the
        request's URL, because the URL can hold an email or a link token and errors get logged."""
        headers = dict(self.headers, **({"Prefer": prefer} if prefer else {}))
        for attempt in range(tries):
            last = attempt == tries - 1
            try:
                resp = requests.request(method, self.url, params=params, json=json, headers=headers,
                                        timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as err:
                if last:
                    raise DatabaseError(f"couldn't reach Supabase ({type(err).__name__}). Check SUPABASE_URL, "
                                        "and that the project still exists.") from None
            else:
                if resp.ok:
                    return resp.json() if resp.content else []
                if resp.status_code == PAUSED:
                    raise DatabaseError("the Supabase project is paused (free projects pause after about a week "
                                        "with no activity). Restore it on the Supabase dashboard.")
                if resp.status_code < 500 or last:
                    raise DatabaseError(f"Supabase answered {resp.status_code}: {_reason(resp)}")
            time.sleep(1.5 * (attempt + 1))

    def ping(self):
        """A tiny read. Free Supabase projects pause after about a week with no activity, so the app
        calls this now and then to keep the database awake."""
        self._call("GET", params={"select": "id", "limit": "1"}, tries=1, timeout=5)

    @staticmethod
    def _row(email, site_id, level, confirmed):
        return {"email": email, "site_id": str(site_id), "level": level,
                "token": secrets.token_urlsafe(24), "confirmed": confirmed, "alerted": False}

    def add(self, email, site_ids, level):
        """Save a sign-up: one unconfirmed row for each beach this email doesn't track yet.
        Beaches it already tracks are left exactly as they are. Anyone can type any email into
        the form, so signing up again must not switch off alerts that were already confirmed, or
        break the links in earlier emails. The level picked now travels in the confirm link and
        is applied when the owner of the email clicks it (see confirm).
        Returns a token for that link; confirming covers every beach for the email."""
        rows = [self._row(email, sid, level, False) for sid in site_ids]
        self._call("POST", params={"on_conflict": "email,site_id"}, json=rows,
                   prefer="resolution=ignore-duplicates,return=minimal")
        # A beach that was already there kept its old token, so read the tokens back.
        stored = self._call("GET", params={"email": f"eq.{email}", "select": "site_id,token"})
        return {r["site_id"]: r["token"] for r in stored}[str(site_ids[0])]

    def _email_for(self, token):
        rows = self._call("GET", params={"token": f"eq.{token}", "select": "email"})
        return rows[0]["email"] if rows else None

    def subscriptions(self, token):
        """Every subscription for the email that `token` belongs to ([] for an unknown token)."""
        email = self._email_for(token)
        return self._call("GET", params={"email": f"eq.{email}", "select": "*"}) if email else []

    def confirm(self, token, level=None):
        """Confirm every subscription for the token's email (clicking the link proves they own it).
        With a `level` (the one picked at sign-up, carried by the link), every beach is set to it.
        Returns the confirmed rows, or [] for an unknown token."""
        email = self._email_for(token)
        if not email:
            return []
        change = {"confirmed": True, **({"level": level} if level in LEVELS else {})}
        return self._call("PATCH", params={"email": f"eq.{email}"}, json=change,
                          prefer="return=representation")

    def unsubscribe(self, token, everything=False):
        """Delete one beach's subscription, or (everything=True) every one for that email.
        Returns the deleted rows, or [] for an unknown token."""
        if everything:
            email = self._email_for(token)
            return self._call("DELETE", params={"email": f"eq.{email}"},
                              prefer="return=representation") if email else []
        return self._call("DELETE", params={"token": f"eq.{token}"}, prefer="return=representation")

    def set_beaches(self, token, site_ids, level):
        """Replace the token's email's beaches with `site_ids` at `level` (from the manage page).
        Beaches kept stay as they were (except the level); new ones start confirmed, since the
        link already proved the email. Returns the new list of rows."""
        current = self.subscriptions(token)
        if not current:
            return []
        email = current[0]["email"]
        have, want = {r["site_id"] for r in current}, {str(s) for s in site_ids}
        if have - want:
            self._call("DELETE", params={"email": f"eq.{email}", "site_id": f"in.({','.join(sorted(have - want))})"})
        if have & want:
            self._call("PATCH", params={"email": f"eq.{email}", "site_id": f"in.({','.join(sorted(have & want))})"},
                       json={"level": level}, prefer="return=minimal")
        if want - have:
            self._call("POST", json=[self._row(email, sid, level, True) for sid in sorted(want - have)],
                       prefer="return=minimal")
        return self._call("GET", params={"email": f"eq.{email}", "select": "*"})

    def confirmed(self):
        return self._call("GET", params={"confirmed": "eq.true", "select": "*"})

    def set_alerted(self, token, alerted):
        self._call("PATCH", params={"token": f"eq.{token}"}, json={"alerted": alerted},
                   prefer="return=minimal")


# --------------------------------------------------------------------------- sending
def send_email(settings, to, subject, text, html):
    """Send one email from the team Gmail (SMTP with an app password)."""
    sender = settings["GMAIL_ADDRESS"].strip()
    msg = EmailMessage()
    msg["From"] = f"Kai Check Oʻahu <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    # Google shows the app password as four groups of letters. Pasted with its spaces (which can
    # be non-breaking spaces that the login can't even send), it fails, so take every space out.
    password = "".join(settings["GMAIL_APP_PASSWORD"].split())
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)


# --------------------------------------------------------------------------- forecast
def forecast_risks(model, beaches, tries=4):
    """{site_id: [risk today, tomorrow, +2, +3]} and the matching dates, from one live fetch.
    Same steps as the app's 3-day outlook (fetch_live_features in ui/app.py). The weather service
    sometimes refuses or times out (it limits requests per minute), and without weather nobody
    gets an alert that day, so a failed fetch is tried again after 20, 40, then 60 seconds."""
    points = {str(b["site_id"]): tuple(model["weather_points"][str(b["site_id"])]) for b in beaches}
    for attempt in range(tries):
        try:
            daily = risk_model.fetch_daily_weather(list(points.values()))
            break
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(20 * (attempt + 1))
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


def _wrap(body_html, unsubscribe_url, manage_url):
    return f"""<div style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #0b1d26; max-width: 560px;">
{body_html}
<p style="color: #555; font-size: 13px;">A forecast from weather, not a lab test or an official advisory. Always follow
posted Hawaiʻi Department of Health signs and advisories. Questions or ideas to make Kai Check better? Just reply to this email.<br>
<a href="{manage_url}">Change my beaches</a> · <a href="{unsubscribe_url}">Unsubscribe from this beach</a></p></div>"""


def beach_list(names):
    """"Kailua", "Kailua and Waialae", "Kailua, Waialae, and Pōkaʻi Bay"."""
    names = list(names)
    return names[0] if len(names) == 1 else (
        " and ".join(names) if len(names) == 2 else ", ".join(names[:-1]) + ", and " + names[-1])


def confirmation_email(beach_names, level, confirm_url, unsubscribe_url):
    beach_name = beach_list(beach_names)
    subject = f"Confirm your beach alerts ({len(beach_names)} beach{'es' if len(beach_names) > 1 else ''})"
    text = (f"Click to start alerts for {beach_name} ({LEVELS[level]}):\n{confirm_url}\n\n"
            "If you didn't sign up, ignore this email and nothing will be sent.\n"
            f"Remove my email: {unsubscribe_url}")
    href = escape(confirm_url)  # the link has an "&" in it, which HTML wants written as "&amp;"
    html = f"""<div style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #0b1d26;">
<p>Click to start email alerts for <b>{beach_name}</b> when its risk is {LEVELS[level]}:</p>
<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr><td style="border-radius: 999px; background: #d2562e;">
<a href="{href}" target="_blank" style="display: inline-block; padding: 12px 22px; border-radius: 999px; background: #d2562e; color: #ffffff; text-decoration: none; font-weight: bold;">Confirm alerts</a>
</td></tr></table>
<p style="color: #555; font-size: 13px;">Button not working? Copy this link into your browser:<br>
<a href="{href}" style="color: #a9411f; word-break: break-all;">{href}</a></p>
<p style="color: #555; font-size: 13px;">If you didn't sign up, ignore this email and nothing will be sent.
Questions or ideas to make Kai Check better? Just reply to this email.<br><a href="{unsubscribe_url}">Remove my email from the list</a></p></div>"""
    return subject, text, html


def welcome_email(beach_names, level, app_url, manage_url, stop_all_url):
    """Sent right after someone confirms, so they know alerts are on and how to change or stop them."""
    beach_name = beach_list(beach_names)
    subject = "You're signed up for beach alerts"
    text = (f"Alerts are on for {beach_name} ({LEVELS[level]}).\n"
            "We'll email you the morning a beach turns risky, and once more when it's back to lower risk. "
            "Nothing on the days in between.\n\n"
            f"Check any beach: {app_url}\nChange my beaches: {manage_url}\nStop all alerts: {stop_all_url}")
    html = f"""<div style="font-family: Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #0b1d26; max-width: 560px;">
<p><b>Alerts are on for {beach_name}</b> ({LEVELS[level]}).</p>
<p>We'll email you the morning a beach turns risky, and once more when it's back to lower risk. Nothing on the days in between.</p>
<p><a href="{app_url}">Check any beach on Kai Check Oʻahu</a></p>
<p style="color: #555; font-size: 13px;">A forecast from weather, not a lab test or an official advisory. Questions or ideas to make Kai Check better? Just reply to this email.<br>
<a href="{manage_url}">Change my beaches</a> · <a href="{stop_all_url}">Stop all alerts</a></p></div>"""
    return subject, text, html


def risky_email(beach_name, risk, level, days, last_date, nearby, app_url, unsubscribe_url, manage_url):
    """The 'turned risky' alert, with how long it may last and lower-risk beaches nearby."""
    if days >= 1 + risk_model.OUTLOOK_DAYS:
        how_long = f"Our forecast shows it staying {STAYING[level]} for at least the next {days} days."
    elif days > 1:
        how_long = f"Our forecast shows it staying {STAYING[level]} through {_weekday(last_date)}."
    else:
        how_long = "Our forecast shows it dropping back below your level tomorrow."
    if nearby:
        lines = [f"{b['beach_name']}: {b['risk']:.0%}, {b['km']:.0f} km from {beach_name}" for b in nearby]
        near_text = "Lower-risk beaches nearby today:\n" + "\n".join(f"  - {line}" for line in lines)
        near_html = "<p><b>Lower-risk beaches nearby today:</b></p><ul>" + "".join(f"<li>{line}</li>" for line in lines) + "</ul>"
    else:
        near_text = near_html = "No beach we track is lower risk today."
    subject = f"Forecast: high bacteria risk at {beach_name} today ({risk:.0%})"
    text = (f"{beach_name} is at {risk:.0%} today, {LEVELS[level]}.\n{how_long}\n\n{near_text}\n\n"
            f"Check any beach: {app_url}\n\nA forecast, not an official advisory.\n"
            f"Change my beaches: {manage_url}\nUnsubscribe from this beach: {unsubscribe_url}")
    html = _wrap(f"""<p><b>{beach_name}</b> is at <b>{risk:.0%}</b> today: {LEVELS[level]}.</p>
<p>{how_long}</p>{near_html if nearby else f"<p>{near_html}</p>"}
<p><a href="{app_url}">Check any beach on Kai Check Oʻahu</a></p>""", unsubscribe_url, manage_url)
    return subject, text, html


def clear_email(beach_name, risk, level, app_url, unsubscribe_url, manage_url):
    subject = f"Forecast: {beach_name} is back to lower risk ({risk:.0%})"
    text = (f"{beach_name} is at {risk:.0%} today, back under your alert level ({level:.0%}).\n"
            "Still skip brown or murky water and stay away from where streams or storm drains flow into the ocean.\n\n"
            f"Check any beach: {app_url}\nChange my beaches: {manage_url}\nUnsubscribe from this beach: {unsubscribe_url}")
    html = _wrap(f"""<p><b>{beach_name}</b> is at <b>{risk:.0%}</b> today, back under your alert level ({level:.0%}).</p>
<p>Still skip brown or murky water and stay away from where streams or storm drains flow into the ocean.</p>
<p><a href="{app_url}">Check any beach on Kai Check Oʻahu</a></p>""", unsubscribe_url, manage_url)
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
    `send`, `risks` and `dates` can be replaced for a dry run or a test. An email that fails is
    logged and skipped, so the rest still go out; the job then ends with an error."""
    if risks is None:
        risks, dates = forecast_risks(model, beaches)
    names = {str(b["site_id"]): b["beach_name"] for b in beaches}
    app_url = base_url(settings["APP_URL"])
    today = {site: day_risks[0] for site, day_risks in risks.items()}
    sent = failed = 0
    for sub in store.confirmed():
        site, level = str(sub["site_id"]), float(sub["level"])
        if site not in today:  # a beach we stopped tracking: nothing to say about it
            continue
        action = decide(sub["alerted"], today[site], level)
        if action is None:
            continue
        unsubscribe_url = link(settings["APP_URL"], unsubscribe=sub["token"])
        manage_url = link(settings["APP_URL"], manage=sub["token"])
        if action == "risky":
            days, last = risky_until(risks[site], dates, level)
            nearby = recommend.safer_beaches(site, beaches, today, below=LOWER_RISK_BELOW)
            email = risky_email(names[site], today[site], level, days, last, nearby,
                                app_url, unsubscribe_url, manage_url)
        else:
            email = clear_email(names[site], today[site], level, app_url, unsubscribe_url, manage_url)
        try:
            send(settings, sub["email"], *email)
            store.set_alerted(sub["token"], action == "risky")
        except Exception as err:  # one bad address must not stop the emails for everyone after it
            failed += 1
            log(f"FAILED {action:5s} -> {names[site]}: {type(err).__name__}")  # no address: this log can be public
            continue
        sent += 1
        log(f"{action:5s} -> {names[site]} ({today[site]:.0%}, level {level:.0%})")
    log(f"{sent} email(s) sent")
    if failed:  # the job ends red, so GitHub tells the repo owner the same day
        raise RuntimeError(f"{failed} email(s) could not be sent (see the FAILED lines above)")
    return sent
