"""Generic public-web intelligence for PE portfolio companies.

This module intentionally keeps operating-company discovery separate from the
configured PE-firm adapters in pe_core.py. All network failures degrade to
empty results so a blocked public site never crashes the Streamlit workspace.
"""

import json
import os
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

from pe_core import (
    get_official_news_cards,
    normalize_insights,
    normalize_jobs,
    normalize_leadership,
    normalize_portfolio,
)


def is_http_url(value):
    try:
        return urlparse(str(value or "")).scheme in {"http", "https"}
    except Exception:
        return False


WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CoforgePEIntelligence/3.0; +public-web-research)",
    "Accept-Language": "en-GB,en;q=0.9",
}

ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com",
    "workdayjobs.com", "myworkdayjobs.com", "workable.com", "teamtailor.com",
)

LOW_VALUE_DOMAINS = (
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com",
    "wikipedia.org", "crunchbase.com", "bloomberg.com", "reuters.com", "ft.com", "wsj.com",
    "pitchbook.com", "glassdoor.", "indeed.", "zoominfo.com", "companieshouse.gov.uk",
)

PRIORITY_NEWS_SOURCES = (
    "reuters", "bloomberg", "financial times", "ft.com", "wall street journal", "wsj",
    "bbc", "cnbc", "forbes", "techcrunch", "the guardian", "business insider",
    "computer weekly", "the register", "businesswire", "pr newswire",
)


def entity_slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "account"


def hostname(url):
    try:
        return urlparse(str(url or "")).netloc.lower().split(":")[0].removeprefix("www.")
    except Exception:
        return ""


def root_url(url):
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}/"
    except Exception:
        pass
    return ""


def compact_text(value, limit=1200):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_public_html(url, timeout=10):
    if not requests or not BeautifulSoup or not is_http_url(url):
        return "", ""
    try:
        r = requests.get(url, headers=WEB_HEADERS, timeout=timeout, allow_redirects=True)
        content_type = r.headers.get("content-type", "")
        if r.status_code >= 400 or "text/html" not in content_type:
            return "", r.url
        return r.text[:2_500_000], r.url
    except Exception:
        return "", ""


def extract_ddg_target(href):
    href = str(href or "")
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlparse(href)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return unquote(target)
    except Exception:
        pass
    return href


