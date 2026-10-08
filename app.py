from __future__ import annotations

import io
import math
import re
import urllib.parse
from pathlib import Path

import pandas as pd
import streamlit as st

CSV_PATH = Path(__file__).resolve().parent / "samples.csv"
HELSINKI_CENTRAL = (60.1708, 24.9414)
WALK_METERS_PER_MIN = 80.0

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

KALLIO_STREETS = (
    "linja",
    "hameentie",
    "helsinginkatu",
    "vaasankatu",
    "porthaninkatu",
    "siltasaarenkatu",
    "castreninkatu",
    "kirstinkatu",
    "fleminginkatu",
    "alppikatu",
)

TOOLO_STREETS = (
    "runeberginkatu",
    "topeliuksenkatu",
    "toolonkatu",
    "arkadiankatu",
    "caloniuksenkatu",
    "mechelininkatu",
    "sibeliuksenkatu",
)

CENTRAL_STREETS = (
    "aleksanterinkatu",
    "kaivokatu",
    "lonnrotinkatu",
    "bulevardi",
    "yronkatu",
    "yrjonkatu",
    "simonkatu",
    "fredrikinkatu",
    "urhokehtosenkatu",
    "kekkosenkatu",
    "keskuskatu",
    "pohjoisesplanadi",
    "etelaesplanadi",
)

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
    ("toinen linja 23", 60.1849, 24.9506),
    ("toinen linja", 60.1849, 24.9506),
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
WEBSITE_TODO = "Website to be done"
HOURS_FALLBACK = "Not specified"


