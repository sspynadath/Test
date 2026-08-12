"""Generic public-web intelligence for PE portfolio companies.

This module intentionally keeps operating-company discovery separate from the
configured PE-firm adapters in pe_core.py. All network failures degrade to
empty results so a blocked public site never crashes the Streamlit workspace.
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

from pe_core import (
    classify_news_signal,
    get_google_news,
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


def normalize_user_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")) and "." in value and " " not in value:
        value = "https://" + value
    return value if is_http_url(value) else ""


def company_domain_candidates(company_name):
    """Generate conservative .com guesses before using a search engine.

    Examples:
      Seismic -> seismic.com
      Fleet Data Centers -> fleetdatacenters.com

    These are only accepted after the returned homepage is identity-checked.
    """
    raw_words = re.findall(r"[a-z0-9]+", str(company_name or "").lower())
    legal = {"limited", "ltd", "plc", "inc", "corp", "corporation", "llc"}
    raw_words = [w for w in raw_words if w not in legal]
    semantic = company_name_tokens(company_name)
    stems = []
    if raw_words:
        stems.extend(["".join(raw_words), "-".join(raw_words)])
    if semantic:
        stems.extend(["".join(semantic), "-".join(semantic)])
    out = []
    for stem in stems:
        stem = stem.strip("-")
        if not stem or len(stem) < 3:
            continue
        for host in [f"{stem}.com", f"www.{stem}.com"]:
            url = f"https://{host}/"
            if url not in out:
                out.append(url)
    return out[:8]


def company_site_identity_score(company_name, url, html=""):
    """Score whether a loaded site plausibly belongs to the selected company."""
    tokens = company_name_tokens(company_name)
    host = hostname(url).replace("-", "")
    if not tokens or not host:
        return 0
    if not html:
        html, _ = fetch_public_html(url, timeout=8)
    if not html:
        return 0
    soup = BeautifulSoup(html, "html.parser") if BeautifulSoup else None
    title = compact_text(soup.title.get_text(" ", strip=True) if soup and soup.title else "", 300).lower()
    description = ""
    if soup:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        description = compact_text(meta.get("content", "") if meta else "", 1000).lower()
        body = compact_text(soup.get_text(" ", strip=True), 7000).lower()
    else:
        body = compact_text(html, 7000).lower()
    if any(x in f"{title} {description} {body}" for x in ["domain for sale", "buy this domain", "parked domain", "this domain is for sale"]):
        return -20
    score = 0
    flat_host = re.sub(r"[^a-z0-9]", "", host)
    for token in tokens:
        flat_token = re.sub(r"[^a-z0-9]", "", token)
        if flat_token and flat_token in flat_host:
            score += 5
        if token in title:
            score += 4
        if token in description:
            score += 2
        elif token in body:
            score += 1
    full_flat = re.sub(r"[^a-z0-9]", "", str(company_name or "").lower())
    if full_flat and full_flat in flat_host:
        score += 7
    return score


def website_resolution_confidence(company_name, website, source):
    if not website:
        return "Unresolved"
    source_l = str(source or "").lower()
    if any(x in source_l for x in ["manual", "direct news", "portfolio company page", "portfolio record"]):
        return "High"
    score = company_site_identity_score(company_name, website)
    if score >= 12:
        return "High"
    if score >= 6:
        return "Medium"
    return "Low"



IDENTITY_STOPWORDS = {
    "about", "across", "also", "around", "business", "businesses", "company", "companies",
    "customer", "customers", "global", "help", "helps", "leading", "leader", "market", "more",
    "organization", "organizations", "platform", "provides", "solutions", "team", "teams", "their",
    "through", "trusted", "using", "with", "world", "worldwide", "your", "technology", "software",
    "services", "service", "group", "growth", "scale", "enterprise", "powerful", "unified", "right",
}


def identity_keywords(company_name, official_bio="", sector="", parent_name=""):
    """Return distinctive context terms used to disambiguate common company names."""
    name_tokens = set(company_name_tokens(company_name))
    text = f"{official_bio} {sector} {parent_name}".lower()
    words = re.findall(r"[a-z][a-z0-9-]{3,}", text)
    counts = {}
    for word in words:
        word = word.strip("-")
        if not word or word in IDENTITY_STOPWORDS or word in name_tokens:
            continue
        counts[word] = counts.get(word, 0) + 1
    # Prefer terms repeated in official copy and longer category/product words.
    ranked = sorted(counts, key=lambda w: (counts[w], len(w)), reverse=True)
    extras = []
    for token in company_name_tokens(parent_name):
        if token not in extras and token not in name_tokens:
            extras.append(token)
    return (ranked[:8] + extras[:2])[:10]


def build_disambiguated_news_query(company_name, website="", official_bio="", sector="", parent_name=""):
    terms = identity_keywords(company_name, official_bio, sector, parent_name)
    qualifier = " OR ".join(f'"{t}"' for t in terms[:6])
    base = f'"{company_name}"'
    return f"{base} ({qualifier})" if qualifier else base


def filter_company_news(articles, company_name, website="", official_bio="", sector="", parent_name=""):
    """Reject homonyms for operating-company names before they reach the UI.

    For ambiguous single-word brands we deliberately optimise for precision over recall:
    an external article needs multiple company-identity cues (or the PE sponsor itself).
    First-party URLs are always allowed because the official domain is already identity-anchored.
    """
    name = compact_text(company_name, 160).lower()
    tokens = company_name_tokens(company_name)
    terms = identity_keywords(company_name, official_bio, sector, parent_name)
    official_host = hostname(website)
    sponsor_tokens = company_name_tokens(parent_name)
    out = []
    for article in articles or []:
        hay = f"{article.get('title','')} {article.get('summary','')}".lower()
        link_host = hostname(article.get("link", ""))
        if official_host and link_host == official_host:
            row = dict(article)
            row["source"] = row.get("source") or f"Official · {official_host}"
            row["identity_hits"] = ["official-domain"]
            out.append(row)
            continue
        if name and name not in hay:
            continue
        context_hits = [t for t in terms if t and t in hay]
        sponsor_hit = any(t in hay for t in sponsor_tokens) if sponsor_tokens else False
        ambiguous = len(tokens) <= 1
        # One generic word is not an identity. Require two independent cues, or one
        # cue plus the PE sponsor. This blocks Seismic/geophysics false positives.
        if ambiguous and not (len(set(context_hits)) >= 2 or (context_hits and sponsor_hit)):
            continue
        row = dict(article)
        publisher = str(row.get("source") or "").lower()
        if publisher and publisher != "google news" and name and name in publisher:
            row["source"] = f"Official · {row.get('source')}"
        row["identity_hits"] = list(dict.fromkeys(context_hits))[:5]
        out.append(row)
    return normalize_insights(out)


def _external_company_links_from_parent_page(url, company_name, parent_domain):
    html, final = fetch_public_html(url)
    if not html or not BeautifulSoup:
        return []
    soup = BeautifulSoup(html, "html.parser")
    tokens = company_name_tokens(company_name)
    ranked = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final or url, a.get("href"))
        host = hostname(href)
        if not host or host == parent_domain or any(x in host for x in LOW_VALUE_DOMAINS):
            continue
        text = compact_text(a.get_text(" ", strip=True), 180).lower()
        score = 0
        if any(t in host.replace("-", "") for t in tokens):
            score += 8
        if any(t in text for t in tokens):
            score += 5
        if any(k in text for k in ["website", "visit site", "company website", "visit website"]):
            score += 5
        if score:
            ranked.append((score, root_url(href)))
    return [u for _, u in sorted(ranked, reverse=True)]


@st.cache_data(ttl=43200, show_spinner=False)
def discover_website_from_parent_portfolio(company_name, row_source, parent_website):
    """Use the PE firm's own portfolio page as the strongest identity anchor."""
    parent_domain = hostname(parent_website)
    candidates = []
    if is_http_url(row_source) and hostname(row_source) == parent_domain:
        candidates.append(row_source)
    # Many PE adapters only retain the generic portfolio URL. Search the PE domain
    # for the selected company's detail page, then follow its official website link.
    if parent_domain:
        for item in public_web_search(f'site:{parent_domain} "{company_name}" portfolio', limit=8):
            if hostname(item.get("url")) == parent_domain:
                candidates.append(item.get("url"))
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        links = _external_company_links_from_parent_page(candidate, company_name, parent_domain)
        if links:
            return links[0], candidate
    return "", ""


