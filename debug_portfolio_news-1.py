#!/usr/bin/env python3
"""
debug_portfolio_news.py

Standalone diagnostic for the PE Intelligence portfolio-company news pipeline.

Run from the SAME folder as:
    app.py
    pe_core.py
    portfolio_intel.py

Example:
    python debug_portfolio_news.py \
      --company "Seismic" \
      --website "https://www.seismic.com" \
      --page "https://www.seismic.com/uk/newsroom/"

What it checks:
1. Which portfolio_intel.py Python is actually importing.
2. Direct HTTP access to the homepage and supplied news page.
3. Redirects / status / content type / HTML size.
4. Whether the page looks JavaScript-rendered.
5. Same-domain article-like links visible in raw HTML.
6. robots.txt + sitemap discovery.
7. Jina Reader fallback.
8. Playwright availability/browser rendering (if installed).
9. The CURRENT portfolio_intel.py official-source discovery functions.
10. Whether discover_company_official_news() actually returns first-party items.

It also writes raw debug artifacts to ./debug_portfolio_news_output/
so you can inspect what each retrieval method actually saw.
"""

import argparse
import importlib
import inspect
import json
import os
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

CONTENT_WORDS = (
    "news", "newsroom", "press", "release", "insight", "resource",
    "blog", "research", "article", "story", "update", "media",
)

DYNAMIC_MARKERS = (
    "loading component",
    "__next_data__",
    "data-reactroot",
    "__nuxt__",
    "webpack",
)


def line(char="=", width=88):
    print(char * width)


def heading(text):
    print()
    line()
    print(text)
    line()


def good(msg):
    print(f"[OK]   {msg}")


def warn(msg):
    print(f"[WARN] {msg}")


def bad(msg):
    print(f"[FAIL] {msg}")


def info(msg):
    print(f"[INFO] {msg}")


def host(url):
    try:
        return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    except Exception:
        return ""


def root_url(url):
    p = urlparse(url)
    if p.scheme in {"http", "https"} and p.netloc:
        return f"{p.scheme}://{p.netloc}/"
    return ""


def same_domain(a, b):
    return bool(host(a) and host(a) == host(b))


def save_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8", errors="ignore")


def request_url(url, timeout=25):
    result = {
        "requested_url": url,
        "ok": False,
        "status": None,
        "final_url": "",
        "content_type": "",
        "html": "",
        "error": "",
    }
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        result["status"] = r.status_code
        result["final_url"] = r.url
        result["content_type"] = r.headers.get("content-type", "")
        result["html"] = r.text
        result["ok"] = r.ok
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def dynamic_markers(html):
    low = (html or "").lower()
    return [x for x in DYNAMIC_MARKERS if x in low]


def visible_text(html):
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    except Exception:
        return ""


def raw_article_links(html, base_url, website):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href"))
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        if not same_domain(href, website):
            continue
        hay = f"{urlparse(href).path} {text}".lower()
        if not any(word in hay for word in CONTENT_WORDS):
            continue
        key = href.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": text[:240], "url": href})
    return out


def parse_sitemap_bytes(payload):
    try:
        root = ET.fromstring(payload)
    except Exception:
        return "", []
    locs = []
    for el in root.iter():
        if str(el.tag).lower().endswith("loc") and el.text:
            locs.append(el.text.strip())
    return str(root.tag).lower(), locs


