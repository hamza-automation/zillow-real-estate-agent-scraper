"""
Zillow Real-Estate Agent Directory Scraper (Final Production Grade).
Features:
  - Windows-native Chrome CDP bridge (bypasses PerimeterX anti-bot heuristics).
  - Silent network response interception (captures raw backend JSON packets).
  - Native DOMParser + JSON-LD schema extraction for direct phone numbers,
    emails, and full street addresses with postal codes.
  - Multi-page pagination support.
  - Client-facing CSV and JSON export pipelines.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import time
from typing import Dict, List, Optional
from urllib.parse import urljoin

import pandas as pd
from playwright.sync_api import Response, sync_playwright

# ===========================================================================
# CONFIGURATION & SCHEMA DEFINITION
# ===========================================================================

DEFAULT_URL = "https://www.zillow.com/professionals/real-estate-agent-reviews/chicago-il/"
LISTING_URL_PATTERN = "https://www.zillow.com/professionals/real-estate-agent-reviews/chicago-il/?page={page}"
OUTPUT_CSV = "zillow_agents_final.csv"
OUTPUT_JSON = "zillow_agents_final.json"
LOG_FILE = "zillow_scraper.log"

DISPLAY_COLUMNS = {
    "agent_name": "Agent Name",
    "agency": "Brokerage / Agency",
    "agent_type": "Agent Type",
    "phone": "Phone",
    "email": "Email",
    "full_address": "Full Address",
    "rating": "Rating",
    "review_count": "Reviews",
    "sales_12m": "Sales (Last 12M)",
    "total_sales": "Total Sales",
    "price_range": "Price Range",
    "profile_url": "Profile URL",
}
ALL_FIELDS = list(DISPLAY_COLUMNS.keys())


def setup_logging():
    logger = logging.getLogger("zillow_production")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = setup_logging()


# ===========================================================================
# CHROME RUNTIME BRIDGE
# ===========================================================================

def find_chrome_executable() -> str:
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Google Chrome executable not found in standard Windows locations.")


def launch_native_chrome(start_url: str):
    """Launches local Chrome with remote debugging on port 9222."""
    chrome_path = find_chrome_executable()
    profile_dir = os.path.abspath("./chrome_bridge_profile")
    cmd = [
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        start_url,
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3.0)


# ===========================================================================
# 1. DIRECTORY-LEVEL HARVESTING (__NEXT_DATA__)
# ===========================================================================

def harvest_agents_from_directory(page) -> List[Dict]:
    """Extracts agent cards and sales volume from the listing page's __NEXT_DATA__."""
    page.wait_for_timeout(2000)
    cards_json = page.evaluate("""() => {
        const el = document.getElementById('__NEXT_DATA__');
        if (!el) return [];
        const json = JSON.parse(el.innerText);
        const results = [];
        const seen = new Set();

        function traverse(obj) {
            if (!obj || typeof obj !== 'object') return;
            if (obj.__typename === "AgentDirectoryFinderProfileResultsCard" && obj.cardTitle && obj.cardActionLink) {
                if (!seen.has(obj.cardActionLink)) {
                    seen.add(obj.cardActionLink);
                    results.push(obj);
                }
                return;
            }
            if (Array.isArray(obj)) obj.forEach(traverse);
            else Object.values(obj).forEach(traverse);
        }
        traverse(json);
        return results;
    }""")

    records = []
    for c in cards_json:
        price_range, sales_12m, total_sales = None, None, None
        for item in c.get("profileData", []):
            label = (item.get("label") or "").lower()
            val = item.get("formattedData")
            if "price range" in label:
                price_range = val
            elif "sales last 12 months" in label:
                sales_12m = val
            elif "sales in" in label or "total sales" in label:
                total_sales = val

        rev = c.get("reviewInformation") or {}
        rating = rev.get("reviewAverageText") or str(rev.get("reviewAverage") or "")
        reviews = rev.get("reviewCountFormattedText") or str(rev.get("reviewCount") or "")
        if reviews:
            reviews = re.sub(r"[^\d]", "", reviews)

        tags = c.get("tags") or []
        agent_type = tags[0].get("text", "AGENT") if tags else "AGENT"

        records.append({
            "agent_name": c.get("cardTitle"),
            "agency": c.get("secondaryCardTitle"),
            "agent_type": agent_type,
            "rating": rating or None,
            "review_count": reviews or None,
            "sales_12m": sales_12m,
            "total_sales": total_sales,
            "price_range": price_range,
            "profile_url": c.get("cardActionLink"),
            "phone": None,
            "email": None,
            "full_address": "Chicago, IL",
        })

    return records


