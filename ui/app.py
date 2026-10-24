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
DOH_URL = "https://health.hawaii.gov/cwb/"  # official Hawaiʻi DOH beach advisories (Clean Water Branch)
CAUTION_AT, UNSAFE_AT = 0.30, 0.60  # risk bands: lower risk / caution / likely unsafe

# Model input -> (slider label, unit, step, number format)
INPUTS = {
    "rain_prev_7days": ("Rain in the past 7 days", "mm", 1.0, "%.0f"),
    "days_since_rain": ("Dry days in a row", "days", 1.0, "%.0f"),
    "temp_mean": ("Mean temperature today", "°C", 0.1, "%.1f"),
    "wind_max": ("Max wind today", "km/h", 1.0, "%.0f"),
}
FACTOR_LABELS = {
    "beach": "This beach's track record",
    "rain_prev_7days": "Rain, past 7 days",
    "days_since_rain": "Dry days in a row",
    "temp_mean": "Temperature",
    "wind_max": "Wind",
}

st.set_page_config(page_title="Kai Check · Oʻahu", page_icon="🌊", layout="wide")
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


def gauge_svg(p):
    """Semicircle gauge, 0–100%."""
    # Arc length of a radius-120 half circle is pi*120 ≈ 377.
    filled = 377 * p
    return f"""
    <svg class="gauge" viewBox="0 0 300 200">
      <path d="M30 160 A120 120 0 0 1 270 160" fill="none" stroke="rgba(34,48,58,.10)"
            stroke-width="14" stroke-linecap="round"/>
      <path d="M30 160 A120 120 0 0 1 270 160" fill="none" stroke="{risk_color(p)}"
            stroke-width="14" stroke-linecap="round" stroke-dasharray="{filled} 400"/>
      <text x="150" y="140" text-anchor="middle" fill="#22303a"
            font-family="DM Serif Display, Georgia, serif" font-size="64">{p:.0%}</text>
      <text x="150" y="194" text-anchor="middle" fill="rgba(34,48,58,.6)"
            font-family="Outfit, sans-serif" font-size="15" font-weight="600">chance of high bacteria today</text>
    </svg>"""


@st.cache_data
def hero_photo():
    """The hero photo (Mokoliʻi from the Kualoa shore) as a data URL, so it ships inside the page."""
    return "data:image/jpeg;base64," + base64.b64encode((APP_DIR / "assets" / "hero.jpg").read_bytes()).decode()


