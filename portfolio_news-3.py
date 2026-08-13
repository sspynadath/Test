import asyncio
import json
import os
import re
import threading
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# Use the operating-system certificate store where available. This is particularly
# useful on managed Windows laptops where browsers trust a corporate root CA but
# requests/certifi may not.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    truststore = None

from pe_core import classify_news_signal, normalize_insights


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

SOURCE_TERMS = {
    "Newsroom": ["newsroom", "news room"],
    "News": ["news", "latest news", "company news"],
    "Press": ["press", "press release", "press releases", "media centre", "media center"],
    "Insights": ["insight", "insights", "perspective", "perspectives", "thought leadership"],
    "Resources": ["resource", "resources", "resource center", "resource centre", "knowledge hub", "knowledge center", "knowledge centre"],
    "Blog": ["blog", "blogs"],
    "Research": ["research", "reports", "publications", "articles", "stories", "updates"],
}

SOURCE_PATH_TERMS = [
    "newsroom", "news", "press", "media", "insight", "resource", "blog",
    "research", "article", "story", "update", "publication", "knowledge",
]

COMMON_SOURCE_PATHS = [
    "/newsroom/", "/news/", "/press/", "/press-releases/", "/media/",
    "/insights/", "/resources/", "/resource/", "/blog/", "/research/",
    "/articles/", "/stories/", "/updates/", "/publications/",
    "/knowledge-hub/", "/knowledge-center/", "/knowledge-centre/",
    "/company/news/", "/company/newsroom/", "/about/news/",
]

NON_ARTICLE_TITLES = {
    "home", "about", "about us", "contact", "contact us", "careers", "jobs",
    "news", "newsroom", "press", "press releases", "media", "insights",
    "resources", "resource", "resource center", "resource centre", "blog", "research",
    "articles", "stories", "updates", "view all", "view more", "read more",
    "learn more", "explore", "see more", "load more", "back", "next", "previous",
    "privacy", "privacy policy", "terms", "terms of use", "cookie policy",
    # Common website navigation / resource-hub labels. These are sections, not articles.
    "professional services", "global services", "product tours", "demo videos",
    "events and webinars", "events & webinars", "analyst reports",
    "analyst 3rd party reports", "third party reports", "enablement consulting",
    "center of growth", "centre of growth", "customer stories", "case studies",
    "webinars", "ebooks", "guides", "whitepapers", "reports",
}

LEGAL_WORDS = {
    "limited", "ltd", "plc", "inc", "incorporated", "corp", "corporation",
    "llc", "company", "co", "holdings", "holding", "group", "the",
}


# -----------------------------------------------------------------------------
# URL / text helpers
# -----------------------------------------------------------------------------
def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(value):
    value = clean_text(value)
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        if "." not in value or " " in value:
            return ""
        value = "https://" + value
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""
    except Exception:
        return ""


def hostname(url):
    try:
        return urlparse(normalize_url(url)).netloc.lower().split(":")[0].removeprefix("www.")
    except Exception:
        return ""


def root_url(url):
    url = normalize_url(url)
    if not url:
        return ""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/"


def same_domain(a, b):
    return bool(hostname(a) and hostname(a) == hostname(b))


def company_tokens(name):
    return [
        x for x in re.findall(r"[a-z0-9]+", clean_text(name).lower())
        if len(x) > 1 and x not in LEGAL_WORDS
    ]


def company_domain_candidates(name):
    words = [x for x in re.findall(r"[a-z0-9]+", clean_text(name).lower()) if x not in LEGAL_WORDS]
    if not words:
        return []
    stems = ["".join(words), "-".join(words)]
    # Also try the first meaningful word for brands such as "Seismic Software".
    if len(words) > 1:
        stems.append(words[0])
    out = []
    for stem in stems:
        if len(stem) < 3:
            continue
        for suffix in [".com", ".co.uk", ".io"]:
            url = f"https://{stem}{suffix}/"
            if url not in out:
                out.append(url)
    return out[:10]


def _date_from_text(text):
    text = clean_text(text)
    if not text:
        return ""
    patterns = [
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Sept|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2}\b",
        r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Sept|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+20\d{2}\b",
        r"\b20\d{2}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/20\d{2}\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(0)
    return ""


def _date_sort_value(value):
    if not value:
        return pd.Timestamp.min.tz_localize("UTC")
    try:
        dt = pd.to_datetime(value, utc=True, errors="coerce", dayfirst=False)
        if pd.isna(dt):
            dt = pd.to_datetime(value, utc=True, errors="coerce", dayfirst=True)
        return dt if pd.notna(dt) else pd.Timestamp.min.tz_localize("UTC")
    except Exception:
        return pd.Timestamp.min.tz_localize("UTC")


def _source_kind(text, url=""):
    hay = f"{clean_text(text)} {urlparse(url).path}".lower()
    best = "Company content"
    best_len = 0
    for label, terms in SOURCE_TERMS.items():
        for term in terms:
            if term in hay and len(term) > best_len:
                best, best_len = label, len(term)
    return best


def _looks_dynamic(html):
    low = (html or "").lower()
    markers = [
        "loading component", "enable javascript", "please enable javascript",
        "__next_data__", "data-reactroot", "__nuxt__",
    ]
    return any(x in low for x in markers)


