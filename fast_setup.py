"""
Fast Setup — Crawl a website and extract business info, doctors, services, pricing, and schedules.
Uses requests + BeautifulSoup to scrape, then an LLM to classify/structure the data.
Falls back to Google Cache / web search if direct scraping fails.
"""

import os
import re
import json
import time
from urllib.parse import urljoin, urlparse, quote_plus
import requests
from bs4 import BeautifulSoup

# Load .env if not already loaded
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_key(name):
    """Get API key from env, reading at call time (not import time) so Flask's dotenv works."""
    return os.environ.get(name, "")

MAX_PAGES = 30
MAX_CONTENT_PER_PAGE = 5000
REQUEST_TIMEOUT = 20

# Realistic browser headers to avoid blocks
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def _create_session():
    """Create a requests session with browser-like headers."""
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    s.verify = True
    return s


def _fetch_page(url, session):
    """Fetch a single page and return (html, final_url)."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        ct = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ("text/html" in ct or "text/" in ct or not ct):
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text, resp.url
        print(f"[fast_setup] Non-HTML or error for {url}: status={resp.status_code} ct={ct}", flush=True)
    except requests.exceptions.SSLError:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, verify=False)
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text, resp.url
        except Exception as e2:
            print(f"[fast_setup] SSL retry failed for {url}: {e2}", flush=True)
    except Exception as e:
        print(f"[fast_setup] Failed to fetch {url}: {e}", flush=True)
    return None, url


def _is_spa(html):
    """Detect if a page is a JavaScript SPA with minimal server-rendered content."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove scripts/styles to get actual content
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(strip=True)
    # If body text is very short and has a root div, it's likely a SPA
    root = soup.find("div", id="root") or soup.find("div", id="app") or soup.find("div", id="__next")
    if root and len(text) < 200:
        return True
    if "enable JavaScript" in text or "JavaScript is required" in text:
        return True
    return False


def _fetch_with_browser(url):
    """Use Playwright headless browser to render JS-heavy pages."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[fast_setup] Playwright not installed, cannot render JS pages", flush=True)
        return None, url

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit for dynamic content
            page.wait_for_timeout(2000)
            html = page.content()
            final_url = page.url
            browser.close()
            return html, final_url
    except Exception as e:
        print(f"[fast_setup] Browser render failed for {url}: {e}", flush=True)
        return None, url


def _fetch_pages_with_browser(urls, max_pages=10):
    """Batch-fetch multiple URLs with a single browser instance."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for url in urls[:max_pages]:
                try:
                    page.goto(url, wait_until="networkidle", timeout=20000)
                    page.wait_for_timeout(1500)
                    html = page.content()
                    results.append((html, page.url))
                except Exception as e:
                    print(f"[fast_setup] Browser failed for {url}: {e}", flush=True)
                    results.append((None, url))
            browser.close()
    except Exception as e:
        print(f"[fast_setup] Browser session error: {e}", flush=True)
    return results


def _extract_text(html):
    """Extract meaningful text content from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content tags
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "path"]):
        tag.decompose()

    # Get page title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Get meta description
    meta_desc = ""
    for attr in [{"name": "description"}, {"property": "og:description"}]:
        meta = soup.find("meta", attrs=attr)
        if meta and meta.get("content"):
            meta_desc = meta["content"].strip()
            break

    # Try to get structured data (JSON-LD) — gold mine for business info
    json_ld_text = ""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = script.string
            if ld:
                json_ld_text += "\nStructured Data: " + ld.strip()
        except Exception:
            pass

    # Get main text content
    text = soup.get_text(separator="\n", strip=True)

    # Collapse multiple newlines and spaces
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{3,}", " ", text)

    result = f"Page Title: {title}\nMeta: {meta_desc}"
    if json_ld_text:
        result += f"\n{json_ld_text}"
    result += f"\n\n{text}"
    return result


def _extract_links(html, base_url):
    """Extract internal links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().replace("www.", "")
    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        clean_domain = parsed.netloc.lower().replace("www.", "")
        # Only same domain, no fragments, no file downloads
        if clean_domain == base_domain:
            clean = parsed._replace(fragment="", query="").geturl()
            if not re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|mp4|mp3|zip|doc|docx|css|js|ico)$", clean, re.I):
                links.add(clean)

    return links