def discover_sitemaps(website, output_dir, max_maps=20, max_urls=1000):
    root = root_url(website)
    candidates = [
        urljoin(root, "sitemap.xml"),
        urljoin(root, "sitemap_index.xml"),
        urljoin(root, "sitemap-index.xml"),
        urljoin(root, "wp-sitemap.xml"),
    ]

    robots = request_url(urljoin(root, "robots.txt"), timeout=15)
    if robots["ok"]:
        save_text(output_dir / "robots.txt", robots["html"])
        for ln in robots["html"].splitlines():
            if ln.lower().startswith("sitemap:"):
                u = ln.split(":", 1)[1].strip()
                if u and same_domain(u, root):
                    candidates.insert(0, u)

    queue = list(dict.fromkeys(candidates))
    visited = set()
    article_like = []
    all_urls = []

    while queue and len(visited) < max_maps and len(all_urls) < max_urls:
        sm = queue.pop(0)
        if sm in visited or not same_domain(sm, root):
            continue
        visited.add(sm)

        try:
            r = requests.get(sm, headers=HEADERS, timeout=18, allow_redirects=True)
            if not r.ok:
                continue
            tag, locs = parse_sitemap_bytes(r.content)
            if not locs:
                continue

            filename = "sitemap_" + str(len(visited)) + ".xml"
            save_text(output_dir / filename, r.text)

            if "sitemapindex" in tag:
                for u in locs:
                    if same_domain(u, root) and u not in visited:
                        queue.append(u)
            else:
                for u in locs:
                    if same_domain(u, root):
                        all_urls.append(u)
                        low = urlparse(u).path.lower()
                        if any(w in low for w in CONTENT_WORDS):
                            article_like.append(u)
        except Exception:
            continue

    return {
        "maps_checked": list(visited),
        "all_urls_count": len(all_urls),
        "article_like_count": len(article_like),
        "article_like_urls": article_like[:150],
    }


def jina_reader(url, output_dir, timeout=35):
    reader_url = "https://r.jina.ai/" + url
    result = {
        "ok": False,
        "status": None,
        "bytes": 0,
        "error": "",
        "text": "",
        "links": [],
    }
    try:
        headers = dict(HEADERS)
        headers["Accept"] = "text/plain, text/markdown, application/json"
        headers["X-Return-Format"] = "markdown"

        key = os.getenv("JINA_API_KEY", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        r = requests.get(reader_url, headers=headers, timeout=timeout)
        result["status"] = r.status_code
        result["ok"] = r.ok
        result["bytes"] = len(r.content)
        result["text"] = r.text

        save_text(output_dir / "jina_reader.txt", r.text)

        link_re = re.compile(r"\[([^\]\n]{3,300})\]\((https?://[^)\s]+)\)")
        seen = set()
        for m in link_re.finditer(r.text):
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            link = m.group(2).replace("&amp;", "&")
            if link in seen:
                continue
            seen.add(link)
            result["links"].append({"title": title[:240], "url": link})
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def playwright_test(url, website, output_dir):
    result = {
        "package_installed": False,
        "browser_started": False,
        "engine": "",
        "error": "",
        "html_bytes": 0,
        "visible_text_bytes": 0,
        "same_domain_content_links": [],
    }

    try:
        from playwright.sync_api import sync_playwright
        result["package_installed"] = True
    except Exception as exc:
        result["error"] = f"Playwright import failed: {exc!r}"
        return result

    try:
        with sync_playwright() as p:
            browser = None
            errors = []

            for args in (
                {"headless": True},
                {"headless": True, "channel": "chrome"},
            ):
                try:
                    browser = p.chromium.launch(**args)
                    result["browser_started"] = True
                    result["engine"] = (
                        "Google Chrome" if args.get("channel") == "chrome"
                        else "Playwright Chromium"
                    )
                    break
                except Exception as exc:
                    errors.append(str(exc))

            if not browser:
                result["error"] = " | ".join(errors)[-2500:]
                return result

            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=HEADERS["User-Agent"],
                locale="en-GB",
            )
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(3500)

                html = page.content()
                try:
                    text = page.locator("body").inner_text(timeout=7000)
                except Exception:
                    text = ""

                result["html_bytes"] = len(html.encode("utf-8", "ignore"))
                result["visible_text_bytes"] = len(text.encode("utf-8", "ignore"))

                save_text(output_dir / "playwright_rendered.html", html)
                save_text(output_dir / "playwright_visible_text.txt", text)

                result["same_domain_content_links"] = raw_article_links(
                    html, page.url, website
                )[:100]
            finally:
                browser.close()

    except Exception as exc:
        result["error"] = traceback.format_exc()[-4000:]

    return result