# -----------------------------------------------------------------------------
# Crawlee runtime helpers
# -----------------------------------------------------------------------------
def _run_async(coro_factory):
    """Run an async crawler safely from Streamlit's synchronous script thread.

    Streamlit normally does not expose a running asyncio loop here, but this
    thread fallback prevents "asyncio.run() cannot be called from a running
    event loop" in notebook/dev environments.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    box = {"value": None, "error": None}

    def runner():
        try:
            box["value"] = asyncio.run(coro_factory())
        except Exception as exc:
            box["error"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()
    if box["error"] is not None:
        raise box["error"]
    return box["value"]


def _crawlee_available():
    try:
        from crawlee.crawlers import PlaywrightCrawler  # noqa: F401
        return True, ""
    except Exception as exc:
        return False, repr(exc)


async def _dismiss_cookie_banner(page):
    patterns = [
        r"^accept all$", r"^accept cookies$", r"^allow all$", r"^agree$",
        r"^i agree$", r"^accept$", r"^continue$",
    ]
    for pattern in patterns:
        for role in ["button", "link"]:
            try:
                loc = page.get_by_role(role, name=re.compile(pattern, re.I)).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=1200)
                    await page.wait_for_timeout(250)
                    return
            except Exception:
                pass


async def _browser_anchor_snapshot(page):
    """Return visible anchor candidates plus nearby card/date context.

    Extraction is intentionally listing-page-only: no individual article pages
    are opened. This keeps the user experience fast and gives the UI exactly
    what it needs: title, date and click-through URL.
    """
    js = r"""
    (els) => els.map((a) => {
        const nav = a.closest('nav,header,footer,aside,[role="navigation"]');
        const container =
            a.closest('article,li,[class*="card"],[class*="item"],[class*="post"],[class*="news"],[class*="press"],[class*="resource"],[class*="insight"]')
            || a.parentElement;
        const timeEl = container ? container.querySelector('time') : null;
        const dateEl = container ? container.querySelector(
            '[class*="date"],[class*="time"],[class*="published"],[class*="meta"]'
        ) : null;
        return {
            href: a.href || '',
            title: (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim(),
            context: container
                ? (container.innerText || container.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 1800)
                : '',
            date: timeEl
                ? ((timeEl.getAttribute('datetime') || timeEl.textContent || '').trim())
                : (dateEl ? (dateEl.textContent || '').replace(/\s+/g, ' ').trim() : ''),
            in_nav: !!nav
        };
    })
    """
    try:
        return await page.locator("a[href]").evaluate_all(js)
    except Exception:
        return []


async def _click_more_or_next(page):
    """Click a pagination/load-more control if one is visible.

    We deliberately favor controls that imply more records, then pagination.
    """
    patterns = [
        r"load\s+more",
        r"show\s+more",
        r"view\s+more",
        r"more\s+(news|articles|press|posts|stories|resources|insights)",
        r"older\s+(news|posts|articles|stories)",
        r"next(\s+page)?",
    ]
    for pattern in patterns:
        for role in ["button", "link"]:
            try:
                loc = page.get_by_role(role, name=re.compile(pattern, re.I))
                count = await loc.count()
                if not count:
                    continue
                # Prefer the last visible matching control; many sites repeat nav.
                for idx in range(count - 1, -1, -1):
                    item = loc.nth(idx)
                    if not await item.is_visible():
                        continue
                    before = page.url
                    await item.click(timeout=2500)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(900)
                    return True, before, page.url
            except Exception:
                continue
    return False, page.url, page.url


async def _crawl_source_async(source_url, website, source_kind, max_passes=14):
    """Use Crawlee's PlaywrightCrawler to exhaust a dynamic content listing."""
    try:
        from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
    except Exception as exc:
        return {
            "ok": False,
            "method": "Crawlee unavailable",
            "url": source_url,
            "anchors": [],
            "error": f"Install crawlee[playwright]: {exc!r}",
            "passes": 0,
        }

    anchors = []
    errors = []
    final_url = source_url
    passes_used = 0

    crawler = PlaywrightCrawler(
        headless=True,
        browser_type="chromium",
        max_requests_per_crawl=1,
        max_request_retries=1,
        retry_on_blocked=True,
        navigation_timeout=timedelta(seconds=35),
        request_handler_timeout=timedelta(seconds=90),
        configure_logging=False,
        browser_new_context_options={
            "locale": "en-GB",
            "viewport": {"width": 1440, "height": 1200},
        },
        browser_launch_options={
            "args": ["--disable-dev-shm-usage"],
        },
    )

    @crawler.router.default_handler
    async def handle(context: PlaywrightCrawlingContext) -> None:
        nonlocal final_url, passes_used
        page = context.page
        final_url = page.url

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass

        await _dismiss_cookie_banner(page)

        seen_signatures = set()
        stable_passes = 0
        visited_page_urls = set()

        for pass_no in range(max_passes):
            passes_used = pass_no + 1
            final_url = page.url

            snapshot = await _browser_anchor_snapshot(page)
            anchors.extend(snapshot)

            signature = tuple(
                sorted(
                    (clean_text(x.get("title")), normalize_url(x.get("href")))
                    for x in snapshot
                    if x.get("href")
                )
            )
            if signature in seen_signatures:
                stable_passes += 1
            else:
                seen_signatures.add(signature)
                stable_passes = 0

            # Infinite-scroll / lazy-load first.
            try:
                before_height = await page.evaluate("document.body.scrollHeight")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(900)
                after_height = await page.evaluate("document.body.scrollHeight")
            except Exception:
                before_height = after_height = 0

            # Then explicitly click load-more / pagination if present.
            clicked, before_url, after_url = await _click_more_or_next(page)
            if clicked:
                final_url = after_url
                # Avoid looping through the same pagination URL forever.
                page_key = (before_url, after_url)
                if page_key in visited_page_urls:
                    clicked = False
                else:
                    visited_page_urls.add(page_key)

            # Collect again after the interaction so the last page is not lost.
            if clicked or after_height > before_height:
                snapshot = await _browser_anchor_snapshot(page)
                anchors.extend(snapshot)
                stable_passes = 0

            if stable_passes >= 2 and not clicked and after_height <= before_height:
                break

    try:
        await crawler.run([source_url])
    except Exception as exc:
        errors.append(repr(exc))

    return {
        "ok": bool(anchors),
        "method": "Crawlee + Playwright",
        "url": final_url,
        "anchors": anchors,
        "error": " | ".join(errors),
        "passes": passes_used,
    }


@st.cache_data(ttl=1800, show_spinner=False)
def crawl_source_with_crawlee(source_url, website, source_kind, max_passes=14):
    """Cached synchronous wrapper used by the Streamlit app."""
    source_url = normalize_url(source_url)
    website = root_url(website)
    if not source_url or not website or not same_domain(source_url, website):
        return {
            "ok": False,
            "method": "Crawlee + Playwright",
            "url": source_url,
            "anchors": [],
            "error": "Source URL is missing or is not on the confirmed company domain.",
            "passes": 0,
        }

    available, import_error = _crawlee_available()
    if not available:
        return {
            "ok": False,
            "method": "Crawlee unavailable",
            "url": source_url,
            "anchors": [],
            "error": f"Crawlee is not installed: {import_error}",
            "passes": 0,
        }

    try:
        return _run_async(
            lambda: _crawl_source_async(
                source_url,
                website,
                source_kind,
                max_passes=max_passes,
            )
        )
    except Exception as exc:
        return {
            "ok": False,
            "method": "Crawlee + Playwright",
            "url": source_url,
            "anchors": [],
            "error": repr(exc),
            "passes": 0,
        }


def _rows_from_crawlee_anchors(anchor_rows, source_url, website, source_kind):
    """Turn Crawlee's rendered anchors into the app's normalized news records."""
    rows = []
    seen = set()

    for item in anchor_rows or []:
        if item.get("in_nav"):
            continue

        href = normalize_url(item.get("href"))
        title = clean_text(item.get("title"))
        context = clean_text(item.get("context"))
        raw_date = clean_text(item.get("date"))

        if not href or not same_domain(href, website):
            continue
        if not _article_within_source_scope(href, source_url, source_kind):
            continue

        title_l = title.lower().strip(" -|·:")
        if not title or title_l in NON_ARTICLE_TITLES:
            continue
        if len(title) < 12 or len(re.findall(r"\b[\w’'-]+\b", title)) < 3:
            continue

        score = _article_candidate_score(title, href, source_url, context)
        if score < 6:
            continue

        published = raw_date or _date_from_text(context)
        key = href.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "title": title[:300],
            "summary": "",
            "link": href,
            "published": published,
            "source": f"Official · {hostname(website)}",
            "source_section": source_kind,
            "signal_type": classify_news_signal(title),
            "credibility": "Official company source",
            "_score": score,
        })

    return _dedupe_and_sort(rows)