def html(markup):
    """Render raw HTML. Lines are un-indented first, because Markdown treats
    indented lines as a code block."""
    st.markdown("\n".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def section_head(num, eyebrow, title, body, anchor=""):
    html(
        f"""<div class="section-head" id="{anchor}"><div class="num">{num}</div>
        <div class="eyebrow">{eyebrow}</div><h2>{title}</h2><p>{body}</p></div>"""
    )


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
    if not found:
        st.info("That link has already been used or has expired.")
    elif action == "confirm":
        st.success(f"Alerts are on for {beach_names.get(found['site_id'], 'your beach')}. "
                   "We'll email you the morning it turns risky, and again when it's back to lower risk.")
    else:
        st.success(f"You're unsubscribed from alerts for {beach_names.get(found['site_id'], 'that beach')}.")
    break

# ------------------------------------------------------------------ Hero
html(
    f"""
<div class="hero" style="background-image:url('{hero_photo()}')">
  <nav class="nav">
    <div class="brand">Safe Beaches Oʻahu</div>
    <div class="links"><a href="#check">Beaches</a><a href="#why">How it works</a><a href="#map">Map</a><a href="#results">Results</a></div>
    <div><a href="#about">About</a></div>
  </nav>
  <div class="hero-copy">
    <h1>Is it safe to swim today?</h1>
    <p class="hero-sub">A daily bacteria forecast for popular Oʻahu beaches, built from today's weather.</p>
  </div>
</div>"""
)

# ------------------------------------------------------------------ Beach picker + official notice, right under the photo
with st.container(key="sec-pick"):
    st.session_state.setdefault("beach", beaches["beach_name"].iloc[4])
    beach = st.selectbox("Choose your beach", beaches["beach_name"], key="beach")
    # Official advisories come before any number we show
    html(f"""<div class="official"><div class="official-text"><b>This is a forecast, not an official
        advisory.</b> Always check the Hawaiʻi Department of Health's current beach advisories first,
        and follow any posted signs.</div>
        <a class="official-btn" href="{DOH_URL}" target="_blank" rel="noopener">Official DOH advisories &rarr;</a></div>""")

# ------------------------------------------------------------------ 01 · Check your beach
with st.container(key="sec-check"):
    text_col, _, card_col = st.columns([5, 1, 4])
    with text_col:
        section_head(
            "01", "Today's forecast", "What the rain means<br>for the water",
            "Lab tests happen only every two weeks, but rain washes bacteria into the ocean "
            "within hours. We turn recent weather into today's chance that enterococcus is "
            "above Hawaiʻi's safety limit (130 MPN/100 mL).",
            anchor="check",
        )
        row = beaches.set_index("beach_name").loc[beach]
        site = str(row.site_id)
        base = live[site] if live else typical
        if live:
            st.caption(f"Today's forecast from Open-Meteo: {weather_line(base)}.")
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
        outlook_html = f"""<div class="outlook"><div class="outlook-head">3-day outlook</div>
            <div class="days">{days}</div>
            <div class="outlook-note">* Less certain: forecast rain gets less reliable further out.</div></div>"""

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
            <div class="better-meta">Lower risk · {alt['km']:.0f} km away (straight line)</div></div>"""
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
              <div class="fine">Historically, {row.n_unsafe} of {row.n_samples} samples here
              ({row.unsafe_pct:.0f}%) were over the limit ({row.first_year}–{row.last_year}).
              <br><br><b>A forecast from weather, not a lab test or an official advisory.</b> If DOH
              has posted an advisory for this beach, follow it, whatever this forecast says.</div>
            </div>"""
        )
        if alt:
            st.button(f"Check {alt['beach_name']} instead  →", key="better-btn", type="primary",
                      on_click=pick_beach, args=(alt["beach_name"],), width="stretch")

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
                html(f"""<div class="swim-card"><div class="swim-row"><span>{b['beach_name']}</span>
                    <b style="color:{risk_color(b['risk'])}">{b['risk']:.0%}</b></div>
                    <div class="swim-meta">{b['region']} Shore · {b['km']:.0f} km</div></div>""")
                st.button("Check this beach  →", key=f"swim-{b['site_id']}", on_click=pick_beach,
                          args=(b["beach_name"],), width="stretch")

# ------------------------------------------------------------------ 02 · Why this score
with st.container(key="sec-why"):
    card_col, _, text_col = st.columns([4, 1, 5], vertical_alignment="center")
    biggest = max(abs(v) for v in pushes.values()) or 1
    factors = ""
    for name, push in sorted(pushes.items(), key=lambda kv: -abs(kv[1])):
        if abs(push) <= 0.05:
            effect, tint = "little effect", "var(--text-muted)"
        else:
            effect, tint = ("raises risk", "var(--unsafe)") if push > 0 else ("lowers risk", "var(--safe)")
        factors += f"""<div class="factor"><div class="row"><b>{FACTOR_LABELS[name]}</b>
            <span style="color:{tint}">{effect}</span></div>
            <div class="bar"><span style="width:{abs(push) / biggest * 100:.0f}%;background:{tint}"></span></div></div>"""
    top = max(pushes, key=lambda k: abs(pushes[k]))
    why = (f"Biggest factor today: <b>{FACTOR_LABELS[top].lower()}</b>, which "
           f"{'raises' if pushes[top] > 0 else 'lowers'} the risk compared with an average beach and day.")
    with card_col:
        html(f"""<div class="card"><div class="label">What moved the needle</div>
            <div class="beach">{beach}</div>{factors}<div class="fine">{why}</div></div>""")
    with text_col:
        section_head(
            "02", "What's driving it", "Why this number?",
            "Rain washes soil, sewage, and animal waste into the surf, and some beaches, like "
            "those near stream mouths, run high most of the time. Each bar shows how much one "
            "factor pushed today's number up or down compared with an average beach and day. "
            f"Tested on {test['n']} samples from {test['years'][0]}–{str(test['years'][1])[2:]} "
            f"that the model never saw, flagging at 30% caught "
            f"{test['flag_at_30']['recall']:.0%} of the unsafe ones.",
            anchor="why",
        )
        st.markdown('<a class="read-more" href="#results">how well it works &nbsp;→</a>',
                    unsafe_allow_html=True)

