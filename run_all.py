# run_all.py

import sys
import json
import os
import glob

# Emoji-heavy logs crash on Windows' default cp1252 console; force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
from job_searcher import search_all
from job_searcher_themuse import search_all_themuse
from job_searcher_linkedin import search_all_linkedin
from matcher import filter_jobs
from tracker import filter_new_jobs, mark_jobs_seen
from notifier import save_to_sheet, send_email
from cv_tailor import tailor_and_generate
from datetime import datetime
import cost_tracker

MAX_PER_SOURCE = 20
MAX_PER_LOCATION = 10
MIN_SCORE = 6
# Hard ceiling on LLM-tailored CVs per run (cost control). Only score-7 product
# roles are tailored; this caps a high-volume day. Highest scores tailored first.
# Steady-state runs score few new jobs (tracker dedups), so this rarely binds.
MAX_LLM_TAILORS = 8

# Multi-user master switch. The multi-user CODE is fully built, but until friends
# are paying we only run the primary user (the primary user) on the cron. Flip to True (and
# push the friend's users/<name>.json with "active": true) once they've paid.
# A local demo for one person always works regardless: `python run_all.py "Name"`.
MULTI_USER_ENABLED = False


def load_all_users() -> list:
    """Load all user profiles from the users/ folder."""
    users = []
    for filepath in sorted(glob.glob("users/*.json")):
        if os.path.basename(filepath).startswith("_"):
            continue
        with open(filepath, "r") as f:
            user = json.load(f)
            users.append(user)
    return users


def _scrape_one_keyword(keywords: str, include_paid: bool = True) -> list:
    """Run the search phases for a single keyword string.

    The paid LinkedIn (Apify) source is gated by `include_paid` and runs for the
    PRIMARY keyword only. Free sources (Remote RSS + The Muse) run for every
    keyword.

    JSearch (RapidAPI / Middle East) was REMOVED: it's quota-limited and poorly
    rated, and the Gulf is already covered by LinkedIn + The Muse.
    """
    all_jobs = []

    print("\n📡 PHASE 1 — REMOTE JOBS")
    print("-" * 40)
    all_jobs += search_all(keywords, MAX_PER_SOURCE)

    # Free EU + Gulf source (no key). Replaces the planned Arbeitnow source,
    # whose free API degraded (search ignored, visa flag removed, ~1% German-
    # skewed PM yield). The Muse supports real category+location filtering, so
    # it gives a genuine second EU source alongside paid LinkedIn at no cost.
    print("\n📡 PHASE 1B — THE MUSE (free; EU + Gulf)")
    print("-" * 40)
    all_jobs += search_all_themuse(keywords, MAX_PER_SOURCE)

    if include_paid:
        print("\n📡 PHASE 2 — LINKEDIN JOBS (paid; incl. Europe + Gulf)")
        print("-" * 40)
        all_jobs += search_all_linkedin(keywords, MAX_PER_LOCATION)
    else:
        print("\n⏭  PHASE 2 — LINKEDIN skipped (paid source runs on primary keyword only)")

    return all_jobs


def scrape_jobs(keywords, use_paid: bool = True) -> list:
    """Run discovery across one or more keyword strings, deduped by URL.

    `keywords` may be a single string or a list (e.g. ["Product Manager",
    "Strategy Manager"]). Each extra keyword multiplies discovery API calls,
    so keep the list short — it's the main per-run scraping cost driver.

    `use_paid=False` skips the paid LinkedIn (Apify) source entirely — used for
    a cheap friend demo run (free sources only, no Apify spend).
    """
    keyword_list = [keywords] if isinstance(keywords, str) else list(keywords)

    all_jobs = []
    seen_urls = set()
    for i, kw in enumerate(keyword_list):
        print(f"\n🔑 Keyword: {kw}")
        # Paid LinkedIn runs only for the primary keyword, and only if allowed.
        for job in _scrape_one_keyword(kw, include_paid=(i == 0 and use_paid)):
            url = job.get("url", "")
            if url and url != "N/A" and url in seen_urls:
                continue
            if url and url != "N/A":
                seen_urls.add(url)
            all_jobs.append(job)

    return all_jobs


def generate_and_upload_cvs(matched_jobs: list, user: dict = None) -> list:
    """Generate tailored CVs for matched jobs (multi-user: uses the user's CV).

    Enforces MAX_LLM_TAILORS per run: jobs are processed highest-score first,
    and once the LLM-tailor budget is spent, any further tailorable jobs fall
    back to the master CV (no extra Claude spend).
    """
    print(f"\n📄 Generating tailored CVs for {len(matched_jobs)} jobs...")

    # Highest scores first so the limited tailor budget goes to the best matches.
    matched_jobs.sort(key=lambda j: j.get("relevance_score", 0), reverse=True)
    llm_tailors_used = 0

    for job in matched_jobs:
        try:
            allow_llm = llm_tailors_used < MAX_LLM_TAILORS
            result = tailor_and_generate(
                job, score=job.get("relevance_score", 10),
                allow_llm_tailor=allow_llm, user=user,
            )
            if result.get("llm_used"):
                llm_tailors_used += 1
            # Carry the LOCAL pdf path: tailored/variant CVs are attached to the
            # daily email (the repo is private, so raw GitHub links 404). Master-
            # CV roles have no file — the user uses his own standard CV.
            job["cv_path"] = result.get("cv_path") or ""
            job["cv_label"] = result.get("cv_label", "")

        except Exception as e:
            print(f"⚠ CV generation failed for {job.get('title')}: {e}")
            job["cv_path"] = ""
            job["cv_label"] = ""

    return matched_jobs