# -----------------------------------------------------------------------------
# Retrieval layers
# -----------------------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_http(url, timeout=18):
    url = normalize_url(url)
    if not url:
        return {"ok": False, "method": "HTTP", "url": "", "html": "", "error": "Invalid URL", "status": None}
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return {
            "ok": True,
            "method": "HTTP",
            "url": r.url,
            "html": r.text,
            "error": "",
            "status": r.status_code,
        }
    except Exception as exc:
        return {"ok": False, "method": "HTTP", "url": url, "html": "", "error": repr(exc), "status": None}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_playwright(url, timeout_ms=30000):
    url = normalize_url(url)
    if not url:
        return {"ok": False, "method": "Browser", "url": "", "html": "", "error": "Invalid URL", "status": None}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"ok": False, "method": "Browser", "url": url, "html": "", "error": f"Playwright unavailable: {exc!r}", "status": None}

    try:
        with sync_playwright() as p:
            browser = None
            launch_errors = []
            for kwargs in ({"headless": True}, {"headless": True, "channel": "chrome"}):
                try:
                    browser = p.chromium.launch(**kwargs)
                    break
                except Exception as exc:
                    launch_errors.append(str(exc))
            if browser is None:
                return {
                    "ok": False, "method": "Browser", "url": url, "html": "",
                    "error": " | ".join(launch_errors)[-2500:], "status": None,
                }
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=REQUEST_HEADERS["User-Agent"],
                locale="en-GB",
            )
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1800)
                html = page.content()
                final = page.url
                status = response.status if response else None
                return {"ok": True, "method": "Browser", "url": final, "html": html, "error": "", "status": status}
            finally:
                browser.close()
    except Exception as exc:
        return {"ok": False, "method": "Browser", "url": url, "html": "", "error": repr(exc), "status": None}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_jina(url, timeout=30):
    """Rendered text fallback for cloud deployments without a local browser."""
    url = normalize_url(url)
    if not url:
        return {"ok": False, "method": "Rendered reader", "url": "", "markdown": "", "error": "Invalid URL"}
    try:
        headers = dict(REQUEST_HEADERS)
        headers["Accept"] = "text/markdown,text/plain"
        headers["X-Return-Format"] = "markdown"
        key = os.getenv("JINA_API_KEY", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = requests.get("https://r.jina.ai/" + url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return {"ok": True, "method": "Rendered reader", "url": url, "markdown": r.text, "error": ""}
    except Exception as exc:
        return {"ok": False, "method": "Rendered reader", "url": url, "markdown": "", "error": repr(exc)}


def fetch_best_page(url, force_render=False):
    """Get a page, escalating only when ordinary HTML is unavailable or clearly incomplete."""
    http = fetch_http(url)
    if http.get("ok") and http.get("html") and not force_render:
        html = http["html"]
        # Keep ordinary HTML when it has meaningful anchor content and is not a JS shell.
        soup = BeautifulSoup(html, "html.parser")
        anchor_count = len(soup.find_all("a", href=True))
        if not _looks_dynamic(html) and anchor_count >= 5:
            return {**http, "fallbacks": []}

    browser = fetch_playwright(url)
    if browser.get("ok") and browser.get("html"):
        return {**browser, "fallbacks": [http]}

    # If no browser binary exists (common on cloud hosting), use a rendered reader.
    jina = fetch_jina(url)
    if jina.get("ok") and jina.get("markdown"):
        return {**jina, "html": "", "fallbacks": [http, browser]}

    # Last chance: usable HTML even if it looked dynamic.
    if http.get("ok") and http.get("html"):
        return {**http, "fallbacks": [browser, jina]}
    return {"ok": False, "method": "Unavailable", "url": normalize_url(url), "html": "", "markdown": "", "error": " | ".join(x.get("error", "") for x in [http, browser, jina] if x.get("error")), "fallbacks": [http, browser, jina]}


def clear_news_cache():
    for fn in [fetch_http, fetch_playwright, fetch_jina, crawl_source_with_crawlee]:
        try:
            fn.clear()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Company website resolution
# -----------------------------------------------------------------------------
def _identity_score(company_name, url, html):
    tokens = company_tokens(company_name)
    if not tokens or not url:
        return 0
    host = hostname(url).replace("-", "")
    soup = BeautifulSoup(html or "", "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "").lower()
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    desc = clean_text(meta.get("content", "") if meta else "").lower()
    body = clean_text(soup.get_text(" ", strip=True))[:8000].lower()
    score = 0
    for token in tokens:
        flat = re.sub(r"[^a-z0-9]", "", token)
        if flat and flat in re.sub(r"[^a-z0-9]", "", host):
            score += 5
        if token in title:
            score += 4
        elif token in desc:
            score += 2
        elif token in body:
            score += 1
    full = re.sub(r"[^a-z0-9]", "", clean_text(company_name).lower())
    if full and full in re.sub(r"[^a-z0-9]", "", host):
        score += 7
    return score


def _external_company_link_from_parent(company_name, row_source, parent_website):
    row_source = normalize_url(row_source)
    if not row_source or not same_domain(row_source, parent_website):
        return ""
    page = fetch_best_page(row_source)
    html = page.get("html", "")
    if not html:
        return ""
    tokens = company_tokens(company_name)
    candidates = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = urljoin(page.get("url") or row_source, a.get("href"))
        if not normalize_url(href) or same_domain(href, parent_website):
            continue
        text = clean_text(a.get_text(" ", strip=True)).lower()
        host = hostname(href)
        score = sum(4 for t in tokens if t in text) + sum(3 for t in tokens if t in host.replace("-", ""))
        if score:
            candidates.append((score, root_url(href)))
    return sorted(candidates, reverse=True)[0][1] if candidates else ""


def resolve_company_website(company_name, manual_website="", manual_content_url="", row=None, parent_website=""):
    """Resolve the operating company's official website.

    Manual inputs are deliberately authoritative. Automatic candidates are identity-checked.
    """
    manual_website = normalize_url(manual_website)
    manual_content_url = normalize_url(manual_content_url)
    row = row or {}

    if manual_content_url:
        return {
            "website": root_url(manual_content_url),
            "source": "Manual content-page URL",
            "confidence": "High",
            "verified": True,
            "diagnostic": "The exact first-party content URL supplied by the user established the company domain.",
        }
    if manual_website:
        return {
            "website": root_url(manual_website),
            "source": "Manual company URL",
            "confidence": "High",
            "verified": True,
            "diagnostic": "The user supplied the official company website.",
        }

    # Structured portfolio exports sometimes carry the operating-company URL directly.
    for key in ["Website", "website", "Company Website", "Company URL", "URL", "Homepage", "Domain"]:
        value = normalize_url(row.get(key, ""))
        if value and not same_domain(value, parent_website):
            return {
                "website": root_url(value), "source": "Portfolio record URL",
                "confidence": "High", "verified": True,
                "diagnostic": f"Official-looking external URL was present in portfolio field '{key}'.",
            }

    row_source = normalize_url(row.get("Source", ""))
    if row_source and not same_domain(row_source, parent_website):
        return {
            "website": root_url(row_source), "source": "Portfolio source URL",
            "confidence": "High", "verified": True,
            "diagnostic": "The portfolio record points directly to an external company domain.",
        }

    discovered = _external_company_link_from_parent(company_name, row_source, parent_website)
    if discovered:
        return {
            "website": discovered, "source": "PE portfolio company page",
            "confidence": "High", "verified": True,
            "diagnostic": "The PE firm's portfolio detail page linked to the operating-company website.",
        }

    # Intuitive company-name domains: Seismic -> seismic.com; Fleet Data Centers -> fleetdatacenters.com.
    for candidate in company_domain_candidates(company_name):
        page = fetch_best_page(candidate)
        if not page.get("ok") or not page.get("html"):
            continue
        final = root_url(page.get("url") or candidate)
        if parent_website and same_domain(final, parent_website):
            continue
        score = _identity_score(company_name, final, page.get("html", ""))
        if score >= 6:
            return {
                "website": final,
                "source": "Company-name domain discovery",
                "confidence": "High" if score >= 12 else "Medium",
                "verified": True,
                "diagnostic": f"Loaded and identity-checked {hostname(final)} (score {score}).",
            }

    return {
        "website": "",
        "source": "Unresolved",
        "confidence": "Unresolved",
        "verified": False,
        "diagnostic": "Automatic domain discovery did not establish a sufficiently confident company website. Supply the company URL or exact content page.",
    }


# -----------------------------------------------------------------------------
# Source-page discovery
# -----------------------------------------------------------------------------
def _candidate_source_links_from_html(html, base_url, website):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, a.get("href")))
        if not href or not same_domain(href, website):
            continue
        text = clean_text(a.get_text(" ", strip=True))
        hay = f"{text} {urlparse(href).path}".lower()
        score = 0
        for label, terms in SOURCE_TERMS.items():
            for term in terms:
                if term in hay:
                    score = max(score, 5 + len(term) / 10)
        if not score:
            continue
        # Prefer section landing pages over individual articles at this stage.
        segments = [x for x in urlparse(href).path.split("/") if x]
        depth = len(segments)
        if depth <= 2:
            score += 4
        elif depth >= 3:
            score -= 2
        if segments and any(segments[-1] == x for x in ["news", "newsroom", "press", "press-releases", "media", "insights", "resources", "resource", "blog", "research", "articles", "stories", "updates"]):
            score += 3
        key = href.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append({"url": href, "label": text or _source_kind(text, href), "kind": _source_kind(text, href), "score": score})
    return sorted(out, key=lambda x: x["score"], reverse=True)


def _candidate_source_links_from_markdown(markdown, website):
    out, seen = [], set()
    for m in re.finditer(r"\[([^\]\n]{1,250})\]\((https?://[^)\s]+)\)", markdown or ""):
        title, href = clean_text(m.group(1)), normalize_url(m.group(2))
        if not href or not same_domain(href, website):
            continue
        hay = f"{title} {urlparse(href).path}".lower()
        if not any(x in hay for x in SOURCE_PATH_TERMS):
            continue
        key = href.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append({"url": href, "label": title, "kind": _source_kind(title, href), "score": 5})
    return out


def _is_source_page(page, website):
    if not page.get("ok"):
        return False
    final = page.get("url", "")
    if final and not same_domain(final, website):
        return False
    html = page.get("html", "")
    markdown = page.get("markdown", "")
    text = clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True) if html else markdown).lower()
    path = urlparse(final or website).path.lower()
    return any(k in f"{path} {text[:5000]}" for k in SOURCE_PATH_TERMS)