st.set_page_config(
    page_title="Helsinki Website Leads",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "manual_leads" not in st.session_state:
    st.session_state["manual_leads"] = []


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
        .lead-map-box {
            display: block;
            width: 140px;
            height: 140px;
            max-width: 140px;
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


def normalize_hours(raw: object) -> str:
    text = clean_text(raw)
    return text if text else HOURS_FALLBACK


def normalize_website(raw: object) -> str:
    text = clean_text(raw)
    low = text.lower().rstrip("/")
    if not text or low in {"https:", "http:", "https://", "http://", "https", "http"}:
        return WEBSITE_TODO
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


def fold_fi(text: str) -> str:
    return (
        text.lower()
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("å", "a")
        .replace("é", "e")
    )


def first_street_number(address: str) -> int | None:
    match = re.search(r"(\d+)", normalize_addr(address))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def street_in_address(haystack: str, streets: tuple[str, ...]) -> bool:
    return any(street in haystack for street in streets)


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
    haystack = fold_fi(normalize_addr(address))
    if not haystack:
        return clean_text(district) or "Central District (Kluuvi/Kamppi)"

    if "mannerheimintie" in haystack:
        number = first_street_number(address)
        if number is not None and number > 30:
            return "Töölö"
        return "Central District (Kluuvi/Kamppi)"

    if street_in_address(haystack, KALLIO_STREETS):
        return "Kallio"
    if street_in_address(haystack, TOOLO_STREETS):
        return "Töölö"
    if street_in_address(haystack, CENTRAL_STREETS):
        return "Central District (Kluuvi/Kamppi)"
    if "helsinki" in haystack or clean_text(district):
        return clean_text(district) or "Central District (Kluuvi/Kamppi)"
    return "Central District (Kluuvi/Kamppi)"


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


def native_geo_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def render_google_map(address: str) -> None:
    query = urllib.parse.quote(f"{address}, Helsinki, Finland")
    st.components.v1.html(
        f"""
<iframe 
    width="100%" 
    height="140" 
    frameborder="0" 
    style="border:0; border-radius:8px; background-color:#ffffff;" 
    src="https://maps.google.com/maps?q={query}&t=&z=15&ie=UTF8&iwloc=&output=embed">
</iframe>
""",
        height=145,
    )


def qp_get(key: str) -> str:
    if key not in st.query_params:
        return ""
    value = st.query_params[key]
    if isinstance(value, list):
        return clean_text(value[0] if value else "")
    return clean_text(value)


def qp_snapshot() -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for key in list(st.query_params.keys()):
        snapshot[str(key)] = qp_get(str(key))
    return snapshot


def qp_write_many(updates: dict[str, str]) -> None:
    merged = qp_snapshot()
    for key, value in updates.items():
        text = clean_text(value)
        if text:
            merged[key] = text
        else:
            merged.pop(key, None)
    try:
        st.query_params.from_dict(merged)
    except Exception:
        for key, value in updates.items():
            text = clean_text(value)
            if text:
                st.query_params[key] = text
            elif key in st.query_params:
                del st.query_params[key]


def lead_sid(prefix: str, idx: int, name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")[:24]
    return f"{prefix}{idx}_{slug}" if slug else f"{prefix}{idx}"


def manual_url_indices() -> list[int]:
    found: list[int] = []
    for key in list(st.query_params.keys()):
        match = re.fullmatch(r"new_name_(\d+)", str(key))
        if match:
            found.append(int(match.group(1)))
    return sorted(set(found))


def parse_manual_leads_from_url() -> list[dict]:
    leads: list[dict] = []
    for extra_i in manual_url_indices():
        name = qp_get(f"new_name_{extra_i}")
        address = qp_get(f"new_addr_{extra_i}")
        if not name or not address:
            continue
        sid = lead_sid("m", extra_i, name)
        leads.append(
            {
                "idx": extra_i,
                "name": name,
                "address": address,
                "website": normalize_website(qp_get(f"new_link_{extra_i}")),
                "hours": normalize_hours(qp_get(f"new_hours_{extra_i}")),
                "status": normalize_status(qp_get(f"new_status_{extra_i}") or qp_get(f"stat_{sid}")),
                "notes": qp_get(f"new_notes_{extra_i}") or qp_get(f"note_{sid}"),
            }
        )
    return leads


def next_manual_index() -> int:
    ids = list(manual_url_indices())
    for lead in st.session_state.get("manual_leads", []):
        try:
            ids.append(int(lead.get("idx", -1)))
        except (TypeError, ValueError):
            continue
    ids = [i for i in ids if i >= 0]
    return (max(ids) + 1) if ids else 0


def hydrate_manual_leads_from_url() -> None:
    if "manual_leads" not in st.session_state or st.session_state["manual_leads"] is None:
        st.session_state["manual_leads"] = []
    by_idx: dict[int, dict] = {}
    for lead in st.session_state["manual_leads"]:
        try:
            by_idx[int(lead.get("idx", -1))] = lead
        except (TypeError, ValueError):
            continue
    for lead in parse_manual_leads_from_url():
        idx = int(lead["idx"])
        if idx not in by_idx:
            st.session_state["manual_leads"].append(lead)
            continue
        existing = by_idx[idx]
        for field in ("name", "address", "website", "hours", "status", "notes"):
            if not clean_text(existing.get(field)) and clean_text(lead.get(field)):
                existing[field] = lead[field]


def write_manual_lead_to_url(lead: dict) -> None:
    idx = int(lead["idx"])
    qp_write_many(
        {
            f"new_name_{idx}": lead.get("name", ""),
            f"new_addr_{idx}": lead.get("address", ""),
            f"new_link_{idx}": lead.get("website", ""),
            f"new_hours_{idx}": lead.get("hours", ""),
            f"new_status_{idx}": lead.get("status", ""),
            f"new_notes_{idx}": lead.get("notes", ""),
        }
    )


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


def overlay_status_notes(sid: str, fallback_status: str = "", fallback_notes: str = "") -> tuple[str, str]:
    status = normalize_status(qp_get(f"stat_{sid}") or fallback_status)
    notes = qp_get(f"note_{sid}")
    if not notes:
        notes = clean_text(fallback_notes)
    return status, notes


def session_manual_rows(cols: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for lead in st.session_state.get("manual_leads", []):
        name = clean_text(lead.get("name"))
        address = clean_text(lead.get("address"))
        if not name or not address:
            continue
        try:
            extra_i = int(lead.get("idx", 0))
        except (TypeError, ValueError):
            extra_i = 0
        sid = lead_sid("m", extra_i, name)
        status, notes = overlay_status_notes(
            sid,
            lead.get("status", ""),
            lead.get("notes", ""),
        )
        rows.append(
            {
                cols["name"]: name,
                cols["address"]: address,
                cols["district"]: infer_district(address),
                cols["industry"]: "",
                cols["website"]: normalize_website(lead.get("website")),
                cols["hours"]: normalize_hours(lead.get("hours")),
                cols["status"]: status,
                cols["notes"]: notes,
                "_sid": sid,
                "_src": "url",
                "_extra_i": str(extra_i),
            }
        )
    return rows


def merge_pipeline(csv_df: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    work = csv_df.copy()
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
        status, notes = overlay_status_notes(
            clean_text(row["_sid"]),
            row[cols["status"]],
            row[cols["notes"]],
        )
        work.loc[idx, cols["status"]] = status
        work.loc[idx, cols["notes"]] = notes

    extras = session_manual_rows(cols)
    if extras:
        extra_df = pd.DataFrame(extras)
        work = pd.concat([work, extra_df], ignore_index=True, sort=False).fillna("")
    return work.reset_index(drop=True)


def persist_lead(df: pd.DataFrame, cols: dict[str, str], row_idx: int, status: str, notes: str) -> None:
    df.loc[row_idx, cols["status"]] = status
    df.loc[row_idx, cols["notes"]] = notes
    row = df.loc[row_idx]
    sid = clean_text(row["_sid"])
    extra_i = clean_text(row["_extra_i"])
    updates = {
        f"stat_{sid}": status if status != STATUSES[0] else "",
        f"note_{sid}": notes,
    }
    if extra_i != "":
        updates[f"new_status_{extra_i}"] = status if status != STATUSES[0] else ""
        updates[f"new_notes_{extra_i}"] = notes
        for lead in st.session_state.get("manual_leads", []):
            try:
                if int(lead.get("idx", -1)) == int(extra_i):
                    lead["status"] = status
                    lead["notes"] = notes
                    break
            except (TypeError, ValueError):
                continue
    qp_write_many(updates)


def add_manual_lead(add_name: str, add_addr: str, add_link: str, add_hours: str) -> None:
    next_idx = next_manual_index()
    website = normalize_website(add_link)
    hours = normalize_hours(add_hours)
    lead = {
        "idx": next_idx,
        "name": add_name.strip(),
        "address": add_addr.strip(),
        "website": website,
        "hours": hours,
        "status": STATUSES[0],
        "notes": "",
    }
    if "manual_leads" not in st.session_state:
        st.session_state["manual_leads"] = []
    st.session_state["manual_leads"].append(lead)
    st.query_params[f"new_name_{next_idx}"] = add_name.strip()
    st.query_params[f"new_addr_{next_idx}"] = add_addr.strip()
    st.query_params[f"new_link_{next_idx}"] = website
    st.query_params[f"new_hours_{next_idx}"] = hours
    st.rerun()


def demo_url(name: str, website: str) -> str:
    if website.startswith(("http://", "https://")):
        return website
    query = re.sub(r"\s+", "+", name.strip()) or "Helsinki"
    return f"https://www.google.com/search?q={query}+Helsinki"


inject_chrome()
forget_old_table_state()
hydrate_manual_leads_from_url()

st.title("🎯 Helsinki Website Leads")
st.markdown(
    "Leads kommen aus `samples.csv`. Manuelle Leads liegen in Session und URL "
    "(`new_name_0`, `new_addr_0`, …) — Link als Lesezeichen speichern."
)

csv_df = load_csv_frame()
cols = detect_cols(csv_df)
df = merge_pipeline(csv_df, cols)
manual_count = len(st.session_state.get("manual_leads", []))

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
    website = normalize_website(row[cols["website"]])
    hours = normalize_hours(row[cols["hours"]])
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
    f"({len(csv_df)} from samples.csv + {manual_count} from URL/session). "
    "Bookmark this page after adding leads or saving notes."
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

            if lead["website"] == WEBSITE_TODO:
                st.button(
                    "⚠️ Website to be done",
                    key=f"todo_web_{uid}",
                    disabled=True,
                    use_container_width=True,
                )
            else:
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
            geo_url = native_geo_url(lead["latitude"], lead["longitude"])
            st.markdown(
                f'<a class="nav-link" href="{geo_url}" target="_blank" rel="noopener noreferrer">'
                f"🗺️ Navigation</a>",
                unsafe_allow_html=True,
            )
            render_google_map(lead["address"])

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
    st.caption(
        "Nur Name und Adresse sind Pflicht. Website und Visiting Hours sind freiwillig "
        "(beliebiges Textformat, z. B. 12.00-24.00 oder Abends)."
    )
    add_name = st.text_input("Name des Geschäfts / Firma", key="add_name")
    add_addr = st.text_input("Adresse (z.B. Hämeentie 38)", key="add_addr")
    add_link = st.text_input("Website / Demo-Link (optional)", key="add_link")
    add_hours = st.text_input("Visiting Hours (optional)", key="add_hours")
    if st.button("➕ Lead zur Pipeline hinzufügen", key="add_lead_btn", type="primary"):
        name = add_name.strip()
        address = add_addr.strip()
        if not name or not address:
            st.warning("Bitte Name des Geschäfts und Adresse ausfüllen.")
        else:
            existing = {
                (clean_text(row[cols["name"]]).lower(), normalize_addr(row[cols["address"]]))
                for _, row in df.iterrows()
            }
            if (name.lower(), normalize_addr(address)) in existing:
                st.warning("Dieser Lead ist bereits in der Pipeline.")
            else:
                add_manual_lead(name, address, add_link, add_hours)