def _prioritize_links(links, base_url):
    """Prioritize links that are likely to have useful content (about, team, services, etc.)."""
    priority_keywords = [
        "about", "team", "doctor", "dentist", "staff", "our-team", "our-doctors",
        "service", "treatment", "procedure", "pricing", "price", "fee",
        "contact", "location", "hour", "schedule", "appointment",
        "specialist", "department", "clinic", "practice", "meet",
        "insurance", "patient", "new-patient", "faq"
    ]

    priority = []
    normal = []
    for link in links:
        path = urlparse(link).path.lower()
        if any(kw in path for kw in priority_keywords):
            priority.append(link)
        else:
            normal.append(link)

    return priority + normal


def crawl_website(start_url, max_pages=MAX_PAGES):
    """Crawl a website starting from start_url. Returns list of {url, text} dicts.
    Auto-detects SPAs and uses headless browser when needed."""
    # Normalize URL
    if not start_url.startswith("http"):
        start_url = "https://" + start_url

    # Try both www and non-www
    urls_to_try = [start_url]
    parsed = urlparse(start_url)
    if not parsed.netloc.startswith("www."):
        urls_to_try.append(start_url.replace("://", "://www."))
    else:
        urls_to_try.append(start_url.replace("://www.", "://"))

    visited = set()
    pages = []
    session = _create_session()
    use_browser = False

    # Try to fetch the start URL (with fallbacks)
    first_html = None
    actual_start = start_url
    for url in urls_to_try:
        first_html, actual_start = _fetch_page(url, session)
        if first_html:
            break

    if not first_html:
        print(f"[fast_setup] Could not fetch any version of {start_url}", flush=True)
        return pages

    # Check if it's a SPA that needs browser rendering
    if _is_spa(first_html):
        print(f"[fast_setup] Detected SPA/JS-rendered site, switching to browser mode", flush=True)
        use_browser = True
        # Re-fetch with browser
        first_html, actual_start = _fetch_with_browser(actual_start)
        if not first_html:
            print(f"[fast_setup] Browser render failed for {start_url}", flush=True)
            return pages

    # Process the first page
    visited.add(actual_start)
    text = _extract_text(first_html)
    if len(text.strip()) > 50:
        pages.append({"url": actual_start, "text": text[:MAX_CONTENT_PER_PAGE]})

    # Get and prioritize links
    all_links = _extract_links(first_html, actual_start)
    to_visit = _prioritize_links(list(all_links), actual_start)

    # Also try common paths that might not be linked
    common_paths = [
        "/about", "/about-us", "/our-team", "/team", "/doctors", "/our-doctors",
        "/staff", "/services", "/treatments", "/pricing", "/fees", "/price-list",
        "/contact", "/contact-us", "/hours", "/location", "/departments",
        "/specialists", "/new-patients", "/insurance", "/faq",
        "/meet-our-team", "/meet-the-team", "/meet-our-doctors",
    ]
    base = f"{parsed.scheme}://{urlparse(actual_start).netloc}"
    for path in common_paths:
        full = base + path
        if full not in visited and full not in to_visit:
            to_visit.append(full)

    if use_browser:
        # For SPAs, batch-fetch pages with browser
        urls_to_render = []
        for url in to_visit:
            if url not in visited:
                urls_to_render.append(url)
                visited.add(url)
            if len(urls_to_render) >= max_pages - 1:
                break

        results = _fetch_pages_with_browser(urls_to_render, max_pages=max_pages - 1)
        for html, final_url in results:
            if not html:
                continue
            text = _extract_text(html)
            if len(text.strip()) > 100:
                pages.append({"url": final_url, "text": text[:MAX_CONTENT_PER_PAGE]})
    else:
        # Standard crawl for server-rendered sites
        while to_visit and len(pages) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            html, final_url = _fetch_page(url, session)
            if not html:
                continue

            text = _extract_text(html)
            if len(text.strip()) > 100:
                pages.append({"url": final_url, "text": text[:MAX_CONTENT_PER_PAGE]})

            # Find more links from this page
            if len(pages) < max_pages // 2:
                new_links = _extract_links(html, final_url)
                prioritized = _prioritize_links(list(new_links - visited), actual_start)
                for link in prioritized:
                    if link not in visited and link not in to_visit:
                        to_visit.append(link)

            time.sleep(0.2)

    print(f"[fast_setup] Crawled {len(pages)} pages from {start_url} (visited {len(visited)} URLs)", flush=True)
    return pages


