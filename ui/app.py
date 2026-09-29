"""Oʻahu Water Quality app (Streamlit).

Layout mimics an editorial landing page: full-bleed hero, then numbered sections
(01 check a beach, 02 why this score, 03 map) that alternate text and a "card", then a footer.

Risk comes from the trained model in models/model.json (written by scripts/build_dataset.py),
scored in risk_model.py with today's weather from the free Open-Meteo forecast API.

Run:  streamlit run ui/app.py
"""
from datetime import date
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

import risk_model

APP_DIR = Path(__file__).parent
BEACHES_CSV = APP_DIR.parent / "data" / "processed" / "beaches.csv"
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
    """({date}, {site_id: features}) from today's forecast. Errors are not cached, so a
    failed fetch is retried on the next rerun."""
    daily = risk_model.fetch_daily_weather([pt for _, pt in site_points])
    today = next(iter(daily.values()))["time"][-1]
    return today, {site: risk_model.features_from_daily(daily[pt]) for site, pt in site_points}


def band(p):
    if p < CAUTION_AT:
        return "LOWER RISK", "var(--safe)"
    return ("CAUTION", "var(--caution)") if p < UNSAFE_AT else ("LIKELY UNSAFE", "var(--unsafe)")


def risk_color(p):
    return band(p)[1]


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
      <path d="M30 160 A120 120 0 0 1 270 160" fill="none" stroke="rgba(255,255,255,.12)"
            stroke-width="14" stroke-linecap="round"/>
      <path d="M30 160 A120 120 0 0 1 270 160" fill="none" stroke="{risk_color(p)}"
            stroke-width="14" stroke-linecap="round" stroke-dasharray="{filled} 400"/>
      <text x="150" y="140" text-anchor="middle" fill="#fff"
            font-family="DM Serif Display, Georgia, serif" font-size="64">{p:.0%}</text>
      <text x="150" y="194" text-anchor="middle" fill="rgba(255,255,255,.6)"
            font-family="Outfit, sans-serif" font-size="12" letter-spacing="3">CHANCE OF HIGH BACTERIA</text>
    </svg>"""


# Hero artwork: a dusk sky, the Koʻolau ridge, and layered ocean swells (inline SVG, no image files).
HERO_SCENE = """
<svg class="scene" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1c3a4a"/><stop offset=".55" stop-color="#5d7f86"/>
      <stop offset="1" stop-color="#d9b98a"/>
    </linearGradient>
    <radialGradient id="sun" cx=".72" cy=".56" r=".35">
      <stop offset="0" stop-color="#fbd784" stop-opacity=".75"/><stop offset="1" stop-color="#fbd784" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="sea" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2f6f7a"/><stop offset="1" stop-color="#0b1d26"/>
    </linearGradient>
  </defs>
  <rect width="1440" height="900" fill="url(#sky)"/>
  <rect width="1440" height="900" fill="url(#sun)"/>
  <path d="M0 520 L90 470 L160 430 L210 450 L270 380 L330 410 L390 330 L450 370 L520 300 L580 350
           L640 290 L700 340 L770 310 L840 380 L920 360 L1000 420 L1080 400 L1170 450 L1260 440
           L1360 480 L1440 470 L1440 560 L0 560 Z" fill="#2a4a4f" opacity=".85"/>
  <path d="M0 540 L120 505 L230 520 L340 470 L470 500 L600 455 L720 495 L860 470 L990 510
           L1120 490 L1260 520 L1440 500 L1440 580 L0 580 Z" fill="#1d3a3f"/>
  <rect y="560" width="1440" height="340" fill="url(#sea)"/>
  <ellipse cx="1040" cy="585" rx="220" ry="10" fill="#fbd784" opacity=".35"/>
  <path d="M0 640 Q180 620 360 640 T720 640 T1080 640 T1440 640 V900 H0 Z" fill="#1f5663" opacity=".6"/>
  <path d="M0 700 Q200 675 400 700 T800 700 T1200 700 T1600 700 V900 H0 Z" fill="#16414d" opacity=".75"/>
  <path d="M0 770 Q220 745 440 770 T880 770 T1320 770 T1760 770 V900 H0 Z" fill="#0f2e39"/>
</svg>"""


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
    forecast_date, live = fetch_live_features(site_points)
except Exception:  # network down, API change, missing values: fall back to a typical day
    forecast_date, live = None, None
test = model["test"]

# ------------------------------------------------------------------ Hero
html(
    f"""