# ------------------------------------------------------------------ 03 · Map
with st.container(key="sec-map"):
    text_col, _, map_col = st.columns([4, 1, 6], vertical_alignment="center")
    with text_col:
        section_head(
            "03", "Map", "Every beach we track,<br>side by side",
            ("Each dot is today's risk at that beach from the live forecast. "
             if live else "Live weather is unavailable, so dots show risk on a typical day. ")
            + "Green is lower risk, orange is caution, red is likely unsafe. Tap a dot for details.",
            anchor="map",
        )
    with map_col:
        rgb = {"LOWER RISK": [18, 160, 122], "CAUTION": [245, 158, 11], "LIKELY UNSAFE": [230, 61, 46]}  # --safe/--caution/--unsafe
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
        section_head(
            "", "Track my beach", "Get a heads-up when your beach turns risky",
            "Pick the beach you swim at and a level. Every morning at about 5:30am we check the "
            "forecast, and email you only the morning it crosses your level, with how long it may "
            "stay risky and lower-risk beaches nearby. You get one more email when it's back to "
            "lower risk.",
            anchor="alerts",
        )
    with form_col:
        settings = alert_settings()
        if alerts.missing_settings(settings):  # accounts not set up yet: no form to fill in for nothing
            html("""<div class="soon"><div class="soon-head">Coming soon</div>
                <p>Email alerts are almost ready. Until then, check this page and the official DOH
                advisories before you swim.</p></div>""")
        else:
            with st.form("alert-form"):
                email = st.text_input("Email", placeholder="you@example.com")
                track = st.selectbox("Beach to track", beaches["beach_name"], index=None,
                                     placeholder="Choose a beach")
                level = st.radio("Email me when risk is", list(alerts.LEVELS), format_func=alerts.LEVELS.get)
                submitted = st.form_submit_button("Send me a confirmation email", type="primary",
                                                  width="stretch")
            st.caption("We store only your email, the beach, and your level, nothing else. Alerts start after "
                       "you click the link in the confirmation email, and every email has an unsubscribe link.")
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
                        token = alerts.SupabaseStore(settings).add(email.strip().lower(), site_id, level)
                        alerts.send_email(settings, email.strip(), *alerts.confirmation_email(
                            track, level, alerts.link(settings["APP_URL"], confirm=token)))
                    except Exception:
                        st.error("Sorry, we couldn't sign you up right now. Please try again later.")
                    else:
                        st.session_state["alert_signups"] = signups + 1
                        st.success(f"Almost done: check {email.strip()} for a confirmation link "
                                   "(it may land in your spam folder).")

