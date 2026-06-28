# job_searcher_linkedin.py
# LinkedIn jobs searcher using Apify's curious_coder/linkedin-jobs-scraper actor
# Cost: ~$1 per 1,000 results

import os
from apify_client import ApifyClient
from dotenv import load_dotenv
from urllib.parse import quote
import cost_tracker

load_dotenv()

APIFY_API_KEY = os.getenv("APIFY_API_KEY")
LINKEDIN_ACTOR_ID = "curious_coder/linkedin-jobs-scraper"

# LinkedIn time filter: jobs posted in the last 48 hours (r172800 secs). Tight on
# purpose — we want to be among the first to apply, and a daily cron keeps the
# pipeline fed. Bonus: a 48h window returns far fewer rows per run than the old
# 7-day one, which cuts Apify scrape cost. (24h = r86400, 7 days = r604800.)
TIME_FILTER = "&f_TPR=r172800"

# LinkedIn workplace type filter: 2 = Remote
REMOTE_FILTER = "&f_WT=2"


def build_linkedin_url(keyword: str, location: str = "", remote: bool = False) -> str:
    """Construct a LinkedIn public job search URL."""
    base = "https://www.linkedin.com/jobs/search/?"
    parts = [f"keywords={quote(keyword)}"]
    if location:
        parts.append(f"location={quote(location)}")
    url = base + "&".join(parts) + TIME_FILTER
    if remote:
        url += REMOTE_FILTER
    return url


def search_linkedin(urls: list, max_jobs: int = 50) -> list:
    """Run the Apify actor with a list of LinkedIn search URLs."""
    if not urls:
        return []

    client = ApifyClient(APIFY_API_KEY)

    run_input = {
        "urls": urls,
        # scrapeCompany visits each job's COMPANY page for enrichment we don't
        # use (companyName already comes from the job card; recruiter contact
        # comes from the job detail, not the company page). It was the cause of
        # an ~18-min hang: the actor finished the jobs, then looped on 502 Bad
        # Gateway retries enriching companies through a flaky LinkedIn proxy.
        # Off = no stall, faster, cheaper.
        "scrapeCompany": False,
        "count": max_jobs,
        "splitByCities": False,
    }

    print(f"🔎 LinkedIn: scraping {len(urls)} search URL(s), target {max_jobs} jobs total...")

    try:
        # timeout_secs is a safety net: even if the actor hangs on flaky proxies
        # again, it gets aborted server-side and .call() returns with whatever
        # was scraped — so an unattended cron run can never stall indefinitely.
        run = client.actor(LINKEDIN_ACTOR_ID).call(run_input=run_input, timeout_secs=300)
    except Exception as e:
        print(f"⚠ LinkedIn actor failed: {e}")
        return []

    if not run or not run.get("defaultDatasetId"):
        print("⚠ LinkedIn actor returned no dataset (timed out or aborted early)")
        return []
    if run.get("status") not in ("SUCCEEDED", None):
        print(f"⚠ LinkedIn actor ended as {run.get('status')} — using partial results")

    dataset_id = run["defaultDatasetId"]
    raw_jobs = list(client.dataset(dataset_id).iterate_items())

    print(f"📥 LinkedIn: received {len(raw_jobs)} raw jobs")
    cost_tracker.record_linkedin(len(raw_jobs))

    # Map to standard schema used by matcher / tracker / notifier
    jobs = []
    for j in raw_jobs:
        workplace = j.get("workplaceTypes") or []
        workplace_type = workplace[0] if workplace else ""

        # Recruiter / "who posted this" contact — field names vary by actor
        # version, so probe the common shapes and fall back gracefully.
        poster = j.get("jobPoster") or j.get("poster") or {}
        contact_name = (
            j.get("jobPosterName")
            or poster.get("name")
            or poster.get("fullName")
            or ""
        )
        contact_url = (
            j.get("jobPosterProfileUrl")
            or poster.get("profileUrl")
            or poster.get("linkedinUrl")
            or poster.get("url")
            or ""
        )
        contact_title = j.get("jobPosterTitle") or poster.get("title") or ""

        jobs.append({
            "title": j.get("title", ""),
            "company": j.get("companyName", "N/A"),
            "location": j.get("location", ""),
            "url": j.get("link", ""),
            "apply_url": j.get("applyUrl", "") or j.get("link", ""),
            "description": j.get("descriptionText", ""),
            "source": "LinkedIn",
            "date_posted": j.get("postedAt", ""),
            "seniority": j.get("seniorityLevel", ""),
            "workplace_type": workplace_type,
            "applicants_count": j.get("applicantsCount", ""),
            "job_function": j.get("jobFunction", ""),
            "contact_name": contact_name,
            "contact_url": contact_url,
            "contact_title": contact_title,
            "company_linkedin": j.get("companyLinkedinUrl") or j.get("companyUrl") or "",
        })

    return jobs


def search_all_linkedin(keywords: str = "Product Manager", max_per_location: int = 25) -> list:
    """
    Search LinkedIn across Middle East, Europe, and Remote.
    Returns a deduplicated list of jobs.
    """
    me_locations = [
        "Dubai, United Arab Emirates",
        "Abu Dhabi, United Arab Emirates",
        "Riyadh, Saudi Arabia",
        "Jeddah, Saudi Arabia",
    ]

    # LinkedIn is now the ONLY Europe source (JSearch removed), so cover the
    # main hubs. Each city adds Apify scraping cost — trim this list if the
    # Apify budget gets tight.
    eu_locations = [
        "London, United Kingdom",
        "Dublin, Ireland",
        "Berlin, Germany",
        "Munich, Germany",
        "Amsterdam, Netherlands",
        "Paris, France",
        "Stockholm, Sweden",
        "Zurich, Switzerland",
        "Madrid, Spain",
        "Lisbon, Portugal",
    ]

    all_urls = []

    # Middle East
    for loc in me_locations:
        all_urls.append(build_linkedin_url(keywords, loc))

    # Europe
    for loc in eu_locations:
        all_urls.append(build_linkedin_url(keywords, loc))

    # Remote
    all_urls.append(build_linkedin_url(keywords, location="", remote=True))

    total_target = max_per_location * len(all_urls)

    jobs = search_linkedin(all_urls, max_jobs=total_target)

    # Dedup by job URL
    seen = set()
    deduped = []
    for j in jobs:
        url = j.get("url", "")
        if url and url not in seen:
            seen.add(url)
            deduped.append(j)

    print(f"✅ LinkedIn: {len(deduped)} unique jobs after dedup")
    return deduped


if __name__ == "__main__":
    # Quick local test
    results = search_all_linkedin("Product Manager", max_per_location=5)
    print(f"\nFound {len(results)} jobs")
    for r in results[:5]:
        print(f"  - [{r['source']}] {r['title']} @ {r['company']} ({r['location']})")
