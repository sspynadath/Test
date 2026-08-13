import json
import math
import os
import re
from datetime import datetime
from html import escape
from urllib.parse import parse_qs, unquote, urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:  # Public web enrichment degrades gracefully if optional packages are absent.
    requests = None
    BeautifulSoup = None

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pe_core import (
    FIRM_CONFIGS,
    ai_signal_count,
    build_ai_context,
    build_why_now,
    classify_news_signal,
    compute_data_confidence,
    compute_opportunity_score,
    detect_technology_signals,
    enrich_job_description,
    extract_skills,
    get_google_news,
    get_official_description,
    get_official_news_cards,
    get_profile_bio,
    get_public_jobs,
    get_public_leadership,
    get_public_portfolio,
    get_wikipedia_summary,
    job_relevance,
    leader_reason,
    load_capabilities,
    load_local_insights,
    load_local_jobs,
    load_local_leadership,
    load_local_portfolio,
    make_account_brief_markdown,
    map_ai_opportunities,
    merge_insights,
    normalize_insights,
    normalize_jobs,
    normalize_leadership,
    normalize_portfolio,
    opportunity_score_breakdown,
    parse_uploaded_file,
    run_ai_analysis,
    score_band,
    skills_relevant_to_coforge,
    source_coverage,
    tech_evidence,
)


APP_VERSION = "4.0.0"

from portfolio_intel import (
    build_disambiguated_news_query,
    build_portco_account,
    choose_bio_record,
    credibility_label,
    discover_company_jobs,
    discover_company_leadership,
    entity_slug,
    filter_company_news,
    hostname,
    local_entity_records,
    portfolio_row_website,
)

from portfolio_news import (
    clear_news_cache,
    resolve_company_website,
    scrape_company_first_party_news,
)

