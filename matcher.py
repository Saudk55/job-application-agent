# matcher.py

import os
from anthropic import Anthropic
from dotenv import load_dotenv
import cost_tracker

load_dotenv()
client = Anthropic()


def batch_prefilter(jobs: list, user: dict) -> list:
    if not jobs:
        return []

    titles_list = "\n".join([
        f"{i+1}. {job.get('title', 'N/A')} @ {job.get('company', 'N/A')}"
        for i, job in enumerate(jobs)
    ])

    years = user['years_experience']
    current_title = user['current_title']
    target_roles = ", ".join(user['target_roles'])

    prompt = f"""You are filtering job listings for a candidate with {years} years of experience as a {current_title}.

The candidate is looking for these roles: {target_roles}.

IMPORTANT: The candidate is open to adjacent role types, not just Product Manager.
Strategy, Business Operations, Corporate Strategy, and Management Consulting roles
at a manager/IC level ARE in scope — do not reject them just because they are not
"Product Manager". (Chief of Staff roles are NOT a fit — exclude them.)

Freelance / contract roles ARE acceptable, but ONLY for Product Manager roles and
preferably based in Europe or Europe-remote. Reject freelance/contract roles that
are not Product Manager, or that are outside Europe/remote.

The candidate is NOT looking for:
- Director, VP, Head of, CPO, C-suite or genuinely executive/leadership roles (too senior for {years} years experience)
- Chief of Staff roles
- Internships or entry-level/junior roles (too junior)
- Roles in completely unrelated fields (e.g. sales, marketing, engineering, design)
- Roles where a keyword matches but the actual job is different

Here are the job listings:
{titles_list}

Return ONLY a comma-separated list of the numbers of jobs that ARE relevant for this candidate.
Example response: 3, 7, 12, 15
If none are relevant, return: none
Do not explain. Just return the numbers."""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    cost_tracker.record("prefilter")

    response = message.content[0].text.strip()
    print(f"⚡ Pre-filter response: {response}")

    if response.lower() == "none":
        return []

    try:
        indices = [int(x.strip()) - 1 for x in response.split(",") if x.strip().isdigit()]
        filtered = [jobs[i] for i in indices if 0 <= i < len(jobs)]
        print(f"⚡ Pre-filter: {len(filtered)} relevant / {len(jobs) - len(filtered)} rejected")
        return filtered
    except Exception as e:
        print(f"⚠ Pre-filter parsing failed: {e}, falling back to all jobs")
        return jobs


def match_job(job: dict, user: dict) -> dict:
    profile_summary = f"""
Candidate: {user['name']}
Current Title: {user['current_title']}
Years of Experience: {user['years_experience']}
Target Roles: {', '.join(user['target_roles'])}
Target Industries: {', '.join(user['target_industries'])}
Core Skills: {', '.join(user['core_skills'])}
Domain Expertise: {', '.join(user['domain_expertise'])}
Key Achievements: {'; '.join(user['notable_achievements'])}
Education: {user['education']}
Relocation: {user['relocation']}
"""

    job_text = f"""
Job Title: {job.get('title', 'N/A')}
Company: {job.get('company', 'N/A')}
Location: {job.get('location', 'N/A')}
Description: {job.get('description', 'N/A')}
"""

    prompt = f"""You are a job relevance evaluator. Score the following job against the candidate profile.

CANDIDATE PROFILE:
{profile_summary}

JOB LISTING:
{job_text}

Respond in this exact format:
SCORE: [1-10]
MATCH_REASONS: [2-3 bullet points on why it's a good fit]
GAPS: [1-2 bullet points on any mismatches or missing requirements]
VERDICT: [STRONG FIT / GOOD FIT / WEAK FIT / NOT A FIT]
"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    cost_tracker.record("score")

    response_text = message.content[0].text

    score = 0
    for line in response_text.split('\n'):
        if line.startswith('SCORE:'):
            try:
                score = int(line.split(':')[1].strip().split('/')[0])
            except:
                score = 0

    return {
        **job,
        "relevance_score": score,
        "ai_analysis": response_text
    }


def filter_jobs(jobs: list, user: dict, min_score: int = 7) -> list:
    relevant = batch_prefilter(jobs, user)

    if not relevant:
        print("No relevant jobs passed the pre-filter.")
        return []

    scored = []
    for job in relevant:
        print(f"  Scoring: {job.get('title')} at {job.get('company')}...")
        result = match_job(job, user)
        scored.append(result)

    scored.sort(key=lambda x: x['relevance_score'], reverse=True)
    filtered = [j for j in scored if j['relevance_score'] >= min_score]

    print(f"\n✓ {len(filtered)}/{len(relevant)} jobs passed relevance filter (score ≥ {min_score})")
    return filtered