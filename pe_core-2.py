import io
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from urllib.parse import quote, urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    import ollama
except Exception:
    ollama = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


# -----------------------------------------------------------------------------
# ACCOUNT CONFIGURATION
# -----------------------------------------------------------------------------
# URLs are intentionally public/official. A source can fail without breaking the app.
FIRM_CONFIGS = {
    "cvc": {
        "name": "CVC Capital Partners",
        "aliases": ["CVC", "CVC Capital"],
        "category": "Global Private Markets",
        "website": "https://www.cvc.com/",
        "about_url": "https://www.cvc.com/about/",
        "portfolio_urls": ["https://www.cvc.com/portfolio/our-portfolio/"],
        "people_urls": ["https://www.cvc.com/about/our-people/"],
        "careers_urls": ["https://www.cvc.com/about/our-people/"],
        "news_urls": ["https://www.cvc.com/media/news/"],
        "wikipedia": "CVC Capital Partners",
        "portfolio_scope": "Public CVC portfolio directory; may span strategies and current/historical holdings depending on CVC's published filters.",
        "portfolio_mode": "cvc",
    },
    "apax": {
        "name": "Apax Partners",
        "aliases": ["Apax"],
        "category": "Global Private Equity & Growth",
        "website": "https://www.apax.com/",
        "about_url": "https://www.apax.com/about-us/",
        "portfolio_urls": ["https://www.apax.com/partnerships/"],
        "people_urls": ["https://www.apax.com/people/our-team/"],
        "careers_urls": ["https://www.apax.com/people/careers/"],
        "news_urls": ["https://www.apax.com/news-views/"],
        "wikipedia": "Apax Partners",
        "portfolio_scope": "Apax public Partnerships directory. It can include current and realised partnerships; use PitchBook export if you need a strict current-fund view.",
        "portfolio_mode": "apax",
    },
    "permira": {
        "name": "Permira",
        "aliases": ["Pereira", "Permira Advisers"],
        "category": "Global Private Equity, Growth & Credit",
        "website": "https://www.permira.com/",
        "about_url": "https://www.permira.com/about",
        "portfolio_urls": ["https://www.permira.com/portfolio"],
        "people_urls": ["https://www.permira.com/people/meet-our-people"],
        "careers_urls": ["https://www.permira.com/people/life-at-permira"],
        "news_urls": ["https://www.permira.com/news-and-insights"],
        "wikipedia": "Permira",
        "portfolio_scope": "Permira public portfolio directory across its investment platform; use fund/status fields where available to distinguish current from historical holdings.",
        "portfolio_mode": "permira",
    },
    "hg": {
        "name": "Hg",
        "aliases": ["Hg Capital", "HgCapital"],
        "category": "Technology & Services Private Equity",
        "website": "https://hgcapital.com/",
        "about_url": "https://hgcapital.com/about-us",
        "portfolio_urls": ["https://hgcapital.com/portfolio"],
        "people_urls": ["https://hgcapital.com/team"],
        "careers_urls": ["https://hgcapital.com/life-at-hg"],
        "news_urls": ["https://hgcapital.com/insights"],
        "wikipedia": "Hg (private equity)",
        "portfolio_scope": "Hg's public portfolio/investment directory, focused on software and services businesses.",
        "portfolio_mode": "generic",
    },
    "bridgepoint": {
        "name": "Bridgepoint",
        "aliases": ["Bridgepoint Group"],
        "category": "Mid-Market Private Markets",
        "website": "https://www.bridgepointgroup.com/",
        "about_url": "https://www.bridgepointgroup.com/about-us",
        "portfolio_urls": ["https://www.bridgepointgroup.com/investment-strategies/private-equity/portfolio"],
        "people_urls": ["https://www.bridgepointgroup.com/about-us/our-people"],
        "careers_urls": ["https://www.bridgepointgroup.com/about-us/joining-the-team"],
        "news_urls": ["https://www.bridgepointgroup.com/news-and-insights"],
        "wikipedia": "Bridgepoint Group",
        "portfolio_scope": "Bridgepoint's published private-equity portfolio. This deliberately excludes infrastructure/credit unless you upload a broader PitchBook dataset.",
        "portfolio_mode": "generic",
    },
    "tdr": {
        "name": "TDR Capital",
        "aliases": ["TDR"],
        "category": "European Mid-Market Private Equity",
        "website": "https://www.tdrcapital.com/",
        "about_url": "https://www.tdrcapital.com/",
        "portfolio_urls": ["https://www.tdrcapital.com/portfolio/"],
        "people_urls": ["https://www.tdrcapital.com/team/"],
        "careers_urls": ["https://www.tdrcapital.com/"],
        "news_urls": ["https://www.tdrcapital.com/news/"],
        "wikipedia": "TDR Capital",
        "portfolio_scope": "TDR's published portfolio of European mid-market businesses; the public page may contain current and selected prior investments.",
        "portfolio_mode": "tdr",
    },
    "coller": {
        "name": "Coller Capital",
        "aliases": ["Coller"],
        "category": "Private Capital Secondaries",
        "website": "https://www.collercapital.com/",
        "about_url": "https://www.collercapital.com/about-coller-capital/",
        "portfolio_urls": ["https://www.collercapital.com/investments/"],
        "people_urls": ["https://www.collercapital.com/our-people/"],
        "careers_urls": ["https://www.collercapital.com/careers/"],
        "news_urls": ["https://www.collercapital.com/news-and-insights/"],
        "wikipedia": "Coller Capital",
        "portfolio_scope": "Coller is a secondaries specialist. Its public 'investments' page is transaction/secondary-investment evidence, not a conventional operating-company portfolio list.",
        "portfolio_mode": "generic",
    },
    "towerbrook": {
        "name": "TowerBrook Capital Partners",
        "aliases": ["TowerBrook", "Tower Brook"],
        "category": "Transatlantic Private Equity",
        "website": "https://www.towerbrook.com/",
        "about_url": "https://www.towerbrook.com/",
        "portfolio_urls": ["https://www.towerbrook.com/investments/"],
        "people_urls": ["https://www.towerbrook.com/our-team/"],
        "careers_urls": ["https://www.towerbrook.com/our-team/"],
        "news_urls": ["https://www.towerbrook.com/news/"],
        "wikipedia": "TowerBrook Capital Partners",
        "portfolio_scope": "TowerBrook's public investments directory across active and prior investments; use status filters or PitchBook for a strict active-only view.",
        "portfolio_mode": "generic",
    },
    "cinven": {
        "name": "Cinven",
        "aliases": [],
        "category": "European Private Equity",
        "website": "https://www.cinven.com/",
        "about_url": "https://www.cinven.com/",
        "portfolio_urls": ["https://www.cinven.com/portfolio/"],
        "people_urls": ["https://www.cinven.com/team/"],
        "careers_urls": ["https://www.cinven.com/culture-values/"],
        "news_urls": ["https://www.cinven.com/news-insights/"],
        "wikipedia": "Cinven",
        "portfolio_scope": "Cinven public portfolio/current investment pages. Use uploaded PitchBook data when the public directory does not expose the full set in parseable HTML.",
        "portfolio_mode": "generic",
    },
    "kkr": {
        "name": "KKR",
        "aliases": ["KKR & Co", "Kohlberg Kravis Roberts"],
        "category": "Global Alternative Asset Management",
        "website": "https://www.kkr.com/",
        "about_url": "https://www.kkr.com/about",
        "portfolio_urls": ["https://www.kkr.com/invest/portfolio"],
        "people_urls": ["https://www.kkr.com/about/our-people"],
        "careers_urls": ["https://www.kkr.com/careers"],
        "news_urls": ["https://www.kkr.com/insights"],
        "wikipedia": "KKR & Co.",
        "portfolio_scope": "KKR's public portfolio directory spans multiple KKR strategies. Treat the count as public directory records, not '300 private-equity buyout companies'.",
        "portfolio_mode": "kkr",
    },
    "blackstone": {
        "name": "Blackstone",
        "aliases": ["The Blackstone Group"],
        "category": "Global Alternative Asset Management",
        "website": "https://www.blackstone.com/",
        "about_url": "https://www.blackstone.com/the-firm/",
        "portfolio_urls": ["https://www.blackstone.com/our-businesses/private-equity/"],
        "people_urls": ["https://www.blackstone.com/the-firm/our-people/"],
        "careers_urls": ["https://www.blackstone.com/careers/careers-blackstone/"],
        "news_urls": ["https://www.blackstone.com/news/"],
        "wikipedia": "Blackstone Inc.",
        "portfolio_scope": "Blackstone publishes PE portfolio metrics and selected companies, but not always a single complete machine-readable corporate-PE directory. PitchBook upload is recommended for exhaustive company coverage.",
        "portfolio_mode": "generic",
    },
    "apollo": {
        "name": "Apollo Global Management",
        "aliases": ["Apollo", "Apollo Global"],
        "category": "Global Alternative Asset Management",
        "website": "https://www.apollo.com/",
        "about_url": "https://www.apollo.com/aboutus",
        "portfolio_urls": ["https://www.apollo.com/strategies/asset-management/equity/private-equity"],
        "people_urls": ["https://www.apollo.com/aboutus/leadership-and-people"],
        "careers_urls": ["https://www.apollo.com/careers"],
        "news_urls": ["https://www.apollo.com/insights-news"],
        "wikipedia": "Apollo Global Management",
        "portfolio_scope": "Apollo publishes aggregate PE portfolio metrics and selected case studies. Use PitchBook upload for a complete company-level portfolio inventory.",
        "portfolio_mode": "generic",
    },
    "advent": {
        "name": "Advent International Europe",
        "aliases": ["Advent International", "Advent"],
        "category": "Global Private Equity — Europe Focus",
        "website": "https://www.adventinternational.com/",
        "about_url": "https://www.adventinternational.com/about-us/",
        "portfolio_urls": ["https://www.adventinternational.com/investments/?country=&sector="],
        "people_urls": ["https://www.adventinternational.com/our-team/"],
        "careers_urls": ["https://www.adventinternational.com/contact-us/"],
        "news_urls": ["https://www.adventinternational.com/news/"],
        "wikipedia": "Advent International",
        "portfolio_scope": "Advent's global public investments directory. The app labels this account 'Europe' for Coforge targeting, but the public source is global unless you filter/upload a Europe-specific export.",
        "portfolio_mode": "generic",
    },
    "eqt": {
        "name": "EQT",
        "aliases": ["EQT Group", "EQT AB"],
        "category": "Global Private Markets",
        "website": "https://eqtgroup.com/",
        "about_url": "https://eqtgroup.com/about",
        "portfolio_urls": ["https://eqtgroup.com/about/current-portfolio"],
        "people_urls": ["https://eqtgroup.com/about/people"],
        "careers_urls": ["https://eqtgroup.com/careers"],
        "news_urls": ["https://eqtgroup.com/news"],
        "wikipedia": "EQT AB",
        "portfolio_scope": "EQT's current portfolio directory across strategies. Fund/market/entry fields are retained when they are exposed by the public page.",
        "portfolio_mode": "eqt",
    },
    "gresham_house": {
        "name": "Gresham House",
        "aliases": ["Gresham"],
        "category": "Specialist Alternative Asset Management",
        "website": "https://greshamhouse.com/",
        "about_url": "https://greshamhouse.com/about/",
        "portfolio_urls": ["https://greshamhouse.com/funds/"],
        "people_urls": ["https://greshamhouse.com/our-team/"],
        "careers_urls": ["https://greshamhouse.com/join-our-team/"],
        "news_urls": ["https://greshamhouse.com/news-and-insights/"],
        "wikipedia": "Gresham House plc",
        "portfolio_scope": "Gresham House is an alternative asset manager across natural capital, energy transition, housing, infrastructure and equity strategies; 'portfolio' is not directly comparable to a classic buyout firm's portco list.",
        "portfolio_mode": "generic",
    },
    "maven": {
        "name": "Maven Capital Partners",
        "aliases": ["Maven", "Maven CP"],
        "category": "UK Private Equity & Alternative Investment",
        "website": "https://www.mavencp.com/",
        "about_url": "https://www.mavencp.com/maven-our-story",
        "portfolio_urls": ["https://www.mavencp.com/our-portfolio/", "https://www.mavencp.com/maven-regional-funds-portfolio"],
        "people_urls": ["https://www.mavencp.com/our-team"],
        "careers_urls": ["https://www.mavencp.com/careers"],
        "news_urls": ["https://www.mavencp.com/latest"],
        "wikipedia": "Maven Capital Partners",
        "portfolio_scope": "Maven public portfolio pages across private equity/growth and regional funds. Uploaded PitchBook data can provide a unified current/historical view.",
        "portfolio_mode": "generic",
    },
}


