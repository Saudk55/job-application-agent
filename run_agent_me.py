# run_agent_me.py

from job_searcher_me import search_all_me
from matcher import filter_jobs
from tracker import filter_new_jobs, mark_jobs_seen
from notifier import save_to_sheet, send_email
from datetime import datetime

SEARCH_KEYWORDS = "D365 Finance & Operations Consultant"
MAX_PER_LOCATION = 10
MIN_SCORE = 6

def main():
    print("=" * 60)
    print(f"JOB AGENT — Middle East Phase | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Step 1: Scrape
    all_jobs = search_all_me(SEARCH_KEYWORDS, MAX_PER_LOCATION)

    # Step 2: Filter already seen
    new_jobs = filter_new_jobs(all_jobs)

    if not new_jobs:
        print("\n✅ No new Middle East jobs today. Try again tomorrow.")
        return

    # Step 3: Score with Claude
    print(f"\n🤖 Scoring {len(new_jobs)} new jobs with Claude...")
    matched_jobs = filter_jobs(new_jobs, min_score=MIN_SCORE)

    # Step 4: Mark all as seen
    mark_jobs_seen(new_jobs)

    if not matched_jobs:
        print("\n✅ No strong Middle East matches today.")
        return

    # Step 5: Save + notify
    sheet_url = save_to_sheet(matched_jobs)
    send_email(matched_jobs, sheet_url)

    # Step 6: Print summary
    print("\n" + "=" * 60)
    print(f"TOP MIDDLE EAST MATCHES ({len(matched_jobs)} jobs)")
    print("=" * 60)
    for job in matched_jobs:
        print(f"\n[{job['relevance_score']}/10] {job['title']} @ {job['company']}")
        print(f"📍 {job['location']} | 🌐 {job['source']}")
        print(f"🔗 {job['url']}")
        print("-" * 60)

if __name__ == "__main__":
    main()