@st.cache_data(ttl=43200, show_spinner=False)
def public_web_search(query, limit=10):
    """Small no-key discovery helper. Failure never blocks the rest of the app."""
    if not requests or not BeautifulSoup:
        return []
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=WEB_HEADERS,
            timeout=10,
        )
        if r.status_code >= 400:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for result in soup.select(".result"):
            a = result.select_one("a.result__a")
            if not a:
                continue
            url = extract_ddg_target(a.get("href"))
            if not is_http_url(url):
                continue
            snippet_el = result.select_one(".result__snippet")
            out.append({
                "title": compact_text(a.get_text(" ", strip=True), 220),
                "url": url,
                "snippet": compact_text(snippet_el.get_text(" ", strip=True) if snippet_el else "", 500),
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def company_name_tokens(name):
    stop = {"the", "group", "holdings", "holding", "limited", "ltd", "plc", "inc", "corp", "corporation", "company", "co", "llc"}
    return [x for x in re.findall(r"[a-z0-9]+", str(name or "").lower()) if len(x) > 2 and x not in stop]


def portfolio_row_website(row, parent_firm):
    for key in ["Website", "website", "Company Website", "Company URL", "URL", "Homepage", "Domain"]:
        value = str((row or {}).get(key) or "").strip()
        if value and not value.startswith("http") and "." in value and " " not in value:
            value = "https://" + value
        if is_http_url(value) and hostname(value) != hostname(parent_firm.get("website")):
            return root_url(value)
    source = str((row or {}).get("Source") or "").strip()
    source_host = hostname(source)
    if is_http_url(source) and source_host != hostname(parent_firm.get("website")) and not any(x in source_host for x in LOW_VALUE_DOMAINS):
        return root_url(source)
    return ""


@st.cache_data(ttl=43200, show_spinner=False)
def discover_official_website(company_name, row_website="", parent_domain=""):
    if is_http_url(row_website):
        return root_url(row_website), "Portfolio record"
    tokens = company_name_tokens(company_name)
    results = public_web_search(f'"{company_name}" official website', limit=10)
    ranked = []
    for item in results:
        url = item.get("url", "")
        host = hostname(url)
        if not host or host == parent_domain or any(x in host for x in LOW_VALUE_DOMAINS):
            continue
        hay = f"{item.get('title','')} {item.get('snippet','')} {host}".lower()
        token_hits = sum(1 for t in tokens if t in hay)
        score = token_hits * 5
        if "official" in hay:
            score += 3
        if tokens and any(t in host.replace("-", "") for t in tokens):
            score += 4
        ranked.append((score, url))
    for score, url in sorted(ranked, reverse=True):
        if score <= 0:
            continue
        html, final_url = fetch_public_html(url)
        if html:
            return root_url(final_url or url), "Public web discovery"
    return "", "Not resolved"


def links_matching(html, base_url, keywords, max_links=12):
    if not html or not BeautifulSoup:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href"))
        text = compact_text(a.get_text(" ", strip=True), 160)
        hay = f"{href} {text}".lower()
        if any(k in hay for k in keywords) and is_http_url(href):
            if href not in out:
                out.append(href)
        if len(out) >= max_links:
            break
    return out


@st.cache_data(ttl=21600, show_spinner=False)
def discover_company_pages(website):
    if not website:
        return {"careers": [], "people": [], "news": [], "about": []}
    html, final = fetch_public_html(website)
    base = final or website
    careers = links_matching(html, base, ["career", "jobs", "vacanc", "join-us", "join us", "work-with-us", "work with us"], 15)
    people = links_matching(html, base, ["leadership", "management", "executive", "our-team", "our team", "/team", "/people", "board of directors"], 12)
    news = links_matching(html, base, ["news", "press", "media", "insight", "stories", "updates"], 12)
    about = links_matching(html, base, ["about-us", "about us", "/about", "who-we-are", "who we are", "company"], 8)
    # Common routes improve recall when the homepage navigation is JS-rendered.
    for path in ["careers", "jobs", "careers/jobs", "join-us", "work-with-us"]:
        candidate = urljoin(base, path)
        if candidate not in careers:
            careers.append(candidate)
    for path in ["leadership", "team", "our-team", "people", "management"]:
        candidate = urljoin(base, path)
        if candidate not in people:
            people.append(candidate)
    for path in ["news", "newsroom", "press", "insights", "media"]:
        candidate = urljoin(base, path)
        if candidate not in news:
            news.append(candidate)
    return {"careers": careers[:18], "people": people[:15], "news": news[:15], "about": about[:10]}


def first_working_page(urls, require_terms=()):
    for url in urls or []:
        html, final = fetch_public_html(url)
        if not html:
            continue
        text = compact_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True) if BeautifulSoup else html, 5000).lower()
        if require_terms and not any(t in text for t in require_terms):
            continue
        return final or url
    return ""


def jsonld_objects(soup):
    items = []
    if not soup:
        return items
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            obj = json.loads(script.string or script.get_text() or "{}")
        except Exception:
            continue
        stack = obj if isinstance(obj, list) else [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                items.append(cur)
                for v in cur.values():
                    if isinstance(v, dict):
                        stack.append(v)
                    elif isinstance(v, list):
                        stack.extend(x for x in v if isinstance(x, (dict, list)))
            elif isinstance(cur, list):
                stack.extend(cur)
    return items


@st.cache_data(ttl=21600, show_spinner=False)
def discover_company_size(website):
    if not website:
        return ""
    pages = discover_company_pages(website)
    urls = [website] + pages.get("about", [])[:3]
    for url in urls:
        html, _ = fetch_public_html(url)
        if not html or not BeautifulSoup:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for obj in jsonld_objects(soup):
            n = obj.get("numberOfEmployees") if isinstance(obj, dict) else None
            if isinstance(n, dict):
                n = n.get("value") or n.get("minValue")
            if n:
                return compact_text(n, 80)
        text = compact_text(soup.get_text(" ", strip=True), 30000)
        m = re.search(r"\b([1-9][\d,.]*\+?)\s+(?:employees|colleagues|people|staff)\b", text, re.I)
        if m:
            return f"{m.group(1)} employees/people (website claim)"
    return ""


def clean_html_text(value):
    if not value:
        return ""
    if BeautifulSoup:
        try:
            return compact_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True), 5000)
        except Exception:
            pass
    return compact_text(re.sub(r"<[^>]+>", " ", str(value)), 5000)