DEFAULT_AI_CAPABILITIES = [
    {
        "Capability": "AI & Generative AI",
        "Description": "AI engineering, GenAI enablement, enterprise copilots and model-enabled workflow transformation.",
        "Signal Keywords": ["artificial intelligence", "generative ai", "genai", "llm", "copilot", "machine learning"],
    },
    {
        "Capability": "Data for AI",
        "Description": "Data engineering, analytics foundations, governed data access and AI-ready information platforms.",
        "Signal Keywords": ["data engineer", "data platform", "snowflake", "databricks", "analytics", "data governance"],
    },
    {
        "Capability": "Intelligent Automation",
        "Description": "Automation of high-volume workflows using AI, orchestration and human-in-the-loop controls.",
        "Signal Keywords": ["automation", "workflow", "servicenow", "process", "operations", "productivity"],
    },
    {
        "Capability": "AI Engineering & MLOps",
        "Description": "Productionisation, model operations, monitoring, cloud-native AI engineering and platform reliability.",
        "Signal Keywords": ["mlops", "machine learning engineer", "python", "kubernetes", "azure", "aws", "gcp"],
    },
]

TECH_KEYWORDS = {
    "AI / GenAI": ["artificial intelligence", "generative ai", "genai", " llm", "large language model", "copilot", "machine learning", " ai "],
    "Microsoft Azure": ["azure", "microsoft cloud"],
    "AWS": ["aws", "amazon web services"],
    "Google Cloud": ["gcp", "google cloud"],
    "Snowflake": ["snowflake"],
    "Databricks": ["databricks"],
    "Salesforce": ["salesforce"],
    "MuleSoft": ["mulesoft"],
    "ServiceNow": ["servicenow"],
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau"],
    "Workday": ["workday"],
    "SAP": [" sap ", "s/4hana", "s4hana"],
    "Pega": ["pega"],
    "Python": ["python"],
    "Java": ["java"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Cybersecurity": ["cyber security", "cybersecurity", "zero trust", "identity access", "iam", "soc "],
    "Data Governance": ["data governance", "data quality", "data lineage", "master data"],
}

SKILL_TAXONOMY = {
    "AI / GenAI": ["genai", "generative ai", "llm", "machine learning", "artificial intelligence", "prompt engineering", "rag", "vector database"],
    "Python": ["python", "pandas", "pytorch", "tensorflow", "scikit-learn"],
    "Data Engineering": ["data engineering", "etl", "elt", "data pipeline", "spark", "airflow", "dbt"],
    "Databricks": ["databricks"],
    "Snowflake": ["snowflake"],
    "Azure": ["azure"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud"],
    "Cloud Native": ["kubernetes", "docker", "terraform", "microservices", "container"],
    "Automation": ["automation", "workflow", "rpa", "process automation"],
    "Cybersecurity": ["cybersecurity", "cyber security", "iam", "zero trust", "siem", "soc"],
    "Enterprise Architecture": ["enterprise architect", "solution architect", "architecture"],
    "Salesforce": ["salesforce", "mulesoft"],
    "ServiceNow": ["servicenow"],
    "Data Governance": ["data governance", "data quality", "data lineage", "master data"],
    "Product / Agile": ["product management", "product owner", "agile", "scrum"],
}

LEADER_RELEVANCE = [
    (5, ["chief information", "chief technology", "cio", "cto", "chief data", "chief digital", "chief ai", "head of ai", "head of data", "head of technology", "technology partner", "digital partner"]),
    (5, ["operating partner", "portfolio operations", "portfolio group", "value creation", "operational excellence", "portfolio performance", "chief operating officer"]),
    (4, ["transformation", "technology", "data", "digital", "ai", "cyber", "information security", "enterprise architecture"]),
    (3, ["managing partner", "chief executive", "co-ceo", "ceo", "president", "chief investment officer"]),
    (2, ["partner", "managing director"]),
]

JOB_RELEVANCE_TERMS = {
    5: ["ai engineer", "machine learning", "data engineer", "data architect", "cloud architect", "enterprise architect", "technology transformation", "platform engineer", "cybersecurity", "automation"],
    4: ["software engineer", "data", "technology", "digital", "cloud", "product", "developer", "security", "architecture"],
    3: ["operations", "transformation", "analytics", "systems", "infrastructure"],
}


# -----------------------------------------------------------------------------
# NETWORK / FILE HELPERS
# -----------------------------------------------------------------------------
def safe_get(url, *, timeout=20, verify=True, params=None):
    try:
        response = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=timeout,
            verify=verify,
            params=params,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response
    except Exception:
        return None


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def canonical_url(base, href):
    href = clean_text(href)
    if not href or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
        return ""
    return urljoin(base, href)


def same_domain(a, b):
    try:
        da = urlparse(a).netloc.replace("www.", "")
        db = urlparse(b).netloc.replace("www.", "")
        return da == db
    except Exception:
        return False


def load_json_if_exists(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def dataframe_records(df):
    if df is None or df.empty:
        return []
    return df.where(pd.notna(df), "").to_dict("records")


def read_dataset_file(path):
    if not path or not os.path.exists(path):
        return []
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".json":
            raw = load_json_if_exists(path)
            if isinstance(raw, dict):
                for key in ["data", "items", "results", "records"]:
                    if isinstance(raw.get(key), list):
                        raw = raw[key]
                        break
            return raw if isinstance(raw, list) else []
        if ext == ".csv":
            return dataframe_records(pd.read_csv(path))
        if ext in {".xlsx", ".xls"}:
            return dataframe_records(pd.read_excel(path))
    except Exception:
        return []
    return []


def parse_uploaded_file(uploaded):
    if uploaded is None:
        return []
    name = uploaded.name.lower()
    try:
        if name.endswith(".json"):
            raw = json.load(uploaded)
            if isinstance(raw, dict):
                for key in ["data", "items", "results", "records"]:
                    if isinstance(raw.get(key), list):
                        raw = raw[key]
                        break
            return raw if isinstance(raw, list) else []
        payload = uploaded.getvalue()
        if name.endswith(".csv"):
            return dataframe_records(pd.read_csv(io.BytesIO(payload)))
        if name.endswith((".xlsx", ".xls")):
            return dataframe_records(pd.read_excel(io.BytesIO(payload)))
    except Exception:
        return []
    return []


def find_local_dataset(firm_key, kind):
    firm_dir = os.path.join(DATA_DIR, firm_key)
    candidates = []
    for ext in ["json", "csv", "xlsx"]:
        candidates.append(os.path.join(firm_dir, f"{kind}.{ext}"))
        candidates.append(os.path.join(BASE_DIR, f"{firm_key}_{kind}.{ext}"))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def dedupe_records(records, key_fields):
    out, seen = [], set()
    for row in records or []:
        if not isinstance(row, dict):
            continue
        key = tuple(clean_text(row.get(k, "")).lower() for k in key_fields)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


# -----------------------------------------------------------------------------
# NORMALISERS
# -----------------------------------------------------------------------------
def normalize_portfolio(raw):
    out = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"Company": clean_text(item), "Sector": "", "Region": "", "Status": "", "Fund": "", "Source": ""})
            continue
        if not isinstance(item, dict):
            continue
        out.append({
            "Company": clean_text(item.get("Company") or item.get("company") or item.get("name") or item.get("title")),
            "Sector": clean_text(item.get("Sector") or item.get("sector") or item.get("industry") or item.get("category")),
            "Region": clean_text(item.get("Region") or item.get("region") or item.get("country") or item.get("market") or item.get("location")),
            "Status": clean_text(item.get("Status") or item.get("status")),
            "Fund": clean_text(item.get("Fund") or item.get("fund") or item.get("strategy")),
            "Source": clean_text(item.get("Source") or item.get("source") or item.get("url") or item.get("link")),
        })
    return dedupe_records([x for x in out if x["Company"]], ["Company", "Fund"])


def normalize_jobs(raw):
    out = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"title": clean_text(item), "location": "", "description": "", "url": "", "source": "Local/Upload"})
            continue
        if not isinstance(item, dict):
            continue
        out.append({
            "title": clean_text(item.get("title") or item.get("job_title") or item.get("name") or item.get("Role") or item.get("role")),
            "location": clean_text(item.get("location") or item.get("city") or item.get("Location")),
            "description": clean_text(item.get("description") or item.get("summary") or item.get("content") or item.get("skills") or item.get("Description")),
            "url": clean_text(item.get("url") or item.get("link") or item.get("job_url") or item.get("Source")),
            "source": clean_text(item.get("source") or item.get("Source Type") or "Local/Upload"),
        })
    return dedupe_records([x for x in out if x["title"]], ["title", "location"])