def _call_llm(prompt, max_tokens=4000):
    """Call an LLM to process the scraped content. Tries Gemini > Groq > OpenAI > Claude."""

    # Try Gemini first (generous limits, good at extraction)
    if _get_key("GEMINI_API_KEY"):
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={_get_key('GEMINI_API_KEY')}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[fast_setup] Gemini failed: {resp.status_code}", flush=True)
        except Exception as e:
            print(f"[fast_setup] Gemini error: {e}", flush=True)

    # Try Groq (fast)
    if _get_key("GROQ_API_KEY"):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {_get_key('GROQ_API_KEY')}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                if content and content.strip():
                    return content
                print(f"[fast_setup] Groq returned empty content, trying next LLM", flush=True)
            else:
                print(f"[fast_setup] Groq failed: {resp.status_code} {resp.text[:200]}", flush=True)
        except Exception as e:
            print(f"[fast_setup] Groq error: {e}", flush=True)

    # Try OpenAI
    if _get_key("OPENAI_API_KEY"):
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {_get_key('OPENAI_API_KEY')}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[fast_setup] OpenAI error: {e}", flush=True)

    # Try OpenRouter (DeepSeek V3 - free)
    if _get_key("OPENROUTER_API_KEY"):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {_get_key('OPENROUTER_API_KEY')}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek/deepseek-chat-v3-0324:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,
                },
                timeout=90,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                if content and content.strip():
                    return content
            print(f"[fast_setup] OpenRouter failed: {resp.status_code}", flush=True)
        except Exception as e:
            print(f"[fast_setup] OpenRouter error: {e}", flush=True)

    # Try Claude
    if _get_key("ANTHROPIC_API_KEY"):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": _get_key("ANTHROPIC_API_KEY"),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
        except Exception as e:
            print(f"[fast_setup] Claude error: {e}", flush=True)

    return None


def extract_business_data(pages):
    """Send crawled pages to LLM and extract structured business data."""

    # Prioritize pages likely to have useful content
    priority_keywords = ["about", "team", "doctor", "dentist", "staff", "service",
                         "treatment", "pricing", "price", "fee", "contact", "hour",
                         "specialist", "meet", "our-"]

    def page_priority(p):
        url = p["url"].lower()
        score = sum(2 for kw in priority_keywords if kw in url)
        if url.endswith("/") or url.count("/") <= 3:
            score += 1  # Homepage gets a boost
        return -score  # Negative for sort (highest first)

    sorted_pages = sorted(pages, key=page_priority)

    # Combine page content — balance between having enough data and LLM token limits
    # Groq 70b-versatile supports ~32K tokens; with compact prompt we can do ~20K chars of content
    max_total = int(os.environ.get("FAST_SETUP_MAX_CONTENT", "18000"))
    combined = ""
    max_per_page = 2500
    for p in sorted_pages:
        # Give more space to high-priority pages (team, services, about)
        url_lower = p['url'].lower()
        if any(k in url_lower for k in ['team', 'doctor', 'staff', 'about', '/services']):
            limit = 3500
        else:
            limit = max_per_page
        chunk = f"\n=== {p['url']} ===\n{p['text'][:limit]}\n"
        if len(combined) + len(chunk) > max_total:
            break
        combined += chunk

    if not combined.strip():
        return None

    prompt = f"""Extract business data from this website into JSON. Return ONLY valid JSON, no markdown.

Format:
{{"company_info":{{"business_name":"","address":"","phone":"","email":"","business_hours":"","about":"","services_summary":"","currency":"USD","website":""}},"doctors":[{{"name":"","specialty":"","bio":"","email":"","phone":"","availability":"Mon-Fri","start_time":"09:00 AM","end_time":"05:00 PM","qualifications":"","languages":"","years_of_experience":0}}],"services":[{{"name":"","price":0,"currency":"USD","duration_minutes":60,"category":"","description":"","assigned_doctors":[]}}]}}

Rules: Include ALL doctors/dentists/staff and ALL services/treatments found. Use HH:MM AM format for times. Use "" for missing strings, 0 for missing numbers.

WEBSITE:
{combined}"""

    result = _call_llm(prompt, max_tokens=4000)
    if not result:
        return None

    # Parse JSON from response (handle markdown code blocks)
    result = result.strip()
    if result.startswith("```"):
        result = re.sub(r"^```(?:json)?\s*", "", result)
        result = re.sub(r"\s*```$", "", result)

    try:
        data = json.loads(result)
        return data
    except json.JSONDecodeError as e:
        print(f"[fast_setup] JSON parse error: {e}", flush=True)
        # Try to repair truncated JSON by closing open brackets
        repaired = _repair_json(result)
        if repaired:
            return repaired
        # Try to find a valid JSON object in the response
        match = re.search(r"\{[\s\S]*\}", result)
        if match:
            repaired = _repair_json(match.group())
            if repaired:
                return repaired
        print(f"[fast_setup] Could not repair JSON. First 300 chars: {result[:300]}", flush=True)
        return None