def discover_company_content_pages(company_name, website, explicit_content_url=""):
    website = root_url(website)
    explicit_content_url = normalize_url(explicit_content_url)
    result = {
        "pages": [],
        "methods": [],
        "errors": [],
    }
    if not website:
        result["errors"].append("No official company website is available.")
        return result

    pages, seen = [], set()
    if explicit_content_url:
        if same_domain(explicit_content_url, website):
            pages.append({
                "url": explicit_content_url,
                "label": "User-supplied content page",
                "kind": _source_kind("", explicit_content_url),
                "score": 100,
                "discovered_by": "Manual",
            })
            seen.add(explicit_content_url.rstrip("/"))
        else:
            result["errors"].append(
                f"The supplied content page is on {hostname(explicit_content_url)}, not {hostname(website)}."
            )

    # Render the homepage when necessary so JS navigation is visible.
    home = fetch_best_page(website)
    if home.get("ok"):
        result["methods"].append(f"Homepage: {home.get('method')}")
        candidates = _candidate_source_links_from_html(home.get("html", ""), home.get("url") or website, website)
        if home.get("markdown"):
            candidates += _candidate_source_links_from_markdown(home.get("markdown", ""), website)
        for item in candidates:
            key = item["url"].rstrip("/")
            if key not in seen:
                item["discovered_by"] = "Homepage navigation"
                pages.append(item)
                seen.add(key)
    else:
        result["errors"].append(f"Homepage could not be read: {home.get('error','')}")

    # If navigation did not expose enough content hubs, test common names on the confirmed domain.
    if not pages:
        for path in COMMON_SOURCE_PATHS:
            candidate = urljoin(website, path.lstrip("/"))
            key = candidate.rstrip("/")
            if key in seen:
                continue
            page = fetch_best_page(candidate)
            if _is_source_page(page, website):
                final = normalize_url(page.get("url") or candidate)
                final_key = final.rstrip("/")
                if final_key not in seen:
                    pages.append({
                        "url": final,
                        "label": _source_kind("", final),
                        "kind": _source_kind("", final),
                        "score": 4,
                        "discovered_by": "Common path",
                    })
                    seen.add(final_key)
            if len(pages) >= 8:
                break

    # Keep the exact user-supplied page first; otherwise rank likely corporate news/insights hubs.
    pages = sorted(pages, key=lambda x: x.get("score", 0), reverse=True)
    result["pages"] = pages[:10]
    return result


