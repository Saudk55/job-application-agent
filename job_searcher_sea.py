# job_searcher_sea.py

import os
import requests
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

SEA_LOCATIONS = [
    "Singapore",
    "Kuala Lumpur, Malaysia",
    "Jakarta, Indonesia",
    "Bangkok, Thailand",
    "Ho Chi Minh City, Vietnam",
]

def search_sea_jobs(keywords: str, location: str, max_jobs: int = 10) -> list:
    """Search Southeast Asia jobs via JSearch API."""
    print(f"🔍 Searching for '{keywords}' in '{location}'...")

    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    params = {
        "query": f"{keywords} in {location}",
        "num_pages": "1",
        "date_posted": "month",
        "employment_types": "FULLTIME"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        jobs = []
        for item in data.get("data", [])[:max_jobs]:
            jobs.append({
                "title": item.get("job_title", "N/A"),
                "company": item.get("employer_name", "N/A"),
                "location": f"{item.get('job_city', '')}, {item.get('job_country', '')}".strip(", "),
                "description": (item.get("job_description", "") or "")[:2000],
                "url": item.get("job_apply_link") or item.get("job_google_link", "N/A"),
                "source": "JSearch",
                "region": "Southeast Asia"
            })

        print(f"  ✓ Found {len(jobs)} jobs in {location}")
        return jobs

    except Exception as e:
        print(f"  ⚠ Search failed for {location}: {e}")
        return []


def search_all_sea(keywords: str, max_per_location: int = 10) -> list:
    """Search across all Southeast Asia locations."""
    all_jobs = []

    for location in SEA_LOCATIONS:
        jobs = search_sea_jobs(keywords, location, max_per_location)
        all_jobs += jobs

    print(f"\n📦 Total Southeast Asia jobs collected: {len(all_jobs)}")
    return all_jobs