@st.cache_data(ttl=10800, show_spinner=False)
def search_official_company_content(company_name, website, limit=30):
    """Search only the company's own domain for newsroom/blog/insight URLs.

    This complements HTML scraping for sites whose article grids are rendered by JS.
    """
    host = hostname(website)
    if not host:
        return []
    queries = [
        f'site:{host} "{company_name}" (newsroom OR "press release" OR news)',
        f'site:{host} "{company_name}" (blog OR insight OR research OR "product release")',
    ]
    rows, seen = [], set()
    for query in queries:
        for item in public_web_search(query, limit=max(8, limit // 2)):
            url = item.get("url", "")
            if hostname(url) != host or url in seen:
                continue
            path = urlparse(url).path.lower()
            if not any(k in path for k in ["news", "press", "blog", "insight", "research", "article", "resource"]):
                continue
            seen.add(url)
            title = compact_text(item.get("title", ""), 220)
            summary = compact_text(item.get("snippet", ""), 700)
            if not title:
                continue
            rows.append({
                "title": title,
                "summary": summary,
                "link": url,
                "published": "",
                "source": f"Official · {host}",
                "signal_type": classify_news_signal(f"{title} {summary}"),
            })
            if len(rows) >= limit:
                return normalize_insights(rows)

    # Google News can index first-party press releases even when the newsroom grid
    # itself is JS-rendered. Keep only results whose publisher is the company itself.
    if len(rows) < limit:
        official_rss = get_google_news(f'site:{host} "{company_name}"', limit=limit)
        company_tokens = company_name_tokens(company_name)
        for item in official_rss:
            publisher = str(item.get("source") or "").lower()
            if publisher == "google news":
                continue
            if not any(t in publisher for t in company_tokens):
                continue
            row = dict(item)
            row["source"] = f"Official · {item.get('source')}"
            rows.append(row)
            if len(rows) >= limit:
                break
    return normalize_insights(rows)


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
    row_website = normalize_user_url(row_website)
    if row_website:
        html, final = fetch_public_html(row_website, timeout=10)
        if html:
            return root_url(final or row_website), "Portfolio / supplied URL"

    # First try the intuitive company-name .com domain. This is exactly right for
    # examples such as Seismic -> seismic.com and Fleet Data Centers ->
    # fleetdatacenters.com, but we only accept it after checking page identity.
    for candidate in company_domain_candidates(company_name):
        html, final = fetch_public_html(candidate, timeout=8)
        if not html:
            continue
        final = final or candidate
        if parent_domain and hostname(final) == parent_domain:
            continue
        if any(x in hostname(final) for x in LOW_VALUE_DOMAINS):
            continue
        if company_site_identity_score(company_name, final, html) >= 6:
            return root_url(final), "Company-name .com discovery"

    # Search-engine discovery remains a fallback, not the identity authority.
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
        if not html:
            continue
        resolved = final_url or url
        identity = company_site_identity_score(company_name, resolved, html)
        if identity >= 5:
            return root_url(resolved), "Public web discovery"
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
    news = links_matching(html, base, ["news", "press", "media", "insight", "blog", "research", "resource", "knowledge", "stories", "updates"], 18)
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
    for path in ["news", "newsroom", "newsroom/press-releases", "press", "press-releases", "insights", "blog", "resources", "research", "knowledge-center", "media"]:
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



OFFICIAL_CONTENT_HINTS = (
    "/newsroom/", "/news/", "/press/", "/press-release", "/blog/", "/insight",
    "/research", "/resource", "/article", "/stories/", "/updates/", "/knowledge-center/",
)


def _fetch_public_resource(url, timeout=12):
    if not is_http_url(url):
        return b"", "", ""
    try:
        r = requests.get(url, headers=WEB_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return b"", r.url, r.headers.get("content-type", "")
        return r.content[:8_000_000], r.url, r.headers.get("content-type", "")
    except Exception:
        return b"", "", ""


def _same_official_domain(url, website):
    return bool(hostname(url) and hostname(url) == hostname(website))


def _content_url(url, website):
    if not _same_official_domain(url, website):
        return False
    path = urlparse(url).path.lower()
    return any(h in path for h in OFFICIAL_CONTENT_HINTS)


def _xml_loc_values(root):
    vals = []
    for el in root.iter():
        if str(el.tag).lower().endswith("loc") and el.text:
            vals.append(el.text.strip())
    return vals


@st.cache_data(ttl=21600, show_spinner=False)
def discover_sitemap_content_urls(website, limit=120):
    """Use the company's own sitemap as a first-party content index.

    This is the main fallback for JS-rendered newsrooms: even when article cards are
    not present in server-rendered HTML, production sites commonly publish every
    canonical article URL in an XML sitemap.
    """
    root = root_url(website)
    if not root:
        return []
    candidates = []
    # robots.txt can advertise non-standard sitemap locations.
    raw, final, _ = _fetch_public_resource(urljoin(root, "robots.txt"), timeout=8)
    if raw:
        text = raw.decode("utf-8", "ignore")
        for line in text.splitlines():
            if line.lower().startswith("sitemap:"):
                u = line.split(":", 1)[1].strip()
                if is_http_url(u) and _same_official_domain(u, root):
                    candidates.append(u)
    for path in ["sitemap.xml", "sitemap_index.xml", "wp-sitemap.xml", "sitemap-index.xml"]:
        candidates.append(urljoin(root, path))

    seen_maps, article_urls = set(), []
    queue = list(dict.fromkeys(candidates))
    map_budget = 18
    while queue and len(seen_maps) < map_budget and len(article_urls) < limit:
        sm = queue.pop(0)
        if sm in seen_maps or not _same_official_domain(sm, root):
            continue
        seen_maps.add(sm)
        payload, final, ctype = _fetch_public_resource(sm, timeout=10)
        if not payload:
            continue
        try:
            xroot = ET.fromstring(payload)
        except Exception:
            continue
        locs = _xml_loc_values(xroot)
        tag = str(xroot.tag).lower()
        if "sitemapindex" in tag:
            # Prioritise child maps whose names look content-related.
            ranked = sorted(
                [u for u in locs if _same_official_domain(u, root)],
                key=lambda u: (not any(k in u.lower() for k in ["post", "news", "press", "blog", "article", "resource"]), u),
            )
            queue.extend(ranked[:12])
        else:
            for u in locs:
                if _content_url(u, root) and u not in article_urls:
                    article_urls.append(u)
                    if len(article_urls) >= limit:
                        break
    return article_urls[:limit]


def _meta_content(soup, *, name=None, prop=None):
    attrs = {"name": name} if name else {"property": prop}
    tag = soup.find("meta", attrs=attrs)
    return compact_text(tag.get("content", ""), 1200) if tag and tag.get("content") else ""


@st.cache_data(ttl=21600, show_spinner=False)
def official_article_from_url(url, website):
    if not _content_url(url, website):
        return None
    html, final = fetch_public_html(url, timeout=12)
    if not html or not BeautifulSoup:
        return None
    soup = BeautifulSoup(html, "html.parser")
    title = (_meta_content(soup, prop="og:title") or _meta_content(soup, name="twitter:title"))
    if not title:
        h = soup.find("h1") or soup.find("h2")
        title = compact_text(h.get_text(" ", strip=True) if h else "", 240)
    if not title or len(title) < 12:
        return None
    summary = (_meta_content(soup, name="description") or _meta_content(soup, prop="og:description"))
    if not summary:
        main = soup.find("main") or soup.body
        if main:
            summary = next((compact_text(p.get_text(" ", strip=True), 900) for p in main.find_all("p") if len(compact_text(p.get_text(" ", strip=True), 900)) >= 70), "")
    published = _meta_content(soup, prop="article:published_time")
    if not published:
        time_tag = soup.find("time")
        if time_tag:
            published = compact_text(time_tag.get("datetime") or time_tag.get_text(" ", strip=True), 100)
    if not published:
        for obj in jsonld_objects(soup):
            if isinstance(obj, dict) and obj.get("datePublished"):
                published = compact_text(obj.get("datePublished"), 100)
                break
    return {
        "title": title,
        "summary": summary,
        "link": final or url,
        "published": published,
        "source": f"Official · {hostname(website)}",
        "signal_type": classify_news_signal(f"{title} {summary}"),
    }


def _feed_links_from_html(html, base):
    if not html or not BeautifulSoup:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tag in soup.find_all("link", href=True):
        typ = str(tag.get("type") or "").lower()
        rel = " ".join(tag.get("rel") or []).lower()
        if "alternate" in rel and any(x in typ for x in ["rss", "atom", "xml"]):
            out.append(urljoin(base, tag.get("href")))
    return list(dict.fromkeys(out))


@st.cache_data(ttl=21600, show_spinner=False)
def discover_official_feed_articles(website, page_urls=(), limit=50):
    root = root_url(website)
    if not root:
        return []
    feeds = []
    for page in [root] + list(page_urls)[:6]:
        html, final = fetch_public_html(page, timeout=10)
        feeds.extend(_feed_links_from_html(html, final or page))
    for path in ["feed/", "blog/feed/", "news/feed/", "newsroom/feed/", "press-releases/feed/"]:
        feeds.append(urljoin(root, path))

    rows, seen = [], set()
    for feed in list(dict.fromkeys(feeds))[:14]:
        if not _same_official_domain(feed, root):
            continue
        payload, final, _ = _fetch_public_resource(feed, timeout=10)
        if not payload:
            continue
        try:
            xroot = ET.fromstring(payload)
        except Exception:
            continue
        # RSS <item> and Atom <entry> are both supported.
        nodes = list(xroot.findall(".//item"))
        if not nodes:
            nodes = [el for el in xroot.iter() if str(el.tag).lower().endswith("entry")]
        for node in nodes:
            def child_text(suffix):
                for child in list(node):
                    if str(child.tag).lower().endswith(suffix):
                        return compact_text(child.text or "", 1400)
                return ""
            title = child_text("title")
            summary = child_text("description") or child_text("summary") or child_text("content")
            published = child_text("pubdate") or child_text("published") or child_text("updated")
            link = child_text("link")
            if not link:
                for child in list(node):
                    if str(child.tag).lower().endswith("link") and child.get("href"):
                        link = child.get("href")
                        break
            link = urljoin(final or feed, link)
            if not title or not _same_official_domain(link, root) or link in seen:
                continue
            seen.add(link)
            rows.append({
                "title": title,
                "summary": BeautifulSoup(summary, "html.parser").get_text(" ", strip=True) if summary and BeautifulSoup else summary,
                "link": link,
                "published": published,
                "source": f"Official · {hostname(root)}",
                "signal_type": classify_news_signal(f"{title} {summary}"),
            })
            if len(rows) >= limit:
                return normalize_insights(rows)
    return normalize_insights(rows)


def _sort_news_newest(rows):
    indexed = []
    for i, row in enumerate(rows or []):
        try:
            dt = pd.to_datetime(row.get("published"), utc=True, errors="coerce")
            score = dt.value if pd.notna(dt) else -1
        except Exception:
            score = -1
        indexed.append((score, -i, row))
    return [x[2] for x in sorted(indexed, key=lambda x: (x[0], x[1]), reverse=True)]


@st.cache_data(ttl=10800, show_spinner=False)
def discover_official_source_pages(website, company_name="", preferred_urls=()):
    """Find likely first-party news/insight/resource landing pages on a confirmed domain."""
    root = root_url(website)
    host = hostname(root)
    if not root or not host:
        return []
    pages = []
    for value in preferred_urls or ():
        value = normalize_user_url(value)
        if value and hostname(value) == host and value not in pages:
            pages.append(value)

    discovered = discover_company_pages(root).get("news", [])
    for url in discovered:
        if hostname(url) == host and url not in pages:
            pages.append(url)

    # Search *within the confirmed company domain*. This lets the site call the
    # section Newsroom, Insights, Resources, Knowledge Hub, Blog, Media, etc.
    queries = [
        f'site:{host} (newsroom OR news OR press OR media)',
        f'site:{host} (insights OR resources OR blog OR research OR articles OR "knowledge hub")',
    ]
    for query in queries:
        for item in public_web_search(query, limit=12):
            url = normalize_user_url(item.get("url", ""))
            if not url or hostname(url) != host:
                continue
            hay = f"{urlparse(url).path} {item.get('title','')} {item.get('snippet','')}".lower()
            if not any(k in hay for k in ["news", "press", "media", "insight", "resource", "blog", "research", "article", "knowledge", "story", "update"]):
                continue
            if url not in pages:
                pages.append(url)
            if len(pages) >= 24:
                break
    return pages[:24]


@st.cache_data(ttl=10800, show_spinner=False)
def discover_company_official_news(website, company_name="", preferred_news_urls=()):
    """Collect first-party newsroom, press-release, blog and insight content.

    Order of attack: direct page HTML -> RSS/Atom -> XML sitemaps -> same-domain
    search fallback. Search engines are discovery-only; every accepted first-party
    record must resolve to the confirmed official company domain.
    """
    if not website:
        return [], []
    working, news = [], []
    news_pages = discover_official_source_pages(website, company_name, tuple(preferred_news_urls))[:24]

    # 1) Direct first-party pages, including a user-supplied newsroom/insights URL.
    for url in news_pages:
        html, final = fetch_public_html(url)
        if not html:
            continue
        final = final or url
        working.append(final)
        try:
            direct = get_official_news_cards(final, limit=24)
            for row in direct:
                if _same_official_domain(row.get("link", ""), website):
                    row["source"] = f"Official · {hostname(website)}"
                    news.append(row)
        except Exception:
            pass
        # A search result or manually supplied URL may itself be an article/resource page.
        # Parse it directly as well as looking for cards within it.
        direct_article = official_article_from_url(final, website)
        if direct_article:
            news.append(direct_article)
        # JSON-LD article objects can exist even when visual cards are JS-rendered.
        soup = BeautifulSoup(html, "html.parser") if BeautifulSoup else None
        for obj in jsonld_objects(soup):
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if not any(t in {"NewsArticle", "Article", "BlogPosting", "Report"} for t in types if t):
                continue
            title = compact_text(obj.get("headline") or obj.get("name"), 240)
            link = urljoin(final, obj.get("url") or obj.get("mainEntityOfPage") or final)
            if isinstance(obj.get("mainEntityOfPage"), dict):
                link = urljoin(final, obj.get("mainEntityOfPage", {}).get("@id") or obj.get("url") or final)
            if title and _same_official_domain(link, website):
                summary = compact_text(obj.get("description"), 1000)
                news.append({
                    "title": title, "summary": summary, "link": link,
                    "published": compact_text(obj.get("datePublished"), 100),
                    "source": f"Official · {hostname(website)}",
                    "signal_type": classify_news_signal(f"{title} {summary}"),
                })

    # 2) RSS/Atom feeds discovered on the official site.
    news.extend(discover_official_feed_articles(website, tuple(working or news_pages), limit=50))

    # 3) XML sitemap: critical for client-side rendered newsroom grids.
    sitemap_urls = discover_sitemap_content_urls(website, limit=100)
    # Fetch a bounded set. Sitemap order is commonly newest-first; sorting below uses dates.
    for article_url in sitemap_urls[:36]:
        article = official_article_from_url(article_url, website)
        if article:
            news.append(article)

    # 4) Same-domain search is last-resort discovery only.
    if company_name:
        news.extend(search_official_company_content(company_name, website, limit=30))

    # Enforce first-party domain on anything marked official.
    clean = []
    for row in normalize_insights(news):
        if _same_official_domain(row.get("link", ""), website):
            row["source"] = f"Official · {hostname(website)}"
            row["credibility"] = "Official company source"
            clean.append(row)
    clean = _sort_news_newest(clean)
    return clean[:70], list(dict.fromkeys(working))[:14]


def credibility_label(article):
    source = str(article.get("source") or "").lower()
    if "official" in source:
        return "Official company source"
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


def build_portco_account(parent_firm_key, parent_firm, row, website_override="", news_page_override=""):
    name = str(row.get("Company") or "Portfolio company").strip()
    website_override = normalize_user_url(website_override)
    news_page_override = normalize_user_url(news_page_override)

    parent_identity_website, parent_detail_url = discover_website_from_parent_portfolio(
        name, str(row.get("Source") or ""), parent_firm.get("website", "")
    )

    # A direct newsroom/insights URL is itself a strong domain anchor. If the user
    # supplies only that field, derive the company homepage from its domain.
    news_root = root_url(news_page_override) if news_page_override else ""
    seed_website = (
        website_override
        or news_root
        or portfolio_row_website(row, parent_firm)
        or parent_identity_website
    )
    website, website_source = discover_official_website(name, seed_website, hostname(parent_firm.get("website")))
    if website_override and website:
        website_source = "Manual company URL"
    elif news_page_override and website and hostname(news_page_override) == hostname(website):
        website_source = "Direct news / insights URL"
    elif parent_identity_website and website == root_url(parent_identity_website):
        website_source = "PE portfolio company page"

    source_warning = ""
    preferred_news_urls = []
    if news_page_override:
        if website and hostname(news_page_override) == hostname(website):
            preferred_news_urls.append(news_page_override)
        elif website:
            source_warning = (
                f"The supplied news/insights URL is on {hostname(news_page_override)}, "
                f"but the company website is {hostname(website)}. It was not treated as an official source."
            )

    pages = discover_company_pages(website) if website else {"careers": [], "people": [], "news": [], "about": []}
    size = discover_company_size(website) if website else ""
    news_urls = list(dict.fromkeys(preferred_news_urls + (pages.get("news") or [])))
    confidence = website_resolution_confidence(name, website, website_source)
    return {
        "name": name,
        "category": str(row.get("Sector") or "Portfolio company"),
        "entity_kind": "Portfolio company",
        "parent_firm_key": parent_firm_key,
        "parent_firm_name": parent_firm.get("name", ""),
        "website": website,
        "official_website": website,
        "website_source": website_source,
        "website_confidence": confidence,
        "source_warning": source_warning,
        "manual_news_page": news_page_override,
        "preferred_news_urls": preferred_news_urls,
        "about_url": (pages.get("about") or [website or parent_firm.get("website")])[0],
        "portfolio_urls": [str(row.get("Source") or parent_firm.get("portfolio_urls", [parent_firm.get("website")])[0])],
        "people_urls": pages.get("people") or ([website] if website else []),
        "careers_urls": pages.get("careers") or ([website] if website else []),
        "news_urls": news_urls or ([website] if website else []),
        "portfolio_scope": f"Portfolio company of {parent_firm.get('name','the selected PE firm')}. Sector: {row.get('Sector') or 'not captured'} · Region: {row.get('Region') or 'not captured'} · Status: {row.get('Status') or 'not captured'} · Fund/strategy: {row.get('Fund') or 'not captured'}.",
        "ownership_note": f"Backed by {parent_firm.get('name','the selected PE firm')} · {row.get('Status') or 'portfolio status not captured'}",
        "sector": str(row.get("Sector") or ""),
        "region": str(row.get("Region") or ""),
        "status": str(row.get("Status") or ""),
        "fund": str(row.get("Fund") or ""),
        "size": size,
        "source_row": row,
        "parent_portfolio_detail_url": parent_detail_url,
        "wikipedia": name,
    }
