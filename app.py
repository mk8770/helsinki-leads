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

if "editing_sid" not in st.session_state:
    st.session_state["editing_sid"] = ""


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
        .hours-line { text-align: left; margin: 0 0 0.35rem 0; }
        .addr-line, .district-line { display: block; margin: 0 0 0.2rem 0; line-height: 1.35; }
        .nav-link {
            display: inline-block;
            font-weight: 800;
            color: #4285F4 !important;
            text-decoration: none;
            font-size: 0.95rem;
            text-align: left;
            margin: 0.1rem 0 0.4rem 0;
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
    if "google.com/search" in low:
        return WEBSITE_TODO
    return text


def website_is_todo(raw: object) -> bool:
    text = normalize_website(raw)
    return (not text) or text == WEBSITE_TODO


def live_website_url(raw: object) -> str:
    text = normalize_website(raw)
    if website_is_todo(text):
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return f"https://{text}"


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
    text = address.lower().replace("ß", "ss")
    text = re.sub(r"[.,]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold_fi(text: str) -> str:
    return text.lower().replace("ä", "a").replace("ö", "o").replace("å", "a").replace("é", "e")


def first_street_number(address: str) -> int | None:
    match = re.search(r"(\d+)", normalize_addr(address))
    if not match:
        return None
    return int(match.group(1))


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
    return clean_text(district) or "Central District (Kluuvi/Kamppi)"


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


def qp_dump() -> dict[str, str]:
    dumped: dict[str, str] = {}
    for key in list(st.query_params.keys()):
        dumped[str(key)] = qp_get(str(key))
    return dumped


def qp_commit(updates: dict[str, str]) -> None:
    merged = qp_dump()
    for key, value in updates.items():
        merged[str(key)] = "" if value is None else str(value)
    try:
        st.query_params.from_dict(merged)
    except Exception:
        for key, value in updates.items():
            st.query_params[str(key)] = "" if value is None else str(value)


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


def next_manual_index() -> int:
    ids = manual_url_indices()
    return (max(ids) + 1) if ids else 0


def parse_manual_leads_from_url() -> list[dict]:
    leads: list[dict] = []
    for extra_i in manual_url_indices():
        name = qp_get(f"new_name_{extra_i}")
        address = qp_get(f"new_addr_{extra_i}")
        if not name or not address:
            continue
        sid = f"m{extra_i}"
        leads.append(
            {
                "idx": extra_i,
                "sid": sid,
                "name": name,
                "address": address,
                "website": normalize_website(qp_get(f"new_link_{extra_i}")),
                "hours": normalize_hours(qp_get(f"new_hours_{extra_i}")),
                "status": normalize_status(qp_get(f"new_status_{extra_i}") or qp_get(f"stat_{sid}")),
                "notes": qp_get(f"new_notes_{extra_i}") or qp_get(f"note_{sid}"),
                "src": "url",
            }
        )
    return leads


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
        st.error("Could not detect a company-name column.")
        st.stop()
    if cols["address"] is None:
        st.error("Could not detect a street-address column.")
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


def csv_edit_patch(sid: str) -> dict[str, str]:
    name = qp_get(f"en_{sid}")
    address = qp_get(f"ea_{sid}")
    website = qp_get(f"ew_{sid}")
    patch: dict[str, str] = {}
    if name:
        patch["name"] = name
    if address:
        patch["address"] = address
    if website:
        patch["website"] = normalize_website(website)
    return patch


def build_pipeline(csv_df: pd.DataFrame, cols: dict[str, str]) -> list[dict]:
    leads: list[dict] = []
    for idx, row in csv_df.iterrows():
        sid = f"c{int(idx)}"
        patch = csv_edit_patch(sid)
        name = patch.get("name") or clean_text(row[cols["name"]])
        address = patch.get("address") or clean_text(row[cols["address"]])
        website = patch.get("website") or normalize_website(row[cols["website"]])
        leads.append(
            {
                "sid": sid,
                "csv_idx": int(idx),
                "extra_i": "",
                "name": name,
                "address": address,
                "website": website,
                "hours": normalize_hours(row[cols["hours"]]),
                "status": normalize_status(qp_get(f"stat_{sid}") or row[cols["status"]]),
                "notes": qp_get(f"note_{sid}") or clean_text(row[cols["notes"]]),
                "district": infer_district(address, clean_text(row[cols["district"]])),
                "industry": clean_text(row[cols["industry"]]) if cols["industry"] else "",
                "src": "csv",
                "lat_src": row[cols["lat"]] if cols["lat"] else "",
                "lon_src": row[cols["lon"]] if cols["lon"] else "",
            }
        )

    for item in parse_manual_leads_from_url():
        address = item["address"]
        leads.append(
            {
                "sid": item["sid"],
                "csv_idx": -1,
                "extra_i": str(item["idx"]),
                "name": item["name"],
                "address": address,
                "website": item["website"],
                "hours": item["hours"],
                "status": item["status"],
                "notes": item["notes"],
                "district": infer_district(address),
                "industry": "",
                "src": "url",
                "lat_src": "",
                "lon_src": "",
            }
        )
    return leads


def add_manual_lead(add_name: str, add_addr: str, add_link: str, add_hours: str) -> None:
    next_idx = next_manual_index()
    st.query_params[f"new_name_{next_idx}"] = add_name.strip()
    st.query_params[f"new_addr_{next_idx}"] = add_addr.strip()
    st.query_params[f"new_link_{next_idx}"] = normalize_website(add_link)
    st.query_params[f"new_hours_{next_idx}"] = normalize_hours(add_hours)
    st.rerun()


def save_lead_edits(sid: str, extra_i: str, name: str, address: str, website: str) -> None:
    name = name.strip()
    address = address.strip()
    website = normalize_website(website)
    if not name or not address:
        st.warning("Bitte Name und Adresse ausfüllen.")
        return
    if extra_i != "":
        st.query_params[f"new_name_{extra_i}"] = name
        st.query_params[f"new_addr_{extra_i}"] = address
        st.query_params[f"new_link_{extra_i}"] = website
    else:
        st.query_params[f"en_{sid}"] = name
        st.query_params[f"ea_{sid}"] = address
        st.query_params[f"ew_{sid}"] = website
    st.session_state["editing_sid"] = ""
    for key in (f"edit_name_{sid}", f"edit_addr_{sid}", f"edit_link_{sid}"):
        st.session_state.pop(key, None)
    st.rerun()


def persist_status_notes(sid: str, extra_i: str, status: str, notes: str) -> None:
    st.query_params[f"stat_{sid}"] = status
    st.query_params[f"note_{sid}"] = notes
    if extra_i != "":
        st.query_params[f"new_status_{extra_i}"] = status
        st.query_params[f"new_notes_{extra_i}"] = notes
    st.rerun()


inject_chrome()

st.title("🎯 Helsinki Website Leads")
st.markdown(
    "Basis-Leads aus `samples.csv`. Manuelle Leads und Korrekturen stehen in der URL "
    "(`new_name_0`, `new_addr_0`, …). Diesen Link als Lesezeichen speichern und teilen."
)

csv_df = load_csv_frame()
cols = detect_cols(csv_df)
all_leads = build_pipeline(csv_df, cols)
manual_count = len(parse_manual_leads_from_url())

st.subheader("Distance")
filter_left, filter_right = st.columns(2)

with filter_left:
    home_mode = st.session_state.get("home_mode", False)
    st.slider(
        "Max walking distance from YOUR location (meters)",
        min_value=100,
        max_value=5000,
        value=2000,
        step=50,
        disabled=home_mode,
        key="max_distance",
    )
    st.checkbox(
        "🏠 Home Mode (Show all prepared leads)",
        key="home_mode",
    )
    home_mode = st.session_state["home_mode"]

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
for lead in all_leads:
    lat, lon = coords_for_address(lead["address"], lead["lat_src"], lead["lon_src"])
    distance_m = haversine_m(origin_lat, origin_lon, lat, lon)
    if not district_matches(lead["district"], district_filter):
        continue
    if keyword:
        blob = f"{lead['industry']} {lead['name']} {lead['address']} {lead['district']}".lower()
        if keyword not in blob:
            continue
    if not home_mode and distance_m > float(st.session_state["max_distance"]):
        continue
    item = dict(lead)
    item["latitude"] = lat
    item["longitude"] = lon
    item["distance_m"] = distance_m
    enriched_rows.append(item)

enriched_rows.sort(
    key=lambda item: (0 if item["status"] == STATUSES[0] else 1, item["distance_m"], item["name"])
)

st.markdown("---")
st.subheader("Active Lead Pipeline")
st.caption(
    f"{len(enriched_rows)} lead(s) match the current filters "
    f"({len(csv_df)} from samples.csv + {manual_count} from URL). "
    "Bookmark the full browser link after adding or editing leads."
)

if not enriched_rows:
    st.info("No leads match these filters. Turn on Home Mode or relax the filters.")

for lead in enriched_rows:
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
            editing = st.session_state.get("editing_sid") == uid
            if editing:
                if f"edit_name_{uid}" not in st.session_state:
                    st.session_state[f"edit_name_{uid}"] = lead["name"]
                if f"edit_addr_{uid}" not in st.session_state:
                    st.session_state[f"edit_addr_{uid}"] = lead["address"]
                if f"edit_link_{uid}" not in st.session_state:
                    st.session_state[f"edit_link_{uid}"] = (
                        "" if website_is_todo(lead["website"]) else lead["website"]
                    )
                st.text_input("Edit Name", key=f"edit_name_{uid}")
                st.text_input("Edit Address", key=f"edit_addr_{uid}")
                st.text_input("Edit Website Link", key=f"edit_link_{uid}")
                save_col, cancel_col = st.columns(2)
                with save_col:
                    if st.button("💾 Save Changes", key=f"save_info_{uid}", type="primary", use_container_width=True):
                        save_lead_edits(
                            uid,
                            lead["extra_i"],
                            st.session_state[f"edit_name_{uid}"],
                            st.session_state[f"edit_addr_{uid}"],
                            st.session_state[f"edit_link_{uid}"],
                        )
                with cancel_col:
                    if st.button("❌ Cancel", key=f"cancel_info_{uid}", use_container_width=True):
                        st.session_state["editing_sid"] = ""
                        for key in (f"edit_name_{uid}", f"edit_addr_{uid}", f"edit_link_{uid}"):
                            st.session_state.pop(key, None)
                        st.rerun()
            else:
                st.markdown(f"### {lead['name']}")
                st.markdown(
                    f"<div class='addr-line'>📍 Address: {lead['address']}, Helsinki</div>",
                    unsafe_allow_html=True,
                )
                if st.button("✏️ Edit Lead Info", key=f"edit_btn_{uid}"):
                    st.session_state["editing_sid"] = uid
                    st.session_state[f"edit_name_{uid}"] = lead["name"]
                    st.session_state[f"edit_addr_{uid}"] = lead["address"]
                    st.session_state[f"edit_link_{uid}"] = (
                        "" if website_is_todo(lead["website"]) else lead["website"]
                    )
                    st.rerun()

            st.markdown(
                f"<div class='district-line'>🏙️ District: {lead['district']}</div>",
                unsafe_allow_html=True,
            )
            if home_mode:
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
                persist_status_notes(uid, lead["extra_i"], chosen_status, st.session_state[notes_key])

            demo_href = live_website_url(lead["website"])
            if website_is_todo(lead["website"]) or not demo_href:
                st.button(
                    "⚠️ Website to be done",
                    key=f"todo_web_{uid}",
                    disabled=True,
                    use_container_width=True,
                )
            else:
                st.link_button(
                    f"🌐 Click here to open Demo Website for {lead['name']}",
                    url=demo_href,
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

        st.text_area("✍️ Field Notes (e.g. Email, Mobile):", key=notes_key)
        if st.button("💾 Save Note", key=save_key, use_container_width=True, type="secondary"):
            persist_status_notes(uid, lead["extra_i"], st.session_state[status_key], st.session_state[notes_key])

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=False):
    st.caption(
        "Nur Name und Adresse sind Pflicht. Der Lead wird sofort in die Browser-URL geschrieben. "
        "Danach den gesamten Link als Lesezeichen speichern."
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
            existing = {(item["name"].lower(), normalize_addr(item["address"])) for item in all_leads}
            if (name.lower(), normalize_addr(address)) in existing:
                st.warning("Dieser Lead ist bereits in der Pipeline.")
            else:
                add_manual_lead(name, address, add_link, add_hours)