# ------------------------------------------------------------------ 04 · How well it works
comparison = test["comparison"]
beach_only = next(c for c in comparison if c["name"] == "Beach only")
with st.container(key="sec-results"):
    text_col, _, card_col = st.columns([5, 1, 5], vertical_alignment="center")
    with text_col:
        section_head(
            "04", "How well it works", "Does it actually work?",
            f"We trained on {model['train_years'][0]}–{model['train_years'][1]} and held back "
            f"{test['n']} samples from {test['years'][0]}–{str(test['years'][1])[2:]}, "
            f"{test['n_unsafe']} of them unsafe. A rule that only warns on flash-flood-level rain "
            f"caught {comparison[0]['recall']:.0%} of the unsafe ones. Our model, flagging at 30% "
            f"risk, caught {test['flag_at_30']['recall']:.0%}.",
            anchor="results",
        )
    with card_col:
        rows = ""
        for c in comparison:
            ours = c["name"] == "Our model"
            auc = f" · AUC {c['auc']:.2f}" if c["auc"] is not None else ""
            rows += f"""<div class="bar-row" tabindex="0">
                <div class="top"><span><b>{c['name']}</b> <span class="note">{c['note']}</span></span>
                <span class="value">{c['recall']:.0%}</span></div>
                <div class="track"><span class="fill{' ours' if ours else ''}" style="width:{c['recall'] * 100:.1f}%"></span></div>
                <div class="tip">{c['precision']:.0%} of its flags were really unsafe{auc}</div></div>"""
        html(f"""<div class="card chart"><div class="label">Share of unsafe samples caught</div>
            <div class="beach">{test['years'][0]}–{str(test['years'][1])[2:]} test samples</div>{rows}
            <div class="fine">Hover or tap a bar for how often its warnings were right.</div></div>""")
        with st.expander("Show as table"):
            st.dataframe(pd.DataFrame([{
                "Approach": f"{c['name']} ({c['note']})",
                "Unsafe caught": f"{c['recall']:.0%}",
                "Flags that were unsafe": f"{c['precision']:.0%}",
                "AUC": "–" if c["auc"] is None else f"{c['auc']:.2f}",
            } for c in comparison]), hide_index=True, width="stretch")

# ------------------------------------------------------------------ Limits
LIMITS = [
    ("The beach does most of the work",
     f"Knowing the beach alone scores an AUC of {beach_only['auc']:.2f}. Weather adds about "
     f"{test['auc'] - beach_only['auc']:.2f} on top. Rain matters, but some spots run high almost always."),
    ("Storm days are rare in the data",
     "Volunteers sample every two weeks on a fixed schedule, so few samples land right after "
     "big storms. The model has seen the worst days least."),
    ("The baseline is a stand-in",
     "There is no archive of real flash-flood warnings to test against, so the comparison uses "
     "days with 25 mm or more of rain as an approximation."),
    ("A forecast, not a lab test",
     f"About {model['n_train'] + test['n']:,} samples at {len(model['site_offsets'])} beaches is a small "
     "dataset. Always follow posted Department of Health advisories."),
]
with st.container(key="sec-limits"):
    html('<div class="eyebrow" id="limits">Know the limits</div><div class="limits">'
         + "".join(f"<div><h3>{t}</h3><p>{b}</p></div>" for t, b in LIMITS) + "</div>")

# ------------------------------------------------------------------ Footer
html(
    """
<footer class="site-footer" id="about">
  <div><div class="brand">Safe Beaches Oʻahu</div>
    <p>A Congressional App Challenge project predicting ocean bacteria risk at Oʻahu beaches.
    A forecast, not a lab test — always follow posted Department of Health advisories.</p></div>
  <div><h4>The Project</h4><a href="#why">How it works</a><a href="#results">Results</a><a href="#limits">Limitations</a>
    <a href="#about">About the team</a></div>
  <div><h4>Data</h4><a href="https://bwtf.surfrider.org/report/44">Surfrider BWTF</a>
    <a href="https://open-meteo.com">Open-Meteo</a><a href="https://health.hawaii.gov/cwb/">Hawaiʻi DOH</a></div>
  <div class="copy">Built with help from AI coding tools, disclosed per CAC rules.</div>
</footer>"""
)
