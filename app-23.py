import json
import os
import re
from datetime import datetime
from html import escape
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pe_core import (
    FIRM_CONFIGS,
    get_google_news,
    get_official_description,
    get_official_news_cards,
    get_profile_bio,
    get_public_portfolio,
    get_wikipedia_summary,
    load_local_jobs,
    load_local_leadership,
    load_local_portfolio,
)
from portfolio_intel import (
    build_disambiguated_news_query,
    build_portco_account,
    discover_company_pages,
    entity_slug,
    filter_company_news,
)
from portfolio_news import clear_news_cache, resolve_company_website, scrape_company_first_party_news
from prototype_core import (
    account_attractiveness,
    build_ai_context,
    build_why_now_events,
    clean_text,
    data_coverage_score,
    dataset_meta,
    format_date,
    get_source_record,
    job_relevance,
    leader_relevance,
    leadership_persona,
    load_demo_capabilities,
    load_demo_capability_payload,
    load_records_csv,
    load_source_registry,
    map_capability_opportunities,
    material_news,
    merge_news,
    normalize_job_rows,
    normalize_leadership_rows,
    normalize_portfolio_rows,
    ownership_summary,
    portfolio_company_view,
    portfolio_mapping_summary,
    qualified_opportunities,
    read_uploaded_table,
    row_profile_text,
    run_local_analysis,
    save_records_csv,
    save_source_record,
    source_quality,
    technology_signals,
)

APP_VERSION = "5.0.0-prototype"