def greenhouse_jobs(url):
    host = hostname(url)
    if "greenhouse.io" not in host:
        return []
    parts = [x for x in urlparse(url).path.split("/") if x]
    if not parts:
        return []
    token = parts[0]
    if token in {"embed", "jobs"} and len(parts) > 1:
        token = parts[1]
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"}, headers=WEB_HEADERS, timeout=10)
        data = r.json() if r.ok else {}
        out = []
        for job in data.get("jobs", []):
            out.append({
                "title": job.get("title", ""),
                "location": (job.get("location") or {}).get("name", ""),
                "description": clean_html_text(job.get("content", "")),
                "url": job.get("absolute_url", ""),
                "source": "Greenhouse",
            })
        return out
    except Exception:
        return []


def lever_jobs(url):
    if "lever.co" not in hostname(url):
        return []
    parts = [x for x in urlparse(url).path.split("/") if x]
    if not parts:
        return []
    token = parts[0]
    out = []
    try:
        for skip in range(0, 2000, 100):
            r = requests.get(
                f"https://api.lever.co/v0/postings/{token}",
                params={"mode": "json", "skip": skip, "limit": 100},
                headers=WEB_HEADERS, timeout=10,
            )
            data = r.json() if r.ok else []
            batch = data if isinstance(data, list) else []
            for job in batch:
                cats = job.get("categories") or {}
                out.append({
                    "title": job.get("text", ""),
                    "location": cats.get("location", ""),
                    "description": clean_html_text(f"{job.get('description','')} {job.get('additional','')}"),
                    "url": job.get("hostedUrl") or job.get("applyUrl") or "",
                    "source": "Lever",
                })
            if len(batch) < 100:
                break
        return out
    except Exception:
        return out

def ashby_jobs(url):
    if "ashbyhq.com" not in hostname(url):
        return []
    parts = [x for x in urlparse(url).path.split("/") if x]
    if not parts:
        return []
    board = parts[0]
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}", headers=WEB_HEADERS, timeout=10)
        data = r.json() if r.ok else {}
        out = []
        for job in data.get("jobs", []):
            out.append({
                "title": job.get("title", ""),
                "location": job.get("location", ""),
                "description": clean_html_text(job.get("descriptionHtml") or job.get("descriptionPlain") or ""),
                "url": job.get("jobUrl") or job.get("applyUrl") or "",
                "source": "Ashby",
            })
        return out
    except Exception:
        return []


def smartrecruiters_jobs(url):
    if "smartrecruiters.com" not in hostname(url):
        return []
    parts = [x for x in urlparse(url).path.split("/") if x]
    token = ""
    if "company" in parts:
        idx = parts.index("company")
        token = parts[idx + 1] if len(parts) > idx + 1 else ""
    elif parts:
        token = parts[-1] if hostname(url).startswith("careers.") else parts[0]
    if not token:
        return []
    out = []
    try:
        offset = 0
        total = None
        while offset < 5000 and (total is None or offset < total):
            r = requests.get(
                f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                params={"limit": 100, "offset": offset}, headers=WEB_HEADERS, timeout=10,
            )
            data = r.json() if r.ok else {}
            batch = data.get("content", []) if isinstance(data, dict) else []
            total = int(data.get("totalFound", len(batch))) if isinstance(data, dict) else len(batch)
            for job in batch:
                loc = job.get("location") or {}
                location = ", ".join(str(loc.get(k)) for k in ["city", "region", "country"] if loc.get(k))
                detail = {}
                job_id = job.get("id") or job.get("uuid")
                if job_id and len(out) < 120:  # enrich a bounded set; list coverage remains complete.
                    try:
                        dr = requests.get(
                            f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{job_id}",
                            headers=WEB_HEADERS, timeout=8,
                        )
                        if dr.ok:
                            detail = dr.json()
                    except Exception:
                        detail = {}
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                description_bits = []
                for section in sections.values() if isinstance(sections, dict) else []:
                    if isinstance(section, dict):
                        description_bits.append(str(section.get("text") or section.get("title") or ""))
                out.append({
                    "title": job.get("name", ""),
                    "location": location,
                    "description": clean_html_text(" ".join(description_bits) or (job.get("department") or {}).get("label", "")),
                    "url": detail.get("applyUrl") or detail.get("jobAd", {}).get("applyUrl") or job.get("ref", ""),
                    "source": "SmartRecruiters",
                })
            if not batch:
                break
            offset += len(batch)
        return out
    except Exception:
        return out


