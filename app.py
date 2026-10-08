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

WEBSITE_TODO = "Website to be done"
HOURS_FALLBACK = "Not specified"

st.set_page_config(
    page_title="Helsinki Website Leads",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

url_params = st.query_params.to_dict()

if "editing_sid" not in st.session_state:
    st.session_state["editing_sid"] = ""


def param_value(params: dict, key: str) -> str:
    value = params.get(key, "")
    if isinstance(value, list):
        value = value[0] if value else ""
    text = str(value).strip() if value is not None else ""
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


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


def infer_district(address: str) -> str:
    haystack = fold_fi(normalize_addr(address))
    if not haystack:
        return "Central District (Kluuvi/Kamppi)"
    if "mannerheimintie" in haystack:
        number = first_street_number(address)
        if number is not None and number > 30:
            return "Töölö"
        return "Central District (Kluuvi/Kamppi)"
    if any(street in haystack for street in KALLIO_STREETS):
        return "Kallio"
    if any(street in haystack for street in TOOLO_STREETS):
        return "Töölö"
    if any(street in haystack for street in CENTRAL_STREETS):
        return "Central District (Kluuvi/Kamppi)"
    return "Central District (Kluuvi/Kamppi)"


def district_matches(row_district: str, selected: str) -> bool:
    if selected == "All Districts":
        return True
    if selected.lower() in row_district.lower():
        return True
    low = normalize_addr(row_district)
    aliases = DISTRICT_ALIASES.get(selected, ())
    return any(alias in low for alias in aliases)


def normalize_status(raw: str) -> str:
    text = clean_text(raw)
    if text in STATUSES:
        return text
    low = text.lower()
    if "not interested" in low:
        return STATUSES[2]
    if "interested" in low:
        return STATUSES[1]
    if "follow-up" in low or "follow up" in low:
        return STATUSES[3]
    return STATUSES[0]


def parse_float(value: object) -> float | None:
    text = clean_text(value).replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def coords_for_address(address: str) -> tuple[float, float]:
    haystack = normalize_addr(address)
    for fragment, c_lat, c_lon in KNOWN_COORDS:
        if fragment in haystack:
            return c_lat, c_lon
    return HELSINKI_CENTRAL


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


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


def load_samples_csv() -> pd.DataFrame:
    if not CSV_PATH.exists():
        st.error("Could not find samples.csv next to the app.")
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


def manual_indices(params: dict) -> list[int]:
    found: list[int] = []
    for key in params.keys():
        match = re.fullmatch(r"new_name_(\d+)", str(key))
        if match:
            found.append(int(match.group(1)))
    return sorted(set(found))


def next_manual_index(params: dict) -> int:
    ids = manual_indices(params)
    return (max(ids) + 1) if ids else 0


def leads_from_csv(df: pd.DataFrame) -> list[dict]:
    name_col = pick_col(df, ("company-name", "company_name", "name", "firma", "company"))
    addr_col = pick_col(df, ("street-address", "street_address", "address", "adresse", "street"))
    link_col = pick_col(df, ("sample-link", "sample_link", "website", "url", "link"))
    hours_col = pick_col(df, ("visiting-hours", "visiting_hours", "hours"))
    if name_col is None or addr_col is None:
        st.error("samples.csv needs Company-Name and Street-Address columns.")
        st.stop()
    leads: list[dict] = []
    for idx, row in df.iterrows():
        sid = f"c{int(idx)}"
        name = param_value(url_params, f"en_{sid}") or clean_text(row[name_col])
        address = param_value(url_params, f"ea_{sid}") or clean_text(row[addr_col])
        website = param_value(url_params, f"ew_{sid}") or (clean_text(row[link_col]) if link_col else "")
        hours = clean_text(row[hours_col]) if hours_col else ""
        leads.append(
            {
                "sid": sid,
                "extra_i": "",
                "name": name,
                "address": address,
                "website": normalize_website(website),
                "hours": normalize_hours(hours),
                "status": normalize_status(param_value(url_params, f"stat_{sid}")),
                "notes": param_value(url_params, f"note_{sid}"),
                "district": infer_district(address),
                "src": "csv",
            }
        )
    return leads


def leads_from_url(params: dict) -> list[dict]:
    leads: list[dict] = []
    for extra_i in manual_indices(params):
        name = param_value(params, f"new_name_{extra_i}")
        address = param_value(params, f"new_addr_{extra_i}")
        if not name or not address:
            continue
        sid = f"m{extra_i}"
        leads.append(
            {
                "sid": sid,
                "extra_i": str(extra_i),
                "name": name,
                "address": address,
                "website": normalize_website(param_value(params, f"new_link_{extra_i}")),
                "hours": normalize_hours(param_value(params, f"new_hours_{extra_i}")),
                "status": normalize_status(
                    param_value(params, f"new_status_{extra_i}") or param_value(params, f"stat_{sid}")
                ),
                "notes": param_value(params, f"new_notes_{extra_i}") or param_value(params, f"note_{sid}"),
                "district": infer_district(address),
                "src": "url",
            }
        )
    return leads


st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
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

st.title("🎯 Helsinki Website Leads")
st.markdown(
    "CSV-Leads aus `samples.csv`. Manuelle Leads stehen in der URL "
    "(`new_name_0`, `new_addr_0`, …). Nach dem Speichern den **vollen Browser-Link** als Lesezeichen sichern."
)

csv_df = load_samples_csv()
csv_leads = leads_from_csv(csv_df)
url_leads = leads_from_url(url_params)
all_leads = csv_leads + url_leads

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
    st.checkbox("🏠 Home Mode (Show all prepared leads)", key="home_mode")
    home_mode = st.session_state["home_mode"]
with filter_right:
    industry_keyword = st.text_input(
        "Industry Keyword Filter (e.g., Ravintola, Café, Barber)",
        key="industry_keyword",
    )
    district_filter = st.selectbox("District Filter", options=DISTRICT_OPTIONS, key="district_filter")

origin_lat, origin_lon = HELSINKI_CENTRAL
keyword = industry_keyword.strip().lower()

enriched_rows: list[dict] = []
for lead in all_leads:
    lat, lon = coords_for_address(lead["address"])
    distance_m = haversine_m(origin_lat, origin_lon, lat, lon)
    if not district_matches(lead["district"], district_filter):
        continue
    if keyword:
        blob = f"{lead['name']} {lead['address']} {lead['district']}".lower()
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
    f"{len(enriched_rows)} lead(s) visible "
    f"({len(csv_leads)} from samples.csv + {len(url_leads)} from URL). "
    "Bookmark the full URL after saving a lead."
)