# ===========================================================================
# 2. PROFILE-LEVEL ENRICHMENT (WIRE TAP + JSON-LD SCHEMA)
# ===========================================================================

def parse_profile_network_json(data: dict) -> dict:
    """Extracts contact fields from intercepted backend JSON payloads."""
    extracted = {}

    def search_tree(obj):
        if not obj or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, dict):
            for k in ["telephone", "cellPhone", "businessPhone", "phoneNumber", "phone"]:
                if k in obj and obj[k] and not extracted.get("phone"):
                    digits = re.sub(r"\D", "", str(obj[k]).strip())
                    if len(digits) >= 10:
                        digits = digits[-10:]
                        extracted["phone"] = f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"

            for k in ["email", "businessEmail", "agentEmail"]:
                if k in obj and obj[k] and not extracted.get("email"):
                    extracted["email"] = str(obj[k]).strip().lower()

            if "streetAddress" in obj and not extracted.get("full_address"):
                street = obj.get("streetAddress")
                city = obj.get("addressLocality") or obj.get("city") or "Chicago"
                state = obj.get("addressRegion") or obj.get("state") or "IL"
                zip_code = obj.get("postalCode") or obj.get("zip") or ""
                extracted["full_address"] = f"{street}, {city}, {state} {zip_code}".strip()

            for v in obj.values():
                search_tree(v)
        elif isinstance(obj, list):
            for item in obj:
                search_tree(item)

    search_tree(data)
    return extracted


def enrich_agent_profile(page, agent_record: Dict, wire_captured: Dict) -> Dict:
    """Enriches an agent record with full address, phone, and email."""
    url = agent_record.get("profile_url")
    if not url:
        return agent_record

    # Bind fields captured by the active network wire tap
    if wire_captured.get("phone"):
        agent_record["phone"] = wire_captured["phone"]
    if wire_captured.get("email"):
        agent_record["email"] = wire_captured["email"]
    if wire_captured.get("full_address"):
        agent_record["full_address"] = wire_captured["full_address"]

    # DOM & JSON-LD fallback for full street address and contact tags
    if not agent_record.get("phone") or agent_record.get("full_address") == "Chicago, IL":
        dom_result = page.evaluate("""async (u) => {
            try {
                const r = await fetch(u);
                const t = await r.text();
                const p = new DOMParser();
                const d = p.parseFromString(t, 'text/html');

                // 1. Phone link
                let phone = null;
                const telEl = d.querySelector("a[href*='tel:']");
                if (telEl) {
                    phone = (telEl.getAttribute('href') || '').replace(/^tel:/i, '').trim();
                }

                // 2. Email link
                let email = null;
                const mailEl = d.querySelector("a[href*='mailto:']");
                if (mailEl) {
                    email = (mailEl.getAttribute('href') || '').replace(/^mailto:/i, '').split('?')[0].trim();
                }

                // 3. Full Street Address from JSON-LD Schema
                let fullAddr = null;
                const ldScripts = d.querySelectorAll("script[type='application/ld+json']");
                for (const s of ldScripts) {
                    try {
                        const data = JSON.parse(s.innerText);
                        if (data.address && data.address.streetAddress) {
                            const street = data.address.streetAddress;
                            const city = data.address.addressLocality || 'Chicago';
                            const state = data.address.addressRegion || 'IL';
                            const zip = data.address.postalCode || '';
                            fullAddr = `${street}, ${city}, ${state} ${zip}`.trim();
                            if (!phone && data.telephone) phone = data.telephone;
                            if (!email && data.email) email = data.email;
                            break;
                        }
                    } catch(e) {}
                }

                // 4. Fallback DOM address selector
                if (!fullAddr) {
                    const addrEl = d.querySelector("[data-test*='address'], address");
                    if (addrEl && addrEl.innerText && addrEl.innerText.trim().length > 5) {
                        fullAddr = addrEl.innerText.trim().replace(/\\s+/g, ' ');
                    }
                }

                return { phone, email, address: fullAddr };
            } catch(e) {
                return null;
            }
        }""", url)

        if dom_result:
            if dom_result.get("phone") and not agent_record.get("phone"):
                digits = re.sub(r"\D", "", dom_result["phone"])
                if len(digits) == 10:
                    agent_record["phone"] = f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
                elif len(digits) == 11 and digits.startswith("1"):
                    agent_record["phone"] = f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
                else:
                    agent_record["phone"] = dom_result["phone"]

            if dom_result.get("email") and not agent_record.get("email"):
                agent_record["email"] = dom_result["email"]

            if dom_result.get("address"):
                agent_record["full_address"] = dom_result["address"]

    return agent_record