def workday_jobs(url):
    """Best-effort public Workday CXS reader. Workday tenants vary, so failure falls back to the careers link."""
    host = hostname(url)
    if not any(x in host for x in ["workdayjobs.com", "myworkdayjobs.com"]):
        return []
    parsed = urlparse(url)
    parts = [x for x in parsed.path.split("/") if x]
    if not parts:
        return []
    site = next((p for p in reversed(parts) if p.lower() not in {"en-us", "en-gb", "en", "jobs", "job"}), parts[-1])
    tenant = host.split(".")[0]
    base = f"{parsed.scheme}://{parsed.netloc}"
    endpoint = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    out = []
    try:
        offset = 0
        total = None
        while offset < 5000 and (total is None or offset < total):
            r = requests.post(
                endpoint,
                json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
                headers={**WEB_HEADERS, "Content-Type": "application/json"},
                timeout=10,
            )
            data = r.json() if r.ok else {}
            batch = data.get("jobPostings", []) if isinstance(data, dict) else []
            total = int(data.get("total", len(batch))) if isinstance(data, dict) else len(batch)
            for job in batch:
                external_path = job.get("externalPath") or ""
                job_url = urljoin(base, external_path) if external_path else url
                out.append({
                    "title": job.get("title", ""),
                    "location": job.get("locationsText") or job.get("location") or "",
                    "description": compact_text(f"{job.get('bulletFields', '')} {job.get('postedOn','')}", 1000),
                    "url": job_url,
                    "source": "Workday",
                })
            if not batch:
                break
            offset += len(batch)
        return out
    except Exception:
        return out

def parse_generic_job_page(url, company_name, max_jobs=250):
    html, final = fetch_public_html(url)
    if not html or not BeautifulSoup:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    generic_titles = {"careers", "jobs", "view jobs", "view all jobs", "search jobs", "open positions", "vacancies", "join us", "apply now"}
    for a in soup.find_all("a", href=True):
        href = urljoin(final or url, a.get("href"))
        title = compact_text(a.get_text(" ", strip=True), 180)
        href_l = href.lower()
        if not title or title.lower() in generic_titles or len(title) < 3 or len(title) > 160:
            continue
        if not any(x in href_l for x in ["/job/", "/jobs/", "jobid=", "job_id=", "/position", "/vacanc", "/opening"]):
            continue
        parent_text = compact_text(a.parent.get_text(" ", strip=True) if a.parent else "", 1200)
        out.append({"title": title, "location": "", "description": parent_text, "url": href, "source": hostname(final or url) or company_name})
        if len(out) >= max_jobs:
            break
    return out


@st.cache_data(ttl=10800, show_spinner=False)
def discover_company_jobs(company_name, website, careers_urls=()):
    if not website or not requests:
        return [], [], "Official careers page not resolved"
    pages = discover_company_pages(website)
    candidates = list(dict.fromkeys(list(careers_urls or []) + pages.get("careers", [])))
    working = []
    ats_links = []
    for url in candidates[:15]:
        html, final = fetch_public_html(url)
        if not html:
            continue
        final = final or url
        working.append(final)
        if any(host in hostname(final) for host in ATS_HOSTS):
            ats_links.append(final)
        ats_links.extend(links_matching(html, final, list(ATS_HOSTS), 15))
    ats_links = list(dict.fromkeys(ats_links))
    jobs = []
    for url in ats_links:
        if "greenhouse.io" in hostname(url):
            jobs.extend(greenhouse_jobs(url))
        elif "lever.co" in hostname(url):
            jobs.extend(lever_jobs(url))
        elif "ashbyhq.com" in hostname(url):
            jobs.extend(ashby_jobs(url))
        elif "smartrecruiters.com" in hostname(url):
            jobs.extend(smartrecruiters_jobs(url))
        elif any(x in hostname(url) for x in ["workdayjobs.com", "myworkdayjobs.com"]):
            jobs.extend(workday_jobs(url))
    # Always parse the visible career pages too; some companies use first-party job detail pages.
    for url in (ats_links + working)[:12]:
        jobs.extend(parse_generic_job_page(url, company_name))
    normalized = normalize_jobs(jobs) if jobs else []
    label = "Official careers / ATS scan" if normalized else ("Careers page discovered; role list not server-readable" if working else "Official careers page not resolved")
    return normalized, list(dict.fromkeys(working + ats_links))[:12], label