if not enriched_rows:
    st.info("No leads match these filters. Turn on Home Mode or relax the filters.")

for lead in enriched_rows:
    uid = lead["sid"]
    status_key = f"status_{uid}"
    notes_key = f"notes_{uid}"
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
                        new_name = st.session_state[f"edit_name_{uid}"].strip()
                        new_addr = st.session_state[f"edit_addr_{uid}"].strip()
                        new_link = normalize_website(st.session_state[f"edit_link_{uid}"])
                        if new_name and new_addr:
                            extra_i = lead["extra_i"]
                            if extra_i != "":
                                st.query_params.update(
                                    {
                                        f"new_name_{extra_i}": new_name,
                                        f"new_addr_{extra_i}": new_addr,
                                        f"new_link_{extra_i}": new_link,
                                    }
                                )
                            else:
                                st.query_params.update(
                                    {
                                        f"en_{uid}": new_name,
                                        f"ea_{uid}": new_addr,
                                        f"ew_{uid}": new_link,
                                    }
                                )
                            st.session_state["editing_sid"] = ""
                            st.rerun()
                with cancel_col:
                    if st.button("❌ Cancel", key=f"cancel_info_{uid}", use_container_width=True):
                        st.session_state["editing_sid"] = ""
                        st.rerun()
            else:
                st.markdown(f"### {lead['name']}")
                st.markdown(
                    f"<div class='addr-line'>📍 Address: {lead['address']}, Helsinki</div>",
                    unsafe_allow_html=True,
                )
                if st.button("✏️ Edit Lead Info", key=f"edit_btn_{uid}"):
                    st.session_state["editing_sid"] = uid
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
                payload = {f"stat_{uid}": chosen_status, f"note_{uid}": st.session_state[notes_key]}
                if lead["extra_i"]:
                    payload[f"new_status_{lead['extra_i']}"] = chosen_status
                st.query_params.update(payload)
                st.rerun()

            demo_href = live_website_url(lead["website"])
            if website_is_todo(lead["website"]) or not demo_href:
                st.button("⚠️ Website to be done", key=f"todo_web_{uid}", disabled=True, use_container_width=True)
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
                f'<a class="nav-link" href="{geo_url}" target="_blank" rel="noopener noreferrer">🗺️ Navigation</a>',
                unsafe_allow_html=True,
            )
            render_google_map(lead["address"])

        st.text_area("✍️ Field Notes (e.g. Email, Mobile):", key=notes_key)
        if st.button("💾 Save Note", key=f"save_note_{uid}", use_container_width=True, type="secondary"):
            payload = {
                f"stat_{uid}": st.session_state[status_key],
                f"note_{uid}": st.session_state[notes_key],
            }
            if lead["extra_i"]:
                payload[f"new_status_{lead['extra_i']}"] = st.session_state[status_key]
                payload[f"new_notes_{lead['extra_i']}"] = st.session_state[notes_key]
            st.query_params.update(payload)
            st.rerun()

st.markdown("---")
with st.expander("➕ Neuen Lead manuell hinzufügen", expanded=False):
    st.caption("Nur Name und Adresse sind Pflicht. Der Lead wird in die Browser-URL geschrieben.")
    with st.form("manual_lead_form", clear_on_submit=True):
        add_name = st.text_input("Name des Geschäfts / Firma")
        add_addr = st.text_input("Adresse (z.B. Hämeentie 38)")
        add_link = st.text_input("Website / Demo-Link (optional)")
        add_hours = st.text_input("Visiting Hours (optional)")
        submitted = st.form_submit_button(
            "💾 LEAD DASHBOARD-WEIT SPEICHERN",
            use_container_width=True,
            type="primary",
        )
        if submitted:
            if not add_name.strip() or not add_addr.strip():
                st.warning("Bitte Name des Geschäfts und Adresse ausfüllen.")
            else:
                next_idx = next_manual_index(url_params)
                st.query_params.update(
                    {
                        f"new_name_{next_idx}": add_name.strip(),
                        f"new_addr_{next_idx}": add_addr.strip(),
                        f"new_link_{next_idx}": normalize_website(add_link),
                        f"new_hours_{next_idx}": normalize_hours(add_hours),
                    }
                )
                st.rerun()