def _repair_json(text):
    """Try to repair truncated JSON by closing open brackets/braces."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Try as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Count open/close brackets and add missing closers
    opens = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            opens.append(ch)
        elif ch == '}' and opens and opens[-1] == '{':
            opens.pop()
        elif ch == ']' and opens and opens[-1] == '[':
            opens.pop()

    # Close any remaining opens
    closers = ""
    for o in reversed(opens):
        closers += ']' if o == '[' else '}'

    if closers:
        # Truncate any trailing partial value (after last comma or colon)
        # Find last complete key-value pair
        trimmed = text.rstrip()
        # Remove trailing partial content after last comma
        last_comma = max(trimmed.rfind(','), trimmed.rfind('}'), trimmed.rfind(']'))
        if last_comma > 0 and last_comma > len(trimmed) - 200:
            # Check if truncation happened mid-value
            after = trimmed[last_comma+1:].strip()
            if after and not after.startswith('"') and not after.startswith('{') and not after.startswith('['):
                trimmed = trimmed[:last_comma]

        try:
            return json.loads(trimmed + closers)
        except json.JSONDecodeError:
            # Try simpler approach: just add closers
            try:
                return json.loads(text + closers)
            except json.JSONDecodeError:
                pass

    return None


def run_fast_setup(website_url):
    """Main entry point: crawl website and extract structured data.
    Returns dict with company_info, doctors, services or None on failure."""
    print(f"[fast_setup] Starting fast setup for: {website_url}", flush=True)

    pages = crawl_website(website_url)
    if not pages:
        return {"error": f"Could not fetch any pages from {website_url}. The site may be blocking requests or is unavailable. Check the URL and try again."}

    data = extract_business_data(pages)
    if not data:
        return {"error": "Could not extract business information. The AI service may be unavailable. Please try again."}

    # Add metadata
    data["_pages_crawled"] = len(pages)
    data["_source_url"] = website_url

    print(f"[fast_setup] Extracted: {len(data.get('doctors', []))} doctors, {len(data.get('services', []))} services", flush=True)
    return data


def apply_fast_setup(admin_id, data):
    """Apply extracted data to the database. Returns summary of what was created.
    Checks for duplicates by name before inserting doctors/services."""
    import database as db

    summary = {"company_info": False, "doctors_added": 0, "doctors_skipped": 0,
               "services_added": 0, "services_skipped": 0, "assignments": 0}

    # 1. Save company info (upsert — always safe to overwrite)
    company = data.get("company_info", {})
    if company and company.get("business_name"):
        db.save_company_info(admin_id, {
            "business_name": company.get("business_name", ""),
            "address": company.get("address", ""),
            "phone": company.get("phone", ""),
            "business_hours": company.get("business_hours", ""),
            "services": company.get("services_summary", ""),
            "about": company.get("about", ""),
            "currency": company.get("currency", "USD"),
            "domain": company.get("website", ""),
        })
        summary["company_info"] = True

    # Load existing doctors and services for duplicate detection
    existing_doctors = _get_existing_doctors(admin_id, db)
    existing_services = _get_existing_services(admin_id, db)

    # 2. Add doctors (skip duplicates by name)
    doctor_name_to_id = {}
    for doc in data.get("doctors", []):
        if not doc.get("name"):
            continue
        doc_name_lower = doc["name"].strip().lower()
        # Check if doctor already exists
        existing_id = existing_doctors.get(doc_name_lower)
        if existing_id:
            doctor_name_to_id[doc["name"]] = existing_id
            summary["doctors_skipped"] += 1
            continue
        doctor_id = db.add_doctor_from_pdf(
            admin_id,
            name=doc["name"],
            email=doc.get("email", ""),
            specialty=doc.get("specialty", ""),
            bio=doc.get("bio", ""),
            availability=doc.get("availability", "Mon-Fri"),
            start_time=doc.get("start_time", "09:00 AM"),
            end_time=doc.get("end_time", "05:00 PM"),
            phone=doc.get("phone", ""),
            qualifications=doc.get("qualifications", ""),
            languages=doc.get("languages", ""),
            years_of_experience=doc.get("years_of_experience", 0),
            pdf_filename="fast_setup",
        )
        doctor_name_to_id[doc["name"]] = doctor_id
        existing_doctors[doc_name_lower] = doctor_id
        summary["doctors_added"] += 1

    # 3. Add services (skip duplicates by name)
    currency = company.get("currency", "USD") if company else "USD"
    service_name_to_id = {}
    for svc in data.get("services", []):
        if not svc.get("name"):
            continue
        svc_name_lower = svc["name"].strip().lower()
        # Check if service already exists
        existing_id = existing_services.get(svc_name_lower)
        if existing_id:
            service_name_to_id[svc["name"]] = existing_id
            summary["services_skipped"] += 1
            continue
        service_id = db.add_company_service(
            admin_id,
            name=svc["name"],
            price=svc.get("price", 0),
            currency=svc.get("currency", currency),
            source="fast_setup",
            category=svc.get("category", ""),
            duration_minutes=svc.get("duration_minutes", 60),
            description=svc.get("description", ""),
        )
        service_name_to_id[svc["name"]] = service_id
        existing_services[svc_name_lower] = service_id
        summary["services_added"] += 1

    # 4. Assign doctors to services (skip if assignment already exists)
    for svc in data.get("services", []):
        if not svc.get("name"):
            continue
        service_id = service_name_to_id.get(svc["name"])
        if not service_id:
            continue
        for doc_name in svc.get("assigned_doctors", []):
            matched_id = doctor_name_to_id.get(doc_name)
            if not matched_id:
                # Try partial match
                for dn, did in doctor_name_to_id.items():
                    if doc_name.lower() in dn.lower() or dn.lower() in doc_name.lower():
                        matched_id = did
                        break
            if matched_id:
                try:
                    db.assign_doctor_to_service(service_id, matched_id, admin_id)
                    summary["assignments"] += 1
                except Exception:
                    pass  # Assignment already exists

    return summary


def _get_existing_doctors(admin_id, db):
    """Get dict of {lowercase_name: id} for existing doctors under this admin."""
    try:
        conn = db.get_db()
        cur = conn.execute("SELECT id, name FROM doctors WHERE admin_id = %s", (admin_id,))
        rows = cur.fetchall()
        conn.close()
        return {row["name"].strip().lower(): row["id"] for row in rows if row.get("name")}
    except Exception:
        return {}


def _get_existing_services(admin_id, db):
    """Get dict of {lowercase_name: id} for existing services under this admin."""
    try:
        conn = db.get_db()
        cur = conn.execute("SELECT id, name FROM company_services WHERE admin_id = %s", (admin_id,))
        rows = cur.fetchall()
        conn.close()
        return {row["name"].strip().lower(): row["id"] for row in rows if row.get("name")}
    except Exception:
        return {}
