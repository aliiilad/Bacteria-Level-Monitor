"""Oʻahu Water Quality app (Streamlit).

Layout mimics an editorial landing page: full-bleed hero, then numbered sections
(01 check a beach, 02 why this score, 03 map) that alternate text and a "card", then a footer.

Risk comes from the trained model in models/model.json (written by scripts/build_dataset.py),
scored in risk_model.py with today's weather from the free Open-Meteo forecast API.

Run:  streamlit run ui/app.py
"""
import base64
import importlib
from datetime import date
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

import alerts
import recommend
import risk_model

# Streamlit re-runs this file after every deploy but keeps imported modules in memory, so a
# deploy that changes recommend.py or risk_model.py would run new app.py against the old
# helpers (an AttributeError on Oct 16). Reloading them each run keeps all three in step.
importlib.reload(recommend)
importlib.reload(risk_model)
importlib.reload(alerts)

APP_DIR = Path(__file__).parent
BEACHES_CSV = APP_DIR.parent / "data" / "processed" / "beaches.csv"
CONTACT_EMAIL = "beachalerts.team@gmail.com"  # team inbox; also sends the alerts
DOH_URL = "https://health.hawaii.gov/cwb/"  # official Hawaiʻi DOH beach advisories (Clean Water Branch)
CAUTION_AT, UNSAFE_AT = 0.30, 0.60  # risk bands: lower risk / caution / likely unsafe

# Model input -> (slider label, unit, step, number format)
INPUTS = {
    "rain_prev_7days": ("Rain in the past 7 days", "mm", 1.0, "%.0f"),
    "days_since_rain": ("Dry days in a row", "days", 1.0, "%.0f"),
    "temp_mean": ("Mean temperature today", "°C", 0.1, "%.1f"),
    "wind_max": ("Max wind today", "km/h", 1.0, "%.0f"),
}

st.set_page_config(page_title="Kai Check Oʻahu", page_icon="🌊", layout="wide")
st.markdown(f"<style>{(APP_DIR / 'style.css').read_text()}</style>", unsafe_allow_html=True)


@st.cache_data
def load_beaches():
    return pd.read_csv(BEACHES_CSV)


@st.cache_resource
def load_model():
    return risk_model.load_model()


@st.cache_data(ttl=3600, show_spinner="Getting today's weather…")
def fetch_live_features(site_points):
    """[(date, {site_id: features}), ...] from the forecast for today and the next 3 days,
    today first. Errors are not cached, so a failed fetch is retried on the next rerun."""
    daily = risk_model.fetch_daily_weather([pt for _, pt in site_points])
    days = []
    for days_ahead in range(1 + risk_model.OUTLOOK_DAYS):
        cut = {pt: risk_model.daily_until(d, days_ahead) for pt, d in daily.items()}
        day = next(iter(cut.values()))["time"][-1]
        days.append((day, {site: risk_model.features_from_daily(cut[pt]) for site, pt in site_points}))
    return days


def band(p):
    if p < CAUTION_AT:
        return "LOWER RISK", "var(--safe)"
    return ("CAUTION", "var(--caution)") if p < UNSAFE_AT else ("LIKELY UNSAFE", "var(--unsafe)")


def risk_color(p):
    return band(p)[1]


def alert_settings():
    """Email-alert settings from Streamlit secrets; empty when they aren't set up yet."""
    try:
        return {name: st.secrets.get(name, "") for name in alerts.SETTING_NAMES}
    except Exception:  # no secrets file at all (e.g. running locally)
        return {}


def pick_beach(name):
    """Button callback: switch the beach picker to `name`."""
    st.session_state["beach"] = name


def weather_line(f):
    dry = int(f["days_since_rain"])
    return (f"{f['rain_prev_7days']:.0f} mm of rain in the past week · "
            f"{dry} dry day{'s' if dry != 1 else ''} in a row · "
            f"{f['temp_mean']:.0f}°C · wind up to {f['wind_max']:.0f} km/h")


def reason_label(name, f):
    """A factor in plain words, with today's value where it helps."""
    dry = int(f["days_since_rain"])
    return {
        "beach": "This beach's track record",
        "rain_prev_7days": f"{f['rain_prev_7days']:.0f} mm of rain this week",
        "days_since_rain": f"{dry} dry day{'s' if dry != 1 else ''} in a row",
        "temp_mean": f"{f['temp_mean']:.0f}°C average temperature",
        "wind_max": f"Wind up to {f['wind_max']:.0f} km/h",
    }[name]