st.set_page_config(
    page_title="Coforge PE Intelligence",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Styling
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    :root{--ink:#172033;--muted:#667085;--line:#e5e7eb;--panel:#fff;--soft:#f7f8fb;--purple:#5b5be9;--green:#067647;--amber:#b54708}
    .stApp{background:#f5f7fb;color:var(--ink)}
    [data-testid="stSidebar"]{background:#10121c}
    [data-testid="stSidebar"] *{color:#f4f4f5}
    [data-testid="stSidebar"] .stRadio label{padding:.15rem 0}
    .brand{padding:.2rem 0 1rem}.brand-title{font-size:1.18rem;font-weight:800}.brand-sub{font-size:.78rem;color:#b8bcc8;margin-top:.2rem}
    .hero{background:linear-gradient(120deg,#1a1d2a,#282e5b);border-radius:20px;padding:25px 28px;color:white;margin:.35rem 0 1rem}
    .hero-kicker,.section-kicker{font-size:.69rem;letter-spacing:.12em;text-transform:uppercase;font-weight:800;opacity:.78}
    .hero-title{font-size:2rem;font-weight:800;margin-top:.25rem}.hero-sub{font-size:.93rem;opacity:.9;margin-top:.2rem}.hero-meta{font-size:.78rem;opacity:.72;margin-top:.8rem}
    .section-title{font-size:1.25rem;font-weight:800;margin-top:.15rem}.section-sub{color:var(--muted);font-size:.86rem;margin:.15rem 0 .9rem}
    .card,.kpi,.news-card,.opp-card,.source-card{background:white;border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(16,24,40,.03)}
    .kpi-label{font-size:.69rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:700}.kpi-value{font-size:1.55rem;font-weight:800;margin:.3rem 0}.kpi-note{font-size:.75rem;color:var(--muted)}
    .badge{display:inline-block;padding:.24rem .48rem;border-radius:999px;font-size:.68rem;font-weight:700;margin:0 .2rem .25rem 0;background:#eef2ff;color:#4338ca}.badge-green{background:#ecfdf3;color:#067647}.badge-amber{background:#fffaeb;color:#b54708}.badge-gray{background:#f2f4f7;color:#475467}.badge-blue{background:#eff8ff;color:#175cd3}
    .news-title{font-weight:750;margin:.45rem 0 .25rem}.news-meta{font-size:.73rem;color:var(--muted);margin-top:.35rem}.news-summary{font-size:.82rem;color:#475467;line-height:1.45}
    .scope-note{background:#fffaeb;border:1px solid #fedf89;border-radius:10px;padding:10px 12px;font-size:.82rem;color:#7a2e0e;margin:.45rem 0 .9rem}
    .empty{background:#fff;border:1px dashed #cfd4dc;border-radius:12px;padding:20px;color:#667085}
    .crumb{font-size:.75rem;color:#667085;margin:.2rem 0 .5rem}.crumb b{color:#344054}
    .source-strip{display:flex;gap:.7rem;flex-wrap:wrap;background:#fff;border:1px solid #e5e7eb;border-radius:11px;padding:9px 12px;font-size:.76rem;color:#475467;margin-bottom:.7rem}
    .opp-score{font-size:1.6rem;font-weight:800}.muted{color:#667085}.small{font-size:.76rem;color:#667085}
    .status-good{color:#067647;font-weight:700}.status-warn{color:#b54708;font-weight:700}
    .pill-row{display:flex;gap:.35rem;flex-wrap:wrap}
    div[data-testid="stDataFrame"]{border:1px solid #e5e7eb;border-radius:12px;overflow:hidden}
    .stButton>button,.stDownloadButton>button{border-radius:9px}
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# UI helpers
# -----------------------------------------------------------------------------
def section_title(title, sub="", kicker=""):
    if kicker:
        st.markdown(f'<div class="section-kicker">{escape(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{escape(title)}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="section-sub">{escape(sub)}</div>', unsafe_allow_html=True)


def kpi(label, value, note=""):
    st.markdown(
        f'<div class="kpi"><div class="kpi-label">{escape(str(label))}</div><div class="kpi-value">{escape(str(value))}</div><div class="kpi-note">{escape(str(note))}</div></div>',
        unsafe_allow_html=True,
    )


def badge(text, kind="purple"):
    cls = {"green": " badge-green", "amber": " badge-amber", "gray": " badge-gray", "blue": " badge-blue"}.get(kind, "")
    return f'<span class="badge{cls}">{escape(str(text))}</span>'


def safe_unique(series):
    vals = []
    for x in series:
        v = clean_text(x)
        if v and v.lower() not in {"nan", "none"} and v not in vals:
            vals.append(v)
    return sorted(vals)


def is_url(value):
    try:
        p = urlparse(clean_text(value))
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


def host(value):
    try:
        return urlparse(clean_text(value)).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def nav_to(label, target, key):
    if st.button(label, key=key, use_container_width=True):
        st.session_state.page = target
        st.rerun()


def confidence_badge(label):
    return badge(label, "green" if label == "High" else "amber" if label == "Medium" else "gray")


def account_hero(firm, attractiveness, coverage, intelligence_count):
    kind = firm.get("entity_kind", "PE firm")
    scope = (
        "Portfolio, people, hiring, technology, news and evidence-backed Coforge opportunity intelligence."
        if kind == "PE firm"
        else "Operating-company intelligence across people, hiring, technology, news and Coforge opportunity mapping."
    )
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-kicker">COFORGE · {'PE ACCOUNT' if kind == 'PE firm' else 'PORTFOLIO COMPANY'} INTELLIGENCE</div>
          <div class="hero-title">{escape(firm.get('name',''))}</div>
          <div class="hero-sub">{escape(firm.get('category','Account'))} · {escape(scope)}</div>
          <div class="hero-meta">Account attractiveness {attractiveness}/100 · Data coverage {coverage}% · {intelligence_count} clustered intelligence event(s)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_news_card(row, compact=False):
    quality = row.get("credibility") or source_quality(row)
    qkind = "green" if quality == "Official company source" else "blue" if quality == "Priority publication" else "gray"
    published = format_date(row.get("published"), include_time=False) or "Undated"
    supporting = int(row.get("source_count", 1) or 1)
    st.markdown(
        f"""
        <div class="news-card">
          <div>{badge(row.get('signal_type','Other'))}{badge(row.get('publisher') or row.get('source','News'),'gray')}{badge(quality,qkind)}</div>
          <div class="news-title">{escape(row.get('title','Untitled'))}</div>
          {'' if compact or not row.get('summary') else f'<div class="news-summary">{escape(clean_text(row.get("summary"))[:550])}</div>'}
          <div class="news-meta">{escape(published)}{' · '+str(supporting)+' supporting sources' if supporting>1 else ''}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if is_url(row.get("link")):
        st.link_button("Open source ↗", row["link"], use_container_width=compact)


def clean_public_portfolio(rows):
    strategy_values = {"strategic opportunities", "catalyst", "credit", "growth", "secondaries"}
    out = []
    for x in rows or []:
        r = dict(x)
        region = clean_text(r.get("Geography") or r.get("Region"))
        strategy = clean_text(r.get("Strategy") or r.get("Fund"))
        if region.lower() in strategy_values:
            if not strategy:
                strategy = region
            region = ""
        r["Geography"] = region
        r["Region"] = region
        r["Strategy"] = strategy
        r.setdefault("Description", "")
        r.setdefault("HQ Location", "")
        r.setdefault("Company Website", "")
        r.setdefault("Deal Date", "")
        r.setdefault("Deal Type", "")
        r.setdefault("Deal Status", r.get("Status", ""))
        r.setdefault("Investors", "")
        r.setdefault("Current Employees", "")
        r.setdefault("Keywords", "")
        out.append(r)
    return out


def latest_meta_label(meta, fallback="Not loaded"):
    if not meta:
        return fallback
    raw = clean_text(meta.get("last_updated"))
    if raw:
        try:
            return pd.to_datetime(raw).strftime("%d %b %Y · %H:%M")
        except Exception:
            return raw
    return fallback


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------
def state(name, default):
    if name not in st.session_state:
        st.session_state[name] = default


state("page", "Command Center")
state("account_scope", "PE firm")
state("selected_portco", {})
state("analysis_history", [])
state("pending_scope", None)
state("pending_portco", None)

# -----------------------------------------------------------------------------
# Sponsor + portfolio loading before sidebar
# -----------------------------------------------------------------------------
firm_keys = list(FIRM_CONFIGS.keys())

with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-title">◆ PE Intelligence</div><div class="brand-sub">Coforge account intelligence workspace</div></div>', unsafe_allow_html=True)
    st.caption(f"Prototype v{APP_VERSION}")
    parent_firm_key = st.selectbox("PE sponsor", firm_keys, format_func=lambda k: FIRM_CONFIGS[k]["name"], key="pe_sponsor")
    parent_firm = FIRM_CONFIGS[parent_firm_key]

# Persistent PitchBook/local data takes precedence; public directory is fallback.
persistent_portfolio = load_records_csv(parent_firm_key, "portfolio", "PE firm")
legacy_local_portfolio = load_local_portfolio(parent_firm_key) if not persistent_portfolio else []
if persistent_portfolio:
    parent_portfolio_raw = clean_public_portfolio(persistent_portfolio)
    parent_portfolio_mode = "Persistent PitchBook / uploaded dataset"
elif legacy_local_portfolio:
    parent_portfolio_raw = clean_public_portfolio(legacy_local_portfolio)
    parent_portfolio_mode = "Local portfolio dataset"
else:
    public_rows, public_label = get_public_portfolio(parent_firm_key)
    parent_portfolio_raw = clean_public_portfolio(public_rows)
    parent_portfolio_mode = public_label

parent_companies = portfolio_company_view(parent_portfolio_raw)
if not parent_companies and parent_portfolio_raw:
    parent_companies = clean_public_portfolio(parent_portfolio_raw)

# -----------------------------------------------------------------------------
# Sidebar account navigation
# -----------------------------------------------------------------------------
with st.sidebar:
    options = ["PE firm"] + (["Portfolio company"] if parent_companies else [])
    if st.session_state.pending_scope in options:
        st.session_state.account_scope = st.session_state.pending_scope
        st.session_state.pending_scope = None
    if st.session_state.account_scope not in options:
        st.session_state.account_scope = "PE firm"
    account_kind = st.radio("View", options, key="account_scope", horizontal=True)

    selected_portco_row = None
    if account_kind == "Portfolio company" and parent_companies:
        pdf = pd.DataFrame(parent_companies).fillna("")
        if st.session_state.pending_portco and st.session_state.pending_portco in set(pdf["Company"].astype(str)):
            st.session_state[f"portco_{parent_firm_key}"] = st.session_state.pending_portco
            st.session_state.pending_portco = None
        search = st.text_input("Portfolio company", placeholder="Search company name…", key=f"portco_search_{parent_firm_key}")
        choices_df = pdf
        if search.strip():
            mask = choices_df.astype(str).apply(lambda c: c.str.contains(search, case=False, na=False)).any(axis=1)
            choices_df = choices_df[mask]
        choices = safe_unique(choices_df["Company"]) or safe_unique(pdf["Company"])
        chosen = st.selectbox("Open company", choices, key=f"portco_{parent_firm_key}")
        rows = pdf[pdf["Company"] == chosen]
        if not rows.empty:
            selected_portco_row = rows.iloc[0].to_dict()
        st.markdown(f"**{escape(chosen)}**  \n{escape(clean_text(selected_portco_row.get('Sector') if selected_portco_row else ''))}")
        if st.button(f"← Back to {parent_firm['name']}", use_container_width=True):
            st.session_state.account_scope = "PE firm"
            st.session_state.page = "Command Center"
            st.rerun()

    pe_pages = ["Command Center", "Portfolio", "Leadership", "Hiring & Skills", "Technology Signals", "Newsroom", "Opportunity Lab", "AI Analyst", "Data Hub"]
    portco_pages = ["Command Center", "Leadership", "Hiring & Skills", "Technology Signals", "Newsroom", "Opportunity Lab", "AI Analyst", "Data Hub"]
    pages = portco_pages if account_kind == "Portfolio company" else pe_pages
    if st.session_state.page not in pages:
        st.session_state.page = "Command Center"
    page_labels = {
        "Command Center": "⌂  Company Overview" if account_kind == "Portfolio company" else "⌂  Command Center",
        "Portfolio": "▦  Portfolio",
        "Leadership": "◎  Leadership",
        "Hiring & Skills": "↗  Hiring & Skills",
        "Technology Signals": "◇  Technology Signals",
        "Newsroom": "◫  News & Insights",
        "Opportunity Lab": "✦  Opportunity Lab",
        "AI Analyst": "◆  AI Analyst",
        "Data Hub": "⇅  Data & Sources" if account_kind == "Portfolio company" else "⇅  Data Hub",
    }
    st.markdown("---")
    st.caption("WORKSPACE")
    selected_page = st.radio("Workspace", pages, index=pages.index(st.session_state.page), format_func=lambda p: page_labels[p], label_visibility="collapsed")
    st.session_state.page = selected_page
    page = selected_page

# -----------------------------------------------------------------------------
# Build current account, source links and datasets
# -----------------------------------------------------------------------------
capability_payload = load_demo_capability_payload()
capabilities = load_demo_capabilities()

if account_kind == "Portfolio company" and selected_portco_row:
    portco_name = clean_text(selected_portco_row.get("Company"))
    selected_firm = f"{parent_firm_key}__portco__{entity_slug(portco_name)}"
    sources = get_source_record(selected_firm)
    firm = build_portco_account(parent_firm_key, parent_firm, selected_portco_row, source_record=sources, auto_discover=False)
    # Verified source metadata can correct ambiguous public directory fields.
    if sources.get("geography"):
        firm["region"] = sources["geography"]
    if sources.get("hq_location"):
        firm["hq_location"] = sources["hq_location"]
    if sources.get("ownership_override"):
        firm["ownership_note"] = sources["ownership_override"]

    portfolio = []
    persistent_jobs = load_records_csv(selected_firm, "jobs", "Portfolio company")
    persistent_leadership = load_records_csv(selected_firm, "leadership", "Portfolio company")
    jobs = persistent_jobs
    leadership = persistent_leadership

    profile_text = clean_text(sources.get("profile_override")) or row_profile_text(selected_portco_row)
    profile_source = "Verified source registry" if sources.get("profile_override") else ("PitchBook / portfolio dataset" if profile_text else "")
    if not profile_text and firm.get("official_website"):
        rec = get_official_description(firm["official_website"])
        if rec and clean_text(rec.get("extract")):
            profile_text = clean_text(rec.get("extract"))
            profile_source = "Official website"
    # Deliberately do not use Wikipedia for unresolved/ambiguous portcos. This avoids Majesco-style identity contamination.

    leadership_url = clean_text(sources.get("leadership_url"))
    careers_url = clean_text(sources.get("careers_url"))
    news_url = clean_text(sources.get("news_url"))
    source_links = {"official_website": firm.get("official_website", ""), "leadership_url": leadership_url, "careers_url": careers_url, "news_url": news_url}

    official_news, external_news = [], []
    official_news_status = {"source_pages": [], "source_results": [], "errors": [], "article_count": 0}
    news_needed = page in {"Command Center", "Newsroom", "Opportunity Lab", "AI Analyst"}
    if news_needed:
        if firm.get("official_website") and news_url:
            official_news, official_news_status = scrape_company_first_party_news(
                firm["name"], firm["official_website"], exact_content_url=news_url,
                max_sources=1 if sources.get("locked_news") else 3,
                max_articles=40,
                locked=bool(sources.get("locked_news")),
            )
        elif page == "Newsroom" and firm.get("official_website"):
            official_news, official_news_status = scrape_company_first_party_news(
                firm["name"], firm["official_website"], max_sources=3, max_articles=30, locked=False
            )
        query = build_disambiguated_news_query(
            clean_text(firm["name"]), firm.get("official_website", ""), profile_text,
            firm.get("sector", ""), parent_firm.get("name", ""),
        )
        raw_external = get_google_news(query, limit=24 if page == "Newsroom" else 12)
        external_news = filter_company_news(raw_external, firm["name"], firm.get("official_website", ""), profile_text, firm.get("sector", ""), parent_firm.get("name", ""))
    insights = merge_news(official_news, external_news)
    official_news_count = len(official_news)
    external_news_count = len(external_news)
    portfolio_mode = "Operating company"
    leadership_mode = "Persistent leadership dataset" if leadership else ("Verified leadership page" if leadership_url else "Not loaded")
    jobs_mode = "Persistent jobs dataset" if jobs else ("Verified careers page" if careers_url else "Not loaded")
else:
    selected_firm = parent_firm_key
    firm = dict(parent_firm)
    firm.update({"entity_kind": "PE firm", "parent_firm_key": parent_firm_key, "parent_firm_name": parent_firm.get("name", "")})
    sources = {}
    source_links = {"leadership_url": (parent_firm.get("people_urls") or [""])[0], "careers_url": (parent_firm.get("careers_urls") or [""])[0], "official_website": parent_firm.get("website", ""), "news_url": (parent_firm.get("news_urls") or [""])[0]}
    portfolio = parent_companies

    persistent_jobs = load_records_csv(parent_firm_key, "jobs", "PE firm")
    persistent_leadership = load_records_csv(parent_firm_key, "leadership", "PE firm")
    jobs = persistent_jobs or load_local_jobs(parent_firm_key)
    leadership = persistent_leadership or load_local_leadership(parent_firm_key)
    jobs_mode = "Persistent jobs dataset" if persistent_jobs else ("Local jobs dataset" if jobs else "Not loaded")
    leadership_mode = "Persistent leadership dataset" if persistent_leadership else ("Local leadership dataset" if leadership else "Not loaded")
    portfolio_mode = parent_portfolio_mode

    official = get_official_description(parent_firm.get("about_url") or parent_firm.get("website"))
    profile_text = clean_text((official or {}).get("extract"))
    profile_source = "Official website" if profile_text else ""
    if not profile_text:
        wiki = get_wikipedia_summary(parent_firm.get("wikipedia", parent_firm["name"]))
        profile_text = clean_text((wiki or {}).get("extract"))
        profile_source = "Wikipedia fallback" if profile_text else ""

    official_news, external_news = [], []
    for url in (parent_firm.get("news_urls") or [])[:2]:
        official_news.extend(get_official_news_cards(url, limit=12))
    external_news = get_google_news(f'"{firm["name"]}" (private equity OR acquisition OR portfolio OR AI OR technology OR digital OR hiring)', limit=24)
    insights = merge_news(official_news, external_news)
    official_news_count, external_news_count = len(official_news), len(external_news)
    official_news_status = {"source_pages": parent_firm.get("news_urls", []), "source_results": [], "errors": [], "article_count": official_news_count}

# Add personas/relevance to leadership rows without altering source facts.
for p in leadership:
    p["Persona"] = leadership_persona(p.get("Role", ""))
    rel, reason = leader_relevance(p)
    p["Coforge Relevance"] = rel
    p["Why Relevant"] = reason

tech_rows = technology_signals(jobs, insights)
opportunities = map_capability_opportunities(capabilities, jobs, insights, leadership, portfolio, firm.get("entity_kind", "PE firm"))
why_now = build_why_now_events(insights, opportunities, jobs)
coverage_score, coverage_components = data_coverage_score(firm.get("entity_kind", "PE firm"), bool(profile_text), portfolio, leadership, jobs, insights, source_links)
attractiveness, attractiveness_breakdown = account_attractiveness(firm.get("entity_kind", "PE firm"), portfolio, leadership, jobs, insights, tech_rows, bool(profile_text))
qualified = qualified_opportunities(opportunities)

# -----------------------------------------------------------------------------
# Header / current-account shortcuts
# -----------------------------------------------------------------------------
st.markdown(
    f'<div class="crumb"><b>{escape(parent_firm.get("name",""))}</b>{" › <b>"+escape(firm.get("name",""))+"</b>" if firm.get("entity_kind")=="Portfolio company" else ""} › {escape(page_labels.get(page,page))}</div>',
    unsafe_allow_html=True,
)
account_hero(firm, attractiveness, coverage_score, len(insights))

if firm.get("entity_kind") == "Portfolio company":
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
    with c1:
        if st.button(f"← {parent_firm['name']}", use_container_width=True):
            st.session_state.account_scope = "PE firm"
            st.session_state.page = "Command Center"
            st.rerun()
    with c2: nav_to("Leadership", "Leadership", f"quick-lead-{selected_firm}")
    with c3: nav_to("News & insights", "Newsroom", f"quick-news-{selected_firm}")
    with c4: nav_to("Opportunities", "Opportunity Lab", f"quick-opp-{selected_firm}")

    st.markdown(
        f'<div class="source-strip"><b>Company sources</b><span>{escape(host(firm.get("official_website")) or "website unresolved")}</span><span>{"Verified news page locked" if sources.get("locked_news") and sources.get("news_url") else "Automatic/fallback news discovery"}</span><span>{official_news_count} first-party · {external_news_count} external</span></div>',
        unsafe_allow_html=True,
    )

# =============================================================================
# COMMAND CENTER / COMPANY OVERVIEW
# =============================================================================
if page == "Command Center":
    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi("Account attractiveness", f"{attractiveness}/100", "Prioritisation heuristic; not purchase intent")
    with c2:
        if firm.get("entity_kind") == "PE firm":
            kpi("Unique companies", len(portfolio), f"Source: {portfolio_mode}")
        else:
            kpi("Ownership / sponsor", parent_firm.get("name", ""), clean_text(firm.get("ownership_note"))[:80])
    with c3: kpi("Priority stakeholders", sum(1 for p in leadership if p.get("Coforge Relevance", 0) >= 4), f"{len(leadership)} captured")
    with c4: kpi("Qualified AI plays", len(qualified), "Direct evidence threshold applied")

    st.write("")
    left, right = st.columns([1.65, 1], gap="large")
    with left:
        section_title("Account snapshot", "Verified/company-sourced profile first; fallback sources are clearly labelled.", "Account")
        ownership = sources.get("ownership_override") if firm.get("entity_kind") == "Portfolio company" else ""
        st.markdown(
            f'<div class="card"><b>{escape(firm.get("name",""))}</b><div class="small" style="margin:.25rem 0 .7rem">{badge(firm.get("category","Account"),"blue")}{badge(profile_source or "Profile unavailable","gray")}</div><div>{escape(profile_text or "No verified company profile is currently loaded.")}</div>'
            + (f'<div class="small" style="margin-top:.8rem"><b>Ownership:</b> {escape(ownership or ownership_summary(selected_portco_row,parent_firm.get("name","")) or firm.get("ownership_note",""))}</div>' if firm.get("entity_kind") == "Portfolio company" else '')
            + (f'<div class="small"><b>HQ:</b> {escape(clean_text(firm.get("hq_location")) or "Not captured")} · <b>Geography:</b> {escape(clean_text(firm.get("region")) or "Not captured")}</div>' if firm.get("entity_kind") == "Portfolio company" else '')
            + '</div>',
            unsafe_allow_html=True,
        )
        if firm.get("entity_kind") == "Portfolio company":
            b1,b2,b3 = st.columns(3)
            if is_url(firm.get("official_website")): b1.link_button("Official website ↗", firm["official_website"], use_container_width=True)
            if is_url(source_links.get("leadership_url")): b2.link_button("Leadership source ↗", source_links["leadership_url"], use_container_width=True)
            if is_url(source_links.get("careers_url")): b3.link_button("Careers source ↗", source_links["careers_url"], use_container_width=True)

        st.write("")
        section_title("Why now?", "Only recent, material events or actual relevant hiring create a trigger. Old volume alone does not.", "Buying signals")
        if why_now:
            for w in why_now[:3]:
                st.markdown(
                    f'<div class="card" style="margin-bottom:.55rem"><div>{badge(w.get("Type"),"amber")}</div><b>{escape(w.get("Signal",""))}</b><div class="small">{escape(w.get("Evidence",""))}</div><div style="margin-top:.5rem">{escape(w.get("Why it matters",""))}</div>'
                    + (f'<div class="small" style="margin-top:.5rem"><b>Potential Coforge angle:</b> {escape(", ".join(w.get("Coforge angles") or []))}</div>' if w.get("Coforge angles") else '')
                    + '</div>', unsafe_allow_html=True)
                if is_url(w.get("link")): st.link_button("Inspect evidence ↗", w["link"])
        else:
            st.markdown('<div class="empty"><b>No qualified near-term trigger yet.</b><br>There may be account potential, but the current evidence does not prove a timely buying signal.</div>', unsafe_allow_html=True)

    with right:
        section_title("Data coverage", "Coverage/completeness only — not a claim that every record is correct.", "Evidence health")
        fig = go.Figure(go.Indicator(mode="gauge+number", value=coverage_score, number={"suffix":"%"}, gauge={"axis":{"range":[0,100]},"bar":{"color":"#5b5be9"}}))
        fig.update_layout(height=210, margin=dict(l=20,r=20,t=10,b=10))
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
        for layer, pct in coverage_components.items():
            status = "Loaded" if pct >= 100 else "Source link available" if pct >= 35 else "Not loaded"
            st.markdown(f"**{layer}** — {status} · {pct}%")
        st.caption("Salesforce / account history is not connected in this prototype.")

        st.write("")
        section_title("Top Coforge opportunities", "Evidence confidence is separate from account/potential scale.", "Coforge")
        if qualified:
            for o in qualified[:3]:
                st.markdown(
                    f'<div class="opp-card" style="margin-bottom:.55rem"><div>{confidence_badge(o["Evidence Confidence"])}{badge("Potential "+o["Potential Scale"],"blue")}</div><b>{escape(o["Coforge Capability"])}</b><div class="small">Evidence {o["Evidence Score"]}/100 · {escape(o["Evidence"])}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No Coforge AI opportunity currently clears the prototype qualification threshold. This is a valid intelligence outcome.")

    st.write("")
    section_title("Latest material account intelligence", "A short, material feed only; the full chronological feed is in News & Insights.", "Live feed")
    material = material_news(insights, 3)
    if material:
        cols = st.columns(min(3, len(material)))
        for i, n in enumerate(material):
            with cols[i % len(cols)]: render_news_card(n, compact=True)
    else:
        st.caption("No recent material intelligence event is currently loaded.")

# =============================================================================
# PORTFOLIO (PE firms only)
# =============================================================================
elif page == "Portfolio":
    section_title("Sponsor portfolio", "PitchBook/persistent uploads override public extraction. Analytics use validated dimensions only.", "Portfolio")
    st.markdown(f'<div class="scope-note"><b>Source:</b> {escape(portfolio_mode)} · {escape(parent_firm.get("portfolio_scope",""))}</div>', unsafe_allow_html=True)
    if not portfolio:
        st.markdown('<div class="empty"><b>No company-level portfolio dataset is loaded.</b><br>Upload a PitchBook XLSX/CSV in Data Hub or open the official portfolio source.</div>', unsafe_allow_html=True)
        if parent_firm.get("portfolio_urls"): st.link_button("Official portfolio source ↗", parent_firm["portfolio_urls"][0])
    else:
        df = pd.DataFrame(portfolio).fillna("")
        for c in ["Company","Sector","Geography","Strategy","Status","Description","HQ Location","Company Website","Deal Count"]:
            if c not in df.columns: df[c] = ""
        a,b,c,d = st.columns(4)
        with a: kpi("Unique companies", df["Company"].nunique(), f"{len(parent_portfolio_raw)} underlying record(s)")
        with b: kpi("Sectors", df.loc[df["Sector"].astype(bool),"Sector"].nunique(), "Validated labels only")
        with c: kpi("Geographies", df.loc[df["Geography"].astype(bool),"Geography"].nunique(), "Strategy values excluded")
        with d: kpi("Source mode", portfolio_mode[:28], "PitchBook wins when loaded")
        f1,f2,f3,f4 = st.columns([1.8,1,1,1])
        q=f1.text_input("Search portfolio", placeholder="Company, description, sector, geography…")
        sector=f2.selectbox("Sector", ["All"]+safe_unique(df["Sector"]))
        geo=f3.selectbox("Geography", ["All"]+safe_unique(df["Geography"]))
        strategy=f4.selectbox("Strategy", ["All"]+safe_unique(df["Strategy"]))
        filt=df.copy()
        if q: filt=filt[filt.astype(str).apply(lambda s:s.str.contains(q,case=False,na=False)).any(axis=1)]
        if sector!="All": filt=filt[filt["Sector"]==sector]
        if geo!="All": filt=filt[filt["Geography"]==geo]
        if strategy!="All": filt=filt[filt["Strategy"]==strategy]
        st.caption(f"Showing {len(filt)} of {len(df)} unique companies")
        display=[c for c in ["Company","Sector","Geography","Strategy","Status","Deal Count"] if c in filt.columns]
        st.dataframe(filt[display], use_container_width=True, hide_index=True, height=430)
        st.download_button("Download filtered portfolio CSV", filt.drop(columns=[c for c in filt.columns if c.startswith("_")], errors="ignore").to_csv(index=False).encode(), file_name=f"{parent_firm_key}_portfolio_companies.csv", mime="text/csv")
        st.write("")
        left,right=st.columns([1.2,1],gap="large")
        with left:
            section_title("Portfolio mix", "Only populated, valid sector labels are charted.")
            counts=filt.loc[filt["Sector"].astype(bool),"Sector"].value_counts().head(12)
            if not counts.empty:
                chart=pd.DataFrame({"Sector":counts.index,"Companies":counts.values})
                fig=px.bar(chart,x="Companies",y="Sector",orientation="h")
                fig.update_layout(height=360,margin=dict(l=10,r=10,t=10,b=10),showlegend=False)
                st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
            else: st.caption("Sector data not sufficiently populated for a chart.")
        with right:
            section_title("Open a portfolio company", "Company-level metadata and deal relationships are preserved.")
            choices=safe_unique(filt["Company"])
            if choices:
                chosen=st.selectbox("Select a portfolio company", ["Select a company…"]+choices)
                if chosen!="Select a company…":
                    r=filt[filt["Company"]==chosen].iloc[0].to_dict()
                    st.markdown(f'<div class="card"><b>{escape(chosen)}</b><div class="small">{escape(r.get("Sector") or "Sector not captured")} · {escape(r.get("Geography") or "Geography not captured")}</div><div style="margin-top:.5rem">{escape(clean_text(r.get("Description"))[:500] or "Description not captured")}</div><div class="small" style="margin-top:.5rem">Deal records: {escape(str(r.get("Deal Count") or 1))} · Strategy: {escape(r.get("Strategy") or "Not captured")}</div></div>',unsafe_allow_html=True)
                    if st.button(f"Open {chosen} →",use_container_width=True):
                        st.session_state.pending_scope="Portfolio company"
                        st.session_state.pending_portco=chosen
                        st.session_state.account_scope="Portfolio company"
                        st.session_state.page="Command Center"
                        st.rerun()

# =============================================================================
# LEADERSHIP
# =============================================================================
elif page == "Leadership":
    meta=dataset_meta(selected_firm,"leadership",firm.get("entity_kind","PE firm"))
    section_title("Leadership intelligence", "Persistent people dataset with clear source/freshness. Scraper automation can be added later without redesigning the UI.", "People")
    c1,c2,c3,c4=st.columns(4)
    with c1:kpi("People captured",len(leadership),"Current persistent/local dataset")
    with c2:kpi("Priority stakeholders",sum(1 for p in leadership if p.get("Coforge Relevance",0)>=4),"4–5/5 relevance")
    with c3:kpi("Tech / Data / AI",sum(1 for p in leadership if p.get("Persona")=="Technology / Data / AI"),"Persona classification")
    with c4:kpi("Last refreshed",latest_meta_label(meta,"Not yet refreshed"),"Dataset timestamp")
    if is_url(source_links.get("leadership_url")):
        st.link_button("Open official leadership / people page ↗",source_links["leadership_url"])
    if not leadership:
        st.markdown('<div class="empty"><b>No people dataset loaded yet.</b><br>The UI is ready for the firm-specific leadership CSV. Use Data Hub to upload a dataset; the official people-page link above remains available in the meantime.</div>',unsafe_allow_html=True)
    else:
        df=pd.DataFrame(leadership).fillna("")
        f1,f2,f3=st.columns([1.6,1,1])
        q=f1.text_input("Search people",placeholder="Name, role, team…")
        persona=f2.selectbox("Persona",["All"]+safe_unique(df["Persona"]))
        loc=f3.selectbox("Location",["All"]+safe_unique(df.get("Location",pd.Series(dtype=str))))
        filt=df.copy()
        if q:filt=filt[filt.astype(str).apply(lambda s:s.str.contains(q,case=False,na=False)).any(axis=1)]
        if persona!="All":filt=filt[filt["Persona"]==persona]
        if loc!="All":filt=filt[filt["Location"]==loc]
        cols=[x for x in ["Name","Role","Team","Location","Persona","Coforge Relevance"] if x in filt.columns]
        st.dataframe(filt[cols],use_container_width=True,hide_index=True,height=430)
        names=safe_unique(filt["Name"])
        if names:
            section_title("Inspect stakeholder","Source fact and Coforge inference are kept separate.")
            name=st.selectbox("Person",names)
            r=filt[filt["Name"]==name].iloc[0].to_dict()
            rel,reason=leader_relevance(r)
            st.markdown(f'<div class="card"><b>{escape(name)}</b><div>{escape(r.get("Role",""))}</div><div class="small">{escape(r.get("Location",""))} · {escape(r.get("Persona",""))}</div><hr><b>Why relevant to Coforge</b><div>{escape(reason)}</div><div class="small">Relevance {rel}/5 — platform inference</div></div>',unsafe_allow_html=True)
            if is_url(r.get("Profile URL")):st.link_button("Official profile ↗",r["Profile URL"])

# =============================================================================
# HIRING
# =============================================================================
elif page == "Hiring & Skills":
    meta=dataset_meta(selected_firm,"jobs",firm.get("entity_kind","PE firm"))
    enriched=[]
    for j in jobs:
        score,skills,caps=job_relevance(j,capabilities)
        r=dict(j);r.update({"Relevance":score,"Skills":", ".join(skills),"Capability match":", ".join(caps)})
        enriched.append(r)
    section_title("Hiring & skills intelligence","Persistent jobs dataset; live firm-specific scrapers can refresh the CSV later without slowing the app.","Talent signals")
    c1,c2,c3,c4=st.columns(4)
    with c1:kpi("Unique roles",len(enriched),"Title + location deduplicated")
    with c2:kpi("High relevance",sum(1 for j in enriched if j["Relevance"]>=4),"4–5/5 capability fit")
    with c3:kpi("Locations",len({clean_text(j.get("location")) for j in enriched if clean_text(j.get("location"))}),"Distinct populated locations")
    with c4:kpi("Last refreshed",latest_meta_label(meta,"Not yet refreshed"),"Dataset timestamp")
    if is_url(source_links.get("careers_url")):st.link_button("Open official careers page ↗",source_links["careers_url"])
    if not enriched:
        st.markdown('<div class="empty"><b>No persistent jobs dataset loaded yet.</b><br>Use the careers link above or upload the scraper CSV in Data Hub. Technology Signals will clearly show this dependency rather than pretending zero hiring means zero technology demand.</div>',unsafe_allow_html=True)
    else:
        df=pd.DataFrame(enriched).fillna("")
        f1,f2,f3=st.columns([1.7,1,1])
        q=f1.text_input("Search roles",placeholder="Title, skill, location, description…")
        loc=f2.selectbox("Location",["All"]+safe_unique(df["location"]))
        rel=f3.selectbox("Relevance",["All","High (4–5)","Medium (3)","Low (1–2)"])
        filt=df.copy()
        if q:filt=filt[filt.astype(str).apply(lambda s:s.str.contains(q,case=False,na=False)).any(axis=1)]
        if loc!="All":filt=filt[filt["location"]==loc]
        if rel=="High (4–5)":filt=filt[filt["Relevance"]>=4]
        elif rel=="Medium (3)":filt=filt[filt["Relevance"]==3]
        elif rel=="Low (1–2)":filt=filt[filt["Relevance"]<=2]
        display=[x for x in ["title","location","function","Skills","Capability match","Relevance"] if x in filt.columns]
        st.dataframe(filt[display],use_container_width=True,hide_index=True,height=430)
        titles=safe_unique(filt["title"])
        if titles:
            section_title("Inspect a role","Full description, detected skills and capability mapping.")
            title=st.selectbox("Role",titles)
            r=filt[filt["title"]==title].iloc[0].to_dict()
            st.markdown(f'<div class="card"><b>{escape(title)}</b><div class="small">{escape(r.get("location",""))} · source {escape(r.get("source",""))}</div><div style="margin-top:.6rem">{escape(clean_text(r.get("description"))[:1500] or "No description loaded")}</div><div class="small" style="margin-top:.6rem"><b>Detected skills:</b> {escape(r.get("Skills") or "None")}<br><b>Coforge mapping:</b> {escape(r.get("Capability match") or "No direct map yet")}</div></div>',unsafe_allow_html=True)
            if is_url(r.get("url")):st.link_button("Open job source ↗",r["url"])

# =============================================================================
# TECHNOLOGY SIGNALS
# =============================================================================
elif page == "Technology Signals":
    section_title("Technology signals","Evidence extracted from loaded jobs plus relevant news. Missing jobs are shown as a data gap, not a false zero.","Technology")
    if not jobs:
        st.warning("No jobs dataset is loaded. Hiring-derived technology signals are unavailable until the Hiring & Skills dataset is populated.")
    if not tech_rows:
        st.markdown('<div class="empty"><b>No recognized technology signal is currently detected.</b><br>This may mean the evidence is genuinely thin, or that the Hiring dataset is not loaded yet. Check Data & Sources before interpreting this as an absence of technology activity.</div>',unsafe_allow_html=True)
    else:
        df=pd.DataFrame(tech_rows)
        fig=px.bar(df.head(15),x="Mentions",y="Technology",orientation="h",hover_data=["Job Evidence","News Evidence"])
        fig.update_layout(height=450,margin=dict(l=10,r=10,t=10,b=10),showlegend=False)
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
        st.dataframe(df,use_container_width=True,hide_index=True)

# =============================================================================
# NEWSROOM
# =============================================================================
elif page == "Newsroom":
    section_title("News & insights","Unified chronology across first-party and external reporting. Same-event articles are clustered so signal volume is not inflated.","Intelligence")
    c1,c2,c3=st.columns(3)
    with c1:kpi("Clustered events",len(insights),"Duplicate coverage grouped")
    with c2:kpi("First-party articles",official_news_count,"Official company/PE source")
    with c3:kpi("External articles",external_news_count,"Before event clustering")
    if firm.get("entity_kind")=="Portfolio company" and is_url(source_links.get("news_url")):
        st.link_button("Open verified news / insights page ↗",source_links["news_url"])
    if not insights:
        st.markdown('<div class="empty">No news items are currently available. For a portfolio company, save the verified newsroom URL in Data & Sources.</div>',unsafe_allow_html=True)
    else:
        df=pd.DataFrame(insights).fillna("")
        f1,f2,f3,f4=st.columns([1.7,1,1,1])
        q=f1.text_input("Search intelligence")
        signal=f2.selectbox("Signal type",["All"]+safe_unique(df["signal_type"]))
        publisher=f3.selectbox("Publisher",["All"]+safe_unique(df["publisher"]))
        quality=f4.selectbox("Source quality",["All"]+safe_unique(df["credibility"]))
        filtered=insights
        if q:
            filtered=[r for r in filtered if q.lower() in f"{r.get('title','')} {r.get('summary','')} {r.get('publisher','')}".lower()]
        if signal!="All":filtered=[r for r in filtered if r.get("signal_type")==signal]
        if publisher!="All":filtered=[r for r in filtered if r.get("publisher")==publisher]
        if quality!="All":filtered=[r for r in filtered if r.get("credibility")==quality]
        counts=pd.Series([r.get("signal_type","Other") for r in filtered]).value_counts()
        if not counts.empty:
            chart=pd.DataFrame({"Signal":counts.index,"Events":counts.values})
            fig=px.bar(chart,x="Events",y="Signal",orientation="h")
            fig.update_layout(height=300,margin=dict(l=10,r=10,t=10,b=10),showlegend=False)
            st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
        page_size=st.selectbox("Items to show",[20,50,"All"],index=0)
        shown=filtered if page_size=="All" else filtered[:int(page_size)]
        st.caption(f"Showing {len(shown)} of {len(filtered)} matching clustered events · newest dated items first; undated items last")
        for i in range(0,len(shown),2):
            cols=st.columns(2)
            for j in range(2):
                if i+j<len(shown):
                    with cols[j]:render_news_card(shown[i+j])

# =============================================================================
# OPPORTUNITY LAB
# =============================================================================
elif page == "Opportunity Lab":
    section_title("Coforge opportunity lab","Separates account attractiveness from capability-specific evidence. Recommendations can legitimately be unqualified.","Opportunity")
    top_evidence=qualified[0]["Evidence Score"] if qualified else 0
    c1,c2,c3=st.columns([1,1,1])
    with c1:kpi("Account attractiveness",f"{attractiveness}/100","Account potential / activity")
    with c2:kpi("Best AI evidence",f"{top_evidence}/100","Capability-specific evidence")
    with c3:kpi("Demo capabilities",len(capabilities),"AI-practice subset, not full Coforge")

    left,right=st.columns([1,1.4],gap="large")
    with left:
        section_title("Attractiveness breakdown","These points rank the account; they do not prove AI purchase intent.")
        bdf=pd.DataFrame({"Component":list(attractiveness_breakdown.keys()),"Points":list(attractiveness_breakdown.values())})
        fig=px.bar(bdf,x="Points",y="Component",orientation="h")
        fig.update_layout(height=330,margin=dict(l=10,r=10,t=10,b=10),showlegend=False)
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
    with right:
        section_title("Qualified Coforge plays","Direct evidence, missing evidence and potential scale are shown separately.")
        if not qualified:
            st.markdown('<div class="empty"><b>No qualified opportunity yet.</b><br>The account may still be attractive, but the current evidence does not support a capability-specific AI recommendation above the prototype threshold. Add leadership/hiring evidence or validate a current initiative.</div>',unsafe_allow_html=True)
        else:
            for o in qualified[:6]:
                buyers=", ".join(o.get("Suggested Buyers") or [])
                proof=" · ".join(o.get("Proof Points") or [])
                st.markdown(
                    f'<div class="opp-card" style="margin-bottom:.7rem"><div>{confidence_badge(o["Evidence Confidence"])}{badge("Potential "+o["Potential Scale"],"blue")}</div><div style="display:flex;justify-content:space-between;gap:1rem"><b>{escape(o["Coforge Capability"])}</b><span class="opp-score">{o["Evidence Score"]}</span></div><div>{escape(o.get("Description",""))}</div><div class="small" style="margin-top:.6rem"><b>Evidence:</b> {escape(o["Evidence"])}<br><b>Suggested buyer personas:</b> {escape(buyers or "Named buyer not yet identified")}<br><b>Relevant proof point:</b> {escape(proof or "Not captured")}<br><b>Coforge source:</b> slide(s) {escape(str(o.get("Source Slides","")))}</div></div>',unsafe_allow_html=True)
                with st.expander(f"Supporting evidence — {o['Coforge Capability']}"):
                    if o.get("Supporting Evidence"):
                        for ev in o["Supporting Evidence"]:
                            st.write(f"**{ev.get('type')}** · {ev.get('label')} · {ev.get('date') or 'date not captured'}")
                            if is_url(ev.get("link")):st.link_button("Open evidence ↗",ev["link"])
                    else: st.caption("No direct evidence record is attached to this hypothesis yet.")

    st.write("")
    meta=capability_payload.get("metadata",{})
    section_title("Capability knowledge base","Detailed keyword/configuration data lives in Data Hub rather than cluttering the commercial view.","Capability model")
    st.info(f"{meta.get('name','Demo capability library')} · {len(capabilities)} detailed capabilities · Source: {meta.get('source','')} · {meta.get('scope_note','')}")
    brief_lines=[f"# {firm.get('name')} — Coforge Account Brief",f"Generated {datetime.now():%Y-%m-%d %H:%M}",f"Account attractiveness: {attractiveness}/100",f"Data coverage: {coverage_score}%","","## Qualified opportunities"]
    if qualified:
        for o in qualified[:5]:brief_lines.append(f"- {o['Coforge Capability']} — {o['Evidence Confidence']} ({o['Evidence Score']}/100): {o['Evidence']}")
    else:brief_lines.append("- No capability currently qualified above the evidence threshold.")
    st.download_button("Download account briefing (.md)","\n".join(brief_lines),file_name=f"{entity_slug(firm.get('name','account'))}_brief.md",mime="text/markdown")

# =============================================================================
# AI ANALYST
# =============================================================================
elif page == "AI Analyst":
    section_title("AI account analyst","Local Ollama analyst grounded in the current account evidence and the demo Coforge capability library.","Research copilot")
    q1,q2,q3,q4=st.columns(4)
    prompts=[
        "What are the top 3 Coforge opportunities for this account and what evidence supports each one?",
        "Who are the highest-priority people Coforge should approach first, and why?",
        "What evidence is missing before we should treat this account as qualified?",
        "Create a concise pre-meeting brief for a Coforge account executive.",
    ]
    qkey=f"question_box_{selected_firm}"
    if qkey not in st.session_state:
        st.session_state[qkey]=""
    for col,label,prompt in zip([q1,q2,q3,q4],["Find opportunities","Who to approach","Evidence gaps","Meeting brief"],prompts):
        with col:
            if st.button(label,use_container_width=True,key=f"qp-{label}-{selected_firm}"):
                st.session_state[qkey]=prompt
    question=st.text_area("Ask the analyst",placeholder="Ask a question about the account, evidence, stakeholders or Coforge opportunity mapping…",height=120,key=qkey)
    with st.expander("Advanced model settings",expanded=False):
        model_name=st.text_input("Local Ollama model",value="gemma3",help="Use the exact model tag installed in Ollama, e.g. gemma3 or a local Llama tag.")
        st.caption("On Streamlit Cloud this local model is not reachable; on your laptop it will use your local Ollama service. A deterministic evidence-grounded fallback is retained.")
    left,right=st.columns([1.6,1],gap="large")
    with right:
        section_title("Analyst context","Source/freshness status rather than record counts alone.")
        status_rows=[
            ("Portfolio / company data",len(portfolio),portfolio_mode if firm.get("entity_kind")=="PE firm" else profile_source),
            ("Leadership",len(leadership),leadership_mode),
            ("Hiring",len(jobs),jobs_mode),
            ("News / events",len(insights),"Verified first-party + filtered external" if insights else "Not loaded"),
            ("Technology themes",len(tech_rows),"Derived from current evidence"),
            ("Coforge demo capabilities",len(capabilities),capability_payload.get("metadata",{}).get("source","Demo library")),
        ]
        for label,count,status in status_rows:
            st.markdown(f"**{label}** — {count}  \n<span class='small'>{escape(clean_text(status))}</span>",unsafe_allow_html=True)
        st.info("The analyst receives observed evidence and platform-generated inferences in separate sections and is explicitly told it may reject weak inferences.")
    with left:
        if st.button("Run account analysis",type="primary",use_container_width=True):
            if not question.strip():st.warning("Enter a question first.")
            else:
                context=build_ai_context(question,firm,profile_text,portfolio,leadership,jobs,insights,tech_rows,opportunities,capabilities,why_now)
                with st.spinner("Synthesising account evidence…"):
                    answer,engine=run_local_analysis(question,firm,context,model_name,opportunities,why_now,leadership,jobs,insights)
                st.success(f"Analysis complete · {engine}")
                st.markdown(answer)
                st.download_button("Download analysis",answer,file_name=f"{entity_slug(firm.get('name','account'))}_analysis.md",mime="text/markdown")
                st.session_state.analysis_history.insert(0,{"firm":firm.get("name"),"question":question,"answer":answer,"engine":engine,"time":datetime.now().strftime("%Y-%m-%d %H:%M")})
        if st.session_state.analysis_history:
            section_title("Recent analyses")
            for item in st.session_state.analysis_history[:4]:
                with st.expander(f"{item['firm']} · {item['question'][:70]}"):
                    st.caption(f"{item['time']} · {item['engine']}")
                    st.markdown(item["answer"])

# =============================================================================
# DATA HUB / DATA & SOURCES
# =============================================================================
elif page == "Data Hub":
    section_title("Data hub & source control","Persistent account datasets and verified source URLs. Uploaded portfolio data overrides public extraction on the next rerun.","Data")
    if firm.get("entity_kind")=="Portfolio company":
        st.markdown(f'<div class="scope-note"><b>{escape(firm.get("name",""))}</b> · save verified URLs once; the app will reuse them and will not probe guessed news paths when the newsroom URL is locked.</div>',unsafe_allow_html=True)
        section_title("Verified company sources","Saved to data/source_registry.json and reused across sessions.")
        current=get_source_record(selected_firm)
        with st.form(f"sources-{selected_firm}"):
            c1,c2=st.columns(2)
            website=c1.text_input("Official company website",value=current.get("official_website",firm.get("official_website", "")))
            news=c2.text_input("Exact News / Insights / Resources page",value=current.get("news_url",""))
            c3,c4=st.columns(2)
            leadership_link=c3.text_input("Leadership / People page",value=current.get("leadership_url",""))
            careers_link=c4.text_input("Careers page",value=current.get("careers_url",""))
            lock=st.checkbox("Lock the verified news page and use only this first-party page",value=bool(current.get("locked_news",True)))
            if st.form_submit_button("Save & use verified sources",type="primary",use_container_width=True):
                if website and not is_url(website):st.error("Official website must be a valid http(s) URL.")
                elif news and not is_url(news):st.error("News page must be a valid http(s) URL.")
                else:
                    save_source_record(selected_firm,{"official_website":website,"news_url":news,"leadership_url":leadership_link,"careers_url":careers_link,"locked_news":lock,"last_verified":datetime.now().strftime("%Y-%m-%d")})
                    clear_news_cache();st.success("Verified sources saved persistently.");st.rerun()
        with st.expander("Automatic source discovery",expanded=False):
            st.caption("Use this only when the official URL has not yet been confirmed. Once you save a verified URL, that source takes precedence.")
            if st.button("Discover official website / source pages"):
                result=resolve_company_website(firm["name"],row=selected_portco_row,parent_website=parent_firm.get("website",""))
                st.json(result)
                resolved=result.get("website","")
                if resolved:
                    pages=discover_company_pages(resolved)
                    st.write("Candidate pages")
                    st.json(pages)

        st.write("")
        t1,t2=st.tabs(["Leadership dataset","Hiring dataset"])
        with t1:
            up=st.file_uploader("Leadership CSV/XLSX/JSON",type=["csv","xlsx","xls","json"],key=f"lead-up-{selected_firm}")
            if up:
                raw,diag=read_uploaded_table(up);parsed=normalize_leadership_rows(raw)
                st.caption(f"Parsed {len(parsed)} people")
                if parsed:st.dataframe(pd.DataFrame(parsed).head(20),use_container_width=True,hide_index=True)
                if st.button("Save leadership dataset",disabled=not bool(parsed)):
                    path=save_records_csv(selected_firm,"leadership",parsed,"Portfolio company");st.success(f"Saved {len(parsed)} people to {path.name}");st.rerun()
        with t2:
            up=st.file_uploader("Jobs CSV/XLSX/JSON",type=["csv","xlsx","xls","json"],key=f"jobs-up-{selected_firm}")
            if up:
                raw,diag=read_uploaded_table(up);parsed,raw_count=normalize_job_rows(raw)
                st.caption(f"{raw_count} raw postings → {len(parsed)} unique title/location roles")
                if parsed:st.dataframe(pd.DataFrame(parsed).head(20),use_container_width=True,hide_index=True)
                if st.button("Save jobs dataset",disabled=not bool(parsed)):
                    path=save_records_csv(selected_firm,"jobs",parsed,"Portfolio company");st.success(f"Saved {len(parsed)} unique roles to {path.name}");st.rerun()
    else:
        status=pd.DataFrame([
            {"Layer":"Portfolio","Records":len(parent_portfolio_raw),"Mode":portfolio_mode,"Last updated":latest_meta_label(dataset_meta(parent_firm_key,"portfolio","PE firm"),"Public/live fallback")},
            {"Layer":"Leadership","Records":len(leadership),"Mode":leadership_mode,"Last updated":latest_meta_label(dataset_meta(parent_firm_key,"leadership","PE firm"))},
            {"Layer":"Hiring","Records":len(jobs),"Mode":jobs_mode,"Last updated":latest_meta_label(dataset_meta(parent_firm_key,"jobs","PE firm"))},
            {"Layer":"Coforge capabilities","Records":len(capabilities),"Mode":"Demo capability file","Last updated":capability_payload.get("metadata",{}).get("last_updated","")},
        ])
        st.dataframe(status,use_container_width=True,hide_index=True)
        tabs=st.tabs(["Portfolio / PitchBook","Leadership","Hiring","Coforge capabilities"])
        with tabs[0]:
            section_title("Upload portfolio / investments","Real PitchBook exports are detected even when the header starts several rows down. Useful company/deal fields are preserved; financial fields remain in the raw record for later expansion.")
            up=st.file_uploader("PitchBook / portfolio file",type=["csv","xlsx","xls","json"],key=f"portfolio-up-{parent_firm_key}")
            if up:
                raw,diag=read_uploaded_table(up)
                parsed=normalize_portfolio_rows(raw)
                companies=portfolio_company_view(parsed)
                mapping=portfolio_mapping_summary(raw)
                if diag.get("error"):st.error(diag["error"])
                else:
                    st.success(f"Detected {diag.get('format','file')} · sheet {diag.get('sheet','—')} · header row {diag.get('header_row','—')} · {len(raw)} source rows → {len(companies)} unique companies")
                    st.write("Detected field mapping");st.json(mapping)
                    if companies:
                        preview=pd.DataFrame(companies).drop(columns=[c for c in pd.DataFrame(companies).columns if c.startswith("_")],errors="ignore")
                        st.dataframe(preview.head(20),use_container_width=True,hide_index=True)
                    if st.button("Use this as the portfolio dataset",type="primary",disabled=not bool(parsed),use_container_width=True):
                        path=save_records_csv(parent_firm_key,"portfolio",parsed,"PE firm")
                        st.success(f"Saved {len(parsed)} investment/deal records. This persistent dataset now overrides public portfolio extraction.")
                        st.rerun()
            st.caption("Displayed MVP fields: company, description, sector/industry, geography/HQ, website, deal date/type/status, ownership/investors, employees and keywords. Financial fields can be added to later analytics without changing the ingestion model.")
        with tabs[1]:
            section_title("Leadership dataset","Upload the CSV created by the firm-specific people scraper. The page UI is already independent of scraper implementation.")
            up=st.file_uploader("Leadership file",type=["csv","xlsx","xls","json"],key=f"lead-up-{parent_firm_key}")
            if up:
                raw,diag=read_uploaded_table(up);parsed=normalize_leadership_rows(raw)
                if parsed:st.dataframe(pd.DataFrame(parsed).head(20),use_container_width=True,hide_index=True)
                if st.button("Save leadership dataset",disabled=not bool(parsed),use_container_width=True):save_records_csv(parent_firm_key,"leadership",parsed,"PE firm");st.success("Leadership dataset saved persistently.");st.rerun()
        with tabs[2]:
            section_title("Hiring dataset","Upload the careers scraper CSV. Raw and deduplicated counts remain explicit.")
            up=st.file_uploader("Jobs file",type=["csv","xlsx","xls","json"],key=f"jobs-up-{parent_firm_key}")
            if up:
                raw,diag=read_uploaded_table(up);parsed,raw_count=normalize_job_rows(raw)
                st.caption(f"{raw_count} raw postings → {len(parsed)} unique title/location roles")
                if parsed:st.dataframe(pd.DataFrame(parsed).head(20),use_container_width=True,hide_index=True)
                if st.button("Save jobs dataset",disabled=not bool(parsed),use_container_width=True):save_records_csv(parent_firm_key,"jobs",parsed,"PE firm");st.success("Jobs dataset saved persistently.");st.rerun()
        with tabs[3]:
            meta=capability_payload.get("metadata",{})
            section_title(meta.get("name","Coforge AI Capability Library — Demo"),meta.get("scope_note",""))
            st.success(f"{len(capabilities)} detailed capabilities loaded from {meta.get('source','demo capability file')}. Opportunity Lab and AI Analyst use this file directly.")
            cap_df=pd.DataFrame([{ "Capability":c.get("Capability"),"Category":c.get("Category"),"Description":c.get("Description"),"Source slides":c.get("Source Slides"),"Confidence":c.get("Confidence") } for c in capabilities])
            st.dataframe(cap_df,use_container_width=True,hide_index=True)
            with st.expander("Capability hierarchy"):
                st.json(capability_payload.get("hierarchy",{}))
            st.caption("For this demo the capability library is deliberately hard-coded in a separate removable JSON file. A future document-ingestion workflow can replace that file without redesigning Opportunity Lab or the AI Analyst.")
