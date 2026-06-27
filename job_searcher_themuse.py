# job_searcher_themuse.py
#
# Free EU + Gulf coverage via The Muse public API (no key required; an optional
# MUSE_API_KEY raises the rate limit). This REPLACES the planned Arbeitnow source:
# Arbeitnow's free board API degraded — its `?search=` is ignored (CDN-cached
# "latest 100"), the `visa_sponsorship` field was removed, and PM yield is ~1%
# and German-skewed. The Muse, by contrast, supports real category + location
# filtering and returns a healthy volume of genuine Product Management roles
# (~2,300 live), giving us a real second EU source alongside paid LinkedIn while
# also adding some Gulf coverage to reduce JSearch reliance.

import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

MUSE_API_KEY = os.getenv("MUSE_API_KEY")  # optional; raises rate limit if present
BASE_URL = "https://www.themuse.com/api/public/jobs"

# The Muse only filters by its own fixed category list. These two are the
# relevant ones (verified live); everything else is narrowed by title matching.
PM_CATEGORY = "Product Management"
STRATEGY_CATEGORY = "Project Management"

# Target locations. The Muse's location filter is loose (it leaks nearby/remote
# rows), so we also post-filter results against these substrings.
EU_LOCATIONS = [
    "Berlin, Germany", "Munich, Germany", "Amsterdam, Netherlands",
    "London, United Kingdom", "Dublin, Ireland", "Paris, France",
    "Madrid, Spain", "Barcelona, Spain",
]
GULF_LOCATIONS = ["Dubai, United Arab Emirates", "Riyadh, Saudi Arabia"]

# Substrings used to (a) keep only EU/Gulf/remote rows and (b) tag region.
_EU_HINTS = ["germany", "netherlands", "united kingdom", "ireland", "france",
             "spain", "italy", "belgium", "sweden", "poland", "portugal"]
_GULF_HINTS = ["united arab emirates", "uae", "saudi", "qatar", "dubai",
               "abu dhabi", "riyadh", "jeddah", "doha"]

# Title words that mark a role we actually want (PM + strategy/ops aperture,
# matching the user profile target_roles). Chief of Staff stays excluded.
_TARGET_TITLE_WORDS = [
    "product manager", "product owner", "product lead", "product director",
    "strategy", "strategic", "business operations", "biz ops", "consultant",
    "operations manager",
]

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """The Muse `contents` is HTML; downstream wants plain-ish text."""
    return _TAG_RE.sub(" ", text or "").replace("&nbsp;", " ").strip()


def _region_for(location: str) -> str:
    loc = location.lower()
    if any(h in loc for h in _GULF_HINTS):
        return "Middle East"
    if any(h in loc for h in _EU_HINTS):
        return "Europe"
    return "Remote/Other"


def _categories_for(keywords: str) -> list:
    kw = (keywords or "").lower()
    if any(w in kw for w in ("strategy", "consult", "operation", "business")):
        return [STRATEGY_CATEGORY]
    return [PM_CATEGORY]


def _wanted_title(title: str) -> bool:
    t = (title or "").lower()
    if "chief of staff" in t:
        return False
    return any(w in t for w in _TARGET_TITLE_WORDS)


def _fetch_page(category: str, locations: list, page: int) -> dict:
    params = [("category", category), ("page", str(page))]
    params += [("location", loc) for loc in locations]
    if MUSE_API_KEY:
        params.append(("api_key", MUSE_API_KEY))
    resp = requests.get(
        BASE_URL, params=params,
        headers={"User-Agent": "job-agent/1.0"}, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def search_all_themuse(keywords: str, max_results: int = 20, max_pages: int = 3) -> list:
    """Search The Muse for EU + Gulf roles matching `keywords`.

    Free source — safe to run for every keyword. Returns the standard schema
    so matcher/tracker/notifier need no changes. Results are post-filtered to
    EU/Gulf/remote locations and target-role titles, and deduped by URL.
    """
    categories = _categories_for(keywords)
    locations = EU_LOCATIONS + GULF_LOCATIONS

    print(f"🔍 The Muse — '{keywords}' ({', '.join(categories)})...")

    jobs = []
    seen = set()
    for category in categories:
        for page in range(1, max_pages + 1):
            try:
                data = _fetch_page(category, locations, page)
            except Exception as e:
                print(f"  ⚠ The Muse fetch failed (cat={category}, page={page}): {e}")
                break

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                locs = [l.get("name", "") for l in item.get("locations", [])]
                location = "; ".join(locs) if locs else "Remote"
                region = _region_for(location)

                # Keep only EU/Gulf (or explicitly remote) target-role rows.
                is_remote = "flexible / remote" in location.lower() or "remote" in location.lower()
                if region == "Remote/Other" and not is_remote:
                    continue
                title = item.get("name", "")
                if not _wanted_title(title):
                    continue

                url = item.get("refs", {}).get("landing_page", "N/A")
                if url in seen:
                    continue
                seen.add(url)

                jobs.append({
                    "title": title,
                    "company": item.get("company", {}).get("name", "N/A"),
                    "location": location,
                    "description": _strip_html(item.get("contents", ""))[:2000],
                    "url": url,
                    "source": "The Muse",
                    "region": region,
                    "date_posted": item.get("publication_date", ""),
                })

                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results:
                break
        if len(jobs) >= max_results:
            break

    print(f"  ✓ The Muse: {len(jobs)} jobs (EU/Gulf/remote, target titles)")
    return jobs


if __name__ == "__main__":
    import json
    found = search_all_themuse("Product Manager", max_results=15)
    print(f"\nTotal: {len(found)}")
    for j in found:
        print(f"  [{j['region']}] {j['title']} @ {j['company']} | {j['location'][:50]}")