def weather_tiles(f):
    """Today's four model inputs as small tiles (section 01)."""
    dry = int(f["days_since_rain"])
    tiles = [(f"{f['rain_prev_7days']:.0f}", "mm", "rain in the past week"),
             (f"{dry}", "day" if dry == 1 else "days", "dry in a row"),
             (f"{f['temp_mean']:.0f}", "°C", "average temperature"),
             (f"{f['wind_max']:.0f}", "km/h", "strongest wind")]
    cells = "".join(f'<div class="wx"><b>{v}<small> {u}</small></b><span>{label}</span></div>'
                    for v, u, label in tiles)
    return (f'<div class="wx-head">Today\'s weather at this beach</div><div class="wx-row">{cells}</div>'
            '<div class="wx-src">From Open-Meteo, a free weather forecast service. Updated hourly.</div>')


READ_KEY = """<div class="key"><div class="key-head">How to read the number</div>
  <div class="key-row"><i style="background:var(--safe)"></i><span><b>Under 30%: lower risk.</b>
    Bacteria are likely under the limit. Still skip murky water.</span></div>
  <div class="key-row"><i style="background:var(--caution)"></i><span><b>30–60%: caution.</b>
    Avoid spots where streams or storm drains flow into the ocean, or pick a lower-risk beach.</span></div>
  <div class="key-row"><i style="background:var(--unsafe)"></i><span><b>Over 60%: likely unsafe.</b>
    Stay out of the water today.</span></div></div>"""


def gauge_svg(p):
    """Semicircle gauge, 0–100%."""
    # Arc length of a radius-120 half circle is pi*120 ≈ 377.
    filled = 377 * p
    return f"""
    <svg class="gauge" viewBox="0 0 300 200">
      <path d="M30 160 A120 120 0 0 1 270 160" fill="none" stroke="#eee3d8"
            stroke-width="14" stroke-linecap="round"/>
      <path d="M30 160 A120 120 0 0 1 270 160" fill="none" stroke="{risk_color(p)}"
            stroke-width="14" stroke-linecap="round" stroke-dasharray="{filled} 400"/>
      <text x="150" y="140" text-anchor="middle" fill="#2b211c"
            font-family="Quicksand, Inter, sans-serif" font-weight="700" font-size="64">{p:.0%}</text>
      <text x="150" y="194" text-anchor="middle" fill="#6e6058"
            font-family="Inter, sans-serif" font-size="15" font-weight="500">chance of high bacteria today</text>
    </svg>"""


# Beach photos in ui/assets/beaches, with the credit each license asks for. Photos are shown
# whole (never cropped), since some licenses don't allow changes (ND). The NC ones are fine
# because the app is non-commercial. Beaches not listed yet show a drawn wave instead.
FLICKR_DH = '<a href="https://www.flickr.com/photos/21442511@N08" target="_blank" rel="noopener">jdnx</a>'
def flickr(title, photo_url, author, author_url, license_name, license_url):
    """Credit line in the form Openverse gives: "Title" by Author, LICENSE (all linked)."""
    a = lambda text, url: f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'
    return f'"{a(title, photo_url)}" by {a(author, author_url)}, {a(license_name, license_url)}'


CC_BY_2 = '<a href="https://creativecommons.org/licenses/by/2.0/" target="_blank" rel="noopener">CC BY 2.0</a>'
MAGIC_ISLAND = ("magic-island.jpg", 'Photo: <a href="https://www.flickr.com/photos/scotnelson/" target="_blank" '
                'rel="noopener">Scot Nelson</a>, public domain')
BEACH_PHOTOS = {
    "858": MAGIC_ISLAND,
    "859": MAGIC_ISLAND,
    "776": ("kaalawai.jpg", f'"Diamond Head Beach" by {FLICKR_DH}, {CC_BY_2}'),
    "777": ("kahaluu.jpg", flickr("Ka'a'awa and Kaneohe Bay", "https://www.flickr.com/photos/71856730@N04/51344812938",
                                  "Eric Tessmer, Honolulu Hawaii", "https://www.flickr.com/photos/71856730@N04",
                                  "CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/")),
    "8894": ("kailua.jpg", flickr("Kailua Beach Park", "https://www.flickr.com/photos/60035031@N06/39410040812",
                                  "acase1968", "https://www.flickr.com/photos/60035031@N06",
                                  "CC BY-NC-ND 2.0", "https://creativecommons.org/licenses/by-nc-nd/2.0/")),
    "780": ("sharks-cove.jpg", flickr("Shark's Cove, Oahu", "https://www.flickr.com/photos/91506145@N00/3643278482",
                                      "Choconancy1", "https://www.flickr.com/photos/91506145@N00",
                                      "CC BY-NC-SA 2.0", "https://creativecommons.org/licenses/by-nc-sa/2.0/")),
    # No free photo of Kaiaka Bay itself yet; this one is nearby Haleʻiwa Beach Park, and the card says so.
    "1197": ("haleiwa.jpg", "Nearby Haleʻiwa Beach Park: " + flickr(
        "Hawaii-Haleiwa Beach Park", "https://www.flickr.com/photos/78672040@N00/2622943406", "coconut wireless",
        "https://www.flickr.com/photos/78672040@N00", "CC BY-ND 2.0", "https://creativecommons.org/licenses/by-nd/2.0/")),
    "8916": ("pokai.jpg", flickr("Pokai Bucht - Oahu", "https://www.flickr.com/photos/81820192@N06/8793374919",
                                 "MarlonBu", "https://www.flickr.com/photos/81820192@N06",
                                 "CC BY 2.0", "https://creativecommons.org/licenses/by/2.0/")),
    "861": ("waialae.jpg", f'"<a href="https://www.flickr.com/photos/21442511@N08/4807552983" target="_blank" '
                           f'rel="noopener">Walk by the beach</a>" by {FLICKR_DH}, {CC_BY_2}'),
}