# -----------------------------------------------------------------------------
# Article extraction
# -----------------------------------------------------------------------------
GENERIC_SECTION_SLUGS = {
    "news", "newsroom", "press", "press-releases", "press_release", "press_release",
    "media", "insights", "insight", "resources", "resource", "blog", "research",
    "articles", "stories", "updates", "publications", "knowledge-hub",
    "knowledge-center", "knowledge-centre", "events", "webinars", "reports",
    "case-studies", "customer-stories",
}


def _path_segments(url):
    return [x for x in urlparse(url).path.lower().strip("/").split("/") if x]


def _inside_navigation(a):
    """Reject global navigation/footer/sidebar links.

    Modern JS sites often render their full navigation into page.content().
    Those links used to be mistaken for article cards.
    """
    node = a
    for _ in range(8):
        node = getattr(node, "parent", None)
        if node is None:
            break
        name = str(getattr(node, "name", "") or "").lower()
        if name in {"nav", "header", "footer", "aside"}:
            return True
        attrs = getattr(node, "attrs", {}) or {}
        classes = " ".join(attrs.get("class", []) if isinstance(attrs.get("class", []), list) else [str(attrs.get("class", ""))]).lower()
        ident = str(attrs.get("id", "") or "").lower()
        role = str(attrs.get("role", "") or "").lower()
        hay = f"{classes} {ident} {role}"
        if any(x in hay for x in [
            "navbar", "navigation", "site-nav", "site_header", "site-header",
            "main-menu", "mega-menu", "megamenu", "footer", "breadcrumb",
            "sidebar", "utility-nav", "mobile-menu",
        ]):
            return True
    return False