def process_user(user: dict):
    """Run the full pipeline for one user.

    Multi-user controls (all optional in the user JSON):
      - "active": false   -> skip this user entirely (e.g. a friend who hasn't
                             paid yet). Default true.
      - "limits": {"max_scored": N, "max_results": M} -> cap Claude scoring
                             cost and the number of matches saved. Used for a
                             cheap demo run (M = 3-4) before a friend pays.
    Cost is reported per user so each person's spend is isolated.
    """
    name = user["name"]
    keywords = user["search_keywords"]

    if not user.get("active", True):
        print(f"\n⏭  Skipping {name} — profile marked inactive (active=false).")
        return

    limits = user.get("limits", {})
    max_scored = limits.get("max_scored")
    max_results = limits.get("max_results")

    cost_before = cost_tracker.estimate()["total_usd"]

    print("\n" + "=" * 60)
    print(f"👤 Processing: {name} | Keywords: {keywords}")
    if limits:
        print(f"   Demo limits: max_scored={max_scored}, max_results={max_results}")
    print("=" * 60)

    # Scrape (a demo can disable the paid LinkedIn source to stay near-free)
    use_paid = user.get("use_paid_sources", True)
    if not use_paid:
        print("   💸 Paid LinkedIn source disabled for this user (free sources only).")
    all_jobs = scrape_jobs(keywords, use_paid=use_paid)
    print(f"\n📦 Total collected for {name}: {len(all_jobs)} jobs")

    # Filter seen
    new_jobs = filter_new_jobs(all_jobs, name)

    if not new_jobs:
        print(f"\n✅ No new jobs for {name} today.")
        return

    # Cost guard: cap how many jobs get scored (demo / per-user budget control).
    if max_scored and len(new_jobs) > max_scored:
        print(f"   ⚖ Capping scored jobs {len(new_jobs)} → {max_scored} (demo limit)")
        new_jobs = new_jobs[:max_scored]

    # Score
    print(f"\n🤖 Scoring {len(new_jobs)} new jobs for {name}...")
    matched_jobs = filter_jobs(new_jobs, user, min_score=MIN_SCORE)

    # Mark seen
    mark_jobs_seen(new_jobs, name)

    if not matched_jobs:
        print(f"\n✅ No strong matches for {name} today.")
        return

    # Cap matches saved/emailed (demo shows just the top few).
    if max_results and len(matched_jobs) > max_results:
        print(f"   ⚖ Capping matches {len(matched_jobs)} → {max_results} (demo limit)")
        matched_jobs = matched_jobs[:max_results]

    # Generate tailored CVs (using this user's CV)
    matched_jobs = generate_and_upload_cvs(matched_jobs, user)

    # Save + notify
    sheet_url = save_to_sheet(matched_jobs, user)
    send_email(matched_jobs, user, sheet_url)

    # Summary
    cost_user = round(cost_tracker.estimate()["total_usd"] - cost_before, 3)
    print(f"\n🎯 {name}: {len(matched_jobs)} matches saved | est. cost this user: ${cost_user:.2f}")
    for job in matched_jobs:
        cv_status = "📎 CV attached" if job.get("cv_path") else "Master CV"
        print(f"  [{job['relevance_score']}/10] {job['title']} @ {job['company']} | {cv_status}")


def main(only_user: str = None):
    print("=" * 60)
    print(f"JOB AGENT — Daily Run | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    cost_tracker.reset()

    users = load_all_users()

    if only_user:
        # Explicit single-user run (e.g. `python run_all.py "Ashar"`) — used for a
        # friend demo. Runs ONLY that user; bypasses MULTI_USER_ENABLED.
        needle = only_user.strip().lower()
        users = [u for u in users
                 if needle in u.get("name", "").lower()
                 or needle in u.get("sheet_tab", "").lower()]
        if not users:
            print(f"\n⚠ No user matched '{only_user}'. Nothing to do.")
            return
    elif not MULTI_USER_ENABLED:
        # Cron / default run: multi-user is OFF, so run only the primary user(s).
        primary = [u for u in users if u.get("primary")]
        if primary:
            skipped = [u["name"] for u in users if not u.get("primary")]
            if skipped:
                print(f"\n⏭  MULTI_USER_ENABLED=False — running primary only; "
                      f"skipping: {', '.join(skipped)}")
            users = primary

    print(f"\n👥 Processing {len(users)} user(s): {', '.join(u['name'] for u in users)}")

    for user in users:
        process_user(user)

    print("\n" + "=" * 60)
    print("✅ Run complete.")
    print(cost_tracker.summary_line())
    print("=" * 60)


if __name__ == "__main__":
    # `python run_all.py` -> all users; `python run_all.py "<name>"` -> just one.
    main(only_user=sys.argv[1] if len(sys.argv) > 1 else None)