# ===========================================================================
# 3. CLEANING & EXPORT PIPELINE
# ===========================================================================

def clean_and_export(records: List[Dict]):
    if not records:
        log.warning("No records collected.")
        return

    df = pd.DataFrame(records)
    for col in ALL_FIELDS:
        if col not in df.columns:
            df[col] = None

    df = df[df["agent_name"].notna() & (df["agent_name"] != "")].copy()
    df = df.drop_duplicates(subset=["profile_url"], keep="first")

    export_df = df[ALL_FIELDS].rename(columns=DISPLAY_COLUMNS)
    export_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(export_df.to_dict(orient="records"), f, indent=2, ensure_ascii=False)

    log.info("=" * 70)
    log.info("SCRAPING COMPLETE: Exported %s verified agent records!", len(export_df))
    log.info("CSV File:  %s", os.path.abspath(OUTPUT_CSV))
    log.info("JSON File: %s", os.path.abspath(OUTPUT_JSON))
    log.info("=" * 70)


# ===========================================================================
# 4. ORCHESTRATOR
# ===========================================================================

def run_scraper(start_url: str, max_pages: int = 1):
    launch_native_chrome(start_url)
    log.info("Connecting to Chrome over CDP on port 9222...")

    with sync_playwright() as p:
        browser = None
        for _ in range(8):
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                break
            except Exception:
                time.sleep(1.0)

        if not browser:
            log.error("Could not connect to Chrome port 9222.")
            return

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        # Silent network wire listener
        wire_data: Dict[str, dict] = {}

        def on_network_response(response: Response):
            url = response.url
            ct = response.headers.get("content-type", "")
            if ("_next/data" in url or "graphql" in url or "api/" in url) and "application/json" in ct:
                try:
                    payload = response.json()
                    contact_info = parse_profile_network_json(payload)
                    if contact_info:
                        wire_data.update(contact_info)
                except Exception:
                    pass

        context.on("response", on_network_response)

        all_agents = []

        for current_page in range(1, max_pages + 1):
            if current_page > 1:
                next_url = LISTING_URL_PATTERN.format(page=current_page)
                log.info("Navigating to page %s: %s", current_page, next_url)
                page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)

            page_agents = harvest_agents_from_directory(page)
            if not page_agents:
                log.warning("No agent cards detected on page %s. Stopping pagination.", current_page)
                break

            log.info("Enriching %s agents on page %s...", len(page_agents), current_page)

            for idx, agent in enumerate(page_agents, start=1):
                wire_data.clear()

                # Trigger background profile fetch through the browser's network tap
                page.evaluate("""async (u) => {
                    try {we
                        await fetch(u, { headers: { 'Accept': 'text/html,application/xhtml+xml,application/json' } });
                    } catch(e) {}
                }""", agent["profile_url"])

                page.wait_for_timeout(600)

                enriched = enrich_agent_profile(page, agent, wire_data)
                all_agents.append(enriched)

                log.info(
                    "[%s/%s] %s | %s | %s | %s | %s",
                    idx,
                    len(page_agents),
                    enriched.get("agent_name"),
                    enriched.get("agency"),
                    enriched.get("phone") or "No Phone",
                    enriched.get("email") or "No Email",
                    enriched.get("full_address"),
                )

        clean_and_export(all_agents)


def main():
    parser = argparse.ArgumentParser(description="Zillow Production Real Estate Scraper")
    parser.add_argument("--url", default=DEFAULT_URL, help="Starting directory listing URL")
    parser.add_argument("--pages", type=int, default=2, help="Number of listing pages to scrape")
    args = parser.parse_args()

    run_scraper(start_url=args.url, max_pages=args.pages)


if __name__ == "__main__":
    main()