def likely_person_name(text):
    text = compact_text(text, 100)
    parts = [x for x in re.split(r"\s+", text) if x]
    if not 2 <= len(parts) <= 6:
        return False
    if any(len(x) > 35 for x in parts):
        return False
    bad = {"leadership", "management", "executive", "board", "directors", "team", "people", "learn", "read", "view", "meet"}
    if text.lower() in bad:
        return False
    return sum(bool(re.search(r"[A-Za-z]", x)) for x in parts) >= 2


ROLE_TERMS = (
    "chief ", " ceo", " cfo", " cio", " cto", " coo", "president", "chair", "director", "partner",
    "vice president", "vp ", "head of", "officer", "founder", "managing director", "general counsel",
)


@st.cache_data(ttl=21600, show_spinner=False)
def discover_company_leadership(company_name, website, people_urls=(), full=False):
    if not website:
        return [], [], "Official leadership page not resolved"
    pages = discover_company_pages(website)
    candidates = list(dict.fromkeys(list(people_urls or []) + pages.get("people", [])))
    out = []
    working = []
    max_pages = 12 if full else 6
    for url in candidates[:max_pages]:
        html, final = fetch_public_html(url)
        if not html or not BeautifulSoup:
            continue
        final = final or url
        working.append(final)
        soup = BeautifulSoup(html, "html.parser")
        for obj in jsonld_objects(soup):
            typ = obj.get("@type") if isinstance(obj, dict) else None
            types = typ if isinstance(typ, list) else [typ]
            if "Person" in types and obj.get("name"):
                role = obj.get("jobTitle") or ""
                person_url = obj.get("url") or final
                out.append({"Name": obj.get("name"), "Role": role, "Location": "", "Bio": compact_text(obj.get("description", ""), 1800), "Profile URL": urljoin(final, person_url), "Source": hostname(final)})
        # Repeated cards are common even when schema.org is absent.
        selectors = ["article", "[class*='leader']", "[class*='executive']", "[class*='team-member']", "[class*='person']", "[class*='people-card']", "[class*='profile']"]
        seen_nodes = set()
        for node in soup.select(",".join(selectors))[:500]:
            ident = id(node)
            if ident in seen_nodes:
                continue
            seen_nodes.add(ident)
            text = compact_text(node.get_text(" ", strip=True), 900)
            if not text or not any(term.strip() in text.lower() for term in ROLE_TERMS):
                continue
            heading = node.find(["h2", "h3", "h4", "h5"])
            name = compact_text(heading.get_text(" ", strip=True) if heading else "", 100)
            if not likely_person_name(name):
                continue
            # role = first compact line after the name containing an executive term.
            role = ""
            for el in node.find_all(["p", "span", "div"], limit=25):
                candidate = compact_text(el.get_text(" ", strip=True), 180)
                if candidate and candidate != name and any(term.strip() in candidate.lower() for term in ROLE_TERMS):
                    role = candidate
                    break
            link = node.find("a", href=True)
            profile_url = urljoin(final, link.get("href")) if link else final
            out.append({"Name": name, "Role": role, "Location": "", "Bio": text, "Profile URL": profile_url, "Source": hostname(final)})
    normalized = normalize_leadership(out) if out else []
    label = "Official leadership / people scan" if normalized else ("People page discovered; profiles not cleanly parsed" if working else "Official leadership page not resolved")
    return normalized, list(dict.fromkeys(working))[:10], label