<div class="hero">
  {HERO_SCENE}
  <nav class="nav">
    <div class="brand">KAI CHECK</div>
    <div class="links"><a href="#check">Beaches</a><a href="#why">How it works</a><a href="#map">Map</a><a href="#results">Results</a></div>
    <div><a href="#about">About</a></div>
  </nav>
  <div class="rail-left">Data · Surfrider Blue Water Task Force</div>
  <div class="rail-right">
    <ol><li>Start</li><li>01</li><li>02</li><li>03</li><li>04</li></ol>
    <div class="track"><span></span></div>
  </div>
  <div class="hero-copy">
    <div class="eyebrow">A beach safety forecast</div>
    <h1>Know The Water<br>Before You Dive In</h1>
    <div class="scroll-hint">scroll down &nbsp;↓</div>
  </div>
</div>"""
)

# ------------------------------------------------------------------ 01 · Check your beach
with st.container(key="sec-check"):
    text_col, _, card_col = st.columns([5, 1, 4], vertical_alignment="center")
    with text_col:
        section_head(
            "01", "Check your beach", "How safe is the<br>water today?",
            "Lab tests happen only every two weeks, but rain washes bacteria into the ocean "
            "within hours. We turn recent weather into today's chance that enterococcus is "
            "above Hawaiʻi's safety limit (130 MPN/100 mL).",
            anchor="check",
        )
        beach = st.selectbox("Beach", beaches["beach_name"], index=4)
        row = beaches.set_index("beach_name").loc[beach]
        site = str(row.site_id)
        base = live[site] if live else risk_model.typical_features(model)
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
    when = ("What-if weather" if what_if or not live
            else date.fromisoformat(forecast_date).strftime("%a %b %-d"))
    with card_col:
        html(
            f"""<div class="card">
              <div class="label">{row.region} Shore · {when}</div>
              <div class="beach">{beach}</div>
              {gauge_svg(prob)}
              <div class="verdict" style="color:{color}">{verdict}</div>
              <div class="fine">Historically, {row.n_unsafe} of {row.n_samples} samples here
              ({row.unsafe_pct:.0f}%) were over the limit ({row.first_year}–{row.last_year}).
              <br><br>A forecast from weather, not a lab test. Always follow posted
              Department of Health advisories.</div>
            </div>"""
        )

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
            "02", "What's driving it", "Why did we give<br>this score?",
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
            "03", "Where to swim", "Every beach,<br>at a glance",
            ("Each dot is today's risk at that beach from the live forecast. "
             if live else "Live weather is unavailable, so dots show risk on a typical day. ")
            + "Green is lower risk, gold is caution, coral is likely unsafe. Tap a dot for details.",
            anchor="map",
        )
    with map_col:
        rgb = {"LOWER RISK": [95, 211, 184], "CAUTION": [251, 215, 132], "LIKELY UNSAFE": [242, 119, 92]}
        rows = []
        for b in beaches.itertuples():
            f = live[str(b.site_id)] if live else risk_model.typical_features(model)
            p = features if b.beach_name == beach else f   # selected beach follows the what-if sliders
            r, _ = risk_model.predict(model, b.site_id, p)
            rows.append({"beach_name": b.beach_name, "latitude": b.latitude, "longitude": b.longitude,
                         "risk": f"{r:.0%}", "history": f"{b.unsafe_pct:.0f}",
                         "color": rgb[band(r)[0]], "radius": 1300 if b.beach_name == beach else 800})
        st.pydeck_chart(pdk.Deck(
            map_style="dark",
            initial_view_state=pdk.ViewState(latitude=21.47, longitude=-157.97, zoom=9),
            layers=[pdk.Layer("ScatterplotLayer", pd.DataFrame(rows), get_position="[longitude, latitude]",
                              get_fill_color="color", get_radius="radius", opacity=0.85, pickable=True)],
            tooltip={"text": "{beach_name}\nRisk now: {risk}\n{history}% of past samples unsafe"},
        ), height=480)

# ------------------------------------------------------------------ 04 · How well it works
comparison = test["comparison"]
beach_only = next(c for c in comparison if c["name"] == "Beach only")
with st.container(key="sec-results"):
    text_col, _, card_col = st.columns([5, 1, 5], vertical_alignment="center")
    with text_col:
        section_head(
            "04", "How well it works", "Tested on days<br>it never saw",
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
            } for c in comparison]), hide_index=True, use_container_width=True)

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
  <div><div class="brand">KAI CHECK</div>
    <p>A Congressional App Challenge project predicting ocean bacteria risk at Oʻahu beaches.
    A forecast, not a lab test — always follow posted Department of Health advisories.</p></div>
  <div><h4>The Project</h4><a href="#why">How it works</a><a href="#results">Results</a><a href="#limits">Limitations</a>
    <a href="#about">About the team</a></div>
  <div><h4>Data</h4><a href="https://bwtf.surfrider.org/report/44">Surfrider BWTF</a>
    <a href="https://open-meteo.com">Open-Meteo</a><a href="https://health.hawaii.gov/cwb/">Hawaiʻi DOH</a></div>
  <div class="copy">Built with help from AI coding tools, disclosed per CAC rules.</div>
</footer>"""
)
