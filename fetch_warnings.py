"""Download historical NWS flood warnings for Oahu (Honolulu County) -> warnings.csv.

Source: Iowa Environmental Mesonet (IEM) NWS VTEC archive — free, no key.
Run this LOCALLY (the cloud sandbox can't reach IEM):
    pip install -r requirements.txt
    python fetch_warnings.py               # 2018-01-01 .. today
    python fetch_warnings.py --start 2018-01-01 --end 2026-12-31

Output `warnings.csv`, one row per warning/advisory event:
    phenomena, significance, event, issue_utc, expire_utc, wfo, eventid
where event = phenomena + "." + significance, e.g.
    FF.W  Flash Flood Warning   <- the state's Brown Water Advisory trigger (our baseline)
    FA.W  Flood Warning (areal)
    FA.Y  Flood Advisory
    FF.A  Flash Flood Watch
We keep all four so baseline.py can report stricter/looser variants; baseline.py uses
FF.W by default.

The raw API response is also saved to `warnings_raw.json`. If normalisation fails, the
script prints the keys it found — send that output back and we'll adapt the parser.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import urllib.request

UGC = "HIC003"                       # Honolulu County (= Oahu) county UGC code
WFO = "HFO"                          # NWS Honolulu forecast office
KEEP = {("FF", "W"), ("FA", "W"), ("FA", "Y"), ("FF", "A")}
BY_UGC = "https://mesonet.agron.iastate.edu/json/vtec_events_byugc.py?ugc={ugc}&sdate={s}&edate={e}"
BY_WFO = ("https://mesonet.agron.iastate.edu/json/vtec_events_bywfo.py"
          "?wfo={wfo}&year={y}&phenomena={p}&significance={sig}")

ISSUE_KEYS = ("issue", "utc_issue", "product_issue", "issued", "start")
EXPIRE_KEYS = ("expire", "utc_expire", "product_expire", "expired", "end")


def get_json(url: str):
    print("GET", url, file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def pick(d: dict, keys) -> str | None:
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k in lower and lower[k]:
            return lower[k]
    return None


def parse_ts(s: str) -> dt.datetime:
    s = s.replace("Z", "+00:00")
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)      # IEM times are UTC
    return t.astimezone(dt.timezone.utc)


def normalise(events: list[dict]) -> list[dict]:
    rows, bad = [], 0
    for ev in events:
        ph = pick(ev, ("phenomena",)); sig = pick(ev, ("significance",))
        iss = pick(ev, ISSUE_KEYS); exp = pick(ev, EXPIRE_KEYS)
        if not (ph and sig and iss and exp):
            bad += 1
            continue
        if (ph, sig) not in KEEP:
            continue
        rows.append({
            "phenomena": ph, "significance": sig, "event": f"{ph}.{sig}",
            "issue_utc": parse_ts(iss).isoformat().replace("+00:00", "Z"),
            "expire_utc": parse_ts(exp).isoformat().replace("+00:00", "Z"),
            "wfo": pick(ev, ("wfo",)) or WFO,
            "eventid": pick(ev, ("eventid", "etn", "event_id")) or "",
        })
    if bad:
        print(f"warning: {bad} events lacked issue/expire/phenomena keys; keys seen: "
              f"{sorted(events[0].keys()) if events else '[]'}", file=sys.stderr)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=dt.date.today().isoformat())
    ap.add_argument("--out", default="warnings.csv")
    args = ap.parse_args()

    # Primary: everything tagged to Honolulu County in one call.
    try:
        raw = get_json(BY_UGC.format(ugc=UGC, s=args.start, e=args.end))
        events = raw.get("events", raw) if isinstance(raw, dict) else raw
        source = "byugc"
    except Exception as e:                                        # noqa: BLE001
        print(f"by-UGC fetch failed ({e}); falling back to by-WFO per year", file=sys.stderr)
        events, source = [], "bywfo"
        y0, y1 = int(args.start[:4]), int(args.end[:4])
        for y in range(y0, y1 + 1):
            for ph, sig in sorted(KEEP):
                raw = get_json(BY_WFO.format(wfo=WFO, y=y, p=ph, sig=sig))
                evs = raw.get("events", raw) if isinstance(raw, dict) else raw
                events.extend(evs)
        print("NOTE: by-WFO results cover all Hawaii counties; filter to Oahu manually if the "
              "rows carry a ugc/county field (baseline.py has --ugc-filter for that).",
              file=sys.stderr)

    json.dump({"source": source, "events": events}, open("warnings_raw.json", "w"), indent=1)
    rows = normalise(events)
    if not rows:
        print("ERROR: no usable rows. Inspect warnings_raw.json and send back the first event.",
              file=sys.stderr)
        sys.exit(1)

    rows.sort(key=lambda r: r["issue_utc"])
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    counts = {}
    for r in rows:
        counts[r["event"]] = counts.get(r["event"], 0) + 1
    print(f"wrote {len(rows)} events to {args.out}: {counts}")


if __name__ == "__main__":
    main()