def normalize_insights(raw):
    out = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"title": clean_text(item), "summary": "", "link": "", "published": "", "source": "Local/Upload", "signal_type": "Other"})
            continue
        if not isinstance(item, dict):
            continue
        out.append({
            "title": clean_text(item.get("title") or item.get("headline") or item.get("name")),
            "summary": clean_text(item.get("summary") or item.get("content") or item.get("description") or item.get("snippet")),
            "link": clean_text(item.get("link") or item.get("url") or item.get("Source")),
            "published": clean_text(item.get("published") or item.get("date") or item.get("published_at")),
            "source": clean_text(item.get("source") or item.get("Source Type") or "Local/Upload"),
            "signal_type": clean_text(item.get("signal_type") or item.get("type") or ""),
        })
    out = [x for x in out if x["title"]]
    for row in out:
        if not row["signal_type"]:
            row["signal_type"] = classify_news_signal(f"{row['title']} {row['summary']}")
    return dedupe_records(out, ["title"])


def normalize_leadership(raw):
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "Name": clean_text(item.get("Name") or item.get("name") or item.get("person")),
            "Role": clean_text(item.get("Role") or item.get("role") or item.get("title") or item.get("position")),
            "Location": clean_text(item.get("Location") or item.get("location") or item.get("office")),
            "Bio": clean_text(item.get("Bio") or item.get("bio") or item.get("description") or item.get("summary")),
            "Profile URL": clean_text(item.get("Profile URL") or item.get("profile_url") or item.get("url") or item.get("link") or item.get("Source")),
            "Source": clean_text(item.get("Source") or item.get("source") or "Official / Upload"),
        })
    out = dedupe_records([x for x in out if x["Name"]], ["Name", "Role"])
    for row in out:
        row["Coforge Relevance"] = leader_relevance(row.get("Role", ""))
    return out


def load_local_portfolio(firm_key):
    return normalize_portfolio(read_dataset_file(find_local_dataset(firm_key, "portfolio")))


def load_local_jobs(firm_key):
    return normalize_jobs(read_dataset_file(find_local_dataset(firm_key, "jobs")))


def load_local_insights(firm_key):
    return normalize_insights(read_dataset_file(find_local_dataset(firm_key, "insights")))


def load_local_leadership(firm_key):
    return normalize_leadership(read_dataset_file(find_local_dataset(firm_key, "leadership")))


def load_capabilities():
    path = os.path.join(DATA_DIR, "coforge_capabilities.json")
    raw = load_json_if_exists(path)
    if isinstance(raw, list) and raw:
        return raw
    legacy = load_json_if_exists(os.path.join(BASE_DIR, "coforge_capabilities.json"))
    if isinstance(legacy, list) and legacy:
        return legacy
    return DEFAULT_AI_CAPABILITIES


