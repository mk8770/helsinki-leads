from __future__ import annotations

import base64
import io
import json
import math
import re
import zlib
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

CSV_PATH = Path(__file__).resolve().parent / "samples.csv"
HELSINKI_CENTRAL = (60.1708, 24.9414)
WALK_METERS_PER_MIN = 80.0  # ~4.8 km/h
SYNC_PARAM = "d"

STATUSES = [
    "🆕 Not Visited Yet",
    "✅ Visited - Interested",
    "❌ Visited - Not Interested",
    "⏳ Follow-up Needed",
]

DISTRICT_OPTIONS = [
    "All Districts",
    "Central District (Kluuvi/Kamppi)",
    "Kallio",
    "Töölö",
    "Punavuori/Ullanlinna",
]

DISTRICT_ALIASES = {
    "Central District (Kluuvi/Kamppi)": (
        "central",
        "kluuvi",
        "kamppi",
        "keskusta",
        "center",
        "centre",
    ),
    "Kallio": ("kallio",),
    "Töölö": ("töölö", "toolo", "toolö", "tölö"),
    "Punavuori/Ullanlinna": ("punavuori", "ullanlinna", "punavuori/ullanlinna"),
}

KNOWN_COORDS = (
    ("hämeentie 38", 60.1852, 24.9602),
    ("hameentie 38", 60.1852, 24.9602),
    ("hämeentie 54-56 l 58", 60.1873, 24.9620),
    ("hameentie 54-56 l 58", 60.1873, 24.9620),
    ("hämeentie 54-56", 60.1873, 24.9620),
    ("hämeentie 54", 60.1873, 24.9620),
    ("hämeentie 56", 60.1873, 24.9620),
    ("hameentie 54-56", 60.1873, 24.9620),
    ("hameentie 54", 60.1873, 24.9620),
    ("pohjoisesplanadi 2", 60.1678, 24.9436),
    ("aleksanterinkatu 26", 60.1691, 24.9522),
    ("mannerheimintie 20", 60.1692, 24.9388),
    ("vaasankatu 11", 60.1878, 24.9505),
    ("topeliuksenkatu 21", 60.1835, 24.9208),
    ("museokatu 18", 60.1756, 24.9215),
    ("fredrikinkatu 19", 60.1635, 24.9380),
    ("iso roobertinkatu 8", 60.1638, 24.9412),
    ("tehtaankatu 27", 60.1589, 24.9448),
)

NAME_CANDIDATES = (
    "company-name",
    "company_name",
    "name",
    "firma",
    "company",
    "business",
    "yritys",
    "nimi",
)
ADDRESS_CANDIDATES = (
    "street-address",
    "street_address",
    "address",
    "adresse",
    "street",
    "strasse",
    "straße",
    "katu",
    "osoite",
)
DISTRICT_CANDIDATES = ("district", "stadtteil", "area", "neighborhood", "kaupunginosa", "alue")
INDUSTRY_CANDIDATES = ("industry", "branche", "category", "keyword", "toimiala", "tyyppi")
WEBSITE_CANDIDATES = (
    "sample-link",
    "sample_link",
    "website",
    "url",
    "demo",
    "link",
    "site",
    "web",
)
HOURS_CANDIDATES = (
    "visiting-hours",
    "visiting_hours",
    "visiting hours",
    "hours",
    "uhrzeit",
    "aukiolo",
    "opening",
)
STATUS_CANDIDATES = ("status", "visit status", "besuchsstatus")
NOTES_CANDIDATES = ("notes", "notizen", "note", "field notes", "kommentar")
LAT_CANDIDATES = ("latitude", "lat", "y")
LON_CANDIDATES = ("longitude", "lon", "lng", "long", "x")