@st.cache_data(ttl=10800, show_spinner=False)
def discover_company_official_news(website):
    if not website:
        return [], []
    pages = discover_company_pages(website)
    working, news = [], []
    for url in pages.get("news", [])[:8]:
        html, final = fetch_public_html(url)
        if not html:
            continue
        working.append(final or url)
        try:
            news.extend(get_official_news_cards(final or url, limit=12))
        except Exception:
            pass
        if len(news) >= 30:
            break
    return news[:30], list(dict.fromkeys(working))[:8]


def credibility_label(article):
    source = str(article.get("source") or "").lower()
    if any(x in source for x in PRIORITY_NEWS_SOURCES):
        return "Priority publication"
    if source and source not in {"google news", "news"}:
        return "Public source"
    return "Aggregated source"


def choose_bio_record(name, official_record, wiki_record):
    """Prefer the company's own description when it looks like real company copy; use Wikipedia as neutral fallback."""
    for record in [official_record, wiki_record]:
        if not record:
            continue
        text = compact_text(record.get("extract", ""), 3000)
        if len(text) >= 70:
            return {**record, "extract": text}
    return official_record or wiki_record or {}


def local_entity_records(entity_key, kind):
    """Supports persistent portfolio-company folders without requiring pe_core configuration entries."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "portfolio_companies", entity_slug(entity_key))
    for ext in ["json", "csv", "xlsx"]:
        path = os.path.join(base, f"{kind}.{ext}")
        if not os.path.exists(path):
            continue
        try:
            if ext == "json":
                raw = json.load(open(path, "r", encoding="utf-8"))
                if isinstance(raw, dict):
                    raw = raw.get("data") or raw.get("records") or raw.get("items") or []
            elif ext == "csv":
                raw = pd.read_csv(path).to_dict(orient="records")
            else:
                raw = pd.read_excel(path).to_dict(orient="records")
            if kind == "jobs":
                return normalize_jobs(raw)
            if kind == "leadership":
                return normalize_leadership(raw)
            if kind == "insights":
                return normalize_insights(raw)
            if kind == "portfolio":
                return normalize_portfolio(raw)
        except Exception:
            return []
    return []


def build_portco_account(parent_firm_key, parent_firm, row, website_override=""):
    name = str(row.get("Company") or "Portfolio company").strip()
    seed_website = website_override or portfolio_row_website(row, parent_firm)
    website, website_source = discover_official_website(name, seed_website, hostname(parent_firm.get("website")))
    pages = discover_company_pages(website) if website else {"careers": [], "people": [], "news": [], "about": []}
    size = discover_company_size(website) if website else ""
    return {
        "name": name,
        "category": str(row.get("Sector") or "Portfolio company"),
        "entity_kind": "Portfolio company",
        "parent_firm_key": parent_firm_key,
        "parent_firm_name": parent_firm.get("name", ""),
        "website": website,
        "official_website": website,
        "website_source": website_source,
        "about_url": (pages.get("about") or [website or parent_firm.get("website")])[0],
        "portfolio_urls": [str(row.get("Source") or parent_firm.get("portfolio_urls", [parent_firm.get("website")])[0])],
        "people_urls": pages.get("people") or ([website] if website else []),
        "careers_urls": pages.get("careers") or ([website] if website else []),
        "news_urls": pages.get("news") or ([website] if website else []),
        "portfolio_scope": f"Portfolio company of {parent_firm.get('name','the selected PE firm')}. Sector: {row.get('Sector') or 'not captured'} · Region: {row.get('Region') or 'not captured'} · Status: {row.get('Status') or 'not captured'} · Fund/strategy: {row.get('Fund') or 'not captured'}.",
        "ownership_note": f"Backed by {parent_firm.get('name','the selected PE firm')} · {row.get('Status') or 'portfolio status not captured'}",
        "sector": str(row.get("Sector") or ""),
        "region": str(row.get("Region") or ""),
        "status": str(row.get("Status") or ""),
        "fund": str(row.get("Fund") or ""),
        "size": size,
        "source_row": row,
        "wikipedia": name,
    }