# -----------------------------------------------------------------------------
# BIOS / NEWS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def get_wikipedia_summary(page_name):
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(page_name)}"
    response = safe_get(url, timeout=12)
    if not response:
        return None
    try:
        data = response.json()
        return {
            "extract": clean_text(data.get("extract")),
            "thumbnail": (data.get("thumbnail") or {}).get("source", ""),
            "url": ((data.get("content_urls") or {}).get("desktop") or {}).get("page", ""),
            "source": "Wikipedia",
        }
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def get_official_description(url):
    response = safe_get(url, timeout=15)
    if not response:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    desc = ""
    for attrs in [
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            desc = clean_text(tag.get("content"))
            if len(desc) > 70:
                break
    if not desc:
        main = soup.find("main") or soup.body
        if main:
            paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in main.find_all("p")]
            desc = next((p for p in paragraphs if 100 <= len(p) <= 900), "")
    return {"extract": desc, "url": response.url, "source": "Official website"} if desc else None


@st.cache_data(ttl=1800, show_spinner=False)
def get_google_news(query, limit=20):
    response = safe_get(
        "https://news.google.com/rss/search",
        timeout=15,
        params={"q": query, "hl": "en-GB", "gl": "GB", "ceid": "GB:en"},
    )
    if not response:
        return []
    try:
        root = ET.fromstring(response.content)
        rows = []
        for item in root.findall(".//item")[:limit]:
            title = clean_text(item.findtext("title"))
            summary = clean_text(BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ", strip=True))
            rows.append({
                "title": title,
                "link": clean_text(item.findtext("link")),
                "published": clean_text(item.findtext("pubDate")),
                "summary": summary,
                "source": "Google News",
                "signal_type": classify_news_signal(f"{title} {summary}"),
            })
        return dedupe_records(rows, ["title"])
    except Exception:
        return []


def classify_news_signal(text):
    t = f" {clean_text(text).lower()} "
    buckets = [
        ("AI & Technology", [" ai ", "artificial intelligence", "genai", "technology", "digital", "cloud", "data platform", "cyber"]),
        ("M&A / Deal", ["acquire", "acquisition", "buyout", "take-private", "investment in", "strategic investment", "merger"]),
        ("Fundraising", ["fund raise", "fundraising", "closes fund", "fund close", "capital raised", "raise €", "raise $"]),
        ("Portfolio", ["portfolio company", "portfolio", "exit", "sale of", "divest", "ipo"]),
        ("Leadership", ["appoint", "appointment", "joins", "named ceo", "named cio", "new partner", "promoted"]),
        ("Growth", ["expansion", "new office", "growth", "partnership", "launch", "new market"]),
    ]
    for label, words in buckets:
        if any(w in t for w in words):
            return label
    return "Other"


@st.cache_data(ttl=3600, show_spinner=False)
def get_official_news_cards(url, limit=20):
    response = safe_get(url, timeout=18)
    if not response:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    domain = response.url
    noisy = {"read more", "learn more", "view all", "news", "insights", "home", "menu"}
    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" ", strip=True))
        href = canonical_url(domain, a.get("href"))
        if not title or len(title) < 20 or len(title) > 180 or title.lower() in noisy:
            continue
        if not same_domain(domain, href):
            continue
        hay = f"{href} {title}".lower()
        if not any(k in hay for k in ["news", "insight", "press", "article", "story", "update"]):
            continue
        parent = a.find_parent(["article", "li", "div"])
        summary = clean_text(parent.get_text(" ", strip=True))[:500] if parent else ""
        rows.append({
            "title": title,
            "summary": summary,
            "link": href,
            "published": "",
            "source": "Official website",
            "signal_type": classify_news_signal(f"{title} {summary}"),
        })
        if len(rows) >= limit:
            break
    return dedupe_records(rows, ["title"])


def merge_insights(*groups):
    rows = []
    for group in groups:
        rows.extend(group or [])
    return dedupe_records(normalize_insights(rows), ["title"])