st.set_page_config(
    page_title="Helsinki Website Leads",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_chrome() -> None:
    st.markdown(
        """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stDeployButton {display: none;}
        .stAppDeployButton {display: none;}
        div[data-testid="stToolbar"] {display: none;}
        div[data-testid="stDecoration"] {display: none;}
        div[data-testid="stStatusWidget"] {display: none;}
        #stDecoration {display: none;}

        .hours-line {
            text-align: left;
            margin: 0 0 0.35rem 0;
        }
        .addr-line, .district-line {
            display: block;
            margin: 0 0 0.2rem 0;
            line-height: 1.35;
        }
        .nav-link {
            display: inline-block;
            font-weight: 800;
            color: #4285F4 !important;
            text-decoration: none;
            font-size: 0.95rem;
            text-align: left;
            margin: 0.1rem 0 0.4rem 0;
        }
        .lead-map-box,
        div[data-testid="stIFrame"],
        iframe[title="st.iframe"] {
            width: 140px !important;
            max-width: 140px !important;
            height: 140px !important;
            margin-left: 0 !important;
            margin-right: auto !important;
            overflow: hidden;
            border-radius: 10px;
            border: 1px solid #d9d9d9;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def pick_col(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for cand in candidates:
        if cand in normalized:
            return normalized[cand]
    for key, original in normalized.items():
        for cand in candidates:
            if cand in key or key in cand:
                return original
    return None


def clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


def parse_float(value: object) -> float | None:
    text = clean_text(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_addr(address: str) -> str:
    text = address.lower()
    text = text.replace("ß", "ss")
    text = re.sub(r"[.,]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def coords_for_address(address: str, lat_val: object = None, lon_val: object = None) -> tuple[float, float]:
    lat = parse_float(lat_val)
    lon = parse_float(lon_val)
    if lat is not None and lon is not None:
        return lat, lon

    haystack = normalize_addr(address)
    for fragment, c_lat, c_lon in KNOWN_COORDS:
        if fragment in haystack:
            return c_lat, c_lon
    return HELSINKI_CENTRAL


def infer_district(address: str, district: str = "") -> str:
    if clean_text(district):
        return clean_text(district)
    low = normalize_addr(address)
    if any(part in low for part in ("hämeentie", "hameentie", "vaasankatu")):
        return "Kallio"
    if any(part in low for part in ("topeliuksenkatu", "museokatu")):
        return "Töölö"
    if any(part in low for part in ("fredrikinkatu", "iso roobertinkatu", "tehtaankatu")):
        return "Punavuori/Ullanlinna"
    if any(part in low for part in ("pohjoisesplanadi", "aleksanterinkatu", "mannerheimintie")):
        return "Central District (Kluuvi/Kamppi)"
    return ""


def normalize_status(raw: str) -> str:
    text = clean_text(raw)
    if text in STATUSES:
        return text
    low = text.lower()
    rules = (
        ("not interested", STATUSES[2]),
        ("interested", STATUSES[1]),
        ("follow-up", STATUSES[3]),
        ("follow up", STATUSES[3]),
        ("not visited", STATUSES[0]),
    )
    for needle, status in rules:
        if needle in low:
            return status
    return STATUSES[0]


def district_matches(row_district: str, selected: str) -> bool:
    if selected == "All Districts":
        return True
    if selected.lower() in row_district.lower():
        return True
    low = normalize_addr(row_district)
    aliases = DISTRICT_ALIASES.get(selected, ())
    return any(alias in low for alias in aliases)


def walking_minutes(meters: float) -> int:
    if meters <= 0:
        return 0
    return max(1, int(round(meters / WALK_METERS_PER_MIN)))


def maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def render_osm_pin_map(lat: float, lon: float, map_id: str) -> None:
    _ = map_id
    pad = 0.0024
    west, south, east, north = lon - pad, lat - pad, lon + pad, lat + pad
    src = (
        "https://www.openstreetmap.org/export/embed.html"
        f"?bbox={west:.6f}%2C{south:.6f}%2C{east:.6f}%2C{north:.6f}"
        f"&layer=mapnik&marker={lat:.6f}%2C{lon:.6f}"
    )
    html = f"""
    <div class="lead-map-box" style="width:140px;height:140px;overflow:hidden;border:0;margin:0;padding:0;">
      <iframe
        src="{src}"
        width="140"
        height="140"
        style="border:0;width:140px;height:140px;margin:0;padding:0;display:block;"
        loading="lazy"
        referrerpolicy="no-referrer-when-downgrade">
      </iframe>
    </div>
    """
    components.html(html, height=140, width=140, scrolling=False)


def forget_old_table_state() -> None:
    try:
        st.cache_data.clear()
        st.cache_resource.clear()
    except Exception:
        pass

    if not CSV_PATH.exists():
        return
    stamp = f"{CSV_PATH.stat().st_mtime_ns}:{CSV_PATH.stat().st_size}"
    if st.session_state.get("_csv_stamp") == stamp:
        return
    for key in list(st.session_state.keys()):
        if key.startswith(("status_", "notes_", "save_")):
            del st.session_state[key]
    st.session_state["_csv_stamp"] = stamp


def load_csv_frame() -> pd.DataFrame:
    if not CSV_PATH.exists():
        st.error(f"Could not find `{CSV_PATH.name}` next to the app.")
        st.stop()

    raw = CSV_PATH.read_bytes()
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig").fillna("")
    except pd.errors.ParserError:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig", sep=";").fillna("")

    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].map(clean_text)
    return df.reset_index(drop=True)


def detect_cols(df: pd.DataFrame) -> dict[str, str]:
    cols = {
        "name": pick_col(df, NAME_CANDIDATES),
        "address": pick_col(df, ADDRESS_CANDIDATES),
        "district": pick_col(df, DISTRICT_CANDIDATES),
        "industry": pick_col(df, INDUSTRY_CANDIDATES),
        "website": pick_col(df, WEBSITE_CANDIDATES),
        "hours": pick_col(df, HOURS_CANDIDATES),
        "status": pick_col(df, STATUS_CANDIDATES),
        "notes": pick_col(df, NOTES_CANDIDATES),
        "lat": pick_col(df, LAT_CANDIDATES),
        "lon": pick_col(df, LON_CANDIDATES),
    }
    if cols["name"] is None:
        st.error("Could not detect a company-name column (Company-Name / Name / Firma).")
        st.stop()
    if cols["address"] is None:
        st.error("Could not detect a street-address column (Street-Address / Address).")
        st.stop()
    if cols["status"] is None:
        df["Status"] = STATUSES[0]
        cols["status"] = "Status"
    if cols["notes"] is None:
        df["Notes"] = ""
        cols["notes"] = "Notes"
    if cols["district"] is None:
        df["District"] = ""
        cols["district"] = "District"
    if cols["industry"] is None:
        df["Industry"] = ""
        cols["industry"] = "Industry"
    if cols["website"] is None:
        df["Sample-Link"] = ""
        cols["website"] = "Sample-Link"
    if cols["hours"] is None:
        df["Visiting-Hours"] = ""
        cols["hours"] = "Visiting-Hours"
    return cols


def encode_sync(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(zlib.compress(payload, 9)).decode("ascii").rstrip("=")


def decode_sync(token: str) -> dict:
    text = clean_text(token)
    if not text:
        return {}
    try:
        padded = text + "=" * (-len(text) % 4)
        raw = zlib.decompress(base64.urlsafe_b64decode(padded.encode("ascii")))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_sync() -> dict:
    data = decode_sync(st.query_params.get(SYNC_PARAM, ""))
    if not data:
        return {"v": 2, "o": {}, "a": []}
    if data.get("v") == 2:
        overrides = data.get("o") if isinstance(data.get("o"), dict) else {}
        added = data.get("a") if isinstance(data.get("a"), list) else []
        clean_added = [item for item in added if isinstance(item, dict)]
        return {"v": 2, "o": overrides, "a": clean_added}
    overrides = {key: value for key, value in data.items() if isinstance(value, dict)}
    return {"v": 2, "o": overrides, "a": []}


def write_sync(sync: dict) -> None:
    payload: dict = {"v": 2}
    overrides = {key: value for key, value in (sync.get("o") or {}).items() if value}
    added = [item for item in (sync.get("a") or []) if isinstance(item, dict)]
    if overrides:
        payload["o"] = overrides
    if added:
        payload["a"] = added
    if "o" not in payload and "a" not in payload:
        if SYNC_PARAM in st.query_params:
            del st.query_params[SYNC_PARAM]
        return
    st.query_params[SYNC_PARAM] = encode_sync(payload)


def lead_sid(prefix: str, idx: int, name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")[:24]
    return f"{prefix}{idx}_{slug}" if slug else f"{prefix}{idx}"


def merge_url_leads(df: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    sync = read_sync()
    work = df.copy()
    work["_sid"] = [
        lead_sid("c", int(idx), clean_text(row[cols["name"]])) for idx, row in work.iterrows()
    ]
    work["_src"] = "csv"
    work["_extra_i"] = ""
    work[cols["status"]] = work[cols["status"]].map(normalize_status)
    work[cols["district"]] = [
        infer_district(clean_text(row[cols["address"]]), clean_text(row[cols["district"]]))
        for _, row in work.iterrows()
    ]

    for idx, row in work.iterrows():
        saved = sync["o"].get(row["_sid"])
        if not isinstance(saved, dict):
            continue
        if "s" in saved:
            work.loc[idx, cols["status"]] = normalize_status(saved.get("s", ""))
        if "n" in saved:
            work.loc[idx, cols["notes"]] = clean_text(saved.get("n", ""))

    extra_rows: list[dict[str, str]] = []
    for extra_i, item in enumerate(sync["a"]):
        name = clean_text(item.get("nm"))
        address = clean_text(item.get("ad"))
        if not name or not address:
            continue
        extra_rows.append(
            {
                cols["name"]: name,
                cols["address"]: address,
                cols["district"]: infer_district(address, clean_text(item.get("di"))),
                cols["industry"]: clean_text(item.get("in")),
                cols["website"]: clean_text(item.get("ws")),
                cols["hours"]: clean_text(item.get("hr")),
                cols["status"]: normalize_status(item.get("s", "")),
                cols["notes"]: clean_text(item.get("n", "")),
                "_sid": lead_sid("a", extra_i, name),
                "_src": "url",
                "_extra_i": str(extra_i),
            }
        )

    if extra_rows:
        extra_df = pd.DataFrame(extra_rows)
        work = pd.concat([work, extra_df], ignore_index=True, sort=False).fillna("")
    return work.reset_index(drop=True)


def persist_lead(df: pd.DataFrame, cols: dict[str, str], row_idx: int, status: str, notes: str) -> None:
    df.loc[row_idx, cols["status"]] = status
    df.loc[row_idx, cols["notes"]] = notes
    sync = read_sync()
    overrides: dict = {}
    added = list(sync["a"])

    for _, row in df.iterrows():
        sid = clean_text(row["_sid"])
        row_status = normalize_status(row[cols["status"]])
        row_notes = clean_text(row[cols["notes"]])
        src = clean_text(row["_src"])
        if src == "url":
            extra_i = parse_float(row["_extra_i"])
            if extra_i is None:
                continue
            idx = int(extra_i)
            if 0 <= idx < len(added) and isinstance(added[idx], dict):
                added[idx]["s"] = row_status
                added[idx]["n"] = row_notes
            continue
        entry: dict[str, str] = {}
        if row_status != STATUSES[0]:
            entry["s"] = row_status
        if row_notes:
            entry["n"] = row_notes
        if entry:
            overrides[sid] = entry
    write_sync({"v": 2, "o": overrides, "a": added})


def append_url_lead(name: str, address: str, website: str, hours: str, district: str) -> None:
    sync = read_sync()
    added = list(sync["a"])
    added.append(
        {
            "nm": name,
            "ad": address,
            "ws": website,
            "hr": hours,
            "di": "" if district == "All Districts" else district,
        }
    )
    write_sync({"v": 2, "o": sync["o"], "a": added})


def demo_url(name: str, website: str) -> str:
    if website.startswith(("http://", "https://")):
        return website
    query = re.sub(r"\s+", "+", name.strip()) or "Helsinki"
    return f"https://www.google.com/search?q={query}+Helsinki"


inject_chrome()
forget_old_table_state()

st.title("🎯 Helsinki Website Leads")
st.markdown(
    "Leads kommen fest aus der aktuellen `samples.csv`. Status, Notizen und neu angelegte "
    "Leads liegen im Internet-Link (`st.query_params`) — URL als Lesezeichen speichern."
)

csv_df = load_csv_frame()
cols = detect_cols(csv_df)
df = merge_url_leads(csv_df, cols)

st.subheader("Distance")
filter_left, filter_right = st.columns(2)

with filter_left:
    disable_distance = st.session_state.get("disable_distance", False)
    st.slider(
        "Max walking distance from YOUR location (meters)",
        min_value=100,
        max_value=5000,
        value=2000,
        step=50,
        disabled=disable_distance,
        key="max_distance",
    )
    st.checkbox(
        "🚫 Disable distance filter (Show all prepared leads)",
        key="disable_distance",
    )
    disable_distance = st.session_state["disable_distance"]

with filter_right:
    industry_keyword = st.text_input(
        "Industry Keyword Filter (e.g., Ravintola, Café, Barber)",
        key="industry_keyword",
    )
    district_filter = st.selectbox(
        "District Filter",
        options=DISTRICT_OPTIONS,
        key="district_filter",
    )

origin_lat, origin_lon = HELSINKI_CENTRAL
keyword = industry_keyword.strip().lower()

enriched_rows: list[dict] = []
for idx, row in df.iterrows():
    address = clean_text(row[cols["address"]])
    lat_src = row[cols["lat"]] if cols["lat"] else ""
    lon_src = row[cols["lon"]] if cols["lon"] else ""
    lat, lon = coords_for_address(address, lat_src, lon_src)
    distance_m = haversine_m(origin_lat, origin_lon, lat, lon)

    name = clean_text(row[cols["name"]])
    district = infer_district(address, clean_text(row[cols["district"]]))
    industry = clean_text(row[cols["industry"]])
    website = clean_text(row[cols["website"]])
    hours = clean_text(row[cols["hours"]]) or "—"
    status = normalize_status(row[cols["status"]])
    notes = clean_text(row[cols["notes"]])

    if not district_matches(district, district_filter):
        continue
    if keyword:
        blob = f"{industry} {name} {address} {district}".lower()
        if keyword not in blob:
            continue
    if not disable_distance and distance_m > float(st.session_state["max_distance"]):
        continue

    enriched_rows.append(
        {
            "idx": int(idx),
            "sid": clean_text(row["_sid"]),
            "name": name,
            "address": address,
            "district": district or "—",
            "industry": industry,
            "website": website,
            "hours": hours,
            "status": status,
            "notes": notes,
            "lat": lat,
            "lon": lon,
            "latitude": lat,
            "longitude": lon,
            "distance_m": distance_m,
        }
    )

enriched_rows.sort(key=lambda item: (0 if item["status"] == STATUSES[0] else 1, item["distance_m"], item["name"]))

st.markdown("---")
st.subheader("Active Lead Pipeline")
st.caption(
    f"{len(enriched_rows)} lead(s) match the current filters "
    f"({len(csv_df)} from samples.csv + {len(read_sync()['a'])} from URL). "
    "Bookmark this page after saving notes."
)

if not enriched_rows:
    st.info("No leads match these filters. Relax the distance, industry, or district filter.")

for lead in enriched_rows:
    row_idx = int(lead["idx"])
    uid = lead["sid"]
    status_key = f"status_{uid}"
    notes_key = f"notes_{uid}"
    save_key = f"save_{uid}"

    if status_key not in st.session_state:
        st.session_state[status_key] = lead["status"]
    if notes_key not in st.session_state:
        st.session_state[notes_key] = lead["notes"]

    with st.container(border=True):
        c1, c2 = st.columns([1.3, 1.0])

        with c1:
            st.markdown(f"### {lead['name']}")
            st.markdown(
                f"<div class='addr-line'>📍 Address: {lead['address']}, Helsinki</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='district-line'>🏙️ District: {lead['district']}</div>",
                unsafe_allow_html=True,
            )
            if disable_distance:
                st.markdown("🚶‍♂️ Distance to you: N/A")
            else:
                meters = int(round(lead["distance_m"]))
                minutes = walking_minutes(lead["distance_m"])
                st.markdown(f"🚶‍♂️ Distance to you: {meters} m (ca. {minutes} Min. Fußweg)")

            chosen_status = st.selectbox(
                "Visit status",
                options=STATUSES,
                key=status_key,
                label_visibility="collapsed",
            )
            if chosen_status != lead["status"]:
                persist_lead(df, cols, row_idx, chosen_status, st.session_state[notes_key])
                st.rerun()

            st.link_button(
                f"🌐 Click here to open Demo Website for {lead['name']}",
                url=demo_url(lead["name"], lead["website"]),
                type="primary",
                use_container_width=True,
            )

        with c2:
            st.markdown(
                f"<div class='hours-line'>⏱️ Visiting Hours: <code>{lead['hours']}</code></div>",
                unsafe_allow_html=True,
            )
            nav_href = maps_url(lead["latitude"], lead["longitude"])
            st.markdown(
                f'<a class="nav-link" href="{nav_href}" target="_blank" rel="noopener noreferrer">'
                f"🗺️ Navigation</a>",
                unsafe_allow_html=True,
            )
            render_osm_pin_map(lead["latitude"], lead["longitude"], uid)

        st.text_area(
            "✍️ Field Notes (e.g. Email, Mobile):",
            key=notes_key,
        )
        if st.button("💾 Save Note", key=save_key, use_container_width=True, type="secondary"):
            persist_lead(
                df,
                cols,
                row_idx,
                st.session_state[status_key],
                st.session_state[notes_key],
            )
            st.success("✅ Note synchronized into the URL. Bookmark this link.")
            st.rerun()

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=False):
    st.caption("Neue Leads werden nicht in die CSV geschrieben, sondern live in den Link gelegt.")
    with st.form("add_lead_form", clear_on_submit=True):
        new_name = st.text_input("Company-Name")
        new_address = st.text_input("Street-Address")
        new_link = st.text_input("Sample-Link")
        new_hours = st.text_input("Visiting-Hours")
        new_district = st.selectbox("District", options=DISTRICT_OPTIONS)
        submitted = st.form_submit_button("Lead zur Pipeline hinzufügen")

    if submitted:
        name = clean_text(new_name)
        address = clean_text(new_address)
        if not name or not address:
            st.warning("Bitte Company-Name und Street-Address ausfüllen.")
        else:
            existing = {
                (clean_text(row[cols["name"]]).lower(), normalize_addr(row[cols["address"]]))
                for _, row in df.iterrows()
            }
            if (name.lower(), normalize_addr(address)) in existing:
                st.warning("Dieser Lead ist bereits in der Pipeline.")
            else:
                append_url_lead(
                    name,
                    address,
                    clean_text(new_link),
                    clean_text(new_hours),
                    new_district,
                )
                st.success("✅ Lead in den Link übernommen und in der Pipeline sichtbar.")
                st.rerun()