def _looks_like_section_landing(href):
    segments = _path_segments(href)
    if not segments:
        return True
    last = segments[-1].replace("_", "-")
    return last in GENERIC_SECTION_SLUGS


def _article_within_source_scope(href, source_url, source_kind):
    """Keep individual content items and reject unrelated same-domain navigation.

    When the user explicitly supplies /newsroom/, /insights/, /resources/, etc.,
    descendants of that hub are authoritative. For newsroom/news/press pages,
    we are particularly strict because unrelated site navigation was the source
    of false records such as "Professional Services".
    """
    href_path = urlparse(href).path.lower().rstrip("/")
    source_path = urlparse(source_url).path.lower().rstrip("/")

    if not href_path or href_path == source_path:
        return False
    if _looks_like_section_landing(href):
        return False

    # Exact hub descendants are the strongest evidence.
    if source_path and href_path.startswith(source_path + "/"):
        return True

    # For corporate newsroom / press pages, do not wander elsewhere on the site.
    if source_kind in {"Newsroom", "News", "Press", "Media"}:
        return False

    # For more generic hubs (Resources / Insights / Blog / Research), allow known
    # article-like paths on the same domain because some CMSs route content under
    # a sibling singular path such as /resource/<slug>.
    return any(
        token in href_path
        for token in [
            "/press-release/", "/press-releases/", "/news/", "/newsroom/",
            "/blog/", "/insight/", "/insights/", "/resource/", "/resources/",
            "/research/", "/article/", "/articles/", "/story/", "/stories/",
            "/update/", "/updates/",
        ]
    )


def _best_anchor_title(a):
    text = clean_text(a.get_text(" ", strip=True))
    if text and text.lower() not in NON_ARTICLE_TITLES and len(text) >= 8:
        return text[:300]
    parent = a.find_parent(["article", "li", "section", "div"])
    if parent:
        heading = parent.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading:
            candidate = clean_text(heading.get_text(" ", strip=True))
            if candidate.lower() not in NON_ARTICLE_TITLES and len(candidate) >= 8:
                return candidate[:300]
    return ""


def _card_context(a):
    node = a
    for _ in range(5):
        node = node.parent if node else None
        if not node:
            break
        text = clean_text(node.get_text(" ", strip=True))
        if 25 <= len(text) <= 1800:
            return text
    return ""