# -----------------------------------------------------------------------------
# PORTFOLIO SOURCES
# -----------------------------------------------------------------------------
@st.cache_data(ttl=21600, show_spinner=False)
def get_kkr_portfolio():
    rows = []
    for page in range(1, 30):
        url = (
            "https://www.kkr.com/content/kkr/sites/global/en/invest/portfolio/"
            "jcr:content/root/main-par/bioportfoliosearch.bioportfoliosearch.json"
            f"?page={page}&sortParameter=&sortingOrder=asc&keyword=&cfnode="
        )
        response = safe_get(url, timeout=18, verify=False)
        if not response:
            break
        try:
            results = response.json().get("results", [])
        except Exception:
            break
        if not results:
            break
        for company in results:
            rows.append({
                "Company": clean_text(company.get("name")),
                "Sector": clean_text(company.get("industry")),
                "Region": clean_text(company.get("region")),
                "Status": clean_text(company.get("status")),
                "Fund": clean_text(company.get("strategy")),
                "Source": "https://www.kkr.com/invest/portfolio",
            })
    return normalize_portfolio(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def get_cvc_portfolio():
    rows = []
    # Prefer the older JSON-ish surface endpoint because it traverses pagination.
    for page in range(1, 35):
        url = (
            "https://www.cvc.com/umbraco/surface/locationitems/PortfolioLocationItems"
            "?pageKey=76273fbf-2d9e-4bb4-8630-70903f7a0cef"
            f"&page={page}&strategy=all&country=all&industries=all&query="
        )
        response = safe_get(url, timeout=18)
        if not response:
            break
        cards = re.findall(
            r'data-title="([^"]+)".*?data-heading="([^"]+)".*?portfolio__card-subtitle.*?>(.*?)<',
            response.text,
            re.DOTALL,
        )
        if not cards:
            break
        for sector, company, region in cards:
            rows.append({
                "Company": unescape(clean_text(company)),
                "Sector": unescape(clean_text(sector)),
                "Region": re.sub(r"<.*?>", "", unescape(region)).strip(),
                "Status": "",
                "Fund": "",
                "Source": "https://www.cvc.com/portfolio/our-portfolio/",
            })
    if rows:
        return normalize_portfolio(rows)
    return scrape_generic_portfolio("https://www.cvc.com/portfolio/our-portfolio/", "cvc")


@st.cache_data(ttl=21600, show_spinner=False)
def get_permira_portfolio():
    rows = []
    for page in range(0, 30):
        response = safe_get(
            "https://www.permira.com/api/portfolio",
            timeout=18,
            verify=False,
            params={"page": page, "filters": "{}", "sort": "a_z"},
        )
        if not response:
            break
        try:
            items = response.json().get("data", [])
        except Exception:
            break
        if not items:
            break
        for item in items:
            rows.append({
                "Company": clean_text(item.get("name") or item.get("title")),
                "Sector": clean_text(item.get("description") or item.get("sector")),
                "Region": clean_text(item.get("country")),
                "Status": clean_text(item.get("status")),
                "Fund": clean_text(item.get("strategy") or item.get("fund")),
                "Source": "https://www.permira.com/portfolio",
            })
    return normalize_portfolio(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def get_apax_portfolio():
    response = safe_get("https://www.apax.com/umbraco/apax/SearchSurface/partnerships", timeout=22)
    rows = []
    if response:
        soup = BeautifulSoup(response.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            title = clean_text(a.get_text(" ", strip=True))
            href = canonical_url(response.url, a.get("href"))
            if not title or len(title) < 2 or len(title) > 90 or title.lower() in {"read more", "view partnership", "view all"}:
                continue
            if "partnership" not in href.lower():
                continue
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            rows.append({"Company": title, "Sector": "", "Region": "", "Status": "", "Fund": "", "Source": href})
    if len(rows) < 10:
        rows = scrape_generic_portfolio("https://www.apax.com/partnerships/", "apax")
    return normalize_portfolio(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def get_tdr_portfolio():
    response = safe_get("https://www.tdrcapital.com/portfolio/", timeout=20)
    if not response:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    # TDR page exposes company name, description and sector in card-like structures.
    for node in soup.find_all(["article", "li", "div"]):
        text = clean_text(node.get_text(" ", strip=True))
        if len(text) < 10 or len(text) > 500:
            continue
        heading = node.find(["h2", "h3", "h4", "h5"])
        if not heading:
            continue
        name = clean_text(heading.get_text(" ", strip=True))
        if not (2 <= len(name) <= 80):
            continue
        sector = ""
        for candidate in ["Business Services", "Financial Services", "Retail", "Education", "Leisure", "Consumer Services", "Healthcare", "Technology"]:
            if candidate.lower() in text.lower():
                sector = candidate
                break
        href = ""
        a = node.find("a", href=True)
        if a:
            href = canonical_url(response.url, a.get("href"))
        rows.append({"Company": name, "Sector": sector, "Region": "Europe", "Status": "", "Fund": "", "Source": href or response.url})
    rows = normalize_portfolio(rows)
    if len(rows) < 8:
        # Known public page also renders a simple name/description list; use h-tags fallback.
        rows = scrape_generic_portfolio(response.url, "tdr")
    return rows


@st.cache_data(ttl=21600, show_spinner=False)
def get_eqt_portfolio():
    response = safe_get("https://eqtgroup.com/about/current-portfolio", timeout=22)
    if not response:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    # Tables are ideal if server-rendered.
    for table in soup.find_all("table"):
        headers = [clean_text(th.get_text(" ", strip=True)) for th in table.find_all("th")]
        for tr in table.find_all("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
            if len(cells) >= 2:
                mapping = dict(zip(headers, cells)) if headers else {}
                rows.append({
                    "Company": mapping.get("Company") or cells[0],
                    "Sector": mapping.get("Sector") or (cells[1] if len(cells) > 1 else ""),
                    "Region": mapping.get("Market") or mapping.get("Country") or (cells[3] if len(cells) > 3 else ""),
                    "Status": "Current",
                    "Fund": mapping.get("Fund") or (cells[2] if len(cells) > 2 else ""),
                    "Source": response.url,
                })
    if len(rows) < 10:
        rows = scrape_generic_portfolio(response.url, "eqt")
    return normalize_portfolio(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def scrape_generic_portfolio(url, firm_key=""):
    response = safe_get(url, timeout=22)
    if not response:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    reject = {
        "portfolio", "investments", "our portfolio", "our investments", "read more", "learn more",
        "view all", "contact", "about", "home", "news", "team", "people", "careers", "filter",
        "private equity", "credit", "infrastructure", "real estate", "consumer", "healthcare",
        "technology", "services", "financial services", "business services", "all",
    }
    link_hints = ["portfolio", "investment", "company", "partnership", "case-study", "our-portfolio"]
    for a in soup.find_all("a", href=True):
        name = clean_text(a.get_text(" ", strip=True))
        href = canonical_url(response.url, a.get("href"))
        if not (2 <= len(name) <= 90) or name.lower() in reject:
            continue
        href_l = href.lower()
        parent_text = clean_text((a.find_parent(["article", "li", "div"]) or a).get_text(" ", strip=True))
        likely = any(h in href_l for h in link_hints)
        # Some portfolio grids link directly to external company websites; then require card-like context.
        if not likely and not any(k in parent_text.lower() for k in ["portfolio", "sector", "investment", "current", "realised", "active"]):
            continue
        sector = ""
        for candidate in [
            "Technology", "Software", "Services", "Business Services", "Financial Services", "Healthcare",
            "Consumer", "Consumer/Retail", "Industrials", "Manufacturing", "Education", "Energy", "Infrastructure",
            "FinTech", "Retail", "Leisure", "TMT",
        ]:
            if candidate.lower() in parent_text.lower():
                sector = candidate
                break
        rows.append({"Company": name, "Sector": sector, "Region": "", "Status": "", "Fund": "", "Source": href or response.url})
    rows = normalize_portfolio(rows)
    # Generic parsing is conservative. Avoid presenting a noisy list as exhaustive.
    return rows[:600]


@st.cache_data(ttl=21600, show_spinner=False)
def get_public_portfolio(firm_key):
    config = FIRM_CONFIGS[firm_key]
    mode = config.get("portfolio_mode", "generic")
    try:
        if mode == "kkr":
            return get_kkr_portfolio(), "Live official directory"
        if mode == "cvc":
            return get_cvc_portfolio(), "Live official directory"
        if mode == "apax":
            return get_apax_portfolio(), "Live official directory"
        if mode == "permira":
            return get_permira_portfolio(), "Live official directory"
        if mode == "tdr":
            return get_tdr_portfolio(), "Live official directory"
        if mode == "eqt":
            return get_eqt_portfolio(), "Live official directory"
        rows = []
        for url in config.get("portfolio_urls", []):
            rows.extend(scrape_generic_portfolio(url, firm_key))
        return normalize_portfolio(rows), "Live official-page extraction"
    except Exception:
        return [], "Source unavailable"


# -----------------------------------------------------------------------------
# LEADERSHIP SOURCES
# -----------------------------------------------------------------------------
def plausible_person_name(text):
    text = clean_text(text)
    if not (4 <= len(text) <= 70):
        return False
    if any(ch.isdigit() for ch in text):
        return False
    low = text.lower()
    blacklist = ["read more", "view profile", "our people", "meet our", "leadership", "team", "contact", "careers", "filter", "search", "investment", "portfolio"]
    if any(b == low or low.startswith(b + " ") for b in blacklist):
        return False
    words = text.split()
    return 2 <= len(words) <= 6 and sum(w[:1].isupper() for w in words) >= 2


def plausible_role(text):
    low = clean_text(text).lower()
    role_terms = [
        "partner", "director", "principal", "associate", "analyst", "manager", "chief", "president", "chair",
        "counsel", "officer", "head of", "vice president", "advisor", "executive", "founder", "co-ceo", "ceo",
        "cio", "cto", "cfo", "coo", "investment", "operations", "technology", "data", "digital",
    ]
    return any(term in low for term in role_terms) and len(low) <= 110


@st.cache_data(ttl=21600, show_spinner=False)
def scrape_people_directory(url, limit=900):
    response = safe_get(url, timeout=24)
    if not response:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    # Strategy 1: card containers with heading + role-like text.
    containers = soup.find_all(["article", "li", "div"])
    for node in containers:
        heading = node.find(["h2", "h3", "h4", "h5", "h6"])
        if not heading:
            continue
        name = clean_text(heading.get_text(" ", strip=True))
        if not plausible_person_name(name):
            continue
        full = clean_text(node.get_text(" ", strip=True))
        if len(full) > 1000:
            continue
        role = ""
        # Try nearby structured elements first.
        for tag in node.find_all(["p", "span", "div", "strong"], limit=12):
            candidate = clean_text(tag.get_text(" ", strip=True))
            candidate = candidate.replace(name, "").strip(" ,-|")
            if plausible_role(candidate):
                role = candidate
                break
        a = node.find("a", href=True)
        profile = canonical_url(response.url, a.get("href")) if a else ""
        bio = full
        if name and bio.lower().startswith(name.lower()):
            bio = bio[len(name):].strip(" ,-|")
        rows.append({"Name": name, "Role": role, "Location": "", "Bio": bio[:700], "Profile URL": profile, "Source": "Official website"})
        if len(rows) >= limit:
            break

    # Strategy 2: links to person/profile pages when cards are not server-rendered cleanly.
    if len(rows) < 8:
        for a in soup.find_all("a", href=True):
            name = clean_text(a.get_text(" ", strip=True))
            href = canonical_url(response.url, a.get("href"))
            if not plausible_person_name(name):
                continue
            if not any(part in href.lower() for part in ["people", "team", "profile", "our-team", "leadership"]):
                continue
            parent = a.find_parent(["article", "li", "div"])
            full = clean_text(parent.get_text(" ", strip=True)) if parent else ""
            role = ""
            after = full.replace(name, "", 1).strip(" ,-|")
            # Take the beginning if it looks like a role.
            for candidate in re.split(r"[|•\n]", after):
                if plausible_role(candidate):
                    role = clean_text(candidate)[:110]
                    break
            rows.append({"Name": name, "Role": role, "Location": "", "Bio": after[:700], "Profile URL": href, "Source": "Official website"})
            if len(rows) >= limit:
                break
    return normalize_leadership(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def discover_directory_pages(url, max_pages=80):
    response = safe_get(url, timeout=20)
    if not response:
        return [url]
    soup = BeautifulSoup(response.text, "html.parser")
    pages = [response.url]
    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True)).lower()
        href = canonical_url(response.url, a.get("href"))
        if not same_domain(response.url, href):
            continue
        is_page_label = text.isdigit() or text in {"next", "next ›", "›", ">", "older"}
        is_page_url = bool(re.search(r"(?:[?&](?:page|paged)=\d+|/page/\d+/?$)", href, re.I))
        if (is_page_label or is_page_url) and href not in pages:
            pages.append(href)
        if len(pages) >= max_pages:
            break
    # Numeric pages are often partially hidden (1 2 3 ... 63). If a query-based page pattern
    # is discoverable, generate the missing range conservatively.
    numeric = []
    pattern_prefix = None
    pattern_suffix = None
    for href in pages:
        m = re.search(r"^(.*?[?&](?:page|paged)=)(\d+)(.*)$", href, re.I)
        if m:
            pattern_prefix, pattern_suffix = m.group(1), m.group(3)
            numeric.append(int(m.group(2)))
    if numeric and max(numeric) > 2 and pattern_prefix:
        ceiling = min(max(numeric), max_pages)
        for n in range(1, ceiling + 1):
            candidate = f"{pattern_prefix}{n}{pattern_suffix}"
            if candidate not in pages:
                pages.append(candidate)
    return pages[:max_pages]


@st.cache_data(ttl=21600, show_spinner=False)
def get_public_leadership(firm_key, full=False):
    config = FIRM_CONFIGS[firm_key]
    rows = []
    for url in config.get("people_urls", []):
        urls = discover_directory_pages(url) if full else [url]
        for page_url in urls:
            rows.extend(scrape_people_directory(page_url))
    return normalize_leadership(rows)


@st.cache_data(ttl=86400, show_spinner=False)
def get_profile_bio(profile_url):
    if not profile_url:
        return None
    response = safe_get(profile_url, timeout=18)
    if not response:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    title = clean_text((soup.find("h1") or soup.find("h2") or {}).get_text(" ", strip=True) if (soup.find("h1") or soup.find("h2")) else "")
    main = soup.find("main") or soup.body
    paragraphs = []
    if main:
        for p in main.find_all("p"):
            text = clean_text(p.get_text(" ", strip=True))
            if 45 <= len(text) <= 1800:
                paragraphs.append(text)
    bio = " ".join(paragraphs[:4])[:1800]
    return {"title": title, "bio": bio, "url": response.url} if bio else None


def leader_relevance(role):
    role_l = clean_text(role).lower()
    for score, terms in LEADER_RELEVANCE:
        if any(term in role_l for term in terms):
            return score
    return 1


def leader_reason(role):
    r = clean_text(role).lower()
    if any(x in r for x in ["technology", "cio", "cto", "digital", "data", "ai", "cyber"]):
        return "Direct technology / data / AI buying influence"
    if any(x in r for x in ["operating partner", "portfolio", "value creation", "operational excellence"]):
        return "Potential sponsor for repeatable portfolio-wide transformation"
    if any(x in r for x in ["chief executive", "ceo", "managing partner", "chief investment"]):
        return "Senior strategic sponsor / account relationship"
    if "partner" in r or "managing director" in r:
        return "Potential investment or sector sponsor; validate remit"
    return "Contextual stakeholder; relevance depends on remit"


# -----------------------------------------------------------------------------
# CAREERS / JOBS
# -----------------------------------------------------------------------------
def looks_like_job_title(text):
    t = clean_text(text)
    low = t.lower()
    if not (4 <= len(t) <= 120):
        return False
    noise = ["careers", "career", "join our team", "view jobs", "open positions", "opportunities", "apply", "learn more", "read more", "internships", "students"]
    if low in noise:
        return False
    job_words = [
        "engineer", "architect", "developer", "analyst", "associate", "manager", "director", "principal", "partner",
        "officer", "counsel", "specialist", "lead", "head of", "vice president", "administrator", "controller",
        "operations", "technology", "data", "product", "risk", "security", "finance", "marketing", "hr ", "human resources",
    ]
    return any(word in low for word in job_words)


@st.cache_data(ttl=7200, show_spinner=False)
def scrape_jobs_page(url, limit=100):
    response = safe_get(url, timeout=20)
    if not response:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    jobs = []
    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" ", strip=True))
        href = canonical_url(response.url, a.get("href"))
        if not looks_like_job_title(title):
            continue
        hay = f"{href} {title}".lower()
        if not any(k in hay for k in ["job", "career", "position", "vacan", "workday", "greenhouse", "lever", "apply"]):
            continue
        parent = a.find_parent(["article", "li", "div"])
        context = clean_text(parent.get_text(" ", strip=True)) if parent else ""
        location = ""
        # A very small heuristic for common city/location patterns.
        m = re.search(r"(?:Location|Office)[:\s]+([^|•]{2,70})", context, re.I)
        if m:
            location = clean_text(m.group(1))
        jobs.append({"title": title, "location": location, "description": context[:900], "url": href, "source": "Official careers"})
        if len(jobs) >= limit:
            break
    return normalize_jobs(jobs)


@st.cache_data(ttl=7200, show_spinner=False)
def get_public_jobs(firm_key):
    rows = []
    for url in FIRM_CONFIGS[firm_key].get("careers_urls", []):
        rows.extend(scrape_jobs_page(url))
    return normalize_jobs(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def enrich_job_description(url):
    if not url:
        return ""
    response = safe_get(url, timeout=16)
    if not response:
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    main = soup.find("main") or soup.body
    if not main:
        return ""
    texts = []
    for tag in main.find_all(["p", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if 20 <= len(txt) <= 1000:
            texts.append(txt)
    return " ".join(texts[:30])[:7000]


def job_relevance(title, description=""):
    hay = f" {clean_text(title).lower()} {clean_text(description).lower()} "
    for score in sorted(JOB_RELEVANCE_TERMS, reverse=True):
        if any(term in hay for term in JOB_RELEVANCE_TERMS[score]):
            return score
    return 1


def extract_skills(text):
    hay = f" {clean_text(text).lower()} "
    hits = []
    for skill, terms in SKILL_TAXONOMY.items():
        count = sum(hay.count(term.lower()) for term in terms)
        if count:
            hits.append((skill, count))
    return [name for name, _ in sorted(hits, key=lambda x: x[1], reverse=True)]


def skills_relevant_to_coforge(job):
    skills = extract_skills(f"{job.get('title','')} {job.get('description','')}")
    return skills[:8]


# -----------------------------------------------------------------------------
# SIGNAL ENGINE
# -----------------------------------------------------------------------------
def corpus_from(jobs, insights):
    chunks = []
    for job in jobs or []:
        chunks.extend([job.get("title", ""), job.get("description", ""), job.get("location", "")])
    for article in insights or []:
        chunks.extend([article.get("title", ""), article.get("summary", "")])
    return f" {' '.join(clean_text(x) for x in chunks).lower()} "


def detect_technology_signals(jobs, insights):
    text = corpus_from(jobs, insights)
    rows = []
    for tech, keywords in TECH_KEYWORDS.items():
        count = sum(text.count(keyword.lower()) for keyword in keywords)
        if count:
            job_hits = sum(1 for job in jobs or [] if any(k.lower() in f" {job.get('title','')} {job.get('description','')} ".lower() for k in keywords))
            news_hits = sum(1 for a in insights or [] if any(k.lower() in f" {a.get('title','')} {a.get('summary','')} ".lower() for k in keywords))
            rows.append({"Technology": tech, "Mentions": count, "Job Evidence": job_hits, "News Evidence": news_hits})
    return sorted(rows, key=lambda x: (x["Mentions"], x["Job Evidence"]), reverse=True)


def tech_evidence(tech, jobs, insights, max_items=8):
    keywords = [x.strip() for x in TECH_KEYWORDS.get(tech, []) if x.strip()]
    matches = []
    for job in jobs or []:
        hay = f"{job.get('title','')} {job.get('description','')}".lower()
        if any(k.lower() in hay for k in keywords):
            matches.append({"type": "Job", "title": job.get("title", ""), "copy": job.get("description", "")[:420], "url": job.get("url", "")})
    for article in insights or []:
        hay = f"{article.get('title','')} {article.get('summary','')}".lower()
        if any(k.lower() in hay for k in keywords):
            matches.append({"type": article.get("source", "News"), "title": article.get("title", ""), "copy": article.get("summary", "")[:420], "url": article.get("link", "")})
    return matches[:max_items]


def growth_signal_count(insights):
    terms = ["acquisition", "acquire", "fund", "raise", "investment", "portfolio", "partnership", "ai", "digital", "technology", "growth", "expansion", "appoint"]
    text = corpus_from([], insights)
    return sum(text.count(term) for term in terms)


def compute_data_confidence(portfolio, jobs, insights, leadership):
    components = {
        "Portfolio": min(100, 20 + len(portfolio) * 2) if portfolio else 0,
        "Hiring": min(100, 20 + len(jobs) * 8) if jobs else 0,
        "News": min(100, 20 + len(insights) * 5) if insights else 0,
        "Leadership": min(100, 20 + len(leadership) * 3) if leadership else 0,
    }
    overall = int(round(sum(components.values()) / len(components)))
    return overall, components


def ai_signal_count(tech_rows, jobs, insights):
    tech = next((r for r in tech_rows if r["Technology"] == "AI / GenAI"), None)
    score = (tech or {}).get("Mentions", 0)
    score += sum(1 for job in jobs if job_relevance(job.get("title", ""), job.get("description", "")) >= 4)
    score += sum(1 for article in insights if article.get("signal_type") == "AI & Technology")
    return score


def compute_opportunity_score(portfolio, jobs, insights, tech_rows, leadership):
    # This is a prioritisation heuristic, not a revenue forecast.
    ai_intensity = min(35, ai_signal_count(tech_rows, jobs, insights) * 3)
    hiring = min(20, sum(1 for j in jobs if job_relevance(j.get("title", ""), j.get("description", "")) >= 3) * 3)
    growth = min(15, growth_signal_count(insights))
    leadership_fit = min(15, sum(1 for p in leadership if p.get("Coforge Relevance", 1) >= 4) * 2)
    portfolio_scale = min(15, len(portfolio) / 8) if portfolio else 0
    # Give a modest baseline so a thin public dataset is "unqualified", not a zero-quality account.
    return int(round(min(100, 10 + ai_intensity + hiring + growth + leadership_fit + portfolio_scale)))


def score_band(score):
    if score >= 75:
        return "High priority", "Multiple evidence layers point to a credible near-term AI/data conversation"
    if score >= 55:
        return "Developing", "Promising signals; qualify them with named stakeholders and live programmes"
    if score >= 35:
        return "Watchlist", "Some relevant evidence exists but the commercial thesis is still thin"
    return "Unqualified", "Public evidence is currently insufficient for a strong account thesis"


def build_why_now(jobs, insights, tech_rows, limit=6):
    signals = []
    for row in tech_rows[:5]:
        if row["Technology"] == "AI / GenAI" or row["Mentions"] >= 2:
            signals.append({
                "Signal": row["Technology"],
                "Evidence": f"{row['Mentions']} mentions across {row['Job Evidence']} job(s) and {row['News Evidence']} news/insight item(s)",
                "Type": "Technology",
                "Strength": min(5, 1 + row["Mentions"]),
            })
    relevant_jobs = [j for j in jobs if job_relevance(j.get("title", ""), j.get("description", "")) >= 4]
    if relevant_jobs:
        signals.append({
            "Signal": "Technology hiring",
            "Evidence": f"{len(relevant_jobs)} highly Coforge-relevant role(s) detected",
            "Type": "Hiring",
            "Strength": min(5, 2 + len(relevant_jobs) // 2),
        })
    ai_news = [a for a in insights if a.get("signal_type") == "AI & Technology"]
    if ai_news:
        signals.append({
            "Signal": "AI / technology activity",
            "Evidence": f"{len(ai_news)} recent technology-related news/insight item(s)",
            "Type": "News",
            "Strength": min(5, 2 + len(ai_news) // 2),
        })
    deal_news = [a for a in insights if a.get("signal_type") in {"M&A / Deal", "Portfolio", "Growth"}]
    if deal_news:
        signals.append({
            "Signal": "Portfolio change / growth",
            "Evidence": f"{len(deal_news)} transaction, portfolio or growth signal(s) can create integration / value-creation triggers",
            "Type": "Growth",
            "Strength": min(5, 2 + len(deal_news) // 3),
        })
    unique = {}
    for s in signals:
        unique[s["Signal"]] = s
    return sorted(unique.values(), key=lambda x: x["Strength"], reverse=True)[:limit]


def map_ai_opportunities(capabilities, tech_rows, jobs, insights, portfolio, leadership):
    corpus = corpus_from(jobs, insights)
    rows = []
    for capability in capabilities:
        name = clean_text(capability.get("Capability") or capability.get("name") or "AI capability")
        description = clean_text(capability.get("Description") or capability.get("description"))
        keywords = capability.get("Signal Keywords") or capability.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [x.strip() for x in re.split(r"[,;]", keywords) if x.strip()]
        hits = sum(corpus.count(clean_text(k).lower()) for k in keywords if clean_text(k))
        evidence = []
        if hits:
            evidence.append(f"{hits} keyword mention(s)")
        relevant_jobs = [j for j in jobs if any(clean_text(k).lower() in f"{j.get('title','')} {j.get('description','')}".lower() for k in keywords if clean_text(k))]
        if relevant_jobs:
            evidence.append(f"{len(relevant_jobs)} matching job(s)")
        matching_news = [a for a in insights if any(clean_text(k).lower() in f"{a.get('title','')} {a.get('summary','')}".lower() for k in keywords if clean_text(k))]
        if matching_news:
            evidence.append(f"{len(matching_news)} matching news/insight item(s)")
        strength = min(5, 1 + hits // 2 + (1 if relevant_jobs else 0) + (1 if matching_news else 0))
        if strength >= 2 or name.lower().startswith("ai"):
            rows.append({
                "Coforge Capability": name,
                "Opportunity": description or "Validate a targeted AI transformation use case with the account.",
                "Evidence": " · ".join(evidence) if evidence else "Baseline AI conversation; direct evidence still limited",
                "Evidence Strength": strength,
                "Recommended Buyer": recommended_buyer_for_capability(name, leadership),
            })
    # Add a portfolio-scale AI angle when there is meaningful company breadth.
    if len(portfolio) >= 20:
        rows.append({
            "Coforge Capability": "Portfolio-wide AI value creation",
            "Opportunity": "Test a repeatable AI / automation play that can be deployed across multiple portfolio companies rather than as a single-point engagement.",
            "Evidence": f"{len(portfolio)} portfolio/investment records captured",
            "Evidence Strength": 4 if len(portfolio) >= 50 else 3,
            "Recommended Buyer": recommended_buyer_for_capability("portfolio operations value creation", leadership),
        })
    return sorted(rows, key=lambda x: x["Evidence Strength"], reverse=True)


def recommended_buyer_for_capability(capability_name, leadership):
    target_terms = ["data", "ai", "technology", "digital", "operating", "portfolio", "value creation", "chief information", "chief technology"]
    if "portfolio" not in capability_name.lower():
        target_terms = ["data", "ai", "technology", "digital", "chief information", "chief technology", "operating"]
    matches = [p for p in leadership if any(term in p.get("Role", "").lower() for term in target_terms)]
    matches = sorted(matches, key=lambda x: x.get("Coforge Relevance", 1), reverse=True)
    return f"{matches[0]['Name']} — {matches[0]['Role']}" if matches else "CIO / CTO / Data & AI / Portfolio Operations leader"


def source_coverage(portfolio, jobs, insights, leadership, portfolio_mode, jobs_mode, leadership_mode):
    return [
        {"Layer": "Portfolio", "Records": len(portfolio), "Mode": portfolio_mode, "Ready": bool(portfolio)},
        {"Layer": "Hiring", "Records": len(jobs), "Mode": jobs_mode, "Ready": bool(jobs)},
        {"Layer": "News & insights", "Records": len(insights), "Mode": "Live + local", "Ready": bool(insights)},
        {"Layer": "Leadership", "Records": len(leadership), "Mode": leadership_mode, "Ready": bool(leadership)},
    ]


# -----------------------------------------------------------------------------
# AI ANALYST
# -----------------------------------------------------------------------------
def capability_text(capabilities):
    lines = []
    for cap in capabilities:
        lines.append(f"- {cap.get('Capability','')}: {cap.get('Description','')}")
    return "\n".join(lines)


def build_ai_context(firm_name, bio, jobs, insights, portfolio, tech_rows, opportunities, leadership, why_now, capabilities):
    port = "\n".join(f"- {x.get('Company','')} | {x.get('Sector','')} | {x.get('Region','')} | {x.get('Status','')}" for x in portfolio[:60]) or "- No company-level portfolio records loaded"
    job = "\n".join(f"- {x.get('title','')} | {x.get('location','')} | skills: {', '.join(skills_relevant_to_coforge(x))}" for x in jobs[:30]) or "- No job records loaded"
    news = "\n".join(f"- [{x.get('signal_type','')}] {x.get('title','')}: {x.get('summary','')[:250]}" for x in insights[:20]) or "- No news/insights loaded"
    tech = "\n".join(f"- {x['Technology']}: {x['Mentions']} mentions ({x['Job Evidence']} jobs, {x['News Evidence']} news)" for x in tech_rows[:15]) or "- No tech signals detected"
    leaders = "\n".join(f"- {x.get('Name','')} | {x.get('Role','')} | relevance {x.get('Coforge Relevance',1)}/5" for x in leadership[:35]) or "- No leadership directory loaded"
    opps = "\n".join(f"- {x['Coforge Capability']}: {x['Opportunity']} | evidence {x['Evidence']}" for x in opportunities[:12]) or "- No mapped opportunities"
    now = "\n".join(f"- {x['Signal']}: {x['Evidence']}" for x in why_now) or "- No strong why-now signals"
    return f"""
FIRM: {firm_name}
BIO: {bio or 'Unavailable'}

PORTFOLIO / INVESTMENTS:
{port}

LEADERSHIP:
{leaders}

HIRING:
{job}

NEWS / INSIGHTS:
{news}

TECH SIGNALS:
{tech}

WHY NOW:
{now}

CURRENT OPPORTUNITY MAPPING:
{opps}

COFORGE CAPABILITIES CURRENTLY LOADED:
{capability_text(capabilities)}
"""


def fallback_answer(question, firm_name, score, tech_rows, opportunities, jobs, insights, portfolio, leadership, why_now):
    band, _ = score_band(score)
    top_tech = ", ".join(x["Technology"] for x in tech_rows[:5]) or "no material technology signals detected"
    lines = [
        f"### {firm_name} — evidence-based account analysis",
        f"**Priority score:** {score}/100 · {band}",
        "",
        f"**Question:** {question}",
        "",
        "#### Executive view",
        f"The platform currently has **{len(portfolio)} portfolio/investment records**, **{len(leadership)} leadership records**, **{len(jobs)} jobs** and **{len(insights)} news/insight items**. Strongest detected technology themes: **{top_tech}**.",
        "",
        "#### Why now",
    ]
    if why_now:
        lines.extend(f"- **{x['Signal']}** — {x['Evidence']}" for x in why_now[:5])
    else:
        lines.append("- No sufficiently strong near-term trigger is proven yet; enrich the account before treating it as qualified.")
    lines += ["", "#### Best Coforge AI angles"]
    if opportunities:
        for row in opportunities[:5]:
            lines.append(f"- **{row['Coforge Capability']}** — {row['Opportunity']} Evidence: {row['Evidence']}. Suggested buyer: {row['Recommended Buyer']}.")
    else:
        lines.append("- Evidence is currently too thin to map a confident AI opportunity.")
    lines += [
        "",
        "#### Recommended next actions",
        "- Validate the top signal with an official source or named stakeholder before outreach.",
        "- Prioritise technology/data/AI and portfolio-operations leaders with the strongest Coforge relevance.",
        "- Use job descriptions to turn broad technology themes into specific capability gaps and conversation starters.",
        "",
        "_Generated by the deterministic signal engine because a local Ollama model was not available or did not respond._",
    ]
    return "\n".join(lines)


def run_ai_analysis(question, firm_name, context, model_name, score, tech_rows, opportunities, jobs, insights, portfolio, leadership, why_now):
    if ollama is not None:
        system_prompt = f"""
You are a senior private-equity account intelligence analyst working for Coforge.
Use only the evidence supplied below. Never invent people, jobs, portfolio companies, technologies or initiatives.
Separate observed evidence from inference. Treat public website extraction as potentially incomplete.
The currently loaded Coforge capability set is AI-focused, so do not invent unrelated Coforge offerings.

Return these sections:
1. Executive answer
2. Why now / buying signals
3. Technology and hiring evidence
4. Stakeholders to approach, with reason
5. Coforge AI opportunities ranked High / Medium / Low confidence
6. Next best actions

Maximum 1,100 words.

EVIDENCE:
{context}
"""
        try:
            response = ollama.chat(
                model=model_name,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": question}],
                options={"num_predict": 2600, "temperature": 0.12},
            )
            return response["message"]["content"], "Ollama"
        except Exception:
            pass
    return fallback_answer(question, firm_name, score, tech_rows, opportunities, jobs, insights, portfolio, leadership, why_now), "Signal engine"


def make_account_brief_markdown(firm, bio, score, band, portfolio, leadership, jobs, insights, tech_rows, why_now, opportunities, coverage):
    lines = [
        f"# {firm['name']} — Coforge PE Intelligence Brief",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Priority score: **{score}/100 — {band}**",
        "",
        "## Company snapshot",
        bio or "Company bio unavailable.",
        "",
        "## Data coverage",
    ]
    for row in coverage:
        lines.append(f"- {row['Layer']}: {row['Records']} records — {row['Mode']}")
    lines += ["", "## Why now"]
    if why_now:
        lines.extend(f"- **{x['Signal']}** — {x['Evidence']}" for x in why_now)
    else:
        lines.append("- No strong near-term trigger proven yet.")
    lines += ["", "## Technology signals"]
    lines.extend(f"- {x['Technology']}: {x['Mentions']} mentions; {x['Job Evidence']} job evidence; {x['News Evidence']} news evidence" for x in tech_rows[:12]) or lines.append("- None detected")
    lines += ["", "## Priority leadership"]
    for p in sorted(leadership, key=lambda x: x.get("Coforge Relevance", 1), reverse=True)[:15]:
        lines.append(f"- {p['Name']} — {p.get('Role','')} — Coforge relevance {p.get('Coforge Relevance',1)}/5")
    lines += ["", "## Relevant hiring"]
    for j in sorted(jobs, key=lambda x: job_relevance(x.get('title',''), x.get('description','')), reverse=True)[:15]:
        lines.append(f"- {j['title']} — {j.get('location','')} — {', '.join(skills_relevant_to_coforge(j)) or 'No mapped skills'}")
    lines += ["", "## Coforge AI opportunity mapping"]
    for o in opportunities[:10]:
        lines.append(f"- **{o['Coforge Capability']}** — {o['Opportunity']} — Evidence {o['Evidence']} — Buyer: {o['Recommended Buyer']}")
    lines += ["", "## Latest intelligence"]
    for a in insights[:12]:
        lines.append(f"- [{a.get('signal_type','Other')}] {a.get('title','')} — {a.get('published','')} — {a.get('link','')}")
    lines += ["", "## Portfolio scope note", firm.get("portfolio_scope", "")]
    return "\n".join(lines)


def opportunity_score_breakdown(portfolio, jobs, insights, tech_rows, leadership):
    ai_intensity = min(35, ai_signal_count(tech_rows, jobs, insights) * 3)
    hiring = min(20, sum(1 for j in jobs if job_relevance(j.get("title", ""), j.get("description", "")) >= 3) * 3)
    growth = min(15, growth_signal_count(insights))
    leadership_fit = min(15, sum(1 for p in leadership if p.get("Coforge Relevance", 1) >= 4) * 2)
    portfolio_scale = min(15, len(portfolio) / 8) if portfolio else 0
    return {
        "Baseline": 10,
        "AI / technology evidence": round(ai_intensity, 1),
        "Relevant hiring": round(hiring, 1),
        "Growth / transaction triggers": round(growth, 1),
        "Priority stakeholder coverage": round(leadership_fit, 1),
        "Portfolio scale": round(portfolio_scale, 1),
    }