# =============================================================================
# PAGE CONFIG + DESIGN SYSTEM
# =============================================================================
st.set_page_config(
    page_title="Coforge PE Intelligence",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --bg: #f5f7fb;
        --panel: rgba(255,255,255,.96);
        --panel-2: #fbfcff;
        --ink: #0f172a;
        --muted: #64748b;
        --line: #e6eaf2;
        --brand: #635bff;
        --brand-deep: #3427b6;
        --cyan: #0ea5e9;
        --green: #16a34a;
        --amber: #d97706;
        --red: #dc2626;
        --nav: #101423;
        --nav2: #171c30;
    }

    html, body, [class*="css"] { font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .stApp {
        background:
          radial-gradient(circle at 85% 2%, rgba(99,91,255,.09), transparent 25rem),
          radial-gradient(circle at 22% 20%, rgba(14,165,233,.045), transparent 23rem),
          var(--bg);
        color: var(--ink);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, var(--nav) 0%, var(--nav2) 100%);
        border-right: 1px solid rgba(255,255,255,.06);
    }
    [data-testid="stSidebar"] * { color: #eef2ff; }
    [data-testid="stSidebar"] label { color: #cbd5e1 !important; }
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] input {
        background-color: rgba(255,255,255,.08) !important;
        border-color: rgba(255,255,255,.12) !important;
        color: white !important;
    }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.08); }

    .block-container {
        max-width: 1540px;
        padding-top: 1.1rem;
        padding-bottom: 3.5rem;
    }

    .brand-lockup { margin-bottom: .35rem; }
    .brand-mark {
        width: 30px; height: 30px; border-radius: 9px;
        display: inline-flex; align-items: center; justify-content: center;
        background: linear-gradient(135deg, #8b5cf6, #4f46e5);
        color: white; font-weight: 900; margin-right: 8px;
        box-shadow: 0 8px 20px rgba(99,91,255,.35);
    }
    .brand-title { font-weight: 780; font-size: 1.05rem; vertical-align: middle; }
    .brand-sub { color:#94a3b8; font-size:.74rem; margin-top:.25rem; }

    .hero {
        position: relative;
        overflow: hidden;
        padding: 1.5rem 1.65rem 1.35rem;
        border-radius: 22px;
        background:
          radial-gradient(circle at 90% 30%, rgba(118,97,255,.48), transparent 23rem),
          linear-gradient(120deg, #0c1324 0%, #1b1d42 55%, #322585 100%);
        box-shadow: 0 20px 52px rgba(21,25,54,.16);
        color:white;
        margin-bottom: 1rem;
    }
    .hero:after {
        content:""; position:absolute; width:340px; height:340px; border-radius:50%;
        border:1px solid rgba(255,255,255,.07); right:-110px; top:-155px;
    }
    .hero-kicker { color:#c4b5fd; font-size:.72rem; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }
    .hero-title { font-size:2.05rem; line-height:1.08; font-weight:800; margin:.35rem 0 .35rem; letter-spacing:-.03em; }
    .hero-sub { color:#dbeafe; font-size:.93rem; max-width:930px; }
    .hero-meta { color:#a5b4fc; font-size:.78rem; margin-top:.65rem; }

    .kpi-card, .glass-card, .signal-card, .leader-card, .news-card, .op-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        box-shadow: 0 9px 26px rgba(15,23,42,.045);
    }
    .kpi-card { padding: .95rem 1rem; min-height:108px; }
    .kpi-label { color:var(--muted); font-size:.69rem; font-weight:800; letter-spacing:.075em; text-transform:uppercase; }
    .kpi-value { color:var(--ink); font-size:1.65rem; font-weight:800; letter-spacing:-.03em; margin:.25rem 0 .08rem; }
    .kpi-note { color:#7c879a; font-size:.73rem; line-height:1.3; }
    .glass-card { padding:1rem 1.05rem; }
    .card-title { font-size:.95rem; font-weight:760; color:#172033; margin-bottom:.3rem; }
    .card-copy { font-size:.86rem; color:#64748b; line-height:1.52; }

    .section-kicker { color:#6366f1; font-size:.69rem; font-weight:800; letter-spacing:.09em; text-transform:uppercase; margin-bottom:.1rem; }
    .section-title { color:#111827; font-size:1.12rem; font-weight:800; letter-spacing:-.01em; margin:.05rem 0 .45rem; }
    .section-sub { color:#64748b; font-size:.84rem; margin-bottom:.65rem; }

    .badge {
        display:inline-block; padding:.22rem .5rem; border-radius:999px; font-size:.68rem; font-weight:750;
        margin:0 .15rem .15rem 0; border:1px solid transparent;
    }
    .badge-purple { background:#eef2ff; color:#4f46e5; border-color:#e0e7ff; }
    .badge-green { background:#ecfdf5; color:#15803d; border-color:#d1fae5; }
    .badge-amber { background:#fffbeb; color:#b45309; border-color:#fef3c7; }
    .badge-blue { background:#eff6ff; color:#1d4ed8; border-color:#dbeafe; }
    .badge-gray { background:#f8fafc; color:#64748b; border-color:#e2e8f0; }
    .badge-red { background:#fef2f2; color:#b91c1c; border-color:#fee2e2; }

    .signal-card { padding:.85rem .9rem; margin-bottom:.55rem; }
    .signal-top { display:flex; align-items:center; justify-content:space-between; gap:.75rem; }
    .signal-name { font-weight:760; color:#172033; font-size:.9rem; }
    .signal-copy { color:#64748b; font-size:.78rem; margin-top:.25rem; line-height:1.42; }

    .score-ring-wrap { display:flex; align-items:center; gap:1rem; }
    .score-number { font-size:2.45rem; font-weight:850; letter-spacing:-.06em; color:#111827; }
    .score-label { font-size:.78rem; color:#64748b; }

    .data-row { display:flex; align-items:center; justify-content:space-between; padding:.52rem 0; border-bottom:1px solid #eef2f7; }
    .data-row:last-child { border-bottom:none; }
    .data-label { color:#334155; font-size:.82rem; font-weight:700; }
    .data-meta { color:#64748b; font-size:.75rem; }

    .news-card { padding:.9rem 1rem; margin-bottom:.55rem; }
    .news-title { color:#172033; font-size:.91rem; font-weight:760; line-height:1.35; }
    .news-summary { color:#64748b; font-size:.78rem; line-height:1.48; margin-top:.35rem; }
    .news-meta { color:#94a3b8; font-size:.68rem; margin-top:.38rem; }

    .op-card { padding:1rem; height:100%; }
    .op-head { display:flex; justify-content:space-between; gap:.8rem; align-items:flex-start; }
    .op-name { color:#172033; font-size:.92rem; font-weight:800; }
    .op-copy { color:#64748b; font-size:.79rem; line-height:1.48; margin-top:.4rem; }
    .op-evidence { color:#475569; font-size:.72rem; margin-top:.55rem; padding-top:.5rem; border-top:1px solid #edf0f5; }

    .person-detail {
        background: linear-gradient(135deg, #ffffff, #f8f8ff);
        border:1px solid #e3e6ef; border-radius:17px; padding:1rem 1.05rem; margin-bottom:.75rem;
    }
    .person-name { font-size:1.08rem; font-weight:820; color:#111827; }
    .person-role { font-size:.83rem; color:#4f46e5; font-weight:720; margin:.14rem 0 .4rem; }
    .person-bio { font-size:.82rem; color:#64748b; line-height:1.52; }

    .empty-state { background:#fff; border:1px dashed #cbd5e1; border-radius:16px; padding:1.2rem; color:#64748b; }
    .scope-note { background:#fffaf0; border:1px solid #fde7b3; color:#7c5b16; padding:.72rem .85rem; border-radius:12px; font-size:.77rem; line-height:1.45; }

    div[data-testid="stMetric"] { background:white; border:1px solid var(--line); border-radius:15px; padding:.75rem .9rem; }
    [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
    .stButton > button, .stDownloadButton > button, .stLinkButton > a {
        border-radius:10px !important; font-weight:680 !important; min-height:2.5rem;
    }
    .stTabs [data-baseweb="tab-list"] { gap:.35rem; }
    .stTabs [data-baseweb="tab"] { border-radius:9px; padding:.45rem .75rem; }

    .explain-card { background:#fbfcff; border:1px solid var(--line); border-radius:14px; padding:.8rem .9rem; }
    .tiny-label { color:#64748b; font-size:.7rem; font-weight:760; text-transform:uppercase; letter-spacing:.06em; }
    .tiny-value { color:#172033; font-size:.83rem; font-weight:760; }
    .evidence-strip { color:#64748b; font-size:.72rem; margin-top:.35rem; padding-top:.4rem; border-top:1px solid #eef2f7; }
    .persona-chip { display:inline-block; padding:.2rem .46rem; border-radius:999px; font-size:.66rem; font-weight:750; background:#f1f5f9; color:#475569; margin:.1rem .15rem .1rem 0; }
    .score-row { margin-bottom:.58rem; }
    .score-row-top { display:flex; justify-content:space-between; gap:.6rem; font-size:.76rem; color:#475569; margin-bottom:.2rem; }
    .score-track { width:100%; height:7px; border-radius:99px; background:#eef2f7; overflow:hidden; }
    .score-fill { height:100%; border-radius:99px; background:linear-gradient(90deg,#635bff,#0ea5e9); }
    #MainMenu, footer {visibility:hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# UI HELPERS
# =============================================================================
def section_title(title, sub=None, kicker=None):
    if kicker:
        st.markdown(f'<div class="section-kicker">{escape(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{escape(title)}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="section-sub">{escape(sub)}</div>', unsafe_allow_html=True)


def kpi_card(label, value, note=""):
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{escape(str(label))}</div>
            <div class="kpi-value">{escape(str(value))}</div>
            <div class="kpi-note">{escape(str(note))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text, kind="purple"):
    return f'<span class="badge badge-{kind}">{escape(str(text))}</span>'


def strength_badge(score):
    if score >= 5:
        return badge("Very strong", "green")
    if score >= 4:
        return badge("Strong", "green")
    if score >= 3:
        return badge("Medium", "amber")
    return badge("Early", "gray")


def priority_badge(score):
    if score >= 75:
        return badge("High priority", "green")
    if score >= 55:
        return badge("Developing", "blue")
    if score >= 35:
        return badge("Watchlist", "amber")
    return badge("Unqualified", "gray")


def relevance_badge(score):
    if score >= 5:
        return badge("5/5 Coforge fit", "green")
    if score >= 4:
        return badge("4/5 Coforge fit", "blue")
    if score >= 3:
        return badge("3/5 Coforge fit", "amber")
    return badge(f"{score}/5 fit", "gray")


def hero(account, score, coverage_score, latest_count):
    kind = account.get("entity_kind", "PE firm")
    kicker = "COFORGE · PE ACCOUNT INTELLIGENCE" if kind == "PE firm" else "COFORGE · PORTFOLIO COMPANY INTELLIGENCE"
    if kind == "PE firm":
        scope_copy = "Portfolio, people, hiring, technology, news and evidence-based AI opportunity intelligence in one workspace."
    else:
        parent = account.get("parent_firm_name", "the selected PE sponsor")
        scope_copy = f"Operating-company intelligence across leadership, hiring, technology, news and Coforge opportunities · backed by {parent}."
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-kicker">{escape(kicker)}</div>
            <div class="hero-title">{escape(account['name'])}</div>
            <div class="hero-sub">{escape(account.get('category','Account'))} · {escape(scope_copy)}</div>
            <div class="hero-meta">Priority {score}/100 &nbsp;·&nbsp; Data confidence {coverage_score}% &nbsp;·&nbsp; {latest_count} intelligence items loaded</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def nav_button(label, target, key):
    if st.button(label, key=key, use_container_width=True):
        st.session_state.page = target
        st.rerun()


def display_news_card(article, compact=False):
    title = escape(article.get("title") or "Untitled")
    summary = escape((article.get("summary") or "")[:350 if compact else 650])
    source = escape(article.get("source") or "News")
    published = escape(article.get("published") or "")
    signal = escape(article.get("signal_type") or "Other")
    quality = article.get("credibility") or credibility_label(article)
    quality_kind = "green" if quality == "Official company source" else "blue" if quality == "Priority publication" else "gray"
    link = article.get("link") or ""
    html = f"""
    <div class="news-card">
        <div>{badge(signal, 'purple')} {badge(source, 'gray')} {badge(quality, quality_kind)}</div>
        <div class="news-title">{title}</div>
        {f'<div class="news-summary">{summary}</div>' if summary else ''}
        <div class="news-meta">{published}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    if link:
        st.link_button("Open source ↗", link, use_container_width=compact)


def safe_unique(values):
    return sorted({str(x).strip() for x in values if str(x).strip() and str(x).strip().lower() not in {"nan", "none"}})


def source_mode(session_key, firm_key, local_data, public_data, public_label):
    uploaded = st.session_state[session_key].get(firm_key)
    if uploaded:
        return "Session upload"
    if local_data:
        return "Local data file"
    if public_data:
        return public_label
    return "Not available"


def is_http_url(value):
    try:
        return urlparse(str(value or "")).scheme in {"http", "https"}
    except Exception:
        return False


def clean_company_search_name(name):
    # Public search engines often struggle with leading symbols (e.g. +Simple).
    text = re.sub(r"^[^A-Za-z0-9]+", "", str(name or "")).strip()
    return text or str(name or "").strip()


def raw_dataset_count(firm_key, kind):
    """Count source rows before the normaliser deduplicates them.

    This is intentionally app-side so the UI can explain Raw -> Unique without
    changing the stable pe_core data contract.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    for ext in ["json", "csv", "xlsx"]:
        candidates.append(os.path.join(base_dir, "data", firm_key, f"{kind}.{ext}"))
        candidates.append(os.path.join(base_dir, f"{firm_key}_{kind}.{ext}"))
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            if path.lower().endswith(".json"):
                with open(path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                if isinstance(raw, list):
                    return len(raw)
                if isinstance(raw, dict):
                    for key in ["data", "items", "results", "records", "jobs"]:
                        if isinstance(raw.get(key), list):
                            return len(raw[key])
                    for value in raw.values():
                        if isinstance(value, list):
                            return len(value)
            elif path.lower().endswith(".csv"):
                return len(pd.read_csv(path))
            else:
                return len(pd.read_excel(path))
        except Exception:
            return None
    return None


def leadership_persona(role):
    r = str(role or "").lower()
    if any(x in r for x in ["chief information", "cio", "chief technology", "cto", "chief data", "chief digital", "chief ai", "head of ai", "head of data", "technology", "digital", "data", "cyber"]):
        return "Technology / Data / AI"
    if any(x in r for x in ["operating partner", "portfolio operations", "portfolio", "value creation", "operational excellence", "capstone"]):
        return "Portfolio value creation"
    if any(x in r for x in ["chief executive", "ceo", "managing partner", "co-executive", "co-ceo", "president", "chief investment"]):
        return "Senior sponsor"
    if any(x in r for x in ["partner", "managing director", "principal", "director"]):
        return "Investment / sector"
    return "Other stakeholder"


def clean_leadership_records(records):
    """Light UI cleanup for directory scrapers without mutating pe_core.

    It separates common trailing office names from roles and strips duplicated
    person names. Badly concatenated directory bios are handled later.
    """
    cities = [
        "New York", "London", "Tokyo", "Frankfurt", "Paris", "Hong Kong",
        "Singapore", "Dubai", "Mumbai", "Sydney", "Menlo Park", "San Francisco",
        "Boston", "Chicago", "Houston", "Los Angeles", "Washington", "Dublin",
        "Luxembourg", "Madrid", "Milan", "Munich", "Stockholm", "Amsterdam",
    ]
    cleaned = []
    for item in records or []:
        row = dict(item)
        name = str(row.get("Name", "")).strip()
        role = str(row.get("Role", "")).strip()
        location = str(row.get("Location", "")).strip()
        if name and role.lower().startswith(name.lower()):
            role = role[len(name):].strip(" ,-|·")
        if not location:
            for city in cities:
                if role.lower().endswith(city.lower()):
                    location = city
                    role = role[:-len(city)].strip(" ,-|·")
                    break
        # Avoid showing an obviously concatenated role string as authoritative.
        if len(role) > 150:
            role = role[:147].rsplit(" ", 1)[0] + "…"
        row["Name"] = name
        row["Role"] = role
        row["Location"] = location
        row["Persona"] = leadership_persona(role)
        cleaned.append(row)
    return cleaned


def clean_person_bio(person, all_people, fetched_profile=None):
    if fetched_profile and fetched_profile.get("bio"):
        return fetched_profile["bio"], "Official profile"
    bio = str(person.get("Bio") or "").strip()
    if not bio:
        return "A longer official biography was not available from the parsed source.", "Directory record"
    # Directory cards occasionally capture neighbouring people. If that happens,
    # stop before the next known name instead of displaying polluted text.
    selected_name = str(person.get("Name") or "").strip()
    cut_points = []
    for other in all_people or []:
        other_name = str(other.get("Name") or "").strip()
        if not other_name or other_name == selected_name:
            continue
        pos = bio.lower().find(other_name.lower())
        if pos > 30:
            cut_points.append(pos)
    if cut_points:
        bio = bio[:min(cut_points)].strip(" ,-|·")
    if selected_name and bio.lower().startswith(selected_name.lower()):
        bio = bio[len(selected_name):].strip(" ,-|·")
    return bio[:1800] or "Biography could not be cleanly separated from the public directory. Open the official profile for the source record.", "Directory extract"


def latest_evidence_date(item, insights):
    typ = item.get("Type", "")
    if typ == "Growth":
        candidates = [x for x in insights if x.get("signal_type") in {"M&A / Deal", "Portfolio", "Growth"}]
    elif typ in {"News", "Technology"}:
        candidates = [x for x in insights if x.get("published")]
    else:
        candidates = []
    dated = []
    for row in candidates:
        try:
            dt = pd.to_datetime(row.get("published"), utc=True, errors="coerce")
            if pd.notna(dt):
                dated.append(dt)
        except Exception:
            pass
    if not dated:
        return "Current captured dataset"
    return max(dated).strftime("%d %b %Y")


def why_now_display_strength(item):
    """Keep 'Very strong' rare: require multi-source or unusually broad evidence."""
    evidence = str(item.get("Evidence", "")).lower()
    typ = item.get("Type", "")
    score = int(item.get("Strength", 1) or 1)
    if typ == "Technology":
        m = re.search(r"across (\d+) job\(s\) and (\d+) news", evidence)
        if m:
            jobs_n, news_n = int(m.group(1)), int(m.group(2))
            if jobs_n > 0 and news_n > 0 and jobs_n + news_n >= 5:
                return 5
            if jobs_n + news_n >= 3:
                return 4
            return 3
    if typ == "Hiring":
        n = int(re.search(r"(\d+)", evidence).group(1)) if re.search(r"(\d+)", evidence) else 0
        return 5 if n >= 12 else 4 if n >= 5 else 3
    if typ == "Growth":
        n = int(re.search(r"(\d+)", evidence).group(1)) if re.search(r"(\d+)", evidence) else 0
        return 5 if n >= 12 else 4 if n >= 5 else 3
    return min(score, 4)


def why_now_source_label(item):
    return {
        "Technology": "Jobs + news / insights",
        "Hiring": "Captured job postings",
        "News": "News + official insights",
        "Growth": "Transactions / portfolio / growth news",
    }.get(item.get("Type"), "Current evidence base")


def coforge_angle_for_signal(item, opportunities):
    signal = str(item.get("Signal", "")).lower()
    for opp in opportunities or []:
        cap = str(opp.get("Coforge Capability", ""))
        cap_l = cap.lower()
        if ("ai" in signal and "ai" in cap_l) or ("automation" in signal and "automation" in cap_l) or ("portfolio" in signal and "portfolio" in cap_l):
            return cap
    if opportunities:
        return opportunities[0].get("Coforge Capability", "Validate against loaded Coforge capabilities")
    return "Validate against loaded Coforge capabilities"


def capability_for_job(job, capabilities):
    hay = f"{job.get('title','')} {job.get('description','')}".lower()
    ranked = []
    for cap in capabilities or []:
        keywords = cap.get("Signal Keywords") or cap.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [x.strip() for x in re.split(r"[,;]", keywords) if x.strip()]
        hits = sum(hay.count(str(k).lower()) for k in keywords if str(k).strip())
        if hits:
            ranked.append((hits, cap.get("Capability") or cap.get("name") or "Coforge capability"))
    return sorted(ranked, reverse=True)[0][1] if ranked else "No loaded Coforge capability maps directly yet"


def score_explanation_html(breakdown):
    maximums = {
        "Baseline": 10,
        "AI / technology evidence": 35,
        "Relevant hiring": 20,
        "Growth / transaction triggers": 15,
        "Priority stakeholder coverage": 15,
        "Portfolio scale": 15,
    }
    rows = []
    for label, points in breakdown.items():
        max_points = maximums.get(label, max(1, points))
        pct = max(0, min(100, (float(points) / max_points) * 100))
        rows.append(
            f'<div class="score-row"><div class="score-row-top"><span>{escape(label)}</span><b>{points:g}/{max_points}</b></div>'
            f'<div class="score-track"><div class="score-fill" style="width:{pct:.1f}%"></div></div></div>'
        )
    return "".join(rows)


# =============================================================================
# STATE
# =============================================================================
def ensure_state(name, default):
    if name not in st.session_state:
        st.session_state[name] = default


ensure_state("page", "Command Center")
ensure_state("uploaded_portfolio", {})
ensure_state("uploaded_jobs", {})
ensure_state("uploaded_insights", {})
ensure_state("uploaded_leadership", {})
ensure_state("analysis_history", [])
ensure_state("uploaded_raw_counts", {})
ensure_state("selected_person", {})
ensure_state("selected_portco", {})
ensure_state("website_overrides", {})
ensure_state("news_page_overrides", {})
ensure_state("source_refresh_notice", {})
ensure_state("account_scope", "PE firm")
ensure_state("pending_account_scope", None)
ensure_state("pending_portco_switch", {})


# =============================================================================
# SIDEBAR — PE FIRM + OPTIONAL PORTFOLIO-COMPANY ACCOUNT
# =============================================================================
with st.sidebar:
    st.markdown(
        '<div class="brand-lockup"><span class="brand-mark">◆</span><span class="brand-title">PE Intelligence</span><div class="brand-sub">Coforge firm + portfolio intelligence workspace</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.caption(f"Build v{APP_VERSION} · official-source-first")

    firm_keys = list(FIRM_CONFIGS.keys())
    firm_search = st.text_input(
        "Find a PE firm",
        placeholder="Type KKR, CVC, Pereira, Bridgepoint…",
        help="Searches configured PE-firm names and aliases.",
    )
    if firm_search.strip():
        needle = firm_search.strip().lower()
        matched_firms = [
            key for key in firm_keys
            if needle in FIRM_CONFIGS[key]["name"].lower()
            or any(needle in alias.lower() for alias in FIRM_CONFIGS[key].get("aliases", []))
        ]
    else:
        matched_firms = firm_keys
    if not matched_firms:
        st.warning("No configured firm matched that search. Showing the full list instead.")
        matched_firms = firm_keys

    parent_firm_key = st.selectbox(
        "PE sponsor",
        matched_firms,
        format_func=lambda key: FIRM_CONFIGS[key]["name"],
        key="pe_sponsor_selector",
    )
    parent_firm = FIRM_CONFIGS[parent_firm_key]

    # Load the sponsor portfolio before choosing scope. This same portfolio powers the sidebar filters.
    parent_local_portfolio = load_local_portfolio(parent_firm_key)
    parent_public_portfolio, parent_public_portfolio_label = get_public_portfolio(parent_firm_key)
    parent_portfolio = st.session_state.uploaded_portfolio.get(parent_firm_key) or parent_local_portfolio or parent_public_portfolio

    scope_options = ["PE firm", "Portfolio company"] if parent_portfolio else ["PE firm"]
    pending_scope = st.session_state.get("pending_account_scope")
    if pending_scope in scope_options:
        st.session_state.account_scope = pending_scope
    st.session_state.pending_account_scope = None
    if st.session_state.account_scope not in scope_options:
        st.session_state.account_scope = "PE firm"
    account_kind = st.radio("Research scope", scope_options, key="account_scope", horizontal=True)

    selected_portco_row = None
    if account_kind == "Portfolio company" and parent_portfolio:
        pdf = pd.DataFrame(parent_portfolio).fillna("")
        for col in ["Company", "Sector", "Region", "Status", "Fund", "Source"]:
            if col not in pdf.columns:
                pdf[col] = ""
        pending_portco = st.session_state.pending_portco_switch.pop(parent_firm_key, None)
        if pending_portco and pending_portco in set(pdf["Company"].astype(str)):
            st.session_state[f"side_sector_{parent_firm_key}"] = "All"
            st.session_state[f"side_region_{parent_firm_key}"] = "All"
            st.session_state[f"side_status_{parent_firm_key}"] = "All"
            st.session_state[f"side_fund_{parent_firm_key}"] = "All"
            st.session_state[f"portco_search_{parent_firm_key}"] = ""
            st.session_state[f"sidebar_portco_{parent_firm_key}"] = pending_portco
        st.caption("PORTFOLIO FILTERS")
        portco_search = st.text_input("Find portfolio company", placeholder="Search company, sector, region…", key=f"portco_search_{parent_firm_key}")
        cf1, cf2 = st.columns(2)
        with cf1:
            sector_filter = st.selectbox("Sector", ["All"] + safe_unique(pdf["Sector"]), key=f"side_sector_{parent_firm_key}")
        with cf2:
            region_filter = st.selectbox("Region", ["All"] + safe_unique(pdf["Region"]), key=f"side_region_{parent_firm_key}")
        cf3, cf4 = st.columns(2)
        with cf3:
            status_filter = st.selectbox("Status", ["All"] + safe_unique(pdf["Status"]), key=f"side_status_{parent_firm_key}")
        with cf4:
            fund_filter = st.selectbox("Fund", ["All"] + safe_unique(pdf["Fund"]), key=f"side_fund_{parent_firm_key}")

        filtered_portcos = pdf.copy()
        if portco_search:
            mask = filtered_portcos.astype(str).apply(lambda c: c.str.contains(portco_search, case=False, na=False)).any(axis=1)
            filtered_portcos = filtered_portcos[mask]
        if sector_filter != "All":
            filtered_portcos = filtered_portcos[filtered_portcos["Sector"] == sector_filter]
        if region_filter != "All":
            filtered_portcos = filtered_portcos[filtered_portcos["Region"] == region_filter]
        if status_filter != "All":
            filtered_portcos = filtered_portcos[filtered_portcos["Status"] == status_filter]
        if fund_filter != "All":
            filtered_portcos = filtered_portcos[filtered_portcos["Fund"] == fund_filter]

        choices = safe_unique(filtered_portcos["Company"])
        if not choices:
            st.warning("No portfolio companies match those filters. Reset one or more filters.")
            choices = safe_unique(pdf["Company"])
        chosen_portco = st.selectbox("Target portfolio company", choices, key=f"sidebar_portco_{parent_firm_key}")
        selected_portco_row = pdf[pdf["Company"] == chosen_portco].iloc[0].to_dict()
        st.session_state.selected_portco[parent_firm_key] = chosen_portco

        prospective_key = f"{parent_firm_key}__portco__{entity_slug(chosen_portco)}"
        st.caption("Company website/news sources can be confirmed in the visible Source Controls panel in the main workspace.")

    pages = [
        "Command Center", "Portfolio", "Leadership", "Hiring & Skills", "Technology Signals",
        "Newsroom", "Opportunity Lab", "AI Analyst", "Data Hub",
    ]
    if st.session_state.page not in pages:
        st.session_state.page = "Command Center"
    page = st.radio("Workspace", pages, index=pages.index(st.session_state.page), label_visibility="collapsed")
    st.session_state.page = page

    st.markdown("---")
    st.caption("PUBLIC SOURCES")
    st.markdown(f"{badge('Official websites', 'green')} {badge('Google News', 'blue')} {badge('ATS APIs', 'purple')}", unsafe_allow_html=True)
    if requests is None or BeautifulSoup is None:
        st.warning("Install requests + beautifulsoup4 to enable portfolio-company website discovery and scraping.")
    st.caption("Uploads still override public extraction for the selected account.")


# Keep a stable sponsor reference; from this point selected_firm means the currently selected account key.
if account_kind == "Portfolio company" and selected_portco_row:
    portco_name = selected_portco_row.get("Company", "Portfolio company")
    selected_firm = f"{parent_firm_key}__portco__{entity_slug(portco_name)}"
    website_override = st.session_state.website_overrides.get(selected_firm, "")
    news_page_override = st.session_state.news_page_overrides.get(selected_firm, "")
    firm = build_portco_account(
        parent_firm_key, parent_firm, selected_portco_row, website_override, news_page_override
    )

    # V4 source resolution is independent of the legacy requests-only resolver.
    # Manual URLs are authoritative; automatic mode checks the PE record / detail
    # page and intuitive company-name domains such as Seismic -> seismic.com and
    # Fleet Data Centers -> fleetdatacenters.com.
    source_resolution = resolve_company_website(
        portco_name,
        manual_website=website_override,
        manual_content_url=news_page_override,
        row=selected_portco_row,
        parent_website=parent_firm.get("website", ""),
    )
    if source_resolution.get("website"):
        firm["official_website"] = source_resolution["website"]
        firm["website"] = source_resolution["website"]
        firm["about_url"] = firm.get("about_url") or source_resolution["website"]
        firm["website_source"] = source_resolution.get("source", "V4 source resolver")
        firm["website_confidence"] = source_resolution.get("confidence", "Medium")
    firm["manual_news_page"] = news_page_override
    firm["source_resolution_diagnostic"] = source_resolution.get("diagnostic", "")
else:
    selected_firm = parent_firm_key
    firm = dict(parent_firm)
    firm["entity_kind"] = "PE firm"
    firm["parent_firm_key"] = parent_firm_key
    firm["parent_firm_name"] = parent_firm.get("name", "")
    firm.setdefault("size", "")
    source_resolution = {}


# =============================================================================
# LOAD DATA — PE firms use configured adapters; portfolio companies use generic live discovery.
# =============================================================================
with st.spinner(f"Refreshing {firm['name']} intelligence…"):
    if firm.get("entity_kind") == "PE firm":
        local_portfolio = parent_local_portfolio
        public_portfolio = parent_public_portfolio
        public_portfolio_label = parent_public_portfolio_label
        portfolio = parent_portfolio

        local_jobs = load_local_jobs(parent_firm_key)
        public_jobs = get_public_jobs(parent_firm_key)
        jobs = st.session_state.uploaded_jobs.get(selected_firm) or local_jobs or public_jobs

        local_leadership = load_local_leadership(parent_firm_key)
        public_leadership = get_public_leadership(parent_firm_key, full=(page == "Leadership"))
        leadership = st.session_state.uploaded_leadership.get(selected_firm) or local_leadership or public_leadership
        leadership = clean_leadership_records(leadership)

        local_insights = load_local_insights(parent_firm_key)
        google_news = get_google_news(
            f'"{firm["name"]}" (private equity OR acquisition OR portfolio OR AI OR technology OR digital OR hiring)',
            limit=24,
        )
        official_news = []
        for news_url in firm.get("news_urls", [])[:3]:
            official_news.extend(get_official_news_cards(news_url, limit=12))
        uploaded_insights = st.session_state.uploaded_insights.get(selected_firm) or []
        insights = merge_insights(uploaded_insights, local_insights, google_news, official_news)
        official_news_count = len(official_news)
        external_news_count = len(google_news)
        official_news_status = {"source_pages": firm.get("news_urls", []), "source_results": [], "errors": [], "article_count": official_news_count}
        official_news_pages = list(firm.get("news_urls", []))

        official_bio = get_official_description(firm.get("about_url") or firm["website"])
        wiki_bio = get_wikipedia_summary(firm.get("wikipedia", firm["name"]))
        # V3: official description is primary; Wikipedia is the neutral fallback.
        bio_record = choose_bio_record(firm["name"], official_bio, wiki_bio)
        bio_text = bio_record.get("extract", "")
        careers_discovered = firm.get("careers_urls", [])
        people_discovered = firm.get("people_urls", [])
    else:
        local_portfolio = local_entity_records(selected_firm, "portfolio")
        public_portfolio = []
        public_portfolio_label = "Operating company"
        portfolio = st.session_state.uploaded_portfolio.get(selected_firm) or local_portfolio or []

        local_jobs = local_entity_records(selected_firm, "jobs")
        public_jobs, careers_discovered, public_jobs_label = discover_company_jobs(
            firm["name"], firm.get("official_website", ""), tuple(firm.get("careers_urls", []))
        )
        jobs = st.session_state.uploaded_jobs.get(selected_firm) or local_jobs or public_jobs

        local_leadership = local_entity_records(selected_firm, "leadership")
        public_leadership, people_discovered, public_leadership_label = discover_company_leadership(
            firm["name"], firm.get("official_website", ""), tuple(firm.get("people_urls", [])), full=(page == "Leadership")
        )
        leadership = st.session_state.uploaded_leadership.get(selected_firm) or local_leadership or public_leadership
        leadership = clean_leadership_records(leadership)

        local_insights = local_entity_records(selected_firm, "insights")

        # Resolve company identity before external news. This is critical for ambiguous
        # brands such as Seismic, Advanced or Access where the plain word has unrelated uses.
        official_bio = get_official_description(firm.get("about_url") or firm.get("official_website", "")) if firm.get("official_website") else None
        wiki_bio = get_wikipedia_summary(firm.get("wikipedia", firm["name"]))
        bio_record = choose_bio_record(firm["name"], official_bio, wiki_bio)
        bio_text = bio_record.get("extract", "")

        official_news, official_news_status = scrape_company_first_party_news(
            firm["name"],
            firm.get("official_website", ""),
            exact_content_url=news_page_override,
            max_sources=5,
            max_articles=50,
        )
        official_news_pages = [x.get("url", "") for x in official_news_status.get("source_pages", []) if x.get("url")]
        news_query = build_disambiguated_news_query(
            clean_company_search_name(firm["name"]),
            firm.get("official_website", ""),
            bio_text,
            firm.get("sector", ""),
            firm.get("parent_firm_name", ""),
        )
        raw_google_news = get_google_news(news_query, limit=36)
        google_news = filter_company_news(
            raw_google_news,
            firm["name"],
            firm.get("official_website", ""),
            bio_text,
            firm.get("sector", ""),
            firm.get("parent_firm_name", ""),
        )
        uploaded_insights = st.session_state.uploaded_insights.get(selected_firm) or []
        # First-party sources outrank aggregated external news in the account feed.
        insights = merge_insights(uploaded_insights, local_insights, official_news, google_news)
        for article in insights:
            article.setdefault("credibility", credibility_label(article))
        official_news_count = len(official_news)
        external_news_count = len(google_news)

capabilities = load_capabilities()
tech_rows = detect_technology_signals(jobs, insights)
why_now = build_why_now(jobs, insights, tech_rows)
opportunities = map_ai_opportunities(capabilities, tech_rows, jobs, insights, portfolio, leadership)
priority_breakdown = opportunity_score_breakdown(portfolio, jobs, insights, tech_rows, leadership)

if firm.get("entity_kind") == "Portfolio company":
    # Portfolio scale is a PE-firm concept. Excluding it prevents operating companies being penalised for not owning a fund portfolio.
    priority_breakdown = {k: v for k, v in priority_breakdown.items() if k != "Portfolio scale"}
    portco_max_score = 95  # Original 110 maximum less the 15-point portfolio-scale component.
    priority_score = int(round(min(100, (sum(priority_breakdown.values()) / portco_max_score) * 100)))
    profile_comp = 100 if bio_text else (50 if firm.get("official_website") else 0)
    jobs_comp = 100 if jobs else (40 if careers_discovered else 0)
    leadership_comp = 100 if leadership else (40 if people_discovered else 0)
    news_comp = 100 if insights else 0
    confidence_components = {"Company profile": profile_comp, "Leadership": leadership_comp, "Jobs": jobs_comp, "News": news_comp}
    confidence_score = int(round(profile_comp * .25 + leadership_comp * .25 + jobs_comp * .25 + news_comp * .25))
else:
    confidence_score, confidence_components = compute_data_confidence(portfolio, jobs, insights, leadership)
    priority_score = int(round(min(100, (sum(priority_breakdown.values()) / 110) * 100)))
priority_band, priority_note = score_band(priority_score)

if firm.get("entity_kind") == "PE firm":
    portfolio_mode = source_mode("uploaded_portfolio", selected_firm, local_portfolio, public_portfolio, public_portfolio_label)
    jobs_mode = source_mode("uploaded_jobs", selected_firm, local_jobs, public_jobs, "Official careers scan")
    leadership_mode = source_mode("uploaded_leadership", selected_firm, local_leadership, public_leadership, "Official people directory")
else:
    portfolio_mode = "Operating company / no nested portfolio expected" if not portfolio else "Uploaded/local company investments"
    jobs_mode = source_mode("uploaded_jobs", selected_firm, local_jobs, public_jobs, public_jobs_label)
    leadership_mode = source_mode("uploaded_leadership", selected_firm, local_leadership, public_leadership, public_leadership_label)

if firm.get("entity_kind") == "Portfolio company":
    coverage = [
        {"Layer": "Company profile", "Mode": firm.get("website_source") or (bio_record.get("source") if bio_record else "Not available"), "Records": 1 if bio_text else 0, "Ready": bool(bio_text or firm.get("official_website"))},
        {"Layer": "Leadership", "Mode": leadership_mode, "Records": len(leadership), "Ready": bool(leadership or people_discovered)},
        {"Layer": "Jobs", "Mode": jobs_mode, "Records": len(jobs), "Ready": bool(jobs or careers_discovered)},
        {"Layer": "News & insights", "Mode": "Official site + Google News + uploads", "Records": len(insights), "Ready": bool(insights)},
    ]
else:
    coverage = source_coverage(portfolio, jobs, insights, leadership, portfolio_mode, jobs_mode, leadership_mode)
raw_jobs_count = st.session_state.uploaded_raw_counts.get((selected_firm, "jobs"))
if raw_jobs_count is None and local_jobs and firm.get("entity_kind") == "PE firm":
    raw_jobs_count = raw_dataset_count(selected_firm, "jobs")
if raw_jobs_count is None:
    raw_jobs_count = len(jobs)

hero(firm, priority_score, confidence_score, len(insights))

if firm.get("entity_kind") == "Portfolio company":
    wb1, wb2, wb3, wb4 = st.columns([1.4, 1, 1, 1])
    wb1.caption(f"Parent sponsor · {firm.get('parent_firm_name','Not captured')}")
    wb2.caption(f"Sector · {firm.get('sector') or 'Not captured'}")
    wb3.caption(f"Region · {firm.get('region') or 'Not captured'}")
    wb4.caption(f"Size · {firm.get('size') or 'Not captured'}")

    # -------------------------------------------------------------------------
    # V4 COMPANY SOURCE CONTROLS — deliberately visible, not hidden in sidebar.
    # Pressing Enter in either field submits the form, stores the override, clears
    # the web cache and reruns the account immediately.
    # -------------------------------------------------------------------------
    with st.container(border=True):
        st.markdown("#### Company Source Controls")
        st.caption(
            "Automatic mode tries the PE portfolio record/detail page and company-name domains, "
            "then searches the confirmed website for Newsroom, News, Press, Insights, Resources, "
            "Blog, Research, Articles, Stories, Updates and similar first-party sections. "
            "If it gets the company wrong, paste the official website. If you know the exact content page, paste that instead."
        )
        with st.form(f"source_controls_{selected_firm}", clear_on_submit=False, enter_to_submit=True):
            sc1, sc2 = st.columns(2)
            with sc1:
                source_website_input = st.text_input(
                    "Official company website URL",
                    value=st.session_state.website_overrides.get(selected_firm, ""),
                    placeholder="https://www.seismic.com or https://fleetdatacenters.com",
                    help="Optional. Leave blank to auto-discover the company website.",
                    key=f"main_company_url_{selected_firm}",
                )
            with sc2:
                source_content_input = st.text_input(
                    "Exact News / Insights / Resources URL",
                    value=st.session_state.news_page_overrides.get(selected_firm, ""),
                    placeholder="https://www.seismic.com/uk/newsroom/",
                    help="Optional. If supplied, this page is scraped first and also establishes the official domain.",
                    key=f"main_content_url_{selected_firm}",
                )
            a1, a2 = st.columns([1, 1])
            with a1:
                apply_sources = st.form_submit_button("Use sources & scrape now", type="primary", use_container_width=True)
            with a2:
                reset_sources = st.form_submit_button("Reset to automatic discovery", use_container_width=True)

        if apply_sources:
            if source_website_input.strip():
                st.session_state.website_overrides[selected_firm] = source_website_input.strip()
            else:
                st.session_state.website_overrides.pop(selected_firm, None)
            if source_content_input.strip():
                st.session_state.news_page_overrides[selected_firm] = source_content_input.strip()
            else:
                st.session_state.news_page_overrides.pop(selected_firm, None)
            clear_news_cache()
            st.session_state.source_refresh_notice[selected_firm] = "Source settings applied. The company website is being rediscovered and first-party content is being scraped now."
            st.rerun()

        if reset_sources:
            st.session_state.website_overrides.pop(selected_firm, None)
            st.session_state.news_page_overrides.pop(selected_firm, None)
            clear_news_cache()
            st.session_state.source_refresh_notice[selected_firm] = "Manual source settings cleared. Automatic website and content discovery is running now."
            st.rerun()

        notice = st.session_state.source_refresh_notice.pop(selected_firm, None)
        if notice:
            st.success(notice)

        resolved_site = firm.get("official_website", "")
        if resolved_site:
            st.markdown(
                f"**Active company domain:** `{hostname(resolved_site)}`  ·  "
                f"**Resolved via:** {firm.get('website_source','Automatic discovery')}  ·  "
                f"**Confidence:** {firm.get('website_confidence','Medium')}"
            )
            if firm.get("source_resolution_diagnostic"):
                st.caption(firm.get("source_resolution_diagnostic"))
        else:
            st.error("The company website could not be confirmed automatically. Paste the official company URL or exact News / Insights / Resources page above and press Enter / click 'Use sources & scrape now'.")

        sr = official_news_status.get("source_results", []) if isinstance(official_news_status, dict) else []
        if sr:
            st.caption(f"First-party scrape result · {official_news_count} article(s) extracted")
            source_table = pd.DataFrame(sr)
            display_cols = [x for x in ["kind", "url", "method", "article_count", "ok"] if x in source_table.columns]
            st.dataframe(source_table[display_cols], use_container_width=True, hide_index=True)
        elif resolved_site:
            st.warning("No first-party content hub produced articles yet. You can paste the exact Newsroom / Insights / Resources URL above to bypass automatic section discovery.")

        if official_news_count == 0 and official_news_status.get("errors"):
            with st.expander("Why the first-party scrape returned no articles", expanded=False):
                for err in official_news_status.get("errors", [])[:12]:
                    st.write(f"• {err}")

    st.caption(f"News source health · {official_news_count} first-party items · {external_news_count} identity-validated external items · build v{APP_VERSION}")


# =============================================================================
# COMMAND CENTER
# =============================================================================
if page == "Command Center":
    high_priority_jobs = [j for j in jobs if job_relevance(j.get("title", ""), j.get("description", "")) >= 4]
    relevant_jobs = [j for j in jobs if job_relevance(j.get("title", ""), j.get("description", "")) >= 3]
    priority_leaders = [p for p in leadership if int(p.get("Coforge Relevance", 1) or 1) >= 4]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        kpi_card("Account priority", f"{priority_score}/100", "Explainable evidence heuristic")
    with c2:
        kpi_card("Portfolio / investments" if firm.get("entity_kind") == "PE firm" else "PE sponsor", len(portfolio) if firm.get("entity_kind") == "PE firm" else firm.get("parent_firm_name", "—"), portfolio_mode if firm.get("entity_kind") == "PE firm" else firm.get("status", "Portfolio company"))
    with c3:
        kpi_card("Priority leaders", len(priority_leaders), f"{len(leadership)} stakeholders captured")
    with c4:
        kpi_card("Priority hiring", len(high_priority_jobs), f"{len(relevant_jobs)} relevant · {len(jobs)} unique roles")
    with c5:
        kpi_card("Tech themes", len(tech_rows), f"{len(insights)} intelligence items")

    with st.expander("How the account priority score is calculated", expanded=False):
        st.caption("A prioritisation heuristic, not a forecast of purchase intent or revenue. Each component is capped and can be traced back to evidence in the workspace.")
        st.markdown(f'<div class="explain-card">{score_explanation_html(priority_breakdown)}</div>', unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([1.42, 1], gap="large")

    with left:
        section_title("Account snapshot", "A neutral account summary plus the scope of the evidence currently loaded.", "Account")
        bio_source = bio_record.get("source") or "Public source"
        snapshot_copy = bio_text or "A neutral public company description could not be retrieved. Use the linked official source and enrich the account in Data Hub."
        st.markdown(
            f"""
            <div class="glass-card">
                <div class="card-title">{escape(firm['name'])}</div>
                <div style="margin-bottom:.45rem">{badge(firm['category'], 'purple')} {badge(bio_source, 'gray')}</div>
                <div class="card-copy">{escape(snapshot_copy[:850])}</div>
                <div class="evidence-strip"><b>{'Portfolio scope' if firm.get('entity_kind') == 'PE firm' else 'Ownership context'}:</b> {escape(firm.get('portfolio_scope','')[:360])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        b1, b2, b3 = st.columns(3)
        with b1:
            if is_http_url(firm.get("website")):
                st.link_button("Official website ↗", firm["website"], use_container_width=True)
        with b2:
            context_url = (firm.get("portfolio_urls") or [""])[0]
            if is_http_url(context_url):
                st.link_button("Ownership / portfolio source ↗" if firm.get("entity_kind") == "Portfolio company" else "Portfolio source ↗", context_url, use_container_width=True)
        with b3:
            people_url = (people_discovered or firm.get("people_urls") or [""])[0]
            if is_http_url(people_url):
                st.link_button("People source ↗", people_url, use_container_width=True)

        st.write("")
        section_title("Why now?", "Each trigger shows the evidence, recency and the Coforge conversation it may support.", "Buying signals")
        if why_now:
            for idx, item in enumerate(why_now[:5]):
                display_strength = why_now_display_strength(item)
                latest = latest_evidence_date(item, insights)
                angle = coforge_angle_for_signal(item, opportunities)
                st.markdown(
                    f"""
                    <div class="signal-card">
                        <div class="signal-top"><div class="signal-name">{escape(item['Signal'])}</div><div>{strength_badge(display_strength)}</div></div>
                        <div class="signal-copy">{escape(item['Evidence'])}</div>
                        <div class="evidence-strip"><b>Evidence:</b> {escape(why_now_source_label(item))} &nbsp;·&nbsp; <b>Latest:</b> {escape(latest)}<br><b>Coforge angle:</b> {escape(angle)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if item.get("Type") == "Hiring":
                    if st.button("Inspect hiring evidence →", key=f"why_hiring_{idx}"):
                        st.session_state.page = "Hiring & Skills"
                        st.rerun()
                elif item.get("Type") in {"Technology", "News"}:
                    if st.button("Inspect technology evidence →", key=f"why_tech_{idx}"):
                        st.session_state.page = "Technology Signals"
                        st.rerun()
                elif item.get("Type") == "Growth":
                    if st.button("Inspect news evidence →", key=f"why_news_{idx}"):
                        st.session_state.page = "Newsroom"
                        st.rerun()
        else:
            st.markdown('<div class="empty-state">No strong near-term trigger is proven yet. Add job data, PitchBook portfolio data or internal account research in Data Hub.</div>', unsafe_allow_html=True)

    with right:
        section_title("Intelligence confidence", "Completeness of the four public/internal evidence layers — not a claim that every record is correct.", "Coverage")
        gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=confidence_score,
            number={"suffix": "%", "font": {"size": 30}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 0},
                "bar": {"color": "#635bff"},
                "bgcolor": "#eef2ff",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 40], "color": "#f8fafc"},
                    {"range": [40, 70], "color": "#f3f4ff"},
                    {"range": [70, 100], "color": "#eef2ff"},
                ],
            },
        ))
        gauge.update_layout(height=165, margin=dict(l=18, r=18, t=5, b=0), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(gauge, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        for row in coverage:
            comp_key = "News" if row["Layer"] == "News & insights" else row["Layer"]
            comp = confidence_components.get(comp_key, 0)
            dot = "🟢" if row["Ready"] else "⚪"
            st.markdown(
                f'<div class="data-row"><div><div class="data-label">{dot} {escape(row["Layer"])}</div><div class="data-meta">{escape(row["Mode"])} · completeness {comp}%</div></div><div class="data-label">{row["Records"]}</div></div>',
                unsafe_allow_html=True,
            )
        st.markdown('<div class="data-row"><div><div class="data-label">⚪ Salesforce / account history</div><div class="data-meta">Not connected in this prototype</div></div><div class="data-label">—</div></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.write("")
        section_title("Top AI opportunities", "Evidence-backed Coforge plays using only the capability library currently loaded.", "Coforge")
        if opportunities:
            for opp in opportunities[:3]:
                st.markdown(
                    f"""
                    <div class="op-card" style="margin-bottom:.55rem">
                        <div class="op-head"><div class="op-name">{escape(opp['Coforge Capability'])}</div>{strength_badge(opp['Evidence Strength'])}</div>
                        <div class="op-copy">{escape(opp['Opportunity'])}</div>
                        <div class="op-evidence"><b>Evidence:</b> {escape(opp['Evidence'])}<br><b>Suggested buyer:</b> {escape(opp.get('Recommended Buyer','Validate stakeholder'))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("Not enough evidence to map a credible opportunity yet.")

    st.write("")
    section_title("Latest account intelligence", "Most recent public news and official-site signals available to the account workspace.", "Live feed")
    if insights:
        cols = st.columns(3)
        for idx, article in enumerate(insights[:6]):
            with cols[idx % 3]:
                display_news_card(article, compact=True)
    else:
        st.info("No recent intelligence could be loaded from public sources.")

    st.write("")
    section_title("Jump into research", kicker="Workspace")
    n1, n2, n3, n4, n5 = st.columns(5)
    with n1:
        nav_button("Portfolio →", "Portfolio", "nav_portfolio")
    with n2:
        nav_button("Leadership →", "Leadership", "nav_leadership")
    with n3:
        nav_button("Hiring →", "Hiring & Skills", "nav_hiring")
    with n4:
        nav_button("Opportunity lab →", "Opportunity Lab", "nav_opp")
    with n5:
        nav_button("Ask AI →", "AI Analyst", "nav_ai")


# =============================================================================
# PORTFOLIO
# =============================================================================
elif page == "Portfolio":
    if firm.get("entity_kind") == "Portfolio company":
        section_title("Ownership & portfolio context", "See where the selected operating company sits inside the sponsor portfolio, compare siblings and switch any sibling into the full intelligence workspace.", "Portfolio context")
        st.markdown(f'<div class="scope-note"><b>Selected company:</b> {escape(firm["name"])} · <b>PE sponsor:</b> {escape(parent_firm["name"])} · <b>Sector:</b> {escape(firm.get("sector") or "Not captured")} · <b>Region:</b> {escape(firm.get("region") or "Not captured")}</div>', unsafe_allow_html=True)

        if parent_portfolio:
            pdf = pd.DataFrame(parent_portfolio).fillna("")
            for col in ["Company", "Sector", "Region", "Status", "Fund", "Source"]:
                if col not in pdf.columns:
                    pdf[col] = ""
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Sponsor portfolio records", len(pdf))
            p2.metric("Same sector", int((pdf["Sector"] == firm.get("sector", "")).sum()) if firm.get("sector") else 0)
            p3.metric("Same region", int((pdf["Region"] == firm.get("region", "")).sum()) if firm.get("region") else 0)
            p4.metric("Fund / strategy", firm.get("fund") or "Not captured")

            f1, f2, f3 = st.columns([1.8, 1, 1])
            with f1:
                sibling_q = st.text_input("Search sponsor portfolio", placeholder="Company, sector, region, fund…")
            with f2:
                sibling_sector = st.selectbox("Sector filter", ["All"] + safe_unique(pdf["Sector"]), index=0)
            with f3:
                sibling_region = st.selectbox("Region filter", ["All"] + safe_unique(pdf["Region"]), index=0)
            sibling_df = pdf.copy()
            if sibling_q:
                mask = sibling_df.astype(str).apply(lambda c: c.str.contains(sibling_q, case=False, na=False)).any(axis=1)
                sibling_df = sibling_df[mask]
            if sibling_sector != "All":
                sibling_df = sibling_df[sibling_df["Sector"] == sibling_sector]
            if sibling_region != "All":
                sibling_df = sibling_df[sibling_df["Region"] == sibling_region]
            st.dataframe(sibling_df[["Company", "Sector", "Region", "Status", "Fund"]], use_container_width=True, hide_index=True, height=430)

            sibling_choices = safe_unique(sibling_df["Company"])
            if sibling_choices:
                sibling = st.selectbox("Open another portfolio company as a full account", sibling_choices)
                if st.button("Switch full workspace to selected company", type="primary", use_container_width=True):
                    st.session_state.pending_portco_switch[parent_firm_key] = sibling
                    st.session_state.pending_account_scope = "Portfolio company"
                    st.session_state.page = "Command Center"
                    st.rerun()
            if st.button(f"Return to {parent_firm['name']} PE-firm workspace", use_container_width=True):
                st.session_state.pending_account_scope = "PE firm"
                st.session_state.page = "Command Center"
                st.rerun()
        else:
            st.info("No sponsor portfolio dataset is currently loaded.")
    else:
        section_title("Portfolio intelligence", "Search and segment the investment universe, then promote any company into a full Coforge intelligence account.", "Portfolio")
        st.markdown(f'<div class="scope-note"><b>Scope:</b> {escape(firm.get("portfolio_scope", ""))}</div>', unsafe_allow_html=True)

        if not portfolio:
            st.markdown('<div class="empty-state"><b>No company-level portfolio list is currently available from the public source.</b><br>Upload a PitchBook CSV/XLSX/JSON in Data Hub for exhaustive coverage.</div>', unsafe_allow_html=True)
            if firm.get("portfolio_urls"):
                st.link_button("Open official portfolio / investments page ↗", firm["portfolio_urls"][0])
        else:
            df = pd.DataFrame(portfolio)
            for col in ["Company", "Sector", "Region", "Status", "Fund", "Source"]:
                if col not in df.columns:
                    df[col] = ""
            df = df.fillna("")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Records captured", len(df))
            m2.metric("Sectors", df.loc[df["Sector"].astype(bool), "Sector"].nunique())
            m3.metric("Regions", df.loc[df["Region"].astype(bool), "Region"].nunique())
            m4.metric("Source mode", portfolio_mode)

            f1, f2, f3, f4 = st.columns([1.8, 1, 1, 1])
            with f1:
                query = st.text_input("Search portfolio", placeholder="Type a company, sector, region or fund")
            with f2:
                sectors = safe_unique(df["Sector"])
                selected_sector = st.selectbox("Sector", ["All"] + sectors)
            with f3:
                regions = safe_unique(df["Region"])
                selected_region = st.selectbox("Region", ["All"] + regions)
            with f4:
                statuses = safe_unique(df["Status"])
                selected_status = st.selectbox("Status", ["All"] + statuses)

            filtered = df.copy()
            if query:
                mask = filtered.astype(str).apply(lambda c: c.str.contains(query, case=False, na=False)).any(axis=1)
                filtered = filtered[mask]
            if selected_sector != "All":
                filtered = filtered[filtered["Sector"] == selected_sector]
            if selected_region != "All":
                filtered = filtered[filtered["Region"] == selected_region]
            if selected_status != "All":
                filtered = filtered[filtered["Status"] == selected_status]

            left, right = st.columns([1.9, 1], gap="large")
            with left:
                st.caption(f"Showing {len(filtered)} of {len(df)} captured records")
                st.dataframe(filtered[["Company", "Sector", "Region", "Status", "Fund"]], use_container_width=True, hide_index=True, height=520)
                st.download_button("Download filtered portfolio CSV", filtered.to_csv(index=False).encode("utf-8"), file_name=f"{selected_firm}_portfolio.csv", mime="text/csv", use_container_width=True)
            with right:
                section_title("Portfolio mix", "Only records with a usable label are included.")
                sector_counts = filtered[filtered["Sector"].astype(bool)]["Sector"].value_counts().head(9).reset_index()
                sector_counts.columns = ["Sector", "Count"]
                if not sector_counts.empty:
                    fig = px.bar(sector_counts.sort_values("Count"), x="Count", y="Sector", orientation="h", text="Count")
                    fig.update_layout(height=285, margin=dict(l=0, r=6, t=5, b=0), xaxis_title=None, yaxis_title=None, showlegend=False)
                    fig.update_traces(marker_color="#635bff")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                region_counts = filtered[filtered["Region"].astype(bool)]["Region"].value_counts().head(8).reset_index()
                region_counts.columns = ["Region", "Count"]
                if not region_counts.empty:
                    fig2 = px.pie(region_counts, names="Region", values="Count", hole=.62)
                    fig2.update_layout(height=245, margin=dict(l=0, r=0, t=0, b=0), legend_title=None)
                    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

            st.divider()
            section_title("Portfolio company launcher", "Choose a company, preview its public profile/news, then open it as a full account across every workspace.", "Research")
            company_choices = safe_unique(filtered["Company"])
            if company_choices:
                chosen = st.selectbox("Inspect portfolio company", company_choices, key=f"portfolio_launcher_company_{parent_firm_key}")
                chosen_row = filtered[filtered["Company"] == chosen].iloc[0].to_dict()
                search_name = clean_company_search_name(chosen)
                # V4 preview uses the same website resolver + first-party news engine as the
                # full portfolio-company account. This avoids the legacy V3 discovery path.
                source_resolution = resolve_company_website(
                    search_name,
                    row=chosen_row,
                    parent_website=parent_firm.get("website", ""),
                )
                website = source_resolution.get("website", "")
                website_source = source_resolution.get("source", "Unresolved")
                source_bio = get_official_description(website) if website else None
                wiki_portco = get_wikipedia_summary(search_name)
                quick_bio = choose_bio_record(search_name, source_bio, wiki_portco)
                if website:
                    preview_official_news, _preview_news_status = scrape_company_first_party_news(
                        search_name,
                        website,
                        max_sources=3,
                        max_articles=12,
                    )
                else:
                    preview_official_news, _preview_news_status = [], {"article_count": 0}
                preview_query = build_disambiguated_news_query(
                    search_name, website, quick_bio.get("extract", ""), chosen_row.get("Sector", ""), parent_firm.get("name", "")
                )
                preview_external_news = filter_company_news(
                    get_google_news(preview_query, limit=18), search_name, website, quick_bio.get("extract", ""),
                    chosen_row.get("Sector", ""), parent_firm.get("name", "")
                )
                portco_news = merge_insights(preview_official_news, preview_external_news)
                for article in portco_news:
                    article.setdefault("credibility", credibility_label(article))
                signal_counts = pd.Series([x.get("signal_type", "Other") for x in portco_news]).value_counts().to_dict() if portco_news else {}

                p1, p2 = st.columns([1.15, 1], gap="large")
                with p1:
                    st.markdown(f"""<div class=\"glass-card\"><div class=\"card-title\">{escape(chosen)}</div><div style=\"margin-bottom:.45rem\">{badge(chosen_row.get('Sector') or 'Sector not captured', 'purple')} {badge(chosen_row.get('Region') or 'Region not captured', 'gray')}</div><div class=\"card-copy\">{escape(quick_bio.get('extract') or 'No reliable short company description was found yet.')}</div><div class=\"evidence-strip\"><b>Status:</b> {escape(chosen_row.get('Status') or 'Not captured')} · <b>Fund/strategy:</b> {escape(chosen_row.get('Fund') or 'Not captured')}<br><b>Website:</b> {escape(hostname(website) or 'not resolved')} · {escape(website_source)}</div></div>""", unsafe_allow_html=True)
                    if website:
                        st.link_button("Official website ↗", website, use_container_width=True)
                    if st.button("Open as full intelligence account →", type="primary", use_container_width=True):
                        st.session_state.pending_portco_switch[parent_firm_key] = chosen
                        st.session_state.pending_account_scope = "Portfolio company"
                        st.session_state.page = "Command Center"
                        st.rerun()
                with p2:
                    section_title("Recent company signals")
                    if portco_news:
                        for article in portco_news[:4]:
                            display_news_card(article, compact=True)
                    else:
                        st.info("No recent public news was returned for this company name.")


# =============================================================================
# LEADERSHIP
# =============================================================================
elif page == "Leadership":
    section_title("Leadership & stakeholder intelligence", "Public people directories are treated as captured stakeholder evidence, not an exhaustive org chart. Filter by buyer persona and open the official profile before outreach.", "People")

    if not leadership:
        st.markdown('<div class="empty-state"><b>No named people were parsed from the public directory.</b><br>Upload a verified leadership CSV/XLSX/JSON in Data Hub for complete coverage.</div>', unsafe_allow_html=True)
        people_link = (people_discovered or firm.get("people_urls") or [firm.get("website")])[0]
        if people_link:
            st.link_button("Open official people / leadership source ↗", people_link)
    else:
        ldf = pd.DataFrame(leadership).fillna("")
        if "Persona" not in ldf.columns:
            ldf["Persona"] = ldf["Role"].apply(leadership_persona)
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Stakeholders captured", len(ldf))
        p2.metric("Priority stakeholders", int((ldf["Coforge Relevance"] >= 4).sum()))
        p3.metric("Tech / value-creation", int(ldf["Persona"].isin(["Technology / Data / AI", "Portfolio value creation"]).sum()))
        p4.metric("Source", leadership_mode)
        st.caption("Coverage note: this is the current parsed/uploaded stakeholder set. It should not be described as 'all leadership' unless a verified complete directory has been loaded.")

        f1, f2, f3, f4 = st.columns([1.55, 1, 1, 1])
        with f1:
            q = st.text_input("Search people", placeholder="Name, CIO, operating partner, data, London…")
        with f2:
            persona_choices = safe_unique(ldf["Persona"])
            persona = st.selectbox("Buyer persona", ["All"] + persona_choices)
        with f3:
            min_rel = st.select_slider("Minimum relevance", options=[1, 2, 3, 4, 5], value=1)
        with f4:
            location_choices = safe_unique(ldf["Location"])
            loc = st.selectbox("Location", ["All"] + location_choices)

        shown = ldf[ldf["Coforge Relevance"] >= min_rel].copy()
        if q:
            mask = shown.astype(str).apply(lambda c: c.str.contains(q, case=False, na=False)).any(axis=1)
            shown = shown[mask]
        if persona != "All":
            shown = shown[shown["Persona"] == persona]
        if loc != "All":
            shown = shown[shown["Location"] == loc]
        shown = shown.sort_values(["Coforge Relevance", "Name"], ascending=[False, True])

        selected_name = st.selectbox("Inspect stakeholder", shown["Name"].tolist() if not shown.empty else ["No matches"])
        if selected_name != "No matches":
            selected_row = shown[shown["Name"] == selected_name].iloc[0].to_dict()
            st.session_state.selected_person[selected_firm] = selected_row

        chosen_person = st.session_state.selected_person.get(selected_firm)
        if chosen_person:
            profile = get_profile_bio(chosen_person.get("Profile URL", "")) if chosen_person.get("Profile URL") else None
            bio, bio_source = clean_person_bio(chosen_person, leadership, profile)
            reason = leader_reason(chosen_person.get("Role", ""))
            persona_name = chosen_person.get("Persona") or leadership_persona(chosen_person.get("Role", ""))
            st.markdown(
                f"""
                <div class="person-detail">
                    <div class="person-name">{escape(chosen_person.get('Name',''))}</div>
                    <div class="person-role">{escape(chosen_person.get('Role','Role not parsed'))}{' · ' + escape(chosen_person.get('Location','')) if chosen_person.get('Location') else ''}</div>
                    <div>{relevance_badge(int(chosen_person.get('Coforge Relevance',1)))} <span class="persona-chip">{escape(persona_name)}</span></div>
                    <div class="card-copy" style="margin-top:.55rem"><b>Why Coforge should care:</b> {escape(reason)}</div>
                    <div class="person-bio" style="margin-top:.55rem">{escape(bio)}</div>
                    <div class="evidence-strip"><b>Bio source:</b> {escape(bio_source)} · Validate role/remit on the official profile before outreach.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if chosen_person.get("Profile URL"):
                st.link_button("Open official profile ↗", chosen_person["Profile URL"])

        st.write("")
        section_title("People directory", "Priority stakeholders first. Persona and relevance filters make the list usable as an account-planning view.")
        if shown.empty:
            st.info("No people match the current filters.")
        else:
            page_size = 18
            max_page = max(1, math.ceil(len(shown) / page_size))
            page_no = st.number_input("Directory page", min_value=1, max_value=max_page, value=1, step=1)
            start = (page_no - 1) * page_size
            subset = shown.iloc[start:start + page_size]
            cols = st.columns(3)
            for idx, (_, person) in enumerate(subset.iterrows()):
                with cols[idx % 3]:
                    role_line = person.get("Role") or "Role not parsed"
                    if person.get("Location"):
                        role_line += f" · {person.get('Location')}"
                    st.markdown(f"<div style='font-size:.72rem;color:#64748b;margin-bottom:.1rem'>{escape(role_line)}</div>", unsafe_allow_html=True)
                    if st.button(person["Name"], key=f"person_{selected_firm}_{start+idx}", use_container_width=True):
                        st.session_state.selected_person[selected_firm] = person.to_dict()
                        st.rerun()
                    st.markdown(f"{relevance_badge(int(person.get('Coforge Relevance', 1)))} <span class='persona-chip'>{escape(person.get('Persona',''))}</span>", unsafe_allow_html=True)

            st.caption(f"Showing {start + 1}-{min(start + page_size, len(shown))} of {len(shown)} filtered stakeholders · page {page_no}/{max_page}")

        st.download_button(
            "Download leadership CSV",
            shown.to_csv(index=False).encode("utf-8"),
            file_name=f"{selected_firm}_leadership.csv",
            mime="text/csv",
        )


# =============================================================================
# HIRING & SKILLS
# =============================================================================
elif page == "Hiring & Skills":
    section_title("Hiring & skills intelligence", "Translate job postings into capability-demand signals: raw postings → unique roles → Coforge-relevant roles → evidence-backed conversation themes.", "Talent signals")

    if not jobs:
        st.markdown('<div class="empty-state"><b>No current job records were discovered from the configured public careers source.</b><br>This can mean there are genuinely no openings, the careers site is JavaScript/Workday-heavy, or the public scanner cannot see them. Upload a jobs export in Data Hub for complete analysis.</div>', unsafe_allow_html=True)
        careers_link = (careers_discovered or firm.get("careers_urls") or [firm.get("website")])[0]
        if careers_link:
            st.link_button("Open careers source ↗", careers_link)
    else:
        enriched_rows = []
        for job in jobs:
            row = dict(job)
            row["Coforge relevance"] = job_relevance(job.get("title", ""), job.get("description", ""))
            row["Relevant skills"] = ", ".join(skills_relevant_to_coforge(job))
            row["Mapped capability"] = capability_for_job(job, capabilities)
            enriched_rows.append(row)
        jdf = pd.DataFrame(enriched_rows).fillna("")
        relevant_count = int((jdf["Coforge relevance"] >= 3).sum())
        high_count = int((jdf["Coforge relevance"] >= 4).sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Raw postings", raw_jobs_count, help="Rows in the source file before title/location deduplication where available.")
        c2.metric("Unique roles", len(jdf), help="The app deduplicates by title + location.")
        c3.metric("Coforge-relevant", relevant_count, help="Relevance score 3/5 or higher.")
        c4.metric("High priority", high_count, help="Relevance score 4/5 or higher.")
        st.caption(f"Source: {jobs_mode} · {jdf.loc[jdf['location'].astype(bool), 'location'].nunique()} locations captured · Duplicate/repeated postings removed: {max(0, int(raw_jobs_count or len(jdf)) - len(jdf))}")

        f1, f2 = st.columns([2, 1])
        with f1:
            q = st.text_input("Search jobs", placeholder="AI, data, cloud, product, London…")
        with f2:
            min_job_rel = st.select_slider("Minimum Coforge relevance", options=[1, 2, 3, 4, 5], value=1)

        shown = jdf[jdf["Coforge relevance"] >= min_job_rel].copy()
        if q:
            mask = shown.astype(str).apply(lambda c: c.str.contains(q, case=False, na=False)).any(axis=1)
            shown = shown[mask]
        shown = shown.sort_values(["Coforge relevance", "title"], ascending=[False, True])

        left, right = st.columns([1.5, 1], gap="large")
        with left:
            st.dataframe(
                shown[["title", "location", "Coforge relevance", "Relevant skills", "Mapped capability", "source"]],
                use_container_width=True,
                hide_index=True,
                height=540,
                column_config={
                    "Coforge relevance": st.column_config.ProgressColumn("Coforge relevance", min_value=0, max_value=5, format="%d / 5"),
                },
            )
        with right:
            section_title("Inspect a role", "Evidence → interpretation → Coforge action.")
            if not shown.empty:
                labels = [f"{r['title']} · {r['location']}".strip(" ·") for _, r in shown.iterrows()]
                selected_label = st.selectbox("Role", labels)
                chosen_idx = labels.index(selected_label)
                job = shown.iloc[chosen_idx].to_dict()
                full_description = job.get("description", "")
                if len(full_description) < 250 and job.get("url"):
                    fetched = enrich_job_description(job["url"])
                    if fetched:
                        full_description = fetched
                skills = extract_skills(f"{job.get('title','')} {full_description}")
                relevance = job_relevance(job.get("title", ""), full_description)
                mapped_cap = capability_for_job({**job, "description": full_description}, capabilities)
                if relevance >= 4:
                    interpretation = "Strong capability-demand signal worth validating with the account."
                elif relevance >= 3:
                    interpretation = "Potentially relevant demand signal; qualify the exact remit before outreach."
                else:
                    interpretation = "Contextual hiring signal rather than a direct Coforge opportunity."
                st.markdown(
                    f"""
                    <div class="glass-card">
                        <div class="card-title">{escape(job.get('title',''))}</div>
                        <div>{relevance_badge(relevance)}</div>
                        <div class="card-copy" style="margin-top:.5rem"><b>Location:</b> {escape(job.get('location') or 'Not captured')}<br><b>Source:</b> {escape(job.get('source') or jobs_mode)}</div>
                        <div class="card-copy" style="margin-top:.5rem"><b>Interpretation:</b> {escape(interpretation)}</div>
                        <div class="card-copy" style="margin-top:.35rem"><b>Mapped Coforge capability:</b> {escape(mapped_cap)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(" ".join(badge(x, "purple") for x in skills[:10]) if skills else badge("No mapped Coforge-relevant skills", "gray"), unsafe_allow_html=True)
                with st.expander("View captured job evidence"):
                    st.write((full_description or "No job-description text was available from the source.")[:5000])
                if job.get("url"):
                    st.link_button("Open job source ↗", job["url"], use_container_width=True)
            else:
                st.info("No roles match the current filters.")

        st.divider()
        section_title("Skill demand map", "Counts distinct captured roles containing each mapped skill — not raw keyword repetitions.", "Demand")
        skill_counts = {}
        for job in jobs:
            for skill in skills_relevant_to_coforge(job):
                skill_counts[skill] = skill_counts.get(skill, 0) + 1
        if skill_counts:
            sdf = pd.DataFrame([{"Skill": k, "Roles containing skill": v} for k, v in skill_counts.items()])
            sdf["% of unique roles"] = (sdf["Roles containing skill"] / max(1, len(jobs)) * 100).round(1)
            sdf = sdf.sort_values("Roles containing skill", ascending=False)
            d1, d2 = st.columns([1.15, 1], gap="large")
            with d1:
                st.dataframe(sdf.head(15), use_container_width=True, hide_index=True, height=410)
            with d2:
                chart_df = sdf.head(10).sort_values("Roles containing skill")
                fig = px.bar(chart_df, x="Roles containing skill", y="Skill", orientation="h", text="Roles containing skill")
                fig.update_traces(marker_color="#635bff")
                fig.update_layout(height=410, margin=dict(l=0, r=8, t=10, b=0), xaxis_title="Unique roles", yaxis_title=None, showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.caption("Example: 'Cybersecurity = 36' means 36 unique captured roles contain a mapped cybersecurity term; it does not mean 36 independent enterprise initiatives.")


# =============================================================================
# TECHNOLOGY SIGNALS
# =============================================================================
elif page == "Technology Signals":
    section_title("Technology signal engine", "Signals are inferred from job titles/descriptions plus recent company/news intelligence. Mentions are evidence of interest or activity — not proof of enterprise-wide adoption.", "Technology")

    if not tech_rows:
        st.markdown('<div class="empty-state">No technology keywords were detected in the current evidence base. Upload richer job descriptions or internal insights in Data Hub.</div>', unsafe_allow_html=True)
    else:
        tdf = pd.DataFrame(tech_rows)
        top = tdf.head(12)
        cols = st.columns(4)
        for idx, (_, row) in enumerate(top.head(8).iterrows()):
            with cols[idx % 4]:
                kpi_card(row["Technology"], row["Mentions"], f"Jobs {row['Job Evidence']} · News {row['News Evidence']}")

        st.write("")
        left, right = st.columns([1.15, 1.5], gap="large")
        with left:
            fig = px.bar(top.sort_values("Mentions"), x="Mentions", y="Technology", orientation="h", text="Mentions")
            fig.update_traces(marker_color="#635bff")
            fig.update_layout(height=455, margin=dict(l=0, r=8, t=10, b=0), xaxis_title=None, yaxis_title=None, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        with right:
            selected_tech = st.selectbox("Inspect supporting evidence", tdf["Technology"].tolist())
            evidence = tech_evidence(selected_tech, jobs, insights, max_items=7)
            if evidence:
                for item in evidence:
                    st.markdown(
                        f"""
                        <div class="signal-card">
                            <div class="signal-top"><div class="signal-name">{escape(item['title'])}</div><div>{badge(item['type'], 'gray')}</div></div>
                            <div class="signal-copy">{escape(item.get('copy') or 'Signal detected in source title.')}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if item.get("url"):
                        st.link_button("Evidence source ↗", item["url"])
            else:
                st.info("The term exists in the aggregate corpus, but a short display extract could not be isolated.")

        st.markdown(" ".join(badge(x["Technology"], "purple") for x in tech_rows[:18]), unsafe_allow_html=True)


# =============================================================================
# NEWSROOM
# =============================================================================
elif page == "Newsroom":
    section_title("Latest news & growth intelligence", "Portfolio-company news is now first-party-first: confirm the company domain, discover its own Newsroom / Insights / Resources / Blog / Press sections, scrape the latest article cards, then add identity-validated external news separately.", "Newsroom")

    if firm.get("entity_kind") == "Portfolio company":
        h1, h2, h3 = st.columns(3)
        h1.metric("First-party items", official_news_count)
        h2.metric("Validated external", external_news_count)
        h3.metric("Official pages discovered", len(official_news_pages))
        if firm.get("manual_news_page"):
            st.success(f"Exact first-party page supplied by user: {firm.get('manual_news_page')}")
        if official_news_pages:
            with st.expander("Official content pages discovered", expanded=False):
                for item in official_news_status.get("source_pages", []):
                    st.write(f"{item.get('kind','Company content')} · {item.get('url','')}")
        else:
            st.info("No first-party content section was confirmed. Use Company Source Controls above to provide the company homepage or exact News / Insights / Resources page.")

    if not insights:
        st.warning("No recent intelligence is available right now.")
    else:
        signal_types = safe_unique([x.get("signal_type", "Other") for x in insights])
        f1, f2, f3, f4 = st.columns([1.6, 1, 1, 1])
        with f1:
            q = st.text_input("Search intelligence", placeholder="AI, acquisition, digital, hiring…")
        with f2:
            signal_filter = st.selectbox("Signal type", ["All"] + signal_types)
        with f3:
            source_filter = st.selectbox("Source", ["All"] + safe_unique([x.get("source", "") for x in insights]))
        with f4:
            credibility_options = safe_unique([x.get("credibility", credibility_label(x)) for x in insights])
            credibility_filter = st.selectbox("Source quality", ["All"] + credibility_options)

        shown = insights
        if q:
            ql = q.lower()
            shown = [x for x in shown if ql in f"{x.get('title','')} {x.get('summary','')}".lower()]
        if signal_filter != "All":
            shown = [x for x in shown if x.get("signal_type") == signal_filter]
        if source_filter != "All":
            shown = [x for x in shown if x.get("source") == source_filter]
        if credibility_filter != "All":
            shown = [x for x in shown if x.get("credibility", credibility_label(x)) == credibility_filter]

        # Signal overview
        counts = pd.Series([x.get("signal_type", "Other") for x in shown]).value_counts().reset_index()
        counts.columns = ["Signal", "Count"]
        if not counts.empty:
            fig = px.bar(counts.sort_values("Count"), x="Count", y="Signal", orientation="h", text="Count")
            fig.update_traces(marker_color="#635bff")
            fig.update_layout(height=310, margin=dict(l=0, r=8, t=8, b=0), xaxis_title=None, yaxis_title=None, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.caption(f"Showing {min(len(shown), 30)} of {len(shown)} matching intelligence items")
        cols = st.columns(2)
        for idx, article in enumerate(shown[:30]):
            with cols[idx % 2]:
                display_news_card(article)


# =============================================================================
# OPPORTUNITY LAB
# =============================================================================
elif page == "Opportunity Lab":
    section_title("Coforge opportunity lab", "Ranks the account using evidence, explains the score and maps only the Coforge capabilities currently loaded in the platform.", "Opportunity")

    score_left, score_right = st.columns([1, 2.3], gap="large")
    with score_left:
        st.markdown(
            f"""
            <div class="glass-card">
                <div class="kpi-label">Composite priority score</div>
                <div class="score-number">{priority_score}<span style="font-size:1rem;color:#94a3b8">/100</span></div>
                <div>{priority_badge(priority_score)}</div>
                <div class="card-copy" style="margin-top:.55rem">{escape(priority_note)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Prioritisation heuristic only — not a forecast of sales value or purchase intent.")
    with score_right:
        breakdown = priority_breakdown
        bdf = pd.DataFrame([{"Component": k, "Points": v} for k, v in breakdown.items()])
        fig = px.bar(bdf, x="Points", y="Component", orientation="h", text="Points")
        fig.update_traces(marker_color="#635bff")
        fig.update_layout(height=330, margin=dict(l=0, r=8, t=8, b=0), xaxis_title="Points toward score", yaxis_title=None, showlegend=False, xaxis_range=[0, 35])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.write("")
    section_title("Recommended AI account plays", "Each opportunity shows the underlying evidence and the best buyer identified from the leadership directory.")
    if opportunities:
        cols = st.columns(2)
        for idx, opp in enumerate(opportunities[:8]):
            with cols[idx % 2]:
                st.markdown(
                    f"""
                    <div class="op-card">
                        <div class="op-head"><div class="op-name">{escape(opp['Coforge Capability'])}</div>{strength_badge(opp['Evidence Strength'])}</div>
                        <div class="op-copy">{escape(opp['Opportunity'])}</div>
                        <div class="op-evidence"><b>Evidence:</b> {escape(opp['Evidence'])}<br><b>Suggested buyer:</b> {escape(opp['Recommended Buyer'])}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.write("")
    else:
        st.info("There is not enough evidence to create a credible AI opportunity map yet.")

    st.divider()
    section_title("Current Coforge capability library", "This is deliberately editable. Replace or extend the JSON in Data Hub as you get more Coforge capability material.", "Capability model")
    cap_df = pd.DataFrame(capabilities)
    st.dataframe(cap_df, use_container_width=True, hide_index=True)

    st.divider()
    section_title("Account briefing pack", "Download a portable Markdown brief containing the current evidence, priority people, jobs, signals and recommended AI angles.", "Export")
    brief = make_account_brief_markdown(
        firm, bio_text, priority_score, priority_band, portfolio, leadership, jobs, insights, tech_rows, why_now, opportunities, coverage
    )
    st.download_button(
        "Download account briefing (.md)",
        brief,
        file_name=f"{entity_slug(firm['name'])}_coforge_account_brief.md",
        mime="text/markdown",
        type="primary",
    )


# =============================================================================
# AI ANALYST
# =============================================================================
elif page == "AI Analyst":
    section_title("AI account analyst", "Ask evidence-grounded questions across portfolio, people, jobs, technology, news and the current Coforge AI capability library.", "Research copilot")

    a1, a2 = st.columns([1.5, 1], gap="large")
    with a1:
        quick_prompts = [
            "What are the top 3 Coforge opportunities for this account and what evidence supports each one?",
            "Who are the highest-priority people Coforge should approach first, and why?",
            "What technology and hiring signals suggest active transformation?",
            "Create a concise pre-meeting brief for a Coforge account executive.",
            "What evidence is missing before we should treat this account as qualified?",
        ]
        preset = st.selectbox("Suggested analysis", ["Write my own question"] + quick_prompts)
        question = st.text_area(
            "Ask the analyst",
            value="" if preset == "Write my own question" else preset,
            placeholder="Example: What is the strongest evidence that this firm could need AI engineering support?",
            height=130,
        )
        model_name = st.text_input("Local Ollama model", value="gemma3", help="Optional. If unavailable, the app uses its deterministic signal engine instead.")

        context = build_ai_context(
            firm["name"], bio_text, jobs, insights, portfolio, tech_rows, opportunities, leadership, why_now, capabilities
        )
        if st.button("Run account analysis", type="primary", use_container_width=True):
            if not question.strip():
                st.warning("Enter a question first.")
            else:
                with st.spinner("Synthesising evidence across the account…"):
                    answer, engine = run_ai_analysis(
                        question,
                        firm["name"],
                        context,
                        model_name,
                        priority_score,
                        tech_rows,
                        opportunities,
                        jobs,
                        insights,
                        portfolio,
                        leadership,
                        why_now,
                    )
                st.session_state.analysis_history.insert(0, {
                    "firm": firm["name"],
                    "question": question,
                    "answer": answer,
                    "engine": engine,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                st.success(f"Analysis complete · {engine}")
                st.markdown(answer)
                st.download_button(
                    "Download analysis",
                    answer,
                    file_name=f"{entity_slug(firm['name'])}_ai_analysis.md",
                    mime="text/markdown",
                )

    with a2:
        section_title("Analyst context", "What the AI is actually allowed to see for this account.")
        st.markdown(
            f"""
            <div class="glass-card">
                <div class="data-row"><div class="data-label">Portfolio / investments</div><div class="data-label">{len(portfolio)}</div></div>
                <div class="data-row"><div class="data-label">Leadership people</div><div class="data-label">{len(leadership)}</div></div>
                <div class="data-row"><div class="data-label">Hiring records</div><div class="data-label">{len(jobs)}</div></div>
                <div class="data-row"><div class="data-label">News / insights</div><div class="data-label">{len(insights)}</div></div>
                <div class="data-row"><div class="data-label">Technology themes</div><div class="data-label">{len(tech_rows)}</div></div>
                <div class="data-row"><div class="data-label">Coforge capabilities</div><div class="data-label">{len(capabilities)}</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.info("The system prompt explicitly tells the analyst not to invent people, portfolio companies, technologies or initiatives, and to flag missing evidence.")

        if st.session_state.analysis_history:
            section_title("Recent analyses")
            for item in st.session_state.analysis_history[:4]:
                with st.expander(f"{item['firm']} · {item['question'][:65]}"):
                    st.caption(f"{item['timestamp']} · {item['engine']}")
                    st.markdown(item["answer"])


# =============================================================================
# DATA HUB
# =============================================================================
elif page == "Data Hub":
    section_title("Data hub & source control", "This is where public web intelligence becomes an internal Coforge-grade account dataset. Upload PitchBook exports or curated research; uploads override public extraction for the current session.", "Data")

    rows = pd.DataFrame(coverage)
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.write("")
    st.markdown(f'<div class="scope-note"><b>Account scope for {escape(firm["name"])}:</b> {escape(firm.get("portfolio_scope", ""))}</div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Portfolio", "Leadership", "Jobs", "News / Insights", "Coforge capabilities"])

    with tab1:
        section_title("Upload portfolio / investments", "Accepted: CSV, XLSX or JSON. PitchBook exports are ideal; common column names are normalized automatically.")
        up = st.file_uploader("Portfolio file", type=["csv", "xlsx", "json"], key=f"port_{selected_firm}")
        if up is not None:
            parsed = normalize_portfolio(parse_uploaded_file(up))
            if parsed:
                st.session_state.uploaded_portfolio[selected_firm] = parsed
                st.success(f"Loaded {len(parsed)} portfolio/investment records. Public data is now overridden for this session.")
                st.dataframe(pd.DataFrame(parsed).head(20), use_container_width=True, hide_index=True)
            else:
                st.error("The file was read but no recognizable portfolio records were found.")
        st.caption("Recommended columns: Company, Sector, Region, Status, Fund, Source")

    with tab2:
        section_title("Upload leadership", "Use a complete people export when you need certainty beyond the official-site parser.")
        up = st.file_uploader("Leadership file", type=["csv", "xlsx", "json"], key=f"lead_{selected_firm}")
        if up is not None:
            parsed = normalize_leadership(parse_uploaded_file(up))
            if parsed:
                st.session_state.uploaded_leadership[selected_firm] = parsed
                st.success(f"Loaded {len(parsed)} people. The Leadership page is now using this dataset.")
                st.dataframe(pd.DataFrame(parsed).head(20), use_container_width=True, hide_index=True)
            else:
                st.error("No recognizable leadership records were found.")
        st.caption("Recommended columns: Name, Role, Location, Bio, Profile URL, Source")

    with tab3:
        section_title("Upload hiring data", "Best results come from job title + location + full description + source URL.")
        up = st.file_uploader("Jobs file", type=["csv", "xlsx", "json"], key=f"jobs_{selected_firm}")
        if up is not None:
            raw_rows = parse_uploaded_file(up)
            parsed = normalize_jobs(raw_rows)
            if parsed:
                st.session_state.uploaded_jobs[selected_firm] = parsed
                st.session_state.uploaded_raw_counts[(selected_firm, "jobs")] = len(raw_rows)
                st.success(f"Loaded {len(raw_rows)} raw postings → {len(parsed)} unique title/location roles. Technology and skill signals update immediately.")
                st.dataframe(pd.DataFrame(parsed).head(20), use_container_width=True, hide_index=True)
            else:
                st.error("No recognizable job records were found.")
        st.caption("Recommended columns: title, location, description, url")

    with tab4:
        section_title("Upload internal news / insights", "Add curated account research, official insights or internal Coforge observations alongside the live public feed.")
        up = st.file_uploader("Insights file", type=["csv", "xlsx", "json"], key=f"ins_{selected_firm}")
        if up is not None:
            parsed = normalize_insights(parse_uploaded_file(up))
            if parsed:
                st.session_state.uploaded_insights[selected_firm] = parsed
                st.success(f"Loaded {len(parsed)} insight records. These are merged with live news rather than replacing it.")
                st.dataframe(pd.DataFrame(parsed).head(20), use_container_width=True, hide_index=True)
            else:
                st.error("No recognizable insight records were found.")
        st.caption("Recommended columns: title, summary, link, published, source, signal_type")

    with tab5:
        section_title("Coforge capability model", "The app currently ships with an AI-focused starter library. Edit data/coforge_capabilities.json to add verified Coforge offerings later.")
        st.dataframe(pd.DataFrame(capabilities), use_container_width=True, hide_index=True)
        st.code(
            '[\n  {\n    "Capability": "AI & Generative AI",\n    "Description": "...",\n    "Signal Keywords": ["genai", "llm", "machine learning"]\n  }\n]',
            language="json",
        )

    st.divider()
    section_title("Persistent local data folders", "For repeatable use, save datasets beside the app instead of re-uploading them every session.", "Developer")
    if firm.get("entity_kind") == "Portfolio company":
        folder_example = f"""data/
  portfolio_companies/
    {entity_slug(selected_firm)}/
      portfolio.csv   # optional
      leadership.csv
      jobs.csv
      insights.csv
  coforge_capabilities.json"""
    else:
        folder_example = f"""data/
  {selected_firm}/
    portfolio.csv   # or .xlsx / .json
    leadership.csv
    jobs.csv
    insights.csv
  coforge_capabilities.json"""
    st.code(folder_example, language="text")
    st.caption("Session uploads take precedence. PE firms use pe_core local adapters; portfolio companies can use data/portfolio_companies/<account-slug>/ for persistent local overrides.")

    st.write("")
    c_refresh, c_clear = st.columns(2)
    with c_refresh:
        if st.button("Refresh live public web intelligence", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with c_clear:
        clear_uploads = st.button("Clear session uploads for this account", use_container_width=True)
    if clear_uploads:
        for key in ["uploaded_portfolio", "uploaded_jobs", "uploaded_insights", "uploaded_leadership"]:
            st.session_state[key].pop(selected_firm, None)
        st.session_state.uploaded_raw_counts.pop((selected_firm, "jobs"), None)
        st.success("Session overrides cleared. The account will return to local/public sources on the next rerun.")