def call_portfolio_intel(company, website, page, output_dir):
    result = {
        "import_ok": False,
        "module_file": "",
        "functions": {},
        "errors": {},
    }

    try:
        pi = importlib.import_module("portfolio_intel")
        result["import_ok"] = True
        result["module_file"] = str(Path(inspect.getfile(pi)).resolve())
    except Exception:
        result["errors"]["import"] = traceback.format_exc()
        return result

    # Clear Streamlit cache for relevant functions if available so this run
    # does not simply replay stale empty results.
    for fn_name in [
        "fetch_public_html",
        "fetch_rendered_reader",
        "fetch_playwright_rendered",
        "discover_playwright_page_articles",
        "discover_rendered_page_articles",
        "discover_sitemap_content_urls",
        "discover_official_source_pages",
        "discover_company_official_news",
        "diagnose_first_party_source",
    ]:
        fn = getattr(pi, fn_name, None)
        try:
            if fn is not None and hasattr(fn, "clear"):
                fn.clear()
        except Exception:
            pass

    # 1. Built-in diagnostic if present.
    fn = getattr(pi, "diagnose_first_party_source", None)
    if fn:
        try:
            value = fn(website, page, company)
            result["functions"]["diagnose_first_party_source"] = value
        except Exception:
            result["errors"]["diagnose_first_party_source"] = traceback.format_exc()

    # 2. Source page discovery.
    fn = getattr(pi, "discover_official_source_pages", None)
    if fn:
        try:
            value = fn(website, company, (page,))
            result["functions"]["discover_official_source_pages"] = value
        except Exception:
            result["errors"]["discover_official_source_pages"] = traceback.format_exc()

    # 3. Final official news function the app should consume.
    fn = getattr(pi, "discover_company_official_news", None)
    if fn:
        try:
            value = fn(website, company, (page,))
            # Usually returns (news, working_pages)
            if isinstance(value, tuple) and len(value) == 2:
                news, pages = value
            else:
                news, pages = value, []
            result["functions"]["discover_company_official_news"] = {
                "news_count": len(news or []),
                "pages_count": len(pages or []),
                "pages": pages,
                "sample_news": (news or [])[:15],
            }
            save_text(
                output_dir / "portfolio_intel_news.json",
                json.dumps(news or [], indent=2, default=str),
            )
        except Exception:
            result["errors"]["discover_company_official_news"] = traceback.format_exc()

    return result