def _article_candidate_score(title, href, source_url, context):
    title_l = clean_text(title).lower()
    path = urlparse(href).path.lower().rstrip("/")
    source_path = urlparse(source_url).path.lower().rstrip("/")
    if not title or title_l in NON_ARTICLE_TITLES:
        return -50
    if href.rstrip("/") == source_url.rstrip("/"):
        return -50
    score = 0
    if 15 <= len(title) <= 220:
        score += 4
    if any(x in path for x in ["press-release", "press_releases", "/news/", "/newsroom/", "/blog/", "/insight", "/resource", "/research", "/article", "/story", "/update"]):
        score += 4
    if source_path and path.startswith(source_path + "/"):
        score += 3
    if _date_from_text(context):
        score += 3
    if any(x in title_l for x in ["cookie", "privacy", "terms", "careers", "contact", "subscribe", "newsletter"]):
        score -= 8
    return score


def _extract_jsonld_articles(html, base_url, website, source_kind):
    rows = []
    if not html:
        return rows
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text("", strip=True) or "{}")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for obj in stack:
            if isinstance(obj, dict) and isinstance(obj.get("@graph"), list):
                stack.extend(obj["@graph"])
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if not any(x in {"NewsArticle", "Article", "BlogPosting", "Report"} for x in types if x):
                continue
            title = clean_text(obj.get("headline") or obj.get("name"))
            link = obj.get("url") or ""
            mep = obj.get("mainEntityOfPage")
            if isinstance(mep, dict):
                link = link or mep.get("@id") or mep.get("url")
            link = normalize_url(urljoin(base_url, link or base_url))
            if not title or not link or not same_domain(link, website):
                continue
            summary = clean_text(obj.get("description"))[:1200]
            rows.append({
                "title": title[:300],
                "summary": summary,
                "link": link,
                "published": clean_text(obj.get("datePublished")),
                "source": f"Official · {hostname(website)}",
                "source_section": source_kind,
                "signal_type": classify_news_signal(f"{title} {summary}"),
                "credibility": "Official company source",
            })
    return rows


def _extract_html_articles(html, final_url, source_url, website, source_kind):
    """Extract article CARD TITLES from a rendered/listing page only.

    We intentionally do not open the individual article URLs here. The platform
    needs the headline, optional listing-page date, and click-through URL; loading
    every article body is slower, noisier, and unnecessary for the news feed.
    """
    rows = []
    soup = BeautifulSoup(html or "", "html.parser")

    # Structured metadata on a listing page can contain genuine article records.
    # Keep only title/date/link; deliberately discard full descriptions.
    for row in _extract_jsonld_articles(html, final_url, website, source_kind):
        href = row.get("link", "")
        if not _article_within_source_scope(href, source_url, source_kind):
            continue
        row["summary"] = ""
        rows.append(row)

    for a in soup.find_all("a", href=True):
        if _inside_navigation(a):
            continue

        href = normalize_url(urljoin(final_url, a.get("href")))
        if not href or not same_domain(href, website):
            continue
        if not _article_within_source_scope(href, source_url, source_kind):
            continue

        title = _best_anchor_title(a)
        if not title:
            continue

        title_clean = clean_text(title)
        title_l = title_clean.lower().strip(" -|·:")
        if title_l in NON_ARTICLE_TITLES:
            continue

        # Headline-like text, not menu labels/buttons.
        word_count = len(re.findall(r"\b[\w’'-]+\b", title_clean))
        if len(title_clean) < 12 or word_count < 3:
            continue

        context = _card_context(a)
        score = _article_candidate_score(title_clean, href, source_url, context)
        if score < 6:
            continue

        rows.append({
            "title": title_clean[:300],
            "summary": "",  # title-only feed by design
            "link": href,
            "published": _date_from_text(context),
            "source": f"Official · {hostname(website)}",
            "source_section": source_kind,
            "signal_type": classify_news_signal(title_clean),
            "credibility": "Official company source",
            "_score": score,
        })
    return rows

def _extract_markdown_articles(markdown, source_url, website, source_kind):
    rows = []
    for m in re.finditer(r"\[([^\]\n]{5,300})\]\((https?://[^)\s]+)\)", markdown or ""):
        title, href = clean_text(m.group(1)), normalize_url(m.group(2))
        if not href or not same_domain(href, website):
            continue
        if not _article_within_source_scope(href, source_url, source_kind):
            continue
        title_l = title.lower().strip(" -|·:")
        if title_l in NON_ARTICLE_TITLES:
            continue
        if len(title) < 12 or len(re.findall(r"\b[\w’'-]+\b", title)) < 3:
            continue
        if _article_candidate_score(title, href, source_url, title) < 6:
            continue
        rows.append({
            "title": title[:300],
            "summary": "",
            "link": href,
            "published": "",
            "source": f"Official · {hostname(website)}",
            "source_section": source_kind,
            "signal_type": classify_news_signal(title),
            "credibility": "Official company source",
        })
    return rows

def _dedupe_and_sort(rows):
    seen, clean = set(), []
    for row in rows:
        link_key = (row.get("link") or "").rstrip("/").lower()
        title_key = re.sub(r"\W+", " ", row.get("title", "").lower()).strip()
        key = link_key or title_key
        if not key or key in seen:
            continue
        seen.add(key)
        row.pop("_score", None)
        clean.append(row)
    # Dated items first/newest first, then retain extraction order for undated items.
    indexed = list(enumerate(clean))
    indexed.sort(key=lambda pair: (_date_sort_value(pair[1].get("published")), -pair[0]), reverse=True)
    return [x[1] for x in indexed]


