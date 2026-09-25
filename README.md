# Zillow Real Estate Agent & Property Data Scraper

A production-grade Python scraper that extracts real-estate agent
directory data from Zillow and enriches each agent's contact details by
combining live network-response interception with direct parsing of each
agent's profile page — engineered to reliably operate against **Zillow's
PerimeterX bot-protection system**, one of the most widely deployed
anti-bot platforms on the web.

## Overview

The scraper connects to a real, locally-installed Google Chrome browser
via the Chrome DevTools Protocol (CDP) rather than launching a bundled
automation browser — the core technique behind its ability to operate
against PerimeterX's detection heuristics. It reads agent directory
listings directly from the page's embedded `__NEXT_DATA__` JSON, then
enriches each agent record with phone, email, and full address by
passively capturing the site's internal network responses and, where
needed, directly fetching and parsing each agent's own profile page
(including JSON-LD structured data). Results are exported to both CSV
and JSON.

This scraper has been repeatedly tested against Zillow's live agent
directory and consistently completes full scraping runs with working
error handling, making it a reliable, production-ready tool rather than
a proof of concept.

## Key Features

- **PerimeterX-resilient by design** — connects to your own
  locally-installed Chrome via CDP (remote debugging on port 9222)
  instead of a managed/bundled automation browser, avoiding the
  automation fingerprints that typically trigger PerimeterX's bot
  detection.
- Extracts agent directory listings directly from the page's
  `__NEXT_DATA__` JSON payload.
- Enriches each agent's contact and address details using two combined
  methods: passive interception of the site's internal API/GraphQL
  network responses, and a direct fetch + HTML/JSON-LD parse of the
  agent's profile page.
- Supports multi-page pagination.
- Filters out records with no agent name and deduplicates by profile URL.
- Exports results to both CSV and JSON with client-facing column headers.
- Logs progress to the console and to a log file.

## Data Collected

| Field | Description |
|---|---|
| Agent Name | Agent's display name |
| Brokerage / Agency | Agent's brokerage or agency name |
| Agent Type | Tag/category associated with the agent listing |
| Phone | Agent's phone number |
| Email | Agent's email address |
| Full Address | Street address, city, state, and postal code (where available) |
| Rating | Average review rating |
| Reviews | Number of reviews |
| Sales (Last 12M) | Sales activity in the last 12 months |
| Total Sales | Total sales figure shown on the listing |
| Price Range | Listed price range |
| Profile URL | Direct link to the agent's Zillow profile |

## Technologies

- **Python 3**
- **Playwright** (Python) — connects to Chrome over the DevTools Protocol
- **pandas** — data cleaning and CSV/JSON export
- **Google Chrome** — a real, locally-installed browser instance (not a
  Playwright-managed browser), the foundation of this scraper's
  PerimeterX resilience

## Project Structure

```
zillow-real-estate-agent-scraper/
├── scraper.py
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```

At runtime the script also creates `chrome_bridge_profile/` (a local
Chrome user-data directory) and a log file — these are local runtime
artifacts and are excluded via `.gitignore`. The CSV and JSON output
files are **not** excluded — sample output from real runs is intended to
be committed to this repository as proof of results.

## Installation

Requires **Google Chrome installed on Windows** in one of the following
locations (auto-detected by the script):

- `C:\Program Files\Google\Chrome\Application\chrome.exe`
- `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
- `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`

```bash
pip install -r requirements.txt
```

## Usage

```bash
python scraper.py --url "https://www.zillow.com/professionals/real-estate-agent-reviews/chicago-il/" --pages 2
```

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `--url` | Zillow's Chicago, IL agent directory | Starting directory listing URL |
| `--pages` | `2` | Number of listing pages to scrape |

> Note: page navigation for page 2 and beyond uses a page-number URL
> pattern currently configured for the Chicago, IL directory
> (`LISTING_URL_PATTERN` in `scraper.py`). Update that pattern in the
> script if targeting a different city/URL across multiple pages.

## Output

Running the script produces:

- **`zillow_agents_final.csv`** — cleaned, deduplicated agent records with client-facing column headers
- **`zillow_agents_final.json`** — the same records in JSON format
- **`zillow_scraper.log`** — a log of the scraping run (console output is also mirrored here)

The CSV and JSON outputs are the scraper's real, verified deliverables
and are included in this repository as evidence of successful, repeated
runs against Zillow's live, PerimeterX-protected agent directory.


## Disclaimer

This project is provided for educational and demonstration purposes. It
is your responsibility to ensure that any use of this scraper complies
with Zillow's Terms of Service and applicable law before running it
against the live site. This repository does not grant any right to
violate a third party's Terms of Service, and the author assumes no
liability for how this code is used.

## Author

**Hamza**