@st.cache_data
def beach_photo(site_id):
    """(photo as a data URL, credit HTML) for a beach, or ("", "") if we don't have one yet."""
    if site_id not in BEACH_PHOTOS:
        return "", ""
    name, credit = BEACH_PHOTOS[site_id]
    path = APP_DIR / "assets" / "beaches" / name
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode(), credit


@st.cache_data
def asset_url(name):
    """A file in ui/assets as a data URL, so it ships inside the page."""
    path = APP_DIR / "assets" / name
    return f"data:image/{path.suffix[1:]};base64," + base64.b64encode(path.read_bytes()).decode()


@st.cache_data
def hero_photo():
    """The hero photo (Mokoliʻi from the Kualoa shore) as a data URL, so it ships inside the page."""
    return "data:image/jpeg;base64," + base64.b64encode((APP_DIR / "assets" / "hero.jpg").read_bytes()).decode()


def html(markup):
    """Render raw HTML. Lines are un-indented first, because Markdown treats
    indented lines as a code block."""
    st.markdown("\n".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


beaches = load_beaches()
model = load_model()
site_points = tuple((str(s), tuple(model["weather_points"][str(s)])) for s in beaches.site_id)
try:
    forecast = fetch_live_features(site_points)
    forecast_date, live = forecast[0]  # today: the gauge, map, and "why" bars use this day
except Exception:  # network down, API change, missing values: fall back to a typical day
    forecast, forecast_date, live = None, None, None
test = model["test"]
# Today's risk at every beach, worked out once: the map and the safer-beach pick both use it.
typical = risk_model.typical_features(model)
today_risks = {str(s): risk_model.predict(model, s, live[str(s)] if live else typical)[0]
               for s in beaches.site_id}

@st.dialog("Email alerts")
def link_result(icon, title, body):
    """Pop-up after someone clicks the confirm or unsubscribe link in an email."""
    html(f"""<div class="link-result"><div class="sent-check {icon}">{'&#10003;' if icon == 'ok' else 'i'}</div>
        <div class="sent-head">{title}</div><p>{body}</p></div>""")


# Email links: ?confirm=<token> starts alerts, ?unsubscribe=<token> stops them.
beach_names = {str(b.site_id): b.beach_name for b in beaches.itertuples()}
for action in ("confirm", "unsubscribe"):
    token = st.query_params.get(action)
    if not token:
        continue
    settings = alert_settings()
    if alerts.missing_settings(settings):
        st.warning("Email alerts aren't set up yet, so this link can't be used right now.")
        break
    try:
        store = alerts.SupabaseStore(settings)
        found = store.confirm(token) if action == "confirm" else store.unsubscribe(token)
    except Exception:
        st.error("Sorry, something went wrong with that link. Please try again later.")
        break
    st.query_params.clear()  # so a refresh doesn't use the link again
    name = beach_names.get(str(found["site_id"]), "your beach") if found else ""
    if not found:
        link_result("info", "This link was already used",
                    "It may have expired, or you already clicked it. Sign up again in the alerts section if you need to.")
    elif action == "confirm":
        try:  # a welcome email, so there's a record of what they signed up for and how to stop it
            alerts.send_email(settings, found["email"], *alerts.welcome_email(
                name, float(found["level"]), alerts.base_url(settings["APP_URL"]),
                alerts.link(settings["APP_URL"], unsubscribe=found["token"])))
        except Exception:
            pass  # they're confirmed either way
        link_result("ok", "You're signed up!",
                    f"You'll get an email the morning <b>{name}</b> turns risky, and one more when it's back "
                    "to lower risk. Every email has an unsubscribe link. We just sent you a welcome email too.")
    else:
        link_result("ok", "You're unsubscribed",
                    f"You won't get any more alerts for <b>{name}</b>, and we deleted your email from our list.")
    break

# ------------------------------------------------------------------ Hero
html(
    f"""
<div class="hero" style="background-image:url('{hero_photo()}')">
  <nav class="nav">
    <div class="brand">Kai Check Oʻahu</div>
    <div class="links"><a href="#check">Forecast</a><a href="#map">Map</a><a href="#alerts">Alerts</a></div>
    <div><a href="#faq">Questions</a></div>
  </nav>
  <div class="hero-copy">
    <h1>Is it safe to swim today?</h1>
    <p class="hero-sub">A daily bacteria forecast for popular Oʻahu beaches, built from today's weather.</p>
  </div>
  <div class="photo-credit">Mokoliʻi from Secret Island, Kualoa, Oʻahu · Photo: Agnes Tang</div>
</div>"""
)

# ------------------------------------------------------------------ Beach picker + official notice, right under the photo
with st.container(key="sec-pick"):
    st.session_state.setdefault("beach", beaches["beach_name"].iloc[4])
    beach = st.selectbox("Choose your beach", beaches["beach_name"], key="beach")
    # Official advisories come before any number we show
    html(f"""<div class="official"><div class="official-text"><b>This is a forecast, not an official
        advisory.</b> Always check the Hawaiʻi Department of Health's current beach advisories first,
        including Brown Water Advisories after heavy rain,
        and follow any posted signs.</div>
        <a class="official-btn" href="{DOH_URL}" target="_blank" rel="noopener">Official DOH advisories &rarr;</a></div>""")

# ------------------------------------------------------------------ 01 · Today's forecast
with st.container(key="sec-check"):
    text_col, _, card_col = st.columns([5, 1, 4])
    with text_col:
        row = beaches.set_index("beach_name").loc[beach]
        site = str(row.site_id)
        html(f"""<div class="section-head" id="check"><h2>Today at {beach}</h2>
            <p>Rain washes bacteria into the ocean within hours, so we turn the past week's weather
            into today's chance of high bacteria.</p></div>""")
        base = live[site] if live else typical
        if live:
            html(weather_tiles(base))
        else:
            st.caption("Live weather is unavailable right now, so this starts from a typical "
                       "day. Move the sliders to try other conditions.")
        what_if = st.toggle("Try different weather", value=live is None)
        features = dict(base)
        if what_if:
            for name, (label, unit, step, fmt) in INPUTS.items():
                lo, hi = model["features"][name]["min"], model["features"][name]["max"]
                features[name] = st.slider(f"{label} ({unit})", lo, hi, min(max(base[name], lo), hi),
                                           step, format=fmt, key=f"{name}-{site}")

    prob, pushes = risk_model.predict(model, site, features)
    verdict, color = band(prob)
    if what_if or not live:
        when = "What-if weather"
    else:
        d = date.fromisoformat(forecast_date)
        when = f"{d:%a %b} {d.day}"

    # Slots in the gauge card, one per feature, so both can be built at the same time.
    # Only change the lines under your own comment; git can't merge edits to touching lines.

    # Feature 1 (Person A): 3-day outlook row.
    outlook_html = ""
    if forecast and what_if:
        outlook_html = ('<div class="outlook"><div class="outlook-note">Turn off "Try different weather" '
                        'to see the 3-day outlook.</div></div>')
    elif forecast:
        days = ""
        for days_ahead, (day, day_features) in enumerate(forecast):
            p = risk_model.predict(model, site, day_features[site])[0]
            name = "Today" if days_ahead == 0 else f"{date.fromisoformat(day):%a}"
            unsure = days_ahead >= 2  # forecast rain gets less reliable further out
            days += f"""<div class="day{' unsure' if unsure else ''}"><span>{name}{'*' if unsure else ''}</span>
                <b style="color:{risk_color(p)}">{p:.0%}</b>
                <i><em style="width:{p * 100:.0f}%;background:{risk_color(p)}"></em></i></div>"""
        outlook_html = f"""<div class="outlook"><div class="outlook-head">3-day bacteria outlook</div>
            <div class="days">{days}</div>
            <div class="outlook-note">* Less certain: these use rain forecasts further ahead, which are less accurate, so the bacteria forecast is less certain too.</div></div>"""

    # Feature 2 (Person B): "What should I do?" + safer beach.
    advice_html = ""
    tips = "".join(f"<li>{tip}</li>" for tip in recommend.ADVICE[verdict])
    alt = None
    if verdict == "LOWER RISK":
        suggestion = ""
    elif what_if:  # the sliders change only this beach, so don't compare made-up weather to real
        suggestion = ('<div class="safer-note">Turn off "Try different weather" to see a safer beach '
                      "on today's real forecast.</div>")
    elif not live:
        suggestion = '<div class="safer-note">Safer-beach suggestions need live weather.</div>'
    else:
        alt = recommend.safer_beach(site, beaches.to_dict("records"), today_risks, below=CAUTION_AT)
        suggestion = (f"""<div class="better"><div class="better-head">Better option today</div>
            <div class="better-row"><span>{alt['beach_name']}</span><span>{alt['risk']:.0%}</span></div>
            <div class="better-meta">Lower risk · {alt['km']:.0f} km from {beach}</div></div>"""
                      if alt else '<div class="safer-note">No beach we track is lower risk today.</div>')
    better = suggestion if alt else ""   # the gold box goes first; notes go under the advice
    advice_html = f"""{better}<div class="advice"><div class="advice-head">What should I do?</div>
        <ul>{tips}</ul>{"" if alt else suggestion}</div>"""

    with card_col:
        html(
            f"""<div class="card">
              <div class="label">{row.region} Shore · {when}</div>
              <div class="beach">{beach}</div>
              {gauge_svg(prob)}
              <div class="verdict" style="color:{color}">FORECAST: {verdict}</div>
              <a class="doh-link" href="{DOH_URL}" target="_blank" rel="noopener">Check today's official DOH
              advisories for this beach &rarr;</a>{advice_html}{outlook_html}
            </div>"""
        )

# ------------------------------------------------------------------ Where to swim today
# Lower-risk beaches nearest the selected one, each with a button that switches to it. Real
# (live) weather only, like the "Better option today" box.
with st.container(key="sec-swim"):
    html(f"""<div class="swim-head"><div class="swim-title">Where to swim today</div>
        <span>Lower-risk beaches, nearest to {beach} first</span></div>""")
    if what_if or not live:
        st.caption('Turn off "Try different weather" to see where to swim today.' if what_if
                   else "Needs live weather, which is unavailable right now.")
    else:
        options = recommend.safer_beaches(site, beaches.to_dict("records"), today_risks, below=CAUTION_AT)
        if not options:
            st.caption("No beach we track is lower risk today.")
        for col, b in zip(st.columns(3), options):
            with col:
                photo, credit = beach_photo(b["site_id"])
                pic = (f'<div class="swim-pic"><img src="{photo}" alt="{b["beach_name"]}"></div>' if photo
                       else '<div class="swim-pic none"></div>')
                html(f"""<div class="swim-card">{pic}<div class="swim-body">
                    <div class="swim-name">{b['beach_name']}</div>
                    <div class="swim-status"><i style="background:{risk_color(b['risk'])}"></i>{band(b['risk'])[0].capitalize()} · {b['risk']:.0%}</div>
                    <div class="swim-meta">{b['region']} Shore · {b['km']:.0f} km from {beach}</div>
                    {f'<div class="swim-credit">{credit}</div>' if credit else ''}</div></div>""")
                st.button("Check this beach  →", key=f"swim-{b['site_id']}", on_click=pick_beach,
                          args=(b["beach_name"],), width="stretch")

# ------------------------------------------------------------------ Map
with st.container(key="sec-map"):
    text_col, _, map_col = st.columns([4, 1, 6], vertical_alignment="center")
    with text_col:
        html(f"""<div class="section-head" id="map"><h2>Every beach at a glance</h2>
            <p>{"Each dot is today's risk at that beach." if live else
                "Live weather is unavailable, so dots show risk on a typical day."}</p></div>""")
        html("""<ul class="map-key"><li><i style="background:var(--safe)"></i>Green: lower risk</li>
            <li><i style="background:var(--caution)"></i>Orange: caution</li>
            <li><i style="background:var(--unsafe)"></i>Red: likely unsafe</li></ul>
            <p class="map-tip">Tap a dot for details.</p>""")
    with map_col:
        rgb = {"LOWER RISK": [21, 128, 61], "CAUTION": [217, 130, 0], "LIKELY UNSAFE": [212, 45, 45]}  # --safe/--caution/--unsafe
        rows = []
        for b in beaches.itertuples():
            # selected beach follows the what-if sliders
            r = prob if b.beach_name == beach else today_risks[str(b.site_id)]
            rows.append({"site_id": str(b.site_id), "beach_name": b.beach_name, "latitude": b.latitude,
                         "longitude": b.longitude, "r": r, "risk": f"{r:.0%}",
                         "history": f"{b.unsafe_pct:.0f}", "n": b.n_samples, "n_unsafe": b.n_unsafe})
        # Sampling points at the same beach (Magic Island) become one pin. The pin follows the
        # point the user picked; otherwise it shows the higher (worse) risk of the two.
        for group in recommend.SAME_BEACH:
            members = [x for x in rows if x["site_id"] in group]
            if len(members) < 2:
                continue
            picked = [x for x in members if x["site_id"] == site]
            shown = picked[0] if picked else max(members, key=lambda x: x["r"])
            short = lambda name: name.split(" (")[0].split(" – ")[-1]   # "Bowls", "Canoe Launch"
            rows = [x for x in rows if x["site_id"] not in group] + [{
                **shown,
                "beach_name": members[0]["beach_name"].split(" – ")[0] + " (Ala Moana)",
                "latitude": sum(x["latitude"] for x in members) / len(members),
                "longitude": sum(x["longitude"] for x in members) / len(members),
                "risk": " · ".join(f"{short(x['beach_name'])} {x['r']:.0%}" for x in members),
                "history": f"{100 * sum(x['n_unsafe'] for x in members) / sum(x['n'] for x in members):.0f}",
            }]
        for x in rows:
            x["color"] = rgb[band(x["r"])[0]]
            x["radius"] = 1300 if recommend.same_beach(x["site_id"], site) else 800
        st.pydeck_chart(pdk.Deck(
            map_style="light",
            initial_view_state=pdk.ViewState(latitude=21.47, longitude=-157.97, zoom=9),
            layers=[pdk.Layer("ScatterplotLayer", pd.DataFrame(rows), get_position="[longitude, latitude]",
                              get_fill_color="color", get_radius="radius", opacity=0.85, pickable=True)],
            tooltip={"text": "{beach_name}\nRisk now: {risk}\n{history}% of past samples unsafe"},
        ), height=480)

# ------------------------------------------------------------------ Track my beach (email alerts)
with st.container(key="sec-alerts"):
    text_col, _, form_col = st.columns([5, 1, 5])
    with text_col:
        html(f"""<div class="section-head" id="alerts"><h2>Get a heads-up when your beach turns risky</h2>
            <p>Pick your beach. We'll email you the morning it turns risky, and once more when it's
            back to lower risk. Nothing on the days in between.</p>
            <p class="contact">Questions? Email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p></div>""")
    with form_col:
        settings = alert_settings()
        if alerts.missing_settings(settings):  # accounts not set up yet: no form to fill in for nothing
            html("""<div class="soon"><div class="soon-head">Coming soon</div>
                <p>Email alerts are almost ready. Until then, check this page and the official DOH
                advisories before you swim.</p></div>""")
        elif "alert_sent" in st.session_state:  # just signed up: show a clear "sent" state instead of the form
            sent = st.session_state["alert_sent"]
            html(f"""<div class="sent"><div class="sent-check">&#10003;</div><div class="sent-head">Sent!</div>
                <p>We emailed a confirmation link to <b>{sent['email']}</b> for <b>{sent['beach']}</b>.
                Click it to turn your alerts on.</p>
                <p class="sent-fine">Don't see it? Check your spam folder and mark it "Not spam" (links
                don't work in spam). Adding {CONTACT_EMAIL} to your contacts keeps later alerts in your inbox.</p></div>""")
            st.button("Track another beach", key="alert-again", width="stretch",
                      on_click=lambda: st.session_state.pop("alert_sent", None))
        else:
            with st.form("alert-form"):
                email = st.text_input("Email", placeholder="you@example.com")
                track = st.selectbox("Beach to track", beaches["beach_name"], index=None,
                                     placeholder="Choose a beach")
                level = st.radio("Email me when risk is", list(alerts.LEVELS), format_func=alerts.LEVELS.get)
                submitted = st.form_submit_button("Send me a confirmation email", type="primary",
                                                  width="stretch")
            st.caption("We store only your email, beach, and level. Every email has an unsubscribe link.")
            if submitted:
                signups = st.session_state.get("alert_signups", 0)
                if not alerts.valid_email(email):
                    st.error("Please enter a valid email address.")
                elif track is None:
                    st.error("Please choose a beach to track.")
                elif signups >= 3:  # keeps one visitor from flooding inboxes with confirmation emails
                    st.error("You've signed up several times already. Please check your inbox.")
                else:
                    site_id = str(beaches.set_index("beach_name").loc[track, "site_id"])
                    try:
                        with st.spinner("Sending your confirmation email…"):
                            token = alerts.SupabaseStore(settings).add(email.strip().lower(), site_id, level)
                            alerts.send_email(settings, email.strip(), *alerts.confirmation_email(
                                track, level, alerts.link(settings["APP_URL"], confirm=token),
                                alerts.link(settings["APP_URL"], unsubscribe=token)))
                    except Exception:
                        st.error("Sorry, we couldn't sign you up right now. Please try again later.")
                    else:
                        st.session_state["alert_signups"] = signups + 1
                        st.session_state["alert_sent"] = {"email": email.strip(), "beach": track}
                        st.rerun()

# ------------------------------------------------------------------ Questions (dropdowns)
# The main page stays short; the details live here.
comparison = [dict(c, name="Heavy-rain rule") if c["name"] == "Flash-flood stand-in" else c
              for c in test["comparison"]]
LIMITS = [
    ("Where you swim matters most",
     "Some beaches test high almost every time, even without rain, so the beach itself tells you "
     "more than the weather does, contrary to our first guess. Our model gets most of its accuracy "
     "from each beach's track record rather than the weather. Rain still matters, just less than "
     "we expected."),
    ("Few tests right after storms",
     "Volunteers test every two weeks on a set schedule, not after storms, so few tests happened "
     "right after heavy rain. The model learns from past examples, so it has the least practice "
     "on the stormy days that matter most and could be off on them."),
    ("We approximated the warnings",
     "Instead of the state's real past flash-flood warnings, we compared against days with heavy "
     "rain (25 mm or more), which is roughly when those warnings go out. Real warnings are archived "
     "by the Iowa Environmental Mesonet; testing against them is our next step, and they might "
     "catch a few more or fewer unsafe days."),
    ("More data would help",
     f"We had about {model['n_train'] + test['n']:,} water tests from {len(model['site_offsets'])} sites. "
     "Ideally there would be daily tests at every beach, especially right after storms, so the "
     "model could learn from many more risky days."),
]
with st.container(key="sec-faq"):
    html('<h2 class="center-title" id="faq">Questions</h2>')

    with st.expander("How do I read the number?"):
        html(READ_KEY)

    with st.expander(f"Why did {beach} get this number?"):
        biggest = max(abs(v) for v in pushes.values()) or 1
        reasons = ""
        for rank, (name, push) in enumerate(sorted(pushes.items(), key=lambda kv: -abs(kv[1]))):
            if abs(push) <= 0.05:
                arrow, tint, how = "•", "var(--text-muted)", "barely matters today"
            else:
                up = push > 0
                arrow, tint = ("▲", "var(--unsafe)") if up else ("▼", "var(--safe)")
                size = ("the biggest reason it's " + ("high" if up else "low")) if rank == 0 else (
                    ("raises" if up else "lowers") + (" it a lot" if abs(push) > biggest / 2 else " it a little"))
                how = size
            reasons += f"""<li><span class="why-arrow" style="color:{tint}">{arrow}</span>
                <span><b>{reason_label(name, features)}</b>: {how}</span></li>"""
        html(f"""<ul class="why-list">{reasons}</ul>
            <p class="faq-fine">Compared with an average beach on an average day. In past lab tests here,
            {row.unsafe_pct:.0f}% were over the safety limit ({row.n_unsafe} of {row.n_samples} tests,
            {row.first_year}–{row.last_year}).</p>""")

    with st.expander("How does the forecast work?"):
        html(f"""<div class="steps">
            <div class="step"><div class="step-num">1</div><h3>We read the weather</h3>
              <p>Rain over the past week, dry days in a row, temperature, and wind at each beach, from
              Open-Meteo, a free weather forecast service.</p></div>
            <div class="step"><div class="step-num">2</div><h3>Our model scores each beach</h3>
              <p>Trained on {model['n_train']:,} Surfrider water samples from {model['train_years'][0]}–{model['train_years'][1]},
              and tested on {test['n']} newer ones.</p></div>
            <div class="step"><div class="step-num">3</div><h3>You get a forecast</h3>
              <p>The chance of high bacteria today, what to do about it, and lower-risk beaches nearby.</p></div>
            </div>
            <p class="faq-fine">Volunteers test the water only every two weeks, but rain washes bacteria
            into the ocean within hours. That's the gap a weather-based forecast fills.</p>""")

    with st.expander("What is enterococcus, and can it make me sick?"):
        pic_col, text_col = st.columns([2, 3])
        with pic_col:
            html(f"""<figure class="germ-pic"><img src="{asset_url('enterococcus.jpg')}"
                alt="Enterococcus bacteria under a microscope: small dark purple ovals in pairs and short chains">
                <figcaption>Enterococcus under a microscope: the small dark purple ovals, in a stained
                tissue sample. Image: CDC / Dr. Mike Miller (PHIL #2899), public domain, via
                <a href="https://commons.wikimedia.org/w/index.php?curid=1670351" target="_blank" rel="noopener">Wikimedia Commons</a>.</figcaption></figure>""")
        with text_col:
            html("""<div class="germ-list"><p>Enterococcus are bacteria that live in the guts of people and
                animals. They usually aren't what makes swimmers sick, but lots of them in the ocean means
                sewage or animal waste got into the water, along with germs that do cause illness. That's
                why Hawaiʻi's Department of Health tests for them.</p>
                <div class="germ-head">Swimming in water over the limit can cause</div>
                <ul><li><b>Stomach illness</b>, the most common: nausea, vomiting, diarrhea, stomach pain, fever</li>
                <li><b>Ear, eye, nose, and throat infections</b></li>
                <li><b>Skin rashes</b> and itching</li></ul>
                <p>Kids, older adults, and people with weaker immune systems get sick more easily.</p>
                <div class="germ-links">Read more:
                <a href="https://www.epa.gov/national-aquatic-resource-surveys/indicators-enterococci" target="_blank" rel="noopener">EPA &rarr;</a>
                <a href="https://beachapedia.org/Bacteria:_enterococcus" target="_blank" rel="noopener">Surfrider Beachapedia &rarr;</a></div></div>""")

    with st.expander("How accurate is it?"):
        ours, rule = test["flag_at_30"], comparison[0]
        caught = lambda recall: round(recall * test["n_unsafe"])
        html(f"""<div class="vs">
              <div class="vs-big ours"><b>{ours['recall']:.0%}</b><span>Our model</span></div>
              <div class="vs-word">vs</div>
              <div class="vs-big"><b>{rule['recall']:.0%}</b><span>Heavy-rain rule</span></div>
            </div>
            <p class="vs-line">We trained on {model['train_years'][0]}–{model['train_years'][1]} and tested on
            {test['n']} newer samples ({test['years'][0]}–{str(test['years'][1])[2:]}) the model had never seen.
            Of the {test['n_unsafe']} unsafe ones, ours flagged {caught(ours['recall'])} (warning at 30% risk or
            more); a rule that only warns on heavy, flash-flood-level rain flagged {caught(rule['recall'])}.
            When ours said "caution or worse," it was right {ours['precision']:.0%} of the time.</p>""")
        st.dataframe(pd.DataFrame([{
            "Approach": f"{c['name']} ({c['note']})",
            "Unsafe caught": f"{c['recall']:.0%}",
            "Flags that were unsafe": f"{c['precision']:.0%}",
            "AUC": "–" if c["auc"] is None else f"{c['auc']:.2f}",
        } for c in comparison]), hide_index=True, width="stretch")

    with st.expander("What are the limits?"):
        html('<div class="faq-limits">' + "".join(f"<h3>{t}</h3><p>{b}</p>" for t, b in LIMITS) + "</div>")

    with st.expander("Is this an official advisory?"):
        html(f"""<p class="faq-p">No. It's a forecast from weather, not a lab test. The Hawaiʻi Department of
            Health posts the official beach advisories, including Brown Water Advisories after heavy rain.
            If DOH has posted one, follow it, whatever this forecast says, and stay out of brown or murky
            water.</p><a class="official-btn" href="{DOH_URL}" target="_blank" rel="noopener">Official DOH advisories &rarr;</a>""")

    with st.expander("How do email alerts work, and how do I stop them?"):
        html(f"""<p class="faq-p">Sign up in the alerts section above and click the link in the confirmation
            email (check your spam folder). After that, every morning around 5:30am we check the forecast and
            email you only the morning your beach turns risky, then once more when it's back to lower risk.
            Every email has an unsubscribe link at the bottom; one click stops them and deletes your email
            from our list. We store only your email, beach, and level.</p>
            <p class="faq-p">Questions? Email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>.</p>""")

    with st.expander("Where does the data come from?"):
        html("""<ul class="faq-list">
            <li><b>Water tests:</b> <a href="https://bwtf.surfrider.org/report/44" target="_blank" rel="noopener">Surfrider
            Foundation Blue Water Task Force</a> volunteers, who test Oʻahu beaches every two weeks.</li>
            <li><b>Weather:</b> <a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo</a>, a free
            weather forecast service.</li>
            <li><b>Official advisories:</b> the <a href="https://health.hawaii.gov/cwb/" target="_blank" rel="noopener">Hawaiʻi
            Department of Health, Clean Water Branch</a>.</li></ul>""")

# ------------------------------------------------------------------ Footer
html(
    f"""
<footer class="site-footer" id="about">
  <div><div class="brand">Kai Check Oʻahu</div>
    <p>A Congressional App Challenge project predicting ocean bacteria risk at Oʻahu beaches.
    A forecast, not a lab test: always follow posted Department of Health advisories.</p></div>
  <div><h4>The Project</h4><a href="#check">Today's forecast</a><a href="#map">Map</a><a href="#alerts">Email alerts</a>
    <a href="#faq">Questions</a><a href="mailto:{CONTACT_EMAIL}">Contact us</a></div>
  <div><h4>Data</h4><a href="https://bwtf.surfrider.org/report/44">Surfrider BWTF</a>
    <a href="https://open-meteo.com">Open-Meteo</a><a href="https://health.hawaii.gov/cwb/">Hawaiʻi DOH</a></div>
  <div class="copy">Built with help from AI coding tools, disclosed per CAC rules.</div>
</footer>"""
)