def scrape_source_page(source, website, limit=100):
    """Scrape one first-party content hub.

    Primary path: Crawlee + Playwright. It renders JavaScript, scrolls, clicks
    load-more / pagination controls, and gathers the full listing before we sort.

    Fallback path: the existing HTTP / direct Playwright / rendered-reader logic.
    """
    source_url = normalize_url(source.get("url") if isinstance(source, dict) else source)
    source_kind = source.get("kind") if isinstance(source, dict) else _source_kind("", source_url)
    result = {
        "url": source_url,
        "kind": source_kind,
        "method": "",
        "ok": False,
        "article_count": 0,
        "articles": [],
        "error": "",
        "passes": 0,
    }

    if not source_url or not website or not same_domain(source_url, website):
        result["error"] = "Source URL is missing or is not on the confirmed company domain."
        return result

    # 1) Primary browser crawler.
    crawled = crawl_source_with_crawlee(
        source_url,
        website,
        source_kind,
        max_passes=14,
    )
    result["method"] = crawled.get("method", "Crawlee + Playwright")
    result["passes"] = crawled.get("passes", 0)

    rows = _rows_from_crawlee_anchors(
        crawled.get("anchors", []),
        source_url,
        website,
        source_kind,
    )

    if rows:
        rows = _dedupe_and_sort(rows)[:limit]
        result.update({
            "ok": True,
            "article_count": len(rows),
            "articles": rows,
            "url": crawled.get("url") or source_url,
        })
        return result

    # 2) Fallback: preserve the older lightweight retrieval paths.
    fallback_errors = []
    if crawled.get("error"):
        fallback_errors.append(crawled["error"])

    page = fetch_best_page(source_url)
    if page.get("ok"):
        final = page.get("url") or source_url
        if page.get("html"):
            rows.extend(
                _extract_html_articles(
                    page["html"],
                    final,
                    source_url,
                    website,
                    source_kind,
                )
            )
        if page.get("markdown"):
            rows.extend(
                _extract_markdown_articles(
                    page["markdown"],
                    source_url,
                    website,
                    source_kind,
                )
            )
        if rows:
            result["method"] = f"{result['method']} → {page.get('method','fallback')}"
    elif page.get("error"):
        fallback_errors.append(page["error"])

    rows = _dedupe_and_sort(rows)[:limit]
    result.update({
        "ok": bool(rows),
        "article_count": len(rows),
        "articles": rows,
    })

    if not rows:
        result["error"] = " | ".join(fallback_errors) or (
            "The page loaded, but no article-like same-domain links could be extracted."
        )
    return result


def scrape_company_first_party_news(company_name, website, exact_content_url="", max_sources=5, max_articles=100):
    """Discover the company's first-party content hubs and return recent articles.

    Returns (articles, status). The status object is designed to be shown directly
    in Streamlit so source failures never happen silently.
    """
    website = root_url(website)
    discovery = discover_company_content_pages(company_name, website, exact_content_url)
    status = {
        "website": website,
        "domain": hostname(website),
        "source_pages": discovery.get("pages", []),
        "source_results": [],
        "errors": list(discovery.get("errors", [])),
        "article_count": 0,
    }
    all_rows = []

    # If the user supplied an exact newsroom / insights / resources page, that
    # page is authoritative. Do not mix in unrelated automatically discovered
    # hubs unless the exact page produces zero usable article titles.
    discovered_pages = discovery.get("pages", [])
    exact_url = normalize_url(exact_content_url)
    if exact_url:
        exact_sources = [x for x in discovered_pages if normalize_url(x.get("url", "")) == exact_url]
        fallback_sources = [x for x in discovered_pages if normalize_url(x.get("url", "")) != exact_url]
        sources_to_try = exact_sources[:1]
    else:
        fallback_sources = []
        sources_to_try = discovered_pages[:max_sources]

    for source in sources_to_try:
        result = scrape_source_page(source, website, limit=100)
        status["source_results"].append({
            "url": result["url"],
            "kind": result["kind"],
            "method": result["method"],
            "ok": result["ok"],
            "article_count": result["article_count"],
            "passes": result.get("passes", 0),
            "error": result["error"],
        })
        if result["ok"]:
            all_rows.extend(result["articles"])
        elif result["error"]:
            status["errors"].append(f"{result['url']}: {result['error']}")

    # If an explicitly supplied page genuinely yielded nothing, try the other
    # discovered hubs as a fallback. Otherwise never pollute its results.
    if exact_url and not all_rows:
        for source in fallback_sources[:max_sources]:
            result = scrape_source_page(source, website, limit=100)
            status["source_results"].append({
                "url": result["url"],
                "kind": result["kind"],
                "method": result["method"],
                "ok": result["ok"],
                "article_count": result["article_count"],
                "error": result["error"],
            })
            if result["ok"]:
                all_rows.extend(result["articles"])
            elif result["error"]:
                status["errors"].append(f"{result['url']}: {result['error']}")

    rows = _dedupe_and_sort(all_rows)[:max_articles]
    for row in rows:
        row["source"] = f"Official · {hostname(website)}"
        row["credibility"] = "Official company source"
    status["article_count"] = len(rows)
    return rows, status