def print_list(items, limit=10):
    for i, item in enumerate((items or [])[:limit], 1):
        if isinstance(item, dict):
            title = item.get("title", "")
            url = item.get("url") or item.get("link", "")
            print(f"  {i:>2}. {title[:100]}")
            if url:
                print(f"      {url}")
        else:
            print(f"  {i:>2}. {item}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", default="Seismic")
    parser.add_argument("--website", default="https://www.seismic.com")
    parser.add_argument("--page", default="https://www.seismic.com/uk/newsroom/")
    parser.add_argument(
        "--skip-playwright",
        action="store_true",
        help="Skip local real-browser test.",
    )
    args = parser.parse_args()

    company = args.company.strip()
    website = args.website.strip().rstrip("/") + "/"
    page = args.page.strip()

    output_dir = Path.cwd() / "debug_portfolio_news_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    full_report = {
        "company": company,
        "website": website,
        "page": page,
        "cwd": str(Path.cwd()),
        "python": sys.executable,
    }

    heading("0. ENVIRONMENT / FILE CHECK")
    print(f"Python executable : {sys.executable}")
    print(f"Working directory : {Path.cwd()}")
    print(f"Company           : {company}")
    print(f"Website           : {website}")
    print(f"News page         : {page}")
    print(f"Output directory  : {output_dir}")

    local_pi = Path.cwd() / "portfolio_intel.py"
    if local_pi.exists():
        good(f"portfolio_intel.py exists here: {local_pi}")
    else:
        bad("portfolio_intel.py is NOT in the current folder. You may be testing the wrong project/environment.")

    if not same_domain(website, page):
        bad(f"Domain mismatch: {host(website)} != {host(page)}")
    else:
        good(f"Domain matches: {host(website)}")

    heading("1. DIRECT HTTP — COMPANY HOMEPAGE")
    homepage = request_url(website)
    full_report["homepage"] = {k: v for k, v in homepage.items() if k != "html"}
    print(json.dumps(full_report["homepage"], indent=2))
    save_text(output_dir / "homepage_raw.html", homepage["html"])
    if homepage["ok"]:
        good(f"Homepage loaded: HTTP {homepage['status']} → {homepage['final_url']}")
    else:
        bad(f"Homepage failed: {homepage['error'] or homepage['status']}")

    heading("2. DIRECT HTTP — SUPPLIED NEWS / INSIGHTS PAGE")
    direct = request_url(page)
    direct_summary = {k: v for k, v in direct.items() if k != "html"}
    direct_summary["html_bytes"] = len(direct["html"].encode("utf-8", "ignore"))
    direct_summary["dynamic_markers"] = dynamic_markers(direct["html"])
    direct_summary["visible_text_preview"] = visible_text(direct["html"])[:600]
    full_report["direct_news_page"] = direct_summary
    print(json.dumps(direct_summary, indent=2))
    save_text(output_dir / "news_page_raw.html", direct["html"])

    raw_links = raw_article_links(
        direct["html"],
        direct["final_url"] or page,
        website,
    )
    full_report["raw_html_article_links"] = raw_links

    print(f"\nSame-domain news/resource-like links visible in raw HTML: {len(raw_links)}")
    print_list(raw_links, 12)

    if direct_summary["dynamic_markers"]:
        warn(
            "Dynamic-rendering markers detected: "
            + ", ".join(direct_summary["dynamic_markers"])
        )
    if len(raw_links) < 3:
        warn("Raw HTML exposes very few article links. A JS/rendered or sitemap fallback is likely required.")

    heading("3. ROBOTS.TXT + SITEMAPS")
    sitemap = discover_sitemaps(website, output_dir)
    full_report["sitemap"] = sitemap
    print(f"Sitemap files checked       : {len(sitemap['maps_checked'])}")
    print(f"Total same-domain URLs seen : {sitemap['all_urls_count']}")
    print(f"News/resource-like URLs     : {sitemap['article_like_count']}")
    print_list(sitemap["article_like_urls"], 15)

    if sitemap["article_like_count"] > 0:
        good("Sitemap contains candidate first-party content URLs.")
    else:
        warn("No news/resource-like URLs found in tested sitemaps.")

    heading("4. JINA RENDERED READER")
    jina = jina_reader(page, output_dir)
    jina_summary = {k: v for k, v in jina.items() if k != "text"}
    same_jina = [
        x for x in jina["links"]
        if same_domain(x.get("url", ""), website)
        and any(w in urlparse(x.get("url", "")).path.lower() for w in CONTENT_WORDS)
    ]
    jina_summary["same_domain_content_links"] = same_jina[:100]
    full_report["jina"] = jina_summary
    print(f"HTTP status                    : {jina['status']}")
    print(f"Reader success                 : {jina['ok']}")
    print(f"Response bytes                 : {jina['bytes']}")
    print(f"All Markdown links             : {len(jina['links'])}")
    print(f"Same-domain content-like links : {len(same_jina)}")
    if jina["error"]:
        print(f"Error                          : {jina['error']}")
    print_list(same_jina, 12)

    if jina["ok"]:
        good("Jina Reader returned content.")
    else:
        warn("Jina Reader did not return usable content.")

    if not args.skip_playwright:
        heading("5. PLAYWRIGHT / REAL BROWSER")
        pw = playwright_test(page, website, output_dir)
        full_report["playwright"] = pw
        print(f"Python package installed : {pw['package_installed']}")
        print(f"Browser started          : {pw['browser_started']}")
        print(f"Engine                   : {pw['engine']}")
        print(f"Rendered HTML bytes      : {pw['html_bytes']}")
        print(f"Visible text bytes       : {pw['visible_text_bytes']}")
        print(f"Content-like links       : {len(pw['same_domain_content_links'])}")
        if pw["error"]:
            print(f"Error:\n{pw['error']}")
        print_list(pw["same_domain_content_links"], 12)

        if pw["browser_started"]:
            good("Real browser executed the page.")
        elif pw["package_installed"]:
            bad("Playwright is installed but no browser could start.")
            print("      Usually fix with: python -m playwright install chromium")
        else:
            warn("Playwright is not installed. This is okay if your current build does not use it.")
    else:
        full_report["playwright"] = {"skipped": True}

    heading("6. CURRENT portfolio_intel.py — INTEGRATION TEST")
    integration = call_portfolio_intel(company, website, page, output_dir)
    full_report["portfolio_intel"] = integration

    if integration["import_ok"]:
        good(f"Imported portfolio_intel.py from: {integration['module_file']}")
        expected = str((Path.cwd() / "portfolio_intel.py").resolve())
        if integration["module_file"] != expected:
            bad("IMPORTANT: Python imported a DIFFERENT portfolio_intel.py than the file in this folder.")
            print(f"      Expected: {expected}")
            print(f"      Actual:   {integration['module_file']}")
    else:
        bad("Could not import portfolio_intel.py")
        print(integration["errors"].get("import", ""))

    diag = integration["functions"].get("diagnose_first_party_source")
    if diag:
        print("\nBuilt-in diagnose_first_party_source():")
        print(json.dumps(diag, indent=2, default=str))

    pages = integration["functions"].get("discover_official_source_pages")
    if pages is not None:
        print(f"\ndiscover_official_source_pages(): {len(pages or [])} page(s)")
        print_list(pages, 15)

    news_result = integration["functions"].get("discover_company_official_news")
    if news_result:
        print(
            "\ndiscover_company_official_news(): "
            f"{news_result['news_count']} news item(s), "
            f"{news_result['pages_count']} working page(s)"
        )
        print("\nWorking first-party pages:")
        print_list(news_result["pages"], 15)
        print("\nSample official news:")
        print_list(news_result["sample_news"], 15)

        if news_result["news_count"] > 0:
            good("portfolio_intel.py IS extracting first-party news.")
            warn(
                "If Streamlit still shows no official items, the failure is now likely "
                "in app.py/session-state/cache/merge/filter/UI rather than website retrieval."
            )
        else:
            bad("portfolio_intel.py returned ZERO official news items.")
            info("Use the stage results above to see which retrieval layer failed.")
    else:
        warn("discover_company_official_news() was unavailable or raised an error.")

    if integration["errors"]:
        print("\nportfolio_intel function errors:")
        for name, err in integration["errors"].items():
            print(f"\n--- {name} ---")
            print(err)

    heading("7. QUICK FAILURE INTERPRETATION")

    news_count = (
        news_result.get("news_count", 0)
        if isinstance(news_result, dict)
        else 0
    )

    if not direct["ok"]:
        print("→ Direct requests cannot reach the supplied page.")
        print("  Check network, TLS, bot blocking, redirects, or URL.")
    elif len(raw_links) >= 3 and news_count == 0:
        print("→ Raw HTML already contains candidate links, but portfolio_intel returns zero.")
        print("  The bug is probably INSIDE portfolio_intel filtering/extraction.")
    elif sitemap["article_like_count"] > 0 and news_count == 0:
        print("→ Sitemap sees first-party content, but final portfolio_intel output is zero.")
        print("  Check sitemap filtering, official_article_from_url(), or final domain filter.")
    elif jina["ok"] and len(same_jina) > 0 and news_count == 0:
        print("→ Jina sees first-party links, but portfolio_intel returns zero.")
        print("  Check discover_rendered_page_articles() / _content_url() filtering.")
    elif (
        not args.skip_playwright
        and full_report.get("playwright", {}).get("browser_started")
        and len(full_report["playwright"].get("same_domain_content_links", [])) > 0
        and news_count == 0
    ):
        print("→ Real browser sees the article links, but portfolio_intel returns zero.")
        print("  The browser extraction/filtering path is the likely bug.")
    elif news_count > 0:
        print("→ Backend retrieval works.")
        print("  If the Streamlit UI still shows unrelated Google results, debug app.py:")
        print("  - manual override session-state value")
        print("  - cache invalidation")
        print("  - build_portco_account() arguments")
        print("  - merge order")
        print("  - final insights variable used by the Newsroom page")
    else:
        print("→ No layer clearly extracted first-party items.")
        print("  Open the saved raw artifacts in debug_portfolio_news_output/ to inspect responses.")

    report_path = output_dir / "debug_report.json"
    save_text(report_path, json.dumps(full_report, indent=2, default=str))

    heading("DONE")
    print(f"Full report: {report_path}")
    print("Saved artifacts may include:")
    print("  homepage_raw.html")
    print("  news_page_raw.html")
    print("  robots.txt")
    print("  sitemap_*.xml")
    print("  jina_reader.txt")
    print("  playwright_rendered.html")
    print("  playwright_visible_text.txt")
    print("  portfolio_intel_news.json")
    print()
    print("Send me the terminal output OR debug_report.json and I can tell you exactly where it failed.")


if __name__ == "__main__":
    main()
