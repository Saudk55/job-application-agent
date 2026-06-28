# job_searcher.py

import requests
import feedparser

def get_remoteok_jobs(keywords: str, max_jobs: int = 20) -> list:
    """Fetch jobs from RemoteOK free JSON API."""
    print("🔍 Fetching from RemoteOK...")
    try:
        headers = {"User-Agent": "job-agent/1.0"}
        response = requests.get("https://remoteok.com/api", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        jobs = []
        keywords_lower = keywords.lower().split()

        for item in data:
            if not isinstance(item, dict) or "position" not in item:
                continue

            title = item.get("position", "")
            description = item.get("description", "") or ""
            tags = " ".join(item.get("tags", []))
            searchable = f"{title} {description} {tags}".lower()

            if any(kw in searchable for kw in keywords_lower):
                jobs.append({
                    "title": title,
                    "company": item.get("company", "N/A"),
                    "location": "Remote",
                    "description": description[:2000],
                    "url": item.get("url", "N/A"),
                    "source": "RemoteOK",
                    "date_posted": item.get("date") or item.get("epoch", ""),
                })

            if len(jobs) >= max_jobs:
                break

        print(f"  ✓ RemoteOK: {len(jobs)} jobs found")
        return jobs

    except Exception as e:
        print(f"  ⚠ RemoteOK failed: {e}")
        return []


def get_remotive_jobs(keywords: str, max_jobs: int = 20) -> list:
    """Fetch jobs from Remotive free API."""
    print("🔍 Fetching from Remotive...")
    try:
        response = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": keywords, "limit": max_jobs},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        jobs = []
        for item in data.get("jobs", []):
            # Surface freelance/contract so the matcher can apply the
            # "freelance OK only for PM roles, preferably Europe" rule. Prepend
            # a marker to the description (the matcher reads description text).
            job_type = (item.get("job_type") or "").lower()
            description = (item.get("description", "") or "")[:2000]
            if job_type in ("freelance", "contract"):
                description = f"[{job_type.upper()}] " + description

            jobs.append({
                "title": item.get("title", "N/A"),
                "company": item.get("company_name", "N/A"),
                "location": item.get("candidate_required_location", "Remote"),
                "description": description,
                "url": item.get("url", "N/A"),
                "source": "Remotive",
                "job_type": job_type,
                "date_posted": item.get("publication_date", ""),
            })

        print(f"  ✓ Remotive: {len(jobs)} jobs found")
        return jobs

    except Exception as e:
        print(f"  ⚠ Remotive failed: {e}")
        return []


def get_weworkremotely_jobs(keywords: str, max_jobs: int = 20) -> list:
    """Fetch jobs from We Work Remotely RSS feed."""
    print("🔍 Fetching from We Work Remotely...")
    try:
        feed = feedparser.parse("https://weworkremotely.com/categories/remote-product-jobs.rss")
        keywords_lower = keywords.lower().split()

        jobs = []
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or ""
            searchable = f"{title} {summary}".lower()

            if any(kw in searchable for kw in keywords_lower):
                # WWR titles are formatted as "Company: Job Title"
                if ": " in title:
                    company, job_title = title.split(": ", 1)
                else:
                    company = entry.get("author", "N/A")
                    job_title = title

                jobs.append({
                    "title": job_title,
                    "company": company,
                    "location": "Remote",
                    "description": summary[:2000],
                    "url": entry.get("link", "N/A"),
                    "source": "WeWorkRemotely",
                    "date_posted": entry.get("published", ""),
                })

            if len(jobs) >= max_jobs:
                break

        print(f"  ✓ We Work Remotely: {len(jobs)} jobs found")
        return jobs

    except Exception as e:
        print(f"  ⚠ We Work Remotely failed: {e}")
        return []


def search_all(keywords: str, max_per_source: int = 20) -> list:
    """Fetch from all sources and combine."""
    all_jobs = []
    all_jobs += get_remoteok_jobs(keywords, max_per_source)
    all_jobs += get_remotive_jobs(keywords, max_per_source)
    all_jobs += get_weworkremotely_jobs(keywords, max_per_source)

    print(f"\n📦 Total collected: {len(all_jobs)} jobs")
    return all_jobs
