# tracker.py

import json
import os

def _tracker_file(user_name: str) -> str:
    """Return the tracker filename for a specific user."""
    safe_name = user_name.lower().replace(" ", "_")
    return f"jobs_seen_{safe_name}.json"

def load_seen_jobs(user_name: str) -> set:
    """Load previously seen job URLs for a user."""
    path = _tracker_file(user_name)
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return set(json.load(f))

def save_seen_jobs(user_name: str, seen: set):
    """Save seen job URLs to file for a user."""
    path = _tracker_file(user_name)
    with open(path, "w") as f:
        json.dump(list(seen), f)

def filter_new_jobs(jobs: list, user_name: str) -> list:
    """Return only jobs this user hasn't seen before."""
    seen = load_seen_jobs(user_name)
    new_jobs = []

    for job in jobs:
        key = job.get("url", "")
        if key and key != "N/A" and key not in seen:
            new_jobs.append(job)

    print(f"🆕 {len(new_jobs)} new jobs for {user_name} (filtered out {len(jobs) - len(new_jobs)} already seen)")
    return new_jobs

def mark_jobs_seen(jobs: list, user_name: str):
    """Add jobs to the seen tracker for a user."""
    seen = load_seen_jobs(user_name)
    for job in jobs:
        key = job.get("url", "")
        if key and key != "N/A":
            seen.add(key)
    save_seen_jobs(user_name, seen)
    print(f"💾 Tracker updated for {user_name} — {len(seen)} total jobs on record")