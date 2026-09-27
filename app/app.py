"""Design sample for the Oahu Water Quality app (Streamlit).

Layout mimics an editorial landing page: full-bleed hero, then numbered sections
(01, 02, 03) that alternate text and a "card", then a footer.

The risk number comes from `placeholder_risk()`, a hand-made stand-in so the UI can be built
before the real model exists. Swap it for `model.pkl` once training is done.

Run:  streamlit run app/app.py
"""
from math import exp, log
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

APP_DIR = Path(__file__).parent
BEACHES_CSV = APP_DIR.parent / "data" / "processed" / "beaches.csv"
UNSAFE_THRESHOLD = 0.5  # probability above which we flag the water as unsafe

st.set_page_config(page_title="Kai Check · Oʻahu", page_icon="🌊", layout="wide")
st.markdown(f"<style>{(APP_DIR / 'style.css').read_text()}</style>", unsafe_allow_html=True)


@st.cache_data
def load_beaches():
    return pd.read_csv(BEACHES_CSV)


def placeholder_risk(history_pct, rain_24h, rain_7d, days_since_rain):
    """Fake model: start from the beach's historical unsafe rate, then push it up with
    rain and down with dry days. Returns (probability, {factor: log-odds push})."""
    p0 = min(max(history_pct / 100, 0.03), 0.97)
    island_avg = log(0.30 / 0.70)  # ~30% of samples island-wide are unsafe
    pushes = {
        "Beach history": log(p0 / (1 - p0)) - island_avg,
        "Rain, last 24 h": 0.09 * rain_24h,
        "Rain, last 7 days": 0.025 * rain_7d,
        "Dry days in a row": -0.18 * min(days_since_rain, 7),
    }
    logit = island_avg + sum(pushes.values())
    return 1 / (1 + exp(-logit)), pushes


def risk_color(p):
    return "var(--safe)" if p < 0.3 else "var(--caution)" if p < UNSAFE_THRESHOLD else "var(--unsafe)"


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


def section_head(num, eyebrow, title, body):
    html(
        f"""<div class="section-head"><div class="num">{num}</div>
        <div class="eyebrow">{eyebrow}</div><h2>{title}</h2><p>{body}</p></div>"""
    )


beaches = load_beaches()

# ------------------------------------------------------------------ Hero
html(
    f"""
<div class="hero">
  {HERO_SCENE}
  <nav class="nav">
    <div class="brand">KAI CHECK</div>
    <div class="links"><a href="#check">Beaches</a><a href="#why">How it works</a><a href="#map">Map</a></div>
    <div><a href="#about">About</a></div>
  </nav>
  <div class="rail-left">Data · Surfrider Blue Water Task Force</div>
  <div class="rail-right">
    <ol><li>Start</li><li>01</li><li>02</li><li>03</li></ol>
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
        )
        beach = st.selectbox("Beach", beaches["beach_name"], index=4)
        st.caption("Weather below will come live from NOAA. Drag to try different conditions.")
        rain_24h = st.slider("Rain in the last 24 hours (mm)", 0.0, 50.0, 8.0, 0.5)
        rain_7d = st.slider("Rain in the last 7 days (mm)", 0.0, 150.0, 25.0, 1.0)
        dry_days = st.slider("Days since it last rained", 0, 14, 1)

    row = beaches.set_index("beach_name").loc[beach]
    prob, pushes = placeholder_risk(row.unsafe_pct, rain_24h, rain_7d, dry_days)
    verdict = "UNSAFE — STAY OUT" if prob >= UNSAFE_THRESHOLD else "LIKELY SAFE"
    with card_col:
        html(
            f"""<div class="card">
              <div class="label">{row.region} Shore · Today</div>
              <div class="beach">{beach}</div>
              {gauge_svg(prob)}
              <div class="verdict" style="color:{risk_color(prob)}">{verdict}</div>
              <div class="fine">Historically, {row.n_unsafe} of {row.n_samples} samples here
              ({row.unsafe_pct:.0f}%) were over the limit ({row.first_year}–{row.last_year}).
              <br><br>Sample design · placeholder numbers, not the trained model yet.</div>
            </div>"""
        )

# ------------------------------------------------------------------ 02 · Why this score
with st.container(key="sec-why"):
    card_col, _, text_col = st.columns([4, 1, 5], vertical_alignment="center")
    biggest = max(abs(v) for v in pushes.values()) or 1
    factors = ""
    for name, push in pushes.items():
        color = "var(--unsafe)" if push > 0 else "var(--safe)"
        effect = "raises risk" if push > 0.05 else "lowers risk" if push < -0.05 else "little effect"
        factors += f"""<div class="factor"><div class="row"><b>{name}</b><span style="color:{color}">{effect}</span></div>
            <div class="bar"><span style="width:{abs(push) / biggest * 100:.0f}%;background:{color}"></span></div></div>"""
    with card_col:
        st.markdown(f'<div class="card"><div class="label">What moved the needle</div>'
                    f'<div class="beach">{beach}</div>{factors}</div>', unsafe_allow_html=True)
    with text_col:
        section_head(
            "02", "What's driving it", "Why did we give<br>this score?",
            "Rain is the big one: storm runoff carries soil, sewage, and animal waste into the "
            "surf. Beaches near streams stay risky for days. Each bar shows how much one "
            "factor pushed today's number up or down.",
        )
        st.markdown('<a class="read-more" href="#about">how the model works &nbsp;→</a>',
                    unsafe_allow_html=True)

# ------------------------------------------------------------------ 03 · Map
with st.container(key="sec-map"):
    text_col, _, map_col = st.columns([4, 1, 6], vertical_alignment="center")
    with text_col:
        section_head(
            "03", "Where to swim", "Every beach,<br>at a glance",
            "Dots are sized and colored by how often each beach has tested unsafe since 2018. "
            "Tap one to see its record. Sites with too few samples show “not enough data”.",
        )
    with map_col:
        pts = beaches.assign(
            color=beaches.unsafe_pct.map(
                lambda u: [95, 211, 184] if u < 20 else [251, 215, 132] if u < 40 else [242, 119, 92]),
            radius=400 + beaches.unsafe_pct * 12,
        )
        st.pydeck_chart(pdk.Deck(
            map_style="dark",
            initial_view_state=pdk.ViewState(latitude=21.47, longitude=-157.97, zoom=9),
            layers=[pdk.Layer("ScatterplotLayer", pts, get_position="[longitude, latitude]",
                              get_fill_color="color", get_radius="radius", opacity=0.85, pickable=True)],
            tooltip={"text": "{beach_name}\n{unsafe_pct}% of samples unsafe"},
        ), height=480)

# ------------------------------------------------------------------ Footer
html(
    """
<footer class="site-footer" id="about">
  <div><div class="brand">KAI CHECK</div>
    <p>A Congressional App Challenge project predicting ocean bacteria risk at Oʻahu beaches.
    A forecast, not a lab test — always follow posted Department of Health advisories.</p></div>
  <div><h4>The Project</h4><a href="#why">How it works</a><a href="#about">Limitations</a>
    <a href="#about">About the team</a></div>
  <div><h4>Data</h4><a href="https://bwtf.surfrider.org/report/44">Surfrider BWTF</a>
    <a href="https://open-meteo.com">Open-Meteo</a><a href="https://health.hawaii.gov/cwb/">Hawaiʻi DOH</a></div>
  <div class="copy">Built with help from AI coding tools, disclosed per CAC rules.</div>
</footer>"""